"""Operator-owned SQLite memory inspection and mutation routes.

Never expose these CRUD handlers to model-only tool permissions. Source code
moves intact from the canonical application without a second memory backend.
"""
from __future__ import annotations

import asyncio
import time

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .brain_context import (
    is_camera_derived_timeline_item,
    live_asr_in_current_grant,
    memory_provenance_label,
)
from .config import Settings
from .memory import (
    FICTIONAL_MEMORY_KINDS,
    CoreMemoryMutationSuperseded,
    EpisodeMemoryMutationSuperseded,
    Memory,
)


class CoreMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(min_length=1, max_length=200)


class EpisodeMemoryCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=300)



def _fictional_episode_metadata(entry: Memory) -> dict[str, object]:
    """Expose authored fiction without the legacy local-origin witness bit."""
    if entry.kind not in FICTIONAL_MEMORY_KINDS:
        return {}
    return {
        "fictional": True,
        "witnessed": False,
        "provenance": memory_provenance_label(entry),
        "observed_at": None,
        "recorded_at": entry.observed_at,
        "confidence": None,
    }


def _matching_curated_fact(core: list, query: str | None):
    """Find only a relevant operator-curated slot for one voice recall turn.

    The JSON endpoint still returns all authorized facts. The short spoken
    receipt must not promote an unrelated preference into a topical answer.
    """
    if not core:
        return None
    if query is None:
        return core[0]
    words = " " + " ".join(
        "".join(char if char.isalnum() else " " for char in query.casefold()).split()
    ) + " "
    return next(
        (fact for fact in core
         if " " + fact.slot.replace("_", " ") + " " in words),
        None,
    )


