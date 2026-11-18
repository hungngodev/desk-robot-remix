"""Operator-owned SQLite memory inspection and mutation routes.

Never expose these CRUD handlers to model-only tool permissions. Source code
moves intact from the canonical application without a second memory backend.
"""
from __future__ import annotations

import asyncio

from fastapi import Depends, FastAPI, HTTPException, Query
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

