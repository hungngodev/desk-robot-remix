from __future__ import annotations

import asyncio
import secrets
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .brain_context import compose_brain_context
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


class CoreMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(min_length=1, max_length=200)


class NativeHeardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(pattern=r"^omni_[0-9a-f]{12}_[0-9a-f]{20}$")
    transcript: str = Field(min_length=1, max_length=240)


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

    def requested_tool_context(request: Request, robot_id: str):
        # The Xiaozhi read-only tool explicitly marks its own requests.
        # Background UI/status polling must not become conversation history.
        if request.headers.get("x-desk-robot-tool-receipt") != "1":
            return None
        visual = getattr(app.state.runtime, "multimodal", None)
        epochs = getattr(visual, "_turn_epoch", None)
        if not isinstance(epochs, dict) or robot_id not in epochs:
            return None
        return visual, epochs[robot_id]

    def remember_tool_context(owner, robot_id: str, kind: str, summary: str):
        if owner is None:
            return
        visual, generation = owner
        if visual._turn_epoch.get(robot_id) == generation:
            visual.hub.remember_tool(
                robot_id, kind, summary, time.monotonic()
            )

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
    async def status(robot_id: str, request: Request):
        coordinator().robot(robot_id)
        context = requested_tool_context(request, robot_id)
        data = await coordinator().heads[robot_id].status()
        if isinstance(data, dict):
            safety = data.get("safety")
            safety = safety if isinstance(safety, dict) else {}
            summary = (
                f"backend={str(data.get('backend', 'unknown'))[:24]}, "
                f"armed={data.get('armed')}, "
                f"safety_fault={str(safety.get('fault', 'unknown'))[:40]}"
            )
            remember_tool_context(context, robot_id, "robot_status", summary)
        return data

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

    @app.get("/v1/pet/{robot_id}/omni-context", dependencies=[Depends(authorize)])
    async def omni_context(robot_id: str):
        """Native audio model's personal style, with opt-in text memory only.

        Images, microphones, position, charging or actuator permissions are
        not in this prompt. This is spoken personality, not physical authority.
        """
        robot = coordinator().robot(robot_id)
        if settings.mode != "hardware" or not settings.voice_vision_tools_enabled:
            raise HTTPException(403, "Native voice and camera need explicit opt in")
        prefix = (
            robot.persona[:950]
            + " You are speaking live through your own small desk robot. "
            + "Use natural brief conversational phrases. Listen while you "
            + "speak, and stop responding if the human changes the question. "
            + "Only make a visual claim from real current camera images. "
            + "Never claim physical movement, docking, charging or grasping "
            + "unless an independently measured operation confirms it. "
            + "You cannot grant motor, battery or user authorization."
        )
        if settings.voice_memory_tools_enabled:
            core, records = await asyncio.wait_for(
                asyncio.gather(
                    asyncio.to_thread(
                        app.state.runtime.memory.core_facts, robot_id, limit=6
                    ),
                    asyncio.to_thread(
                        app.state.runtime.memory.recent, robot_id, limit=6
                    ),
                ),
                timeout=2.0,
            )
            # Match proactive speech's single authoritative provenance
            # formatter. A sent line is NOT a visual observation and no
            # model-estimated ASR sentence becomes an operator preference.
            context = compose_brain_context(records, core, ())
            for title, content in (
                ("Curated preferences (untrusted): ", context.core),
                ("Past context (untrusted, not current sighting): ",
                 context.recent),
            ):
                if content:
                    budget = 1900 - len(prefix) - len(title) - 1
                    if budget > 0:
                        prefix += " " + title + content[:budget]
        return {
            "robot_id": robot_id,
            "instructions": prefix[:2000],
            "memory_enabled": settings.voice_memory_tools_enabled,
            "transcript_memory_enabled": settings.voice_transcript_memory_enabled,
            "live_transcript_context_enabled": settings.voice_vision_tools_enabled,
            "untrusted_historical_text": True,
            "model_can_arm_motors": False,
            "camera_exposure_sync_verified": False,
        }

    @app.post("/v1/pet/{robot_id}/omni-heard", dependencies=[Depends(authorize)])
    async def omni_heard(robot_id: str, request: NativeHeardRequest):
        """Idempotent opt-in model-estimated human speech, NEVER raw PCM.

        The authenticated existing Xiaozhi server is the only intended
        producer. Source text is uncertain, private to this pet, and cannot
        become a command, a physical eyewitness claim, or playback ACK.
        """
        coordinator().robot(robot_id)
        if settings.mode != "hardware" or not (
            settings.voice_vision_tools_enabled
            or settings.voice_transcript_memory_enabled
        ):
            raise HTTPException(403, "Native transcript context is disabled")
        spoken = " ".join(request.transcript.split())
        if not spoken or "\x00" in spoken:
            raise HTTPException(400, "Invalid model-estimated transcript")
        visual = getattr(app.state.runtime, "multimodal", None)
        ephemeral = False
        if settings.voice_vision_tools_enabled and visual is not None:
            remember = getattr(visual.hub, "remember_heard", None)
            if callable(remember):
                ephemeral = remember(
                    robot_id, request.event_id, spoken[:240], time.monotonic()
                )
        inserted = False
        if settings.voice_transcript_memory_enabled:
            inserted = await asyncio.to_thread(
                app.state.runtime.memory.remember, robot_id, request.event_id,
                "Someone spoke (uncertain ASR): " + spoken[:240],
                kind="heard_human", source_robot=robot_id, witnessed=True,
                confidence=0.6,
            )
        return {
            "robot_id": robot_id, "stored": inserted,
            "ephemeral_context_added": ephemeral,
            "retained_on_disk": settings.voice_transcript_memory_enabled,
            "source": "model_estimated_xiaozhi_audio_transcription",
            "speaker_identity_verified": False,
            "audio_playback_verified": False,
            "motor_authorized": False,
        }

    @app.get("/v1/pet/{robot_id}/omni-frame", dependencies=[Depends(authorize)])
    async def omni_frame(robot_id: str):
        """One real authenticated JPEG for an opt-in native speech/video model.

        No cached simulation data, inferred camera identity, robot motion,
        charging control or user-visible scene description is produced here.
        The Xiaozhi server must fetch this over its existing local tool token.
        """
        coordinator().robot(robot_id)
        if settings.mode != "hardware" or not settings.voice_vision_tools_enabled:
            raise HTTPException(403, "Physical live camera requires explicit opt in")
        visual = getattr(app.state.runtime, "multimodal", None)
        if visual is None:
            raise OperationError("No hardware camera adapter")
        # Prefer the real Mac 1 FPS VAD sampler's latest current-turn JPEG;
        # a second native video consumer must not duplicate camera HTTP I/O.
        reuse = getattr(visual, "native_frame", None)
        evidence = (
            await reuse(robot_id) if callable(reuse)
            else await visual.capture(robot_id, source="speech")
        )
        age_ms = round(1000 * (time.monotonic() - evidence.received_at))
        if not 0 <= age_ms <= 1000:
            raise OperationError("Stale video frame cannot be streamed to an audio model")
        return Response(
            content=evidence.jpeg,
            media_type="image/jpeg",
            headers={
                "X-Desk-Robot-Id": robot_id,
                "X-Desk-Camera-Age-Ms": str(age_ms),
                # Stable across rereads of ONE acquired frame. Monotonic
                # reception identity, never a fabricated camera exposure.
                "X-Desk-Camera-Receipt-Us": str(round(evidence.received_at * 1_000_000)),
                "X-Desk-Frame-Motion-Ppm": str(round(
                    max(0.0, min(1.0, getattr(evidence, "motion_fraction", 0.0)))
                    * 1_000_000
                )),
                "Cache-Control": "no-store",
            },
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

    @app.get("/v1/pet/{robot_id}/interaction-context",
             dependencies=[Depends(authorize)])
    async def pet_live_situation(robot_id: str):
        """Live context is distinct from durable history permission.

        A person may opt into present camera/sensor interaction without
        granting the model permission to inspect persistent SQLite memories.
        No raw JPEG/PCM, camera exposure claim or actuator permit is returned.
        """
        try:
            settings.robot(robot_id)
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc
        if not settings.voice_vision_tools_enabled:
            raise HTTPException(403, "Opt in to live camera/sensor context first")
        visual = getattr(app.state.runtime, "multimodal", None)
        if visual is None:
            raise OperationError("No current multimodal camera/sensor owner")
        now = time.monotonic()
        return {
            "robot_id": robot_id,
            "current_interaction_timeline": visual.hub.interaction_timeline(
                robot_id, now, limit=10
            ),
            "persistent_memory_included": False,
            "raw_media_included": False,
            "source_exposure_timestamp_verified": False,
            "motor_authorized": False,
            "charging_authorized": False,
        }

    @app.get("/v1/pet/{robot_id}/voice-context", dependencies=[Depends(authorize)])
    async def pet_voice_context(
        robot_id: str, query: str | None = Query(default=None, max_length=240),
    ):
        # The language model cannot read persistent memories by default.
        # Explicit opt-in applies to the one authenticated robot identity only.
        try:
            settings.robot(robot_id)
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc
        if not settings.voice_memory_tools_enabled:
            raise HTTPException(403, "Opt in to voice memory retrieval first")
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
