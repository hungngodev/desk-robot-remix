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



def register_memory_routes(
    app: FastAPI, settings: Settings, *, operator,
) -> None:
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
        changed = await asyncio.to_thread(
            app.state.runtime.memory.set_core_fact,
            robot_id, slot, request.value
        )
        return {"robot_id": robot_id, "slot": slot, "changed": changed,
                "operator_curated": True, "motor_authorized": False}

    @app.delete("/v1/pet/{robot_id}/core-memory/{slot}",
                dependencies=[Depends(operator)])
    async def delete_core_memory(robot_id: str, slot: str):
        try:
            settings.robot(robot_id)
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc
        removed = await asyncio.to_thread(
            app.state.runtime.memory.forget_core_fact, robot_id, slot
        )
        return {"robot_id": robot_id, "slot": slot, "removed": removed}

    @app.delete("/v1/pet/{robot_id}/memories/{event_id}",
                dependencies=[Depends(operator)])
    async def delete_episode(robot_id: str, event_id: str):
        try:
            settings.robot(robot_id)
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc
        removed = await asyncio.to_thread(
            app.state.runtime.memory.forget_episode, robot_id, event_id
        )
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
        visual = getattr(app.state.runtime, "multimodal", None)
        sensor_cues, tool_cues, timeline = [], [], []
        if settings.voice_vision_tools_enabled and visual is not None:
            clock = time.monotonic()
            sensor_cues = visual.hub.recent_events(robot_id, clock)
            recent_tools = getattr(visual.hub, "recent_tool_context", None)
            if callable(recent_tools):
                tool_cues = recent_tools(robot_id, clock)
            ordered = getattr(visual.hub, "interaction_timeline", None)
            if callable(ordered):
                timeline = ordered(robot_id, clock, limit=10)
        core = await asyncio.to_thread(
            app.state.runtime.memory.core_facts, robot_id, limit=8
        )
        # Each SQLite operation yields to the event loop. A local opt-out
        # during that read invalidates the entire current private tool reply.
        if not settings.voice_memory_tools_enabled:
            raise HTTPException(403, "Voice memory consent revoked during read")
        # Camera and interaction consent can be revoked while the SQLite
        # core-fact query yields. Never return previously collected live cues
        # after that independent opt-out.
        if not settings.voice_vision_tools_enabled:
            sensor_cues, tool_cues, timeline = [], [], []
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

