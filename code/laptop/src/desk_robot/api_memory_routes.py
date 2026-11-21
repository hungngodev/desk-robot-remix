"""Operator-owned SQLite memory inspection and mutation routes.

Never expose these CRUD handlers to model-only tool permissions. Source code
moves intact from the canonical application without a second memory backend.
"""
from __future__ import annotations

import asyncio
import time

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings


class CoreMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(min_length=1, max_length=200)


class EpisodeMemoryCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=300)



def register_memory_routes(
    app: FastAPI, settings: Settings, *, operator,
) -> None:
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
            changed = await asyncio.to_thread(
                app.state.runtime.memory.set_core_fact,
                robot_id, slot, request.value
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if changed:
            # Core preferences enter the same private dialogue prompts as
            # episodes; an old model completion must not speak stale facts.
            invalidate_private_prompt(robot_id)
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
            removed = await asyncio.to_thread(
                app.state.runtime.memory.forget_core_fact, robot_id, slot
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if removed:
            invalidate_private_prompt(robot_id)
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
            corrected = await asyncio.to_thread(
                app.state.runtime.memory.correct_episode,
                robot_id, event_id, request.summary,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if corrected:
            retract_live_asr(robot_id, event_id)
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
            removed = await asyncio.to_thread(
                app.state.runtime.memory.forget_episode, robot_id, event_id
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        # The durable tombstone applies even when a delayed transcript
        # has not inserted its episode yet. Retract this same event in RAM
        # whether or not a row existed at delete time.
        retract_live_asr(robot_id, event_id)
        return {"robot_id": robot_id, "event_id": event_id,
                "removed": removed, "local_only": True}



def register_voice_context_route(
    app: FastAPI, settings: Settings, *, authorize,
    requested_tool_context, remember_tool_context,
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
        # Capture the current voice turn BEFORE off-thread SQLite lookups.
        # A completed older lookup must not become a new turn's memory cue.
        owner = requested_tool_context(request, robot_id)
        # SQLite lookups yield to operator edits. A valid voice turn token
        # alone cannot certify that retrieved private facts are still current.
        conversation = getattr(app.state.runtime, "conversation", None)
        revisions = getattr(conversation, "_private_memory_generation", None)
        memory_revision = (
            revisions.get(robot_id) if isinstance(revisions, dict) else None
        )
        if type(memory_revision) is not int or memory_revision < 0:
            # A partial runtime must not bypass correction/deletion fencing
            # or disclose old private voice memories after an operator edit.
            raise HTTPException(409, "Private memory revision unavailable")
        if query is None:
            records = await asyncio.to_thread(
                app.state.runtime.memory.recent, robot_id, limit=6
            )
        else:
            try:
                records = await asyncio.to_thread(
                    app.state.runtime.memory.search, robot_id, query, limit=6
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        # One existing per-head camera/sensor/tool hub, not an extra agent.
        # Keep historical text and current transient cues separate so a
        # model cannot reinterpret yesterday's memory as today's sighting.
        vision_at_start = settings.voice_vision_tools_enabled
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
                timeline = [
                    item for item in timeline
                    if item.get("channel") != "camera"
                    and not (item.get("channel") == "sensor"
                             and item.get("kind") == "camera_face")
                ]
        core = await asyncio.to_thread(
            app.state.runtime.memory.core_facts, robot_id, limit=8
        )
        # Each SQLite operation yields to the event loop. A local opt-out
        # during that read invalidates the entire current private tool reply.
        if not settings.voice_memory_tools_enabled:
            raise HTTPException(403, "Voice memory consent revoked during read")
        # Camera consent revoked while the SQLite core-fact query yielded.
        # Discard cues collected under the previous live vision permit.
        if vision_at_start and not settings.voice_vision_tools_enabled:
            sensor_cues, tool_cues, timeline = [], [], []
        elif not settings.voice_vision_tools_enabled:
            timeline = [
                item for item in timeline
                if item.get("channel") != "camera"
                and not (item.get("channel") == "sensor"
                         and item.get("kind") == "camera_face")
            ]
        # Room USB context has independent consent; a cached sample read
        # before SQLite yielded must disappear if the operator opted out.
        if not settings.room_station_context_enabled:
            timeline = [
                item for item in timeline
                if item.get("channel") != "room_station"
            ]
        # A completed read may contain text from before an operator correction
        # or deletion, even if it still belongs to the same voice turn.
        current_revisions = getattr(
            getattr(app.state.runtime, "conversation", None),
            "_private_memory_generation", None,
        )
        if (not isinstance(current_revisions, dict)
                or type(current_revisions.get(robot_id)) is not int
                or current_revisions[robot_id] != memory_revision):
            raise HTTPException(409, "Private memory changed during retrieval")
        # A SQLite worker may complete after a NEW authenticated voice turn.
        # Discard the entire private response, not merely its Mac timeline
        # receipt; the superseded caller has no authority to reuse these facts.
        if owner is not None:
            if not isinstance(owner, tuple) or len(owner) != 2:
                raise HTTPException(409, "Unverifiable voice tool turn identity")
            turn_owner, turn_generation = owner
            current_epochs = getattr(turn_owner, "_turn_epoch", None)
            if (type(turn_generation) is not int
                    or not isinstance(current_epochs, dict)
                    or current_epochs.get(robot_id) != turn_generation):
                raise HTTPException(409, "Voice tool turn superseded during memory retrieval")
        # Voice memory consent is independent from the vision opt-in.
        # Only a marked, still-current voice tool turn may publish a short
        # memory receipt; ordinary operator/dashboard reads cannot.
        if owner is not None:
            if records:
                item = records[0]
                provenance = (
                    "own observed event" if item.witnessed
                    else f"reported by {item.source_robot}"
                )
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
            "retrieval": "topic" if query is not None else "recent",
            "matched": bool(records),
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
                } for entry in records
            ],
        }

