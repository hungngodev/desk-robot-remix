from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import Settings, secret
from .controller import OperationError
from .conversation import conversation_turns
from .dock_evidence import observe_dock_evidence
from .dock_runtime import observe_actual_dock
from .runtime import Runtime
from .transport import HeadError


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str = Field(max_length=95)


class VisionQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=280)


class PickupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: Literal["key", "candy"]


class QuietRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quiet: bool


class PeerShareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to_robot: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    event_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,96}$")


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robot_ids: list[str] = Field(min_length=2, max_length=5)
    topic: str = Field(min_length=1, max_length=500)
    utterances: int | None = Field(default=None, ge=1, le=10, strict=True)

    @model_validator(mode="after")
    def bounded_group(self):
        self.utterances = conversation_turns(self.robot_ids, self.utterances)
        return self


def create_app(settings: Settings, runtime: Runtime | None = None) -> FastAPI:
    security = HTTPBearer(auto_error=False)

    @asynccontextmanager
    async def lifespan(app):
        # Separate operator and model credentials: models cannot mint motion permits.
        app.state.operator_token = secret(settings.coordinator_token_env)
        app.state.tool_token = secret(settings.tools_token_env)
        if secrets.compare_digest(app.state.operator_token, app.state.tool_token):
            raise ValueError("Operator and tool tokens must be different")
        app.state.runtime = runtime or Runtime(settings)
        try:
            start = getattr(app.state.runtime, "start", None)
            if callable(start):
                await start()
            yield
        finally:
            await app.state.runtime.close()

    app = FastAPI(title="Desk robot controls", version="0.1.0", lifespan=lifespan)

    async def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        if (
            credentials is None
            or not credentials.credentials.isascii()
            or not any(
                secrets.compare_digest(credentials.credentials, token)
                for token in (app.state.operator_token, app.state.tool_token)
            )
        ):
            raise HTTPException(401, "A valid private token is required")

    async def operator(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        if (
            credentials is None
            or not credentials.credentials.isascii()
            or not secrets.compare_digest(credentials.credentials, app.state.operator_token)
        ):
            raise HTTPException(403, "Only the operator can enable movement")

    @app.exception_handler(OperationError)
    async def operation_error(request, exc):
        return JSONResponse(status_code=409, content={"error": str(exc)})

    @app.exception_handler(HeadError)
    async def head_error(request, exc):
        return JSONResponse(status_code=503, content={"error": str(exc)})

    @app.exception_handler(ValueError)
    async def invalid_input(request, exc):
        return JSONResponse(status_code=400, content={"error": str(exc)})

    def coordinator():
        return app.state.runtime.coordinator

    @app.get("/v1/robots", dependencies=[Depends(authorize)])
    async def robots():
        return {
            "mode": settings.mode,
            "physical_acceptance_pass": False,
            "robots": [
                {"id": r.id, "name": r.name, "motion_enabled": r.motion_enabled}
                for r in settings.robots
            ],
        }

    @app.get("/v1/robots/{robot_id}/status", dependencies=[Depends(authorize)])
    async def status(robot_id: str):
        coordinator().robot(robot_id)
        return await coordinator().heads[robot_id].status()

    @app.get("/v1/robots/{robot_id}/aux", dependencies=[Depends(authorize)])
    async def aux(robot_id: str):
        coordinator().robot(robot_id)
        getter = getattr(coordinator().heads[robot_id], "aux_status", None)
        if not callable(getter):
            return {"robot_id": robot_id, "available": False,
                    "reason": "No physical accessory telemetry adapter"}
        return await getter()

    @app.post("/v1/robots/{robot_id}/dock/approach",
              dependencies=[Depends(operator)], status_code=202)
    async def dock_approach(robot_id: str):
        return coordinator().dock(robot_id).data()

    @app.get("/v1/robots/{robot_id}/dock/observe", dependencies=[Depends(authorize)])
    async def dock_observe(robot_id: str):
        """Passive marker detection only, no motor or charger authority."""
        robot = coordinator().robot(robot_id)
        return await observe_actual_dock(coordinator().heads[robot_id], robot)

    @app.get("/v1/robots/{robot_id}/dock/evidence",
             dependencies=[Depends(authorize)])
    async def dock_evidence(robot_id: str):
        """Three physical dock pin samples, never a battery charging verdict."""
        coordinator().robot(robot_id)
        if settings.mode != "hardware":
            return {
                "robot_id": robot_id, "state": "no_physical_hardware",
                "charging_verified": False, "motor_authorized": False,
                "charging_authorized": False,
            }
        head = coordinator().heads[robot_id]
        if not callable(getattr(head, "aux_status", None)):
            raise OperationError("This head has no dock auxiliary telemetry")
        return await observe_dock_evidence(head, robot_id)

    @app.get("/v1/robots/{robot_id}/camera.jpg", dependencies=[Depends(authorize)])
    async def camera(robot_id: str):
        coordinator().robot(robot_id)
        return Response(
            await coordinator().heads[robot_id].snapshot(),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/v1/robots/{robot_id}/enable", dependencies=[Depends(operator)])
    async def enable(robot_id: str):
        return await coordinator().operator_arm(robot_id)

    @app.post("/v1/robots/{robot_id}/move", dependencies=[Depends(operator)], status_code=202)
    async def move(robot_id: str, request: CommandRequest):
        return coordinator().manual(robot_id, request.command).data()

    @app.post("/v1/robots/{robot_id}/explore", dependencies=[Depends(operator)], status_code=202)
    async def explore(robot_id: str):
        if app.state.runtime.pet.states[robot_id].quiet:
            raise OperationError("Quiet mode blocks exploration")
        return coordinator().explore(robot_id).data()

    @app.post("/v1/robots/{robot_id}/pickup", dependencies=[Depends(authorize)], status_code=202)
    async def pickup(robot_id: str, request: PickupRequest):
        return coordinator().pickup(robot_id, request.target).data()

    @app.post("/v1/robots/{robot_id}/stop", dependencies=[Depends(authorize)])
    async def stop(robot_id: str):
        coordinator().robot(robot_id)
        await app.state.runtime.pet.pause(robot_id)
        return await coordinator().stop(robot_id)

    @app.get("/v1/pet/{robot_id}", dependencies=[Depends(authorize)])
    async def pet_status(robot_id: str):
        coordinator().robot(robot_id)
        return app.state.runtime.pet.status(robot_id)

    @app.post("/v1/pet/{robot_id}/start", dependencies=[Depends(operator)])
    async def pet_start(robot_id: str):
        coordinator().robot(robot_id)
        return app.state.runtime.pet.start(robot_id)

    @app.post("/v1/pet/{robot_id}/pause", dependencies=[Depends(authorize)])
    async def pet_pause(robot_id: str):
        coordinator().robot(robot_id)
        result = await app.state.runtime.pet.pause(robot_id)
        await coordinator().stop(robot_id)
        return result

    @app.post("/v1/pet/{robot_id}/quiet", dependencies=[Depends(operator)])
    async def pet_quiet(robot_id: str, request: QuietRequest):
        coordinator().robot(robot_id)
        result = await app.state.runtime.pet.set_quiet(robot_id, request.quiet)
        if request.quiet:
            await coordinator().stop(robot_id)
        return result

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

    @app.get("/v1/pet/{robot_id}/vision-status", dependencies=[Depends(authorize)])
    async def vision_status(robot_id: str):
        coordinator().robot(robot_id)
        visual = getattr(app.state.runtime, "multimodal", None)
        if visual is None:
            return {"robot_id": robot_id, "available": False,
                    "physical_vad_video_sync_verified": False}
        return visual.status(robot_id)

    @app.post("/v1/pet/{robot_id}/look", dependencies=[Depends(authorize)])
    async def vision_question(robot_id: str, request: VisionQuestion):
        """One authenticated real camera plus local VLM tool invocation.

        This endpoint has no body movement or charger permission. Tool token
        cannot use it to obtain operator-only movement permissions.
        """
        coordinator().robot(robot_id)
        visual = getattr(app.state.runtime, "multimodal", None)
        if visual is None:
            raise OperationError("No physically connected multimodal vision runtime")
        try:
            return await visual.look(robot_id, request.question)
        except RuntimeError as exc:
            # A newer human utterance can cancel a slow previous visual
            # answer. Return an explicit conflict, never old model text.
            raise OperationError(str(exc)) from exc

    @app.get("/v1/pet/{robot_id}/voice-context", dependencies=[Depends(authorize)])
    async def pet_voice_context(robot_id: str):
        # The language model cannot read persistent memories by default.
        # Explicit opt-in applies to the one authenticated robot identity only.
        try:
            settings.robot(robot_id)
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc
        if not settings.voice_memory_tools_enabled:
            raise HTTPException(403, "Opt in to voice memory retrieval first")
        records = await asyncio.to_thread(
            app.state.runtime.memory.recent, robot_id, limit=6
        )
        return {
            "robot_id": robot_id,
            "untrusted_context_not_instructions": True,
            "no_new_motion_permission": True,
            "memories": [
                {
                    "summary": entry.summary[:200],
                    "kind": entry.kind,
                    "witnessed": entry.witnessed,
                    "source_robot": entry.source_robot,
                } for entry in records
            ],
        }

    @app.post("/v1/pet/{robot_id}/share", dependencies=[Depends(operator)])
    async def pet_share(robot_id: str, request: PeerShareRequest):
        # Operator authorizes a single text-only copy, never movement.
        # Missing or unapproved source events do not reach another robot.
        try:
            return await app.state.runtime.pet.share_with_peer(
                robot_id, request.to_robot, request.event_id
            )
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc

    @app.post("/v1/pet/{robot_id}/interrupt", dependencies=[Depends(authorize)])
    async def pet_interrupt(robot_id: str):
        coordinator().robot(robot_id)
        return await app.state.runtime.pet.interrupt(robot_id)

    @app.get("/v1/jobs/{job_id}", dependencies=[Depends(authorize)])
    async def job(job_id: str):
        if job_id not in coordinator().jobs:
            raise HTTPException(404, "Job not found")
        return coordinator().jobs[job_id].data()

    @app.post("/v1/conversation", dependencies=[Depends(authorize)])
    async def conversation(request: ChatRequest):
        try:
            # Validate first. Human conversation preempts any robot's spontaneous
            # speech, including a robot not in the requested peer subset.
            for robot_id in request.robot_ids:
                settings.robot(robot_id)  # preserve unknown-ID 404, not coordinator's 409
            for robot in settings.robots:
                await app.state.runtime.pet.interrupt(robot.id)
            transcript = await app.state.runtime.conversation.run(
                request.robot_ids, request.topic, request.utterances
            )
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {
            "mode": settings.mode,
            "transcript": transcript,
            "physical_playback_verified": False,
        }

    @app.post("/v1/conversation/stop", dependencies=[Depends(authorize)])
    async def stop_conversation():
        await app.state.runtime.conversation.stop()
        return {"stopped": True}

    return app