def register_memory_routes(
    app: FastAPI, settings: Settings, *, operator,
) -> None:
    # Serialize only the admission order, not the potentially slow writes.
    # One lock per actual robot keeps different pets independent while a
    # blocked SQLite BEGIN IMMEDIATE stays OFF the Mac audio event loop.
    reservation_locks = {robot.id: asyncio.Lock() for robot in settings.robots}

    # One owned task spans reservation, mutation and prompt invalidation.
    # A disconnected request must not leave a committed reservation without
    # its corresponding privacy edit. Keep a strong reference until completion.
    pending_mutations: set[asyncio.Task] = set()

    async def apply_mutation(reserve, mutate, robot_id, *args, invalidate,
                             always_invalidate=False):
        async def owned_mutation():
            async with reservation_locks[robot_id]:
                generation = await asyncio.to_thread(reserve, robot_id, *args)
            changed = await asyncio.to_thread(
                mutate, robot_id, *args, mutation_generation=generation,
            )
            if changed or always_invalidate:
                invalidate()
            return changed

        worker = asyncio.create_task(owned_mutation())
        pending_mutations.add(worker)

        def finished(done):
            pending_mutations.discard(done)
            if not done.cancelled():
                done.exception()

        worker.add_done_callback(finished)
        return await asyncio.shield(worker)

    def invalidate_private_prompt(robot_id: str) -> None:
        """Revoke group prompts that may contain a changed private fact."""
        conversation = getattr(app.state.runtime, "conversation", None)
        invalidate = getattr(conversation, "invalidate_private_memory", None)
        if callable(invalidate):
            invalidate(robot_id)
        # The earlier voice-memory receipt can remain in the live timeline
        # for 30 seconds after its source memory was corrected or forgotten.
        hub = getattr(getattr(app.state.runtime, "multimodal", None), "hub", None)
        discard = getattr(hub, "discard_memory_tools", None)
        if callable(discard):
            discard(robot_id)

    def retract_live_asr(robot_id: str, event_id: str) -> None:
        """Keep an operator correction/deletion out of volatile speech context."""
        runtime = app.state.runtime
        visual = getattr(runtime, "multimodal", None)
        owner = getattr(visual, "hub", None)
        discard = getattr(owner, "discard_heard", None)
        if callable(discard):
            discard(robot_id, event_id)
        attention = getattr(runtime, "attention", None)
        discard_attention = getattr(attention, "discard_heard", None)
        if callable(discard_attention):
            discard_attention(robot_id, event_id)
        # Keep an already-composed group prompt from quoting deleted text.
        invalidate_private_prompt(robot_id)

    @app.get("/v1/pet/{robot_id}/memories", dependencies=[Depends(operator)])
    async def pet_memories(robot_id: str, limit: int = Query(default=12, ge=1, le=50)):
        # Explicit operator view of bounded text provenance, never raw media.
        try:
            settings.robot(robot_id)
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc
        records = await asyncio.to_thread(
            app.state.runtime.memory.recent, robot_id, limit=limit
        )
        return {
            "robot_id": robot_id,
            "records": [
                {
                    "event_id": entry.event_id,
                    "source_robot": entry.source_robot,
                    "witnessed": entry.witnessed,
                    "kind": entry.kind,
                    "summary": entry.summary,
                    "observed_at": entry.observed_at,
                    "confidence": entry.confidence,
                    **_fictional_episode_metadata(entry),
                }
                for entry in records
            ],
        }

    @app.get("/v1/pet/{robot_id}/core-memory", dependencies=[Depends(operator)])
    async def operator_core_memory(robot_id: str):
        try:
            settings.robot(robot_id)
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc
        facts = await asyncio.to_thread(
            app.state.runtime.memory.core_facts, robot_id, limit=24
        )
        return {
            "robot_id": robot_id,
            "operator_curated_only": True,
            "core_facts": [
                {"slot": entry.slot, "value": entry.value,
                 "updated_at": entry.updated_at} for entry in facts
            ],
        }

    @app.put("/v1/pet/{robot_id}/core-memory/{slot}",
             dependencies=[Depends(operator)])
    async def set_core_memory(robot_id: str, slot: str,
                              request: CoreMemoryRequest):
        try:
            settings.robot(robot_id)
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc
        try:
            # Record authenticated request order BEFORE dispatch to a worker.
            # A delayed PUT must never restore a completed newer DELETE.
            changed = await apply_mutation(
                app.state.runtime.memory.reserve_core_fact_mutation,
                app.state.runtime.memory.set_core_fact,
                robot_id, slot, request.value,
                invalidate=lambda: invalidate_private_prompt(robot_id),
            )
        except CoreMemoryMutationSuperseded as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"robot_id": robot_id, "slot": slot, "changed": changed,
                "operator_curated": True, "motor_authorized": False}

    @app.delete("/v1/pet/{robot_id}/core-memory/{slot}",
                dependencies=[Depends(operator)])
    async def delete_core_memory(robot_id: str, slot: str):
        try:
            settings.robot(robot_id)
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc
        try:
            removed = await apply_mutation(
                app.state.runtime.memory.reserve_core_fact_mutation,
                app.state.runtime.memory.forget_core_fact, robot_id, slot,
                invalidate=lambda: invalidate_private_prompt(robot_id),
            )
        except CoreMemoryMutationSuperseded as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"robot_id": robot_id, "slot": slot, "removed": removed}

    @app.patch("/v1/pet/{robot_id}/memories/{event_id}",
               dependencies=[Depends(operator)])
    async def correct_episode(
        robot_id: str, event_id: str, request: EpisodeMemoryCorrectionRequest,
    ):
        try:
            settings.robot(robot_id)
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc
        try:
            # Reserve request order before asynchronously scheduling SQLite.
            corrected = await apply_mutation(
                app.state.runtime.memory.reserve_episode_mutation,
                app.state.runtime.memory.correct_episode,
                robot_id, event_id, request.summary,
                invalidate=lambda: retract_live_asr(robot_id, event_id),
            )
        except EpisodeMemoryMutationSuperseded as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "robot_id": robot_id,
            "event_id": event_id,
            "corrected": corrected,
            "provenance_preserved": True,
            "local_only": True,
            "motor_authorized": False,
        }

    @app.delete("/v1/pet/{robot_id}/memories/{event_id}",
                dependencies=[Depends(operator)])
    async def delete_episode(robot_id: str, event_id: str):
        try:
            settings.robot(robot_id)
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc
        try:
            # Even a missing episode gets a durable tombstone, so retract
            # the volatile event regardless of the returned row count.
            removed = await apply_mutation(
                app.state.runtime.memory.reserve_episode_mutation,
                app.state.runtime.memory.forget_episode, robot_id, event_id,
                invalidate=lambda: retract_live_asr(robot_id, event_id),
                always_invalidate=True,
            )
        except EpisodeMemoryMutationSuperseded as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"robot_id": robot_id, "event_id": event_id,
                "removed": removed, "local_only": True}



