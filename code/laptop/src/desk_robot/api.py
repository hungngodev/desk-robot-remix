from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .api_dock_routes import register_dock_routes
from .api_ingress import APIIngress, authorized_token, token_matches
from .api_lifecycle import require_runtime_ready, runtime_ready
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
from .api_spatial_pose import register_spatial_pose_route
from .config import Settings, api_credentials, quiet_hours_active, secret
from .controller import OperationError
from .conversation import conversation_turns
from .operations import _bounded_head_reply
from .runtime import Runtime
from .transport import HeadError

_PET_SHUTDOWN_TIMEOUT_S = 1.0
_TOOL_RECEIPT_MAX_AGE_US = 5_000_000
_TOOL_RECEIPT_REPLAY_TTL_S = 10.0


def _tool_receipt_message(
    robot_id: str,
    device_id: str,
    generation: int,
    method: str,
    path: str,
    issued_us: int,
    receipt_id: str,
) -> bytes:
    """Canonical bridge to Mac receipt payload, never model supplied text."""
    return json.dumps(
        [1, robot_id, device_id, generation, method.upper(), path, issued_us, receipt_id],
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


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


async def _bounded_cleanup(coro, *, seconds: float, message: str):
    """A cancelled but uncooperative adapter must not block later STOPs."""
    return await _bounded_head_reply(coro, seconds=seconds, timeout_message=message)


def create_app(settings: Settings, runtime: Runtime | None = None) -> FastAPI:
    security = HTTPBearer(auto_error=False)

    @asynccontextmanager
    async def lifespan(app):
        # Separate operator and model credentials: models cannot mint motion permits.
        app.state.operator_token, app.state.tool_token = api_credentials(settings)
        app.state.runtime = runtime if runtime is not None else await Runtime.create(settings)
        app.state.runtime_started = False
        cancelled = False
        try:
            start = getattr(app.state.runtime, "start", None)
            if callable(start):
                await start()
            app.state.runtime_started = True
            yield
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            app.state.runtime_started = False
            try:
                await app.state.runtime.close()
            except Exception as error:
                if not cancelled:
                    raise
                logging.getLogger(__name__).error(
                    "Runtime shutdown failed after lifespan cancellation", exc_info=error,
                )

    app = FastAPI(title="Desk robot controls", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        APIIngress, tokens=lambda: (app.state.operator_token, app.state.tool_token),
        mode=settings.mode,
    )
    consumed_tool_receipts: dict[str, float] = {}
    group_request_active = False

    async def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        if (
            credentials is None
            or not credentials.credentials.isascii()
            or not authorized_token(
                credentials.credentials, app.state.operator_token, app.state.tool_token,
            )
        ):
            raise HTTPException(401, "A valid private token is required")

    async def operator(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        if (
            credentials is None
            or not credentials.credentials.isascii()
            or not token_matches(credentials.credentials, app.state.operator_token)
        ):
            raise HTTPException(403, "Only the operator can enable movement")

    @app.get("/v1/health", dependencies=[Depends(operator)])
    async def health() -> JSONResponse:
        """Report Mac lifecycle, not physical connectivity or movement authority."""
        owner = app.state.runtime
        ready = runtime_ready(app.state)
        warnings = []
        if settings.mode == "simulation":
            warnings.append({"code": "simulation_mode"})
        else:
            warnings.append({"code": "hardware_connectivity_not_verified_by_health"})
        room = getattr(owner, "room_feed", None)
        if settings.room_station_enabled and getattr(room, "last_error", None):
            warnings.append({"code": "room_usb_unavailable"})
        if not ready:
            warnings.append({"code": "runtime_unavailable"})
        return JSONResponse(
            {
                "mode": settings.mode,
                "runtime_ready": ready,
                "physical_acceptance_pass": False,
                "warnings": warnings,
            },
            status_code=200 if ready else 503,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # FastAPI's default errors echo rejected inputs. Nonfinite numbers
        # and escaped Unicode surrogates then crash JSONResponse itself.
        # Keep useful field diagnostics without serializing rejected values.
        def safe(value: str) -> str:
            return value.encode("utf-8", "backslashreplace").decode("utf-8")

        errors = [
            {
                "type": error["type"],
                "loc": [
                    safe(value) if isinstance(value, str) else value
                    for value in error["loc"]
                ],
                "msg": safe(error["msg"]),
            }
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(OperationError)
    async def operation_error(request, exc):
        return JSONResponse(status_code=409, content={"error": str(exc)})

    @app.exception_handler(HeadError)
    async def head_error(request, exc):
        return JSONResponse(status_code=503, content={"error": str(exc)})

    @app.exception_handler(TimeoutError)
    async def deadline_error(request, exc):
        return JSONResponse(
            status_code=503,
            content={"error": str(exc) or "Hardware deadline exceeded"},
        )

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
        # The tool bearer authorizes the bounded Mac route, but it is not proof
        # that this HTTP request came from the active Xiaozhi voice turn.
        authorization = request.headers.get("authorization", "")
        scheme, separator, credential = authorization.partition(" ")
        if (scheme.lower() != "bearer" or not separator
                or not credential.isascii()
                or not secrets.compare_digest(credential, app.state.tool_token)):
            return None
        try:
            configured_device = settings.robot(robot_id).device_id
        except KeyError:
            return None
        receipt_id = request.headers.get("x-desk-robot-tool-receipt-id", "")
        issued_text = request.headers.get("x-desk-robot-tool-receipt-at-us", "")
        device_id = request.headers.get("x-desk-robot-tool-receipt-device", "")
        generation_text = request.headers.get(
            "x-desk-robot-tool-receipt-generation", ""
        )
        signature = request.headers.get("x-desk-robot-tool-receipt-signature", "")
        if (
            not configured_device
            or device_id != configured_device
            or len(receipt_id) != 32
            or any(char not in "0123456789abcdef" for char in receipt_id)
            or len(signature) != 64
            or any(char not in "0123456789abcdef" for char in signature)
            or not 1 <= len(issued_text) <= 19
            or not issued_text.isascii()
            or not issued_text.isdigit()
            or not 1 <= len(generation_text) <= 19
            or not generation_text.isascii()
            or not generation_text.isdigit()
        ):
            return None
        issued_us = int(issued_text)
        generation = int(generation_text)
        if generation > 0x7fffffffffffffff:
            return None
        now_us = time.time_ns() // 1000
        if abs(now_us - issued_us) > _TOOL_RECEIPT_MAX_AGE_US:
            return None
        try:
            signing_token = secret(settings.speech_bridge_token_env)
        except ValueError:
            return None
        if secrets.compare_digest(signing_token, app.state.tool_token):
            return None
        expected = hmac.new(
            signing_token.encode("utf-8"),
            _tool_receipt_message(
                robot_id,
                device_id,
                generation,
                request.method,
                request.url.path,
                issued_us,
                receipt_id,
            ),
            hashlib.sha256,
        ).hexdigest()
        if not secrets.compare_digest(signature, expected):
            return None

        runtime_owner = app.state.runtime
        visual = getattr(runtime_owner, "multimodal", None)
        epochs = getattr(visual, "_turn_epoch", None)
        source_generations = getattr(runtime_owner, "_voice_turn_generations", None)
        listener = getattr(runtime_owner, "voice_events", None)
        listener_epoch = getattr(listener, "_event_generation", None)
        # Mac camera epochs cancel local work; they are NOT signed Xiaozhi
        # voice generations. The active authenticated server stream must
        # independently own the exact signed generation before any read.
        if (
            not isinstance(epochs, dict)
            or type(epochs.get(robot_id)) is not int
            or not isinstance(source_generations, dict)
            or type(source_generations.get(robot_id)) is not int
            or source_generations[robot_id] != generation
            or getattr(listener, "monitor_ready", False) is not True
            or type(listener_epoch) is not int
            or listener_epoch < 0
            or getattr(
                getattr(runtime_owner, "pet", None), "voice_monitor_ready", False
            ) is not True
        ):
            return None

        # Every signed bridge request is a one-shot provenance receipt.
        # Prune only expired IDs and consume after all authentication checks.
        now = time.monotonic()
        for old_id, expires_at in tuple(consumed_tool_receipts.items()):
            if expires_at <= now:
                consumed_tool_receipts.pop(old_id, None)
        if receipt_id in consumed_tool_receipts:
            return None
        consumed_tool_receipts[receipt_id] = now + _TOOL_RECEIPT_REPLAY_TTL_S
        return visual, epochs[robot_id], generation, listener, listener_epoch

    def current_tool_context(owner, robot_id: str, message: str) -> None:
        """Reject a completed tool result if EITHER independent turn moved."""
        runtime_owner = app.state.runtime
        if not isinstance(owner, tuple) or len(owner) != 5:
            raise HTTPException(409, message)
        visual, mac_epoch, source_generation, listener, listener_epoch = owner
        epochs = getattr(visual, "_turn_epoch", None)
        source_generations = getattr(runtime_owner, "_voice_turn_generations", None)
        if (
            getattr(runtime_owner, "multimodal", None) is not visual
            or not isinstance(epochs, dict)
            or type(mac_epoch) is not int
            or epochs.get(robot_id) != mac_epoch
            or not isinstance(source_generations, dict)
            or type(source_generation) is not int
            or source_generations.get(robot_id) != source_generation
            or getattr(runtime_owner, "voice_events", None) is not listener
            or getattr(listener, "monitor_ready", False) is not True
            or type(listener_epoch) is not int
            or getattr(listener, "_event_generation", None) != listener_epoch
            or getattr(
                getattr(runtime_owner, "pet", None), "voice_monitor_ready", False
            ) is not True
        ):
            raise HTTPException(409, message)

    def remember_tool_context(owner, robot_id: str, kind: str, summary: str) -> bool:
        if owner is None:
            return False
        current_tool_context(owner, robot_id, "Voice tool result superseded")
        visual = owner[0]
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
            "pet_quiet": state.quiet is True or quiet_hours_active(settings.pet_quiet_hours),
        }

    register_robot_status_routes(
        app, settings, authorize=authorize, coordinator=coordinator,
        requested_tool_context=requested_tool_context,
        remember_tool_context=remember_tool_context,
        current_tool_context=current_tool_context,
    )

    register_spatial_pose_route(
        app,
        operator=operator,
        coordinator=coordinator,
        authorize=authorize,
        settings=settings,
        spatial=lambda: getattr(app.state.runtime, "spatial", None),
        motion_ready=require_runtime_ready,
    )

    register_dock_routes(
        app, settings, authorize=authorize, operator=operator, coordinator=coordinator,
    )

    # Raw JPEG preview is an operator action, never a privilege granted by
    # the read-only Xiaozhi model/tool token. Conversed visual facts have
    # separately consented, bounded /v1/pet/* routes.
    @app.get("/v1/robots/{robot_id}/camera.jpg", dependencies=[Depends(operator)])
    async def camera(robot_id: str):
        coordinator().robot(robot_id)
        head = coordinator().heads.get(robot_id)
        snapshot = getattr(head, "snapshot", None)
        if not callable(snapshot):
            raise HTTPException(503, "Robot camera unavailable")
        return Response(
            await snapshot(),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/v1/robots/{robot_id}/enable",
              dependencies=[Depends(operator), Depends(require_runtime_ready)])
    async def enable(robot_id: str):
        return await coordinator().operator_arm(robot_id)

    @app.post("/v1/robots/{robot_id}/move", dependencies=[Depends(operator)], status_code=202)
    async def move(
        robot_id: str, request: CommandRequest, http_request: Request, defer_on_voice: bool = False,
    ):
        await require_runtime_ready(http_request)
        coord = coordinator()
        if defer_on_voice and coord.voice_blocks_motion():
            return coord.defer_motion(
                robot_id, "manual",
                submit_fn=lambda: coord.manual(robot_id, request.command),
            ).data()
        return coord.manual(robot_id, request.command).data()

    @app.post("/v1/robots/{robot_id}/explore",
              dependencies=[Depends(operator), Depends(require_runtime_ready)], status_code=202)
    async def explore(robot_id: str, defer_on_voice: bool = False):
        if app.state.runtime.pet.states[robot_id].quiet:
            raise OperationError("Quiet mode blocks exploration")
        coord = coordinator()
        if defer_on_voice and coord.voice_blocks_motion():
            return coord.defer_motion(
                robot_id, "exploration",
                submit_fn=lambda: coord.explore(robot_id),
                consent_check=lambda: (
                    not app.state.runtime.pet.states[robot_id].quiet
                    and coord.robot(robot_id).exploration_qualified
                ),
            ).data()
        return coord.explore(robot_id).data()

    # A spoken key/candy request may consume ONE recent operator-granted
    # permit; the model cannot mint or extend that permit itself.
    @app.post("/v1/robots/{robot_id}/pickup", dependencies=[Depends(authorize)], status_code=202)
    async def pickup(
        robot_id: str, request: PickupRequest, http_request: Request, defer_on_voice: bool = False,
    ):
        await require_runtime_ready(http_request)
        coord = coordinator()
        if defer_on_voice and coord.voice_blocks_motion():
            return coord.defer_motion(
                robot_id, "pickup",
                submit_fn=lambda: coord.pickup(robot_id, request.target),
            ).data()
        return coord.pickup(robot_id, request.target).data()

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
        await _bounded_cleanup(
            interrupt(robot), seconds=2.5,
            message="XIAO speech interruption unconfirmed",
        )

    async def stop_pet_and_audio(robot_id: str, *, quiet: bool):
        """Stop body, pet initiative, and native speaker concurrently.

        Cleanup must run despite previous failures. Crucially, a slow or
        blocked WROOM STOP must never delay urgent XIAO speaker interruption,
        while a failed WROOM STOP stays the primary failure over secondary
        pet or speaker cleanup failures.
        """
        async def _stop_pet():
            operation = (
                app.state.runtime.pet.set_quiet(robot_id, True)
                if quiet else app.state.runtime.pet.pause(robot_id)
            )
            return await _bounded_cleanup(
                operation, seconds=_PET_SHUTDOWN_TIMEOUT_S,
                message="Pet pause timeout; speaker STOP still required",
            )

        body_res, pet_res, audio_res = await asyncio.gather(
            coordinator().stop(robot_id),
            _stop_pet(),
            stop_native_pet_speech(robot_id),
            return_exceptions=True,
        )
        failures: list[tuple[str, BaseException]] = []
        for stage, outcome in (
            ("WROOM STOP", body_res),
            ("pet pause", pet_res),
            ("XIAO speech STOP", audio_res),
        ):
            if isinstance(outcome, BaseException):
                failures.append((stage, outcome))
        if failures:
            primary = failures[0][1]
            for stage, secondary in failures[1:]:
                primary.add_note(
                    f"Additional {stage} failure: {type(secondary).__name__}"
                )
            raise primary
        return body_res, pet_res

    @app.post("/v1/robots/{robot_id}/stop", dependencies=[Depends(authorize)])
    async def stop(robot_id: str):
        coordinator().robot(robot_id)
        acknowledgement, _ = await stop_pet_and_audio(robot_id, quiet=False)
        return acknowledgement

    @app.get("/v1/pet/{robot_id}", dependencies=[Depends(authorize)])
    async def pet_status(robot_id: str):
        coordinator().robot(robot_id)
        return app.state.runtime.pet.status(robot_id)

    @app.post("/v1/pet/{robot_id}/start",
              dependencies=[Depends(operator), Depends(require_runtime_ready)])
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
        current_tool_context=current_tool_context,
        native_pet_speech_policy=native_pet_speech_policy,
    )

    register_readonly_planner_routes(
        app, settings, authorize=authorize,
        requested_tool_context=requested_tool_context,
        current_tool_context=current_tool_context,
    )

    register_voice_context_route(
        app, settings, authorize=authorize,
        requested_tool_context=requested_tool_context,
        remember_tool_context=remember_tool_context,
        current_tool_context=current_tool_context,
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
        loss = any(event.startswith("object_lost:") for event in job.events)
        hold_note = (
            "object_lost: fresh jaw contact low; hold unverified; no retry; "
            if loss else ""
        )
        remember_tool_context(
            owner, robot_id, "pickup_status",
            f"{hold_note}pickup job {job.id[:24]} state={job.state}; "
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
        nonlocal group_request_active
        if group_request_active:
            raise HTTPException(409, "A conversation request is already active")
        group_request_active = True
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
                raise HTTPException(
                    409, "Enable fleet peer text sharing consent before group dialogue"
                )
            owner = app.state.runtime.conversation
            if owner.active is not None and not owner.active.done():
                raise HTTPException(409, "A conversation is already active")
            stop_generation = owner.stop_generation
            for robot in settings.robots:
                await app.state.runtime.pet.interrupt(robot.id)
                if (app.state.runtime.conversation is not owner
                        or owner.stop_generation != stop_generation):
                    raise HTTPException(409, "Conversation startup superseded by STOP")
            # Preemption awaits can allow revocation and immediate regrant.
            # An older request must not inherit a newer consent epoch.
            if settings.mode == "hardware" and (
                not settings.fleet_text_sharing_enabled
                or settings.fleet_sharing_consent_generation != sharing_generation
            ):
                raise HTTPException(409, "Fleet peer text sharing consent changed during startup")
            transcript = await owner.run(
                request.robot_ids, request.topic, request.utterances
            )
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            group_request_active = False
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
