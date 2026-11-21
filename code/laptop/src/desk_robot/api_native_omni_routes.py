"""The existing Xiaozhi native context, transcript and video HTTP routes.

All requests use the parent Mac API authorizer, operator consent and current
multimodal/SQLite owners. An Opus send is NOT a physical playback receipt.
This extraction does not introduce another camera or speech pipeline.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .brain_context import compose_brain_context
from .config import Settings
from .controller import OperationError


class NativeHeardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(pattern=r"^omni_[0-9a-f]{12}_[0-9a-f]{20}$")
    transcript: str = Field(min_length=1, max_length=240)


class NativeSpokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(pattern=r"^omni_sent_[0-9a-f]{12}_[0-9a-f]{20}$")
    model_text: str = Field(min_length=1, max_length=200)
    sent_at_us: int = Field(gt=0, le=9_223_372_036_854_775_807, strict=True)



def register_native_omni_routes(
    app: FastAPI, settings: Settings, *, authorize, coordinator,
    native_pet_speech_policy,
) -> None:
    @app.get("/v1/pet/{robot_id}/omni-context", dependencies=[Depends(authorize)])
    async def omni_context(robot_id: str):
        """Native audio model's personal style, with opt-in text memory only.

        Images, microphones, position, charging or actuator permissions are
        not in this prompt. This is spoken personality, not physical authority.
        """
        robot = coordinator().robot(robot_id)
        if settings.mode != "hardware" or not settings.voice_vision_tools_enabled:
            raise HTTPException(403, "Native voice and camera need explicit opt in")
        camera_grant = settings.camera_consent_generation
        prefix = (
            robot.persona[:950]
            + " You are speaking live through your own small desk robot. "
            + "Listen continuously to live microphone audio and observe "
            + "the selected live camera frames, including during silence. "
            + "Notice meaningful changes without waiting for a user request. "
            + "At each model step decide whether to speak briefly or stay "
            + "quiet; do not narrate every motion, background noise or "
            + "other people's conversation. Speak only if a new relevant "
            + "event or direct engagement warrants it. Naturally yield "
            + "to human speech and stop if the question changes. "
            + "Only make visual claims from fresh current camera images. "
            + "Never claim physical movement, docking, charging or grasping "
            + "unless an independently measured operation confirms it. "
            + "You cannot grant motor, battery or user authorization."
        )
        # Historical memory is untrusted data, not native model policy.
        # The existing voice-context tool still supports opt-in recall.
        historical_evidence = {"core": "", "recent": ""}
        if settings.voice_memory_tools_enabled:
            memory_grant = settings.voice_memory_consent_generation
            # A SQLite snapshot is valid only for the current memory
            # correction/deletion generation of this particular pet.
            owner = getattr(app.state.runtime, "conversation", None)
            revisions = getattr(owner, "_private_memory_generation", None)
            if not isinstance(revisions, dict):
                raise HTTPException(409, "Native private memory revision unavailable")
            generation = revisions.get(robot_id)
            if type(generation) is not int or generation < 0:
                raise HTTPException(409, "Native private memory revision unavailable")
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
            # Private consent can change WHILE SQLite is reading. Never
            # return historical text in a native startup persona after an
            # opt-out, even if the camera permit remains enabled.
            if (not settings.voice_memory_tools_enabled
                    or settings.voice_memory_consent_generation != memory_grant):
                raise HTTPException(403, "Native memory consent revoked during read")
            if (not settings.voice_vision_tools_enabled
                    or settings.camera_consent_generation != camera_grant):
                # Even an immediate OFF/ON replaces the old camera grant.
                # Private memory read under old live consent must not escape.
                raise HTTPException(403, "Native live consent revoked during read")
            current = getattr(
                getattr(app.state.runtime, "conversation", None),
                "_private_memory_generation", None,
            )
            # The owner and its exact per-pet integer lease must still
            # exist after SQLite yields. Never allow a missing key to
            # masquerade as generation zero or bool True as integer one.
            if (not isinstance(current, dict)
                    or type(current.get(robot_id)) is not int
                    or current[robot_id] != generation):
                raise HTTPException(409, "Private memory changed during native startup")
            # Match proactive speech's single authoritative provenance
            # formatter. A sent line is NOT a visual observation and no
            # model-estimated ASR sentence becomes an operator preference.
            context = compose_brain_context(records, core, ())
            historical_evidence = {"core": context.core, "recent": context.recent}
        return {
            "robot_id": robot_id,
            "instructions": prefix[:2000],
            "untrusted_historical_evidence": historical_evidence,
            "startup_memory_instructions_excluded": True,
            "persona": robot.persona[:900],
            "memory_enabled": settings.voice_memory_tools_enabled,
            "transcript_memory_enabled": (
                settings.voice_transcript_memory_enabled
                and settings.voice_memory_tools_enabled
            ),
            "live_transcript_context_enabled": settings.voice_vision_tools_enabled,
            # The same Mac pet state must govern the native model speaker:
            # a camera/voice consent flag alone never authorizes initiative.
            **native_pet_speech_policy(robot_id),
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
            or (settings.voice_transcript_memory_enabled
                and settings.voice_memory_tools_enabled)
        ):
            raise HTTPException(403, "Native transcript context is disabled")
        spoken = " ".join(request.transcript.split())
        if not spoken or "\x00" in spoken:
            raise HTTPException(400, "Invalid model-estimated transcript")
        visual = getattr(app.state.runtime, "multimodal", None)
        observed_at = time.monotonic()
        live_consent_generation = settings.camera_consent_generation
        ephemeral = False
        if settings.voice_vision_tools_enabled and visual is not None:
            remember = getattr(visual.hub, "remember_heard", None)
            if callable(remember):
                ephemeral = remember(
                    robot_id, request.event_id, spoken[:240], observed_at
                )
        memory_opt_in = (
            settings.voice_transcript_memory_enabled
            and settings.voice_memory_tools_enabled
        )
        memory_grant = settings.transcript_consent_generation if memory_opt_in else None
        parent_memory_grant = (
            settings.voice_memory_consent_generation if memory_opt_in else None
        )

        def transcript_grant_valid() -> bool:
            return (
                settings.voice_transcript_memory_enabled
                and settings.voice_memory_tools_enabled
                and settings.transcript_consent_generation == memory_grant
                and settings.voice_memory_consent_generation == parent_memory_grant
            )

        inserted = False
        if memory_opt_in:
            def persist_transcript_with_cleanup() -> bool:
                # Cancelling an asyncio.to_thread await never stops its SQLite
                # worker. Keep the consent fence and compensating delete in
                # that same worker, even when the HTTP caller disconnects.
                if not transcript_grant_valid():
                    return False
                added = app.state.runtime.memory.remember(
                    robot_id, request.event_id,
                    "Someone spoke (uncertain ASR): " + spoken[:240],
                    kind="heard_human", source_robot=robot_id, witnessed=True,
                    confidence=0.6,
                )
                if added and not transcript_grant_valid():
                    app.state.runtime.memory.forget_episode(
                        robot_id, request.event_id,
                    )
                    return False
                return added

            try:
                inserted = await asyncio.to_thread(persist_transcript_with_cleanup)
            except asyncio.CancelledError:
                # The HTTP request can be gone while its SQLite worker is
                # still running. That worker owns durable consent cleanup,
                # but the current event loop must retract its own transient
                # ASR receipt rather than leaving an abandoned live cue.
                if ephemeral:
                    visual.hub.discard_heard(robot_id, request.event_id)
                raise
        # A newly completed ASR can also be in the short-lived Mac timeline
        # before SQLite I/O finishes. Live context consent is separate from
        # durable transcript consent: retract only THIS newly accepted item
        # if the operator disabled live observation during the awaited write.
        if (ephemeral and (
                not settings.voice_vision_tools_enabled
                or settings.camera_consent_generation != live_consent_generation)):
            # An OFF/ON during SQLite must not re-admit prior-grant ASR.
            visual.hub.discard_heard(robot_id, request.event_id)
            ephemeral = False
        # Deletion may finish while a SQLite writer is still pending.
        # A tombstoned or already-seen event is not a NEW voice observation,
        # even when the caller replays the same authenticated HTTP receipt.
        revoked_check = (
            getattr(visual.hub, "heard_revoked", None)
            if visual is not None else None
        )
        if (ephemeral and visual is not None
                and ((memory_opt_in and not inserted)
                     or (callable(revoked_check)
                         and revoked_check(robot_id, request.event_id)))):
            discard = getattr(visual.hub, "discard_heard", None)
            if callable(discard):
                discard(robot_id, request.event_id)
            ephemeral = False
        # A private SQLite write may take longer than the operator's
        # opt-out. Remove ONLY this request's newly inserted episode if
        # permission changed during I/O; never delete an older duplicate.
        if (memory_opt_in != (
                settings.voice_transcript_memory_enabled
                and settings.voice_memory_tools_enabled
            ) or (memory_opt_in and not transcript_grant_valid())):
            if inserted:
                await asyncio.to_thread(
                    app.state.runtime.memory.forget_episode,
                    robot_id, request.event_id,
                )
            raise HTTPException(403, "Transcript storage consent changed during read")
        # Keep the same ephemeral and consented model ASR in the shared
        # Mac attention snapshot. A transcript is uncertain context only,
        # never an instruction or automatic permission to operate motors.
        attention = getattr(app.state.runtime, "attention", None)
        if ephemeral and settings.voice_vision_tools_enabled and attention is not None:
            attention.heard(
                robot_id, request.event_id, spoken[:240], observed_at
            )
        return {
            "robot_id": robot_id, "stored": inserted,
            "ephemeral_context_added": ephemeral,
            "retained_on_disk": memory_opt_in,
            "source": "model_estimated_xiaozhi_audio_transcription",
            "speaker_identity_verified": False,
            "audio_playback_verified": False,
            "motor_authorized": False,
        }

    @app.post("/v1/pet/{robot_id}/omni-spoken",
              dependencies=[Depends(authorize)])
    async def omni_spoken(robot_id: str, request: NativeSpokenRequest):
        """Share only native model text paired with transmitted XIAO Opus.

        No audio, playback claim, persistent memory, or motor permission.
        Reuses the Mac's bounded per-pet multimodal conversation timeline.
        """
        coordinator().robot(robot_id)
        if settings.mode != "hardware" or not settings.voice_vision_tools_enabled:
            raise HTTPException(403, "Native live context is disabled")
        visual = getattr(app.state.runtime, "multimodal", None)
        if visual is None:
            raise HTTPException(503, "No authenticated Mac interaction owner")
        sent_at = request.sent_at_us / 1_000_000
        added = visual.hub.remember_native_spoken(
            robot_id, request.event_id, request.model_text, sent_at,
        )
        attention = getattr(app.state.runtime, "attention", None)
        if added and attention is not None and settings.voice_vision_tools_enabled:
            # This receipt proves the server forwarded encoded audio, not
            # that the XIAO speaker acoustically played every word.
            attention.sent(robot_id, request.model_text, sent_at)
        return {
            "robot_id": robot_id,
            "ephemeral_context_added": added,
            "retained_on_disk": False,
            "source": "native_model_text_opus_sent_playback_unverified",
            "audio_playback_verified": False,
            "motor_authorized": False,
            "charging_authorized": False,
        }

    @app.get("/v1/pet/{robot_id}/omni-stream",
             dependencies=[Depends(authorize)])
    async def omni_stream(robot_id: str, request: Request):
        """One authenticated PUSH subscription to continuous Mac camera evidence.

        No extra capture or snapshot request. The selected native MiniCPM
        observer sees new frames even during silent microphone input, and a
        slow reader drops frames instead of growing a queue.
        """
        coordinator().robot(robot_id)
        if settings.mode != "hardware" or not settings.voice_vision_tools_enabled:
            raise HTTPException(403, "Physical live camera requires explicit opt in")
        # Bind this HTTP subscription to the grant at admission. The async
        # iterator may resume after a rapid opt out and regrant.
        camera_grant = settings.camera_consent_generation
        visual = getattr(app.state.runtime, "multimodal", None)
        if visual is None or not callable(getattr(visual, "native_live_frames", None)):
            raise HTTPException(503, "Continuous visual observer unavailable")

        async def events():
            last_sent = float("-inf")
            async for frame in visual.native_live_frames(robot_id):
                if await request.is_disconnected():
                    return
                # A live frame can arrive just before the operator revokes
                # vision consent, then wait here on the client socket.
                # Recheck after that await and before any JPEG is emitted.
                if (settings.mode != "hardware"
                        or not settings.voice_vision_tools_enabled
                        or settings.camera_consent_generation != camera_grant):
                    return
                now = time.monotonic()
                age_ms = round((now - frame.received_at) * 1000)
                if (not 0 <= age_ms <= 1000
                        or frame.received_at - last_sent < 0.85):
                    continue
                last_sent = frame.received_at
                yield (json.dumps({
                    "robot_id": robot_id,
                    "camera_age_ms": age_ms,
                    "camera_receipt_us": round(frame.received_at * 1_000_000),
                    "motion_ppm": round(
                        max(0.0, min(1.0, frame.motion_fraction)) * 1_000_000
                    ),
                    "source": frame.source,
                    "jpeg_base64": base64.b64encode(frame.jpeg).decode("ascii"),
                    "motor_authorized": False,
                    "charging_authorized": False,
                }, separators=(",", ":")) + "\n").encode("ascii")
        return StreamingResponse(
            events(), media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Desk-Robot-Id": robot_id,
                     "X-Content-Type-Options": "nosniff"},
        )

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
        camera_grant = settings.camera_consent_generation
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
        if (settings.mode != "hardware" or not settings.voice_vision_tools_enabled
                or settings.camera_consent_generation != camera_grant):
            raise HTTPException(403, "Camera consent revoked during capture")
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

