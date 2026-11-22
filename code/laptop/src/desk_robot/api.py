from __future__ import annotations

import asyncio
import secrets
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .api_memory_routes import (
    CoreMemoryRequest as CoreMemoryRequest,
)
from .api_memory_routes import (
    register_memory_routes,
    register_voice_context_route,
)
from .api_native_omni_routes import (
    NativeHeardRequest as NativeHeardRequest,
)
from .api_native_omni_routes import (
    NativeSpokenRequest as NativeSpokenRequest,
)
from .api_native_omni_routes import (
    register_native_omni_routes,
)
from .api_readonly_context import register_readonly_context_routes
from .api_readonly_planner import (
    ReadonlyPlanRequest as ReadonlyPlanRequest,
)
from .api_readonly_planner import (
    register_readonly_planner_routes,
)
from .api_robot_status import register_robot_status_routes
from .config import Settings, secret
from .controller import OperationError
from .conversation import conversation_turns
from .dock_evidence import observe_dock_evidence
from .dock_runtime import observe_actual_dock
from .runtime import Runtime
from .transport import HeadError

_PET_SHUTDOWN_TIMEOUT_S = 1.0


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

    @app.exception_handler(TimeoutError)
    async def deadline_error(request, exc):
        return JSONResponse(status_code=503, content={"error": str(exc) or "Hardware deadline exceeded"})

    @app.exception_handler(ValueError)
    async def invalid_input(request, exc):
        return JSONResponse(status_code=400, content={"error": str(exc)})

    def coordinator():
        return app.state.runtime.coordinator

    def requested_tool_context(request: Request, robot_id: str):
        # The Xiaozhi read-only tool explicitly marks its own requests.
        # Background UI/status polling must not become conversation history.
        if request.headers.get("x-desk-robot-tool-receipt") != "1":
            return None
        # Operator dashboard access and Xiaozhi tool execution intentionally
        # have different credentials. A caller cannot promote a normal
        # operator read into model dialogue by adding an untrusted header.
        authorization = request.headers.get("authorization", "")
        scheme, separator, credential = authorization.partition(" ")
        if (scheme.lower() != "bearer" or not separator
                or not credential.isascii()
                or not secrets.compare_digest(credential, app.state.tool_token)):
            return None
        visual = getattr(app.state.runtime, "multimodal", None)
        epochs = getattr(visual, "_turn_epoch", None)
        if not isinstance(epochs, dict) or robot_id not in epochs:
            return None
        return visual, epochs[robot_id]

    def remember_tool_context(owner, robot_id: str, kind: str, summary: str) -> bool:
        if owner is None:
            return False
        visual, generation = owner
        if visual._turn_epoch.get(robot_id) != generation:
            return False
        visual.hub.remember_tool(robot_id, kind, summary, time.monotonic())
        return True

    def native_pet_speech_policy(robot_id: str) -> dict:
        """One Mac operator policy owner; missing pet state fails closed.

        Minimal connector/HTTP test runtimes can lack autonomous pet state.
        More importantly, an unavailable Mac pet owner must NEVER imply
        permission for model-initiated physical speaker output.
        """
        pet = getattr(app.state.runtime, "pet", None)
        states = getattr(pet, "states", None)
        state = states.get(robot_id) if isinstance(states, dict) else None
        ready = (settings.mode != "hardware"
                 or getattr(pet, "voice_monitor_ready", False) is True)
        if state is None:
            return {"pet_autonomy_enabled": False, "pet_quiet": True,
                    "voice_monitor_ready": False}
        return {
            # Mac VAD loss independently suppresses *all* native speaker
            # output; pause/quiet remain separate operator-owned settings.
            "voice_monitor_ready": ready,
            "pet_autonomy_enabled": state.enabled is True and ready,
            "pet_quiet": state.quiet is True,
        }

    register_robot_status_routes(
        app, settings, authorize=authorize, coordinator=coordinator,
        requested_tool_context=requested_tool_context,
        remember_tool_context=remember_tool_context,
    )

    @app.post("/v1/robots/{robot_id}/dock/approach",
              dependencies=[Depends(operator)], status_code=202)
    async def dock_approach(robot_id: str):
        return coordinator().dock(robot_id).data()

    @app.get("/v1/robots/{robot_id}/dock/observe", dependencies=[Depends(authorize)])
    async def dock_observe(robot_id: str):
        """Passive marker detection only, bounded by the original camera grant."""
        robot = coordinator().robot(robot_id)
        if not settings.voice_vision_tools_enabled:
            raise HTTPException(403, "Camera consent required for dock observation")
        camera_grant = settings.camera_consent_generation

        def original_camera_grant_valid() -> bool:
            return (
                settings.voice_vision_tools_enabled
                and settings.camera_consent_generation == camera_grant
            )

        result = await observe_actual_dock(
            coordinator().heads[robot_id], robot,
            consent_valid=original_camera_grant_valid,
        )
        if not settings.voice_vision_tools_enabled:
            raise HTTPException(403, "Camera consent revoked during dock observation")
        if settings.camera_consent_generation != camera_grant:
            raise HTTPException(409, "Camera grant changed during dock observation")
        return result

    @app.get("/v1/robots/{robot_id}/dock/ir",
             dependencies=[Depends(authorize)])
    async def dock_ir(robot_id: str):
        """Observe two independent NEC receivers, never move or charge."""
        coordinator().robot(robot_id)
        if settings.mode != "hardware":
            return {
                "robot_id": robot_id, "available": False,
                "physical_qualified": False,
                "motor_authorized": False,
                "charging_authorized": False,
            }
        getter = getattr(coordinator().heads[robot_id], "ir_status", None)
        if not callable(getter):
            raise OperationError("This head has no direct dual NEC receiver")
        return await getter()

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

    # Raw JPEG preview is an operator action, never a privilege granted by
    # the read-only Xiaozhi model/tool token. Conversed visual facts have
    # separately consented, bounded /v1/pet/* routes.
    @app.get("/v1/robots/{robot_id}/camera.jpg", dependencies=[Depends(operator)])
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

    # A spoken key/candy request may consume ONE recent operator-granted
    # permit; the model cannot mint or extend that permit itself.
    @app.post("/v1/robots/{robot_id}/pickup", dependencies=[Depends(authorize)], status_code=202)
    async def pickup(robot_id: str, request: PickupRequest):
        return coordinator().pickup(robot_id, request.target).data()

    async def bounded_cleanup(coro, *, seconds: float, message: str):
        """A cancelled but uncooperative adapter must not block later STOPs."""
        task = asyncio.create_task(coro)
        try:
            done, _ = await asyncio.wait({task}, timeout=seconds)
            if not done:
                raise TimeoutError(message)
            return await task
        finally:
            if not task.done():
                task.cancel()
                task.add_done_callback(
                    lambda done: None if done.cancelled() else done.exception()
                )

    async def stop_native_pet_speech(robot_id: str):
        """Interrupt the one existing Xiaozhi speaker, never a second TTS."""
        if settings.mode != "hardware":
            return
        conversation = getattr(app.state.runtime, "conversation", None)
        speaker = getattr(conversation, "speaker", None)
        # Older simulated speakers expose only interrupt(). Hardware
        # KokoroHeadSpeaker uses explicit operator_stop() so ordinary human
        # barge does not silently revoke future proactive initiative.
        interrupt = getattr(speaker, "operator_stop", None)
        if not callable(interrupt):
            interrupt = getattr(speaker, "interrupt", None)
        robot = settings.robot(robot_id)
        if not robot.device_id:
            # The WROOM has already been stopped and pet initiative revoked.
            # But no authenticated XIAO target means we cannot certify the
            # speaker STOP. A successful HTTP 200 would silently hide audio
            # that could still be playing on an unknown or previous head.
            raise HeadError("XIAO speech STOP unconfirmed: no device identity")
        if not callable(interrupt):
            raise HeadError("XIAO speech STOP unconfirmed: no speaker adapter")
        await bounded_cleanup(
            interrupt(robot), seconds=2.5,
            message="XIAO speech interruption unconfirmed",
        )

    async def stop_pet_and_audio(robot_id: str, *, quiet: bool):
        """Stop body first, then revoke pet initiative and native speaker.

        Cleanup must run despite previous failures. Crucially, a failed WROOM
        STOP may never be hidden by a later pet or speaker cleanup failure.
        """
        acknowledgement = None
        pet_status = None
        failures: list[tuple[str, BaseException]] = []
        try:
            acknowledgement = await coordinator().stop(robot_id)
        except (Exception, asyncio.CancelledError) as exc:
            failures.append(("WROOM STOP", exc))
        try:
            operation = (
                app.state.runtime.pet.set_quiet(robot_id, True)
                if quiet else app.state.runtime.pet.pause(robot_id)
            )
            pet_status = await bounded_cleanup(
                operation, seconds=_PET_SHUTDOWN_TIMEOUT_S,
                message="Pet pause timeout; speaker STOP still required",
            )
        except (Exception, asyncio.CancelledError) as exc:
            failures.append(("pet pause", exc))
        try:
            await stop_native_pet_speech(robot_id)
        except (Exception, asyncio.CancelledError) as exc:
            failures.append(("XIAO speech STOP", exc))
        if failures:
            primary = failures[0][1]
            for stage, secondary in failures[1:]:
                primary.add_note(
                    f"Additional {stage} failure: {type(secondary).__name__}"
                )
            raise primary
        return acknowledgement, pet_status

    @app.post("/v1/robots/{robot_id}/stop", dependencies=[Depends(authorize)])
    async def stop(robot_id: str):
        coordinator().robot(robot_id)
        acknowledgement, _ = await stop_pet_and_audio(robot_id, quiet=False)
        return acknowledgement

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
        _, result = await stop_pet_and_audio(robot_id, quiet=False)
        return result

    @app.post("/v1/pet/{robot_id}/quiet", dependencies=[Depends(operator)])
    async def pet_quiet(robot_id: str, request: QuietRequest):
        coordinator().robot(robot_id)
        if request.quiet:
            _, result = await stop_pet_and_audio(robot_id, quiet=True)
            return result
        return await app.state.runtime.pet.set_quiet(robot_id, False)

    register_memory_routes(app, settings, operator=operator)

    register_native_omni_routes(
        app, settings, authorize=authorize, coordinator=coordinator,
        native_pet_speech_policy=native_pet_speech_policy,
    )

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

    register_readonly_context_routes(
        app, settings, authorize=authorize, coordinator=coordinator,
        requested_tool_context=requested_tool_context,
        remember_tool_context=remember_tool_context,
        native_pet_speech_policy=native_pet_speech_policy,
    )

    register_readonly_planner_routes(app, settings, authorize=authorize)

    register_voice_context_route(
        app, settings, authorize=authorize,
        requested_tool_context=requested_tool_context,
        remember_tool_context=remember_tool_context,
    )

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

    @app.get("/v1/robots/{robot_id}/jobs/latest-pickup",
             dependencies=[Depends(authorize)])
    async def latest_pickup(robot_id: str, request: Request):
        """Read the Mac job owner after a head WiFi reconnect.

        A per-WebSocket remembered ID is not durable. Only jobs for this
        robot and pickup kind are visible; no job means no inferred success.
        This endpoint cannot submit, permit or retry a physical action.
        """
        try:
            settings.robot(robot_id)
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc
        owner = requested_tool_context(request, robot_id)
        matches = [
            job for job in coordinator().jobs.values()
            if job.robot_id == robot_id and job.kind == "pickup"
        ]
        if not matches:
            remember_tool_context(
                owner, robot_id, "pickup_status",
                "No Mac pickup job recorded; no grasp verified",
            )
            return {
                "robot_id": robot_id, "available": False,
                "physical_grasp_verified": False,
            }
        job = matches[-1]
        remember_tool_context(
            owner, robot_id, "pickup_status",
            f"pickup job {job.id[:24]} state={job.state}; "
            "physical grasp requires separate trial evidence",
        )
        return {"available": True, **job.data()}

    @app.get("/v1/jobs/{job_id}", dependencies=[Depends(authorize)])
    async def job(job_id: str):
        if job_id not in coordinator().jobs:
            raise HTTPException(404, "Job not found")
        return coordinator().jobs[job_id].data()

    @app.post("/v1/conversation", dependencies=[Depends(operator)])
    async def conversation(request: ChatRequest):
        try:
            # Validate first. Human conversation preempts any robot's spontaneous
            # speech, including a robot not in the requested peer subset.
            for robot_id in request.robot_ids:
                settings.robot(robot_id)  # preserve unknown-ID 404, not coordinator's 409
            # A hardware group needs a distinct peer-text sharing grant.
            # Otherwise the second model never receives the first reply,
            # even though the endpoint reports a completed conversation.
            sharing_generation = settings.fleet_sharing_consent_generation
            if settings.mode == "hardware" and not settings.fleet_text_sharing_enabled:
                raise HTTPException(409, "Enable fleet peer text sharing consent before group dialogue")
            for robot in settings.robots:
                await app.state.runtime.pet.interrupt(robot.id)
            # Preemption awaits can allow revocation and immediate regrant.
            # An older request must not inherit a newer consent epoch.
            if settings.mode == "hardware" and (
                not settings.fleet_text_sharing_enabled
                or settings.fleet_sharing_consent_generation != sharing_generation
            ):
                raise HTTPException(409, "Fleet peer text sharing consent changed during startup")
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