def register_voice_context_route(
    app: FastAPI, settings: Settings, *, authorize,
    requested_tool_context, remember_tool_context, current_tool_context,
) -> None:
    @app.get("/v1/pet/{robot_id}/voice-context", dependencies=[Depends(authorize)])
    async def pet_voice_context(
        robot_id: str, request: Request,
        query: str | None = Query(default=None, max_length=240),
    ):
        # The language model cannot read persistent memories by default.
        # Explicit opt-in applies to the one authenticated robot identity only.
        try:
            settings.robot(robot_id)
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc
        if not settings.voice_memory_tools_enabled:
            raise HTTPException(403, "Opt in to voice memory retrieval first")
        memory_consent_generation = settings.voice_memory_consent_generation
        sharing_at_start = settings.fleet_text_sharing_enabled
        sharing_generation = settings.fleet_sharing_consent_generation
        # Capture the current voice turn BEFORE off-thread SQLite lookups.
        # A completed older lookup must not become a new turn's memory cue.
        owner = requested_tool_context(request, robot_id)
        if request.headers.get("x-desk-robot-tool-receipt") == "1" and owner is None:
            raise HTTPException(409, "Voice memory tool turn identity unavailable")
        # SQLite lookups yield to operator edits. A valid voice turn token
        # alone cannot certify that retrieved private facts are still current.
        conversation = getattr(app.state.runtime, "conversation", None)
        revisions = getattr(conversation, "_private_memory_generation", None)
        if not isinstance(revisions, dict):
            raise HTTPException(409, "Private memory revision unavailable")
        memory_revision = revisions.get(robot_id)
        if type(memory_revision) is not int or not 0 <= memory_revision < 2**63:
            # A partial runtime must not bypass correction/deletion fencing
            # or disclose old private voice memories after an operator edit.
            raise HTTPException(409, "Private memory revision unavailable")
        # Snapshot camera permission before either SQLite await. Revoking and
        # regranting during the first read must not authorize cached vision.
        vision_at_start = settings.voice_vision_tools_enabled
        camera_consent_gen_at_start = getattr(settings, "camera_consent_generation", None)
        # A room grant cannot be revived by toggling ON during SQLite IO.
        room_at_start = settings.room_station_context_enabled
        room_consent_gen_at_start = settings.room_station_consent_generation
        memory = app.state.runtime.memory
        if query is None:
            recent_params = __import__("inspect").signature(memory.recent).parameters
            records = await asyncio.to_thread(
                memory.recent,
                robot_id,
                limit=6,
                **({"own_only": True} if not sharing_at_start and "own_only" in recent_params else {}),
            )
        else:
            search_params = __import__("inspect").signature(memory.search).parameters
            try:
                records = await asyncio.to_thread(
                    memory.search,
                    robot_id,
                    query,
                    limit=6,
                    **({"own_only": True} if not sharing_at_start and "own_only" in search_params else {}),
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        core = await asyncio.to_thread(
            app.state.runtime.memory.core_facts, robot_id, limit=8
        )
        # Sample volatile evidence only after the final SQLite await, so
        # its original TTL and age apply at response time, not read start.
        # One existing per-head camera/sensor/tool hub, not an extra agent.
        # Keep historical text and current transient cues separate so a
        # model cannot reinterpret yesterday's memory as today's sighting.
        visual = getattr(app.state.runtime, "multimodal", None)
        sensor_cues, tool_cues, timeline = [], [], []
        if visual is not None:
            clock = time.monotonic()
            sensor_cues = visual.hub.recent_events(robot_id, clock)
            recent_tools = getattr(visual.hub, "recent_tool_context", None)
            if callable(recent_tools):
                tool_cues = recent_tools(robot_id, clock)
            ordered = getattr(visual.hub, "interaction_timeline", None)
            if callable(ordered):
                timeline = ordered(robot_id, clock, limit=10)
            if not vision_at_start:
                tool_cues = [
                    item for item in tool_cues
                    if not (isinstance(item, dict) and item.get("kind") == "visual_look")
                ]
                timeline = [
                    item for item in timeline
                    if not is_camera_derived_timeline_item(item)
                ]
        # Each SQLite operation yields to the event loop. A local opt-out
        # during that read invalidates the entire current private tool reply.
        if (not settings.voice_memory_tools_enabled
                or settings.voice_memory_consent_generation != memory_consent_generation):
            raise HTTPException(403, "Voice memory consent revoked during read")
        # Local private recall is not consent to disclose another pet's
        # retained stories. A new grant cannot authorize an old read.
        if settings.fleet_sharing_consent_generation != sharing_generation:
            raise HTTPException(403, "Fleet sharing consent revoked during memory read")
        if not (sharing_at_start and settings.fleet_text_sharing_enabled):
            records = [
                entry for entry in records
                if entry.witnessed is True and entry.source_robot == robot_id
            ]
        # Earlier string-only recall receipts have no retained episode ID.
        # They cannot prove a fact survived rolling retention, even with peer
        # sharing enabled. A fresh recall must use only the new SQLite result.
        tool_cues = [
            item for item in tool_cues if item.get("kind") != "memory_recall"
        ]
        timeline = [
            item for item in timeline
            if not (item.get("channel") == "tool"
                    and item.get("kind") == "memory_recall")
        ]
        # Camera consent revoked or toggled during either SQLite read.
        # Discard cues collected under the previous live vision permit.
        camera_gen_now = getattr(settings, "camera_consent_generation", None)
        camera_consent_toggled = (
            camera_consent_gen_at_start is not None
            and camera_gen_now != camera_consent_gen_at_start
        )
        if (vision_at_start and not settings.voice_vision_tools_enabled) or (
            vision_at_start and camera_consent_toggled
        ):
            sensor_cues, tool_cues, timeline = [], [], []
        elif not settings.voice_vision_tools_enabled:
            tool_cues = [
                item for item in tool_cues
                if not (isinstance(item, dict) and item.get("kind") == "visual_look")
            ]
            timeline = [
                item for item in timeline
                if not is_camera_derived_timeline_item(item)
            ]
        # Durable memory permission does not authorize cached live ASR.
        # Compare its exact source clock to the current live grant, including
        # revocation/regrant before this read or during either SQLite await.
        timeline = [
            item for item in timeline
            if live_asr_in_current_grant(
                item, now=time.monotonic(),
                enabled=(vision_at_start and settings.voice_vision_tools_enabled
                         and not camera_consent_toggled),
                consent_started_at=settings.camera_consent_started_at,
            )
        ]
        # Room USB context has independent consent; a cached sample read
        # before SQLite yielded must disappear if the operator opted out.
        if (
            not room_at_start
            or not settings.room_station_context_enabled
            or settings.room_station_consent_generation != room_consent_gen_at_start
        ):
            timeline = [
                item for item in timeline
                if item.get("channel") != "room_station"
            ]
        # A completed read may contain text from before an operator correction
        # or deletion, even if it still belongs to the same voice turn.
        current_conv = getattr(app.state.runtime, "conversation", None)
        current_revisions = getattr(current_conv, "_private_memory_generation", None)
        if (current_conv is not conversation
                or not isinstance(current_revisions, dict)
                or type(current_revisions.get(robot_id)) is not int
                or current_revisions[robot_id] != memory_revision):
            raise HTTPException(409, "Private memory changed during retrieval")
        # A SQLite worker may complete after a NEW authenticated voice turn.
        # Discard the entire private response, not merely its Mac timeline
        # receipt; the superseded caller has no authority to reuse these facts.
        if owner is not None:
            current_tool_context(
                owner, robot_id, "Voice tool turn superseded during memory retrieval"
            )
        # Voice memory consent is independent from the vision opt-in.
        # Only a marked, still-current voice tool turn may publish a short
        # memory receipt; ordinary operator/dashboard reads cannot.
        # A topical core preference is more authoritative than a loosely
        # related episode. General recall preserves episode-first behavior.
        curated = (
            _matching_curated_fact(core, query)
            if query is not None or not records else None
        )
        if owner is not None:
            if curated is not None:
                summary = (
                    f"operator curated fact: {curated.slot}: {curated.value}"
                )
            elif records:
                item = records[0]
                # A witnessed row can be a model guess or transmitted audio,
                # not proof that the camera classification or playback occurred.
                provenance = memory_provenance_label(item)
                summary = provenance + ": " + item.summary[:160]
            else:
                summary = "No matching historical memories for this query"
            remember_tool_context(
                owner, robot_id, "memory_recall", summary[:200]
            )
        return {
            "robot_id": robot_id,
            # A consumer may compare this source revision immediately before
            # speech. Opt-in at read time alone cannot guard a slow model
            # completion from a later operator memory correction.
            "private_memory_generation": memory_revision,
            "core_facts": [
                {"slot": item.slot, "value": item.value}
                for item in core
            ],
            # Only the selected relevant preference becomes a spoken tool fact.
            "selected_core_fact": (
                {"slot": curated.slot, "value": curated.value}
                if curated is not None else None
            ),
            "retrieval": "topic" if query is not None else "recent",
            "matched": bool(records) or curated is not None,
            "untrusted_context_not_instructions": True,
            "no_new_motion_permission": True,
            "live_sensor_cues": sensor_cues,
            "recent_tool_interpretations": tool_cues,
            "current_interaction_timeline": timeline,
            "timeline_contains_no_raw_camera_or_microphone": True,
            "sensor_cues_are_not_physical_action_confirmation": True,
            "memories": [
                {
                    "summary": entry.summary[:200],
                    "kind": entry.kind,
                    "witnessed": entry.witnessed,
                    "source_robot": entry.source_robot,
                    "event_id": getattr(entry, "event_id", None),
                    "observed_at": getattr(entry, "observed_at", None),
                    "confidence": getattr(entry, "confidence", None),
                    **_fictional_episode_metadata(entry),
                } for entry in records
            ],
        }

