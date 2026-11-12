"""Bounded voice + camera context for the existing Xiaozhi and Mac runtime.

Reuses LiveKit's VAD-adaptive frame cadence and Frigate's motion-first
inference strategy. These are algorithmic reuses, not new media transports.
Only the authenticated XIAO head supplies JPEGs. Frames live in RAM only,
are never persisted, never authorize motors and expire on disconnect/close.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import math
import re
import time
from collections import deque
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image, ImageOps, ImageStat

if TYPE_CHECKING:
    from .config import Settings
    from .transport import Head
    from .vision import OllamaScene

TEMPORAL_WORDS = re.compile(
    r"\b(chang(?:e|ed|ing)|mov(?:e|ed|ing)|happen(?:ed|ing)?|"
    r"before|after|just|appear(?:ed)?|disappear(?:ed)?|"
    r"pick(?:ed)?|put|drop(?:ped)?)\b", re.I
)

TRIGGERS = frozenset({
    "human_voice", "touch", "touch_tap", "touch_double", "touch_hold",
    "petting_zone", "hand_wave", "nearby_object", "nose_twist",
    "squeeze", "bumper", "magnet", "pir", "battery_low", "safety_fault",
    "handling_tilt", "handling_shake",
    "side_object", "paw_contact", "ambient_shift", "nfc_tag",
})


def _finite(value: float) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _prepare(jpeg: bytes, max_side: int = 768) -> tuple[bytes, bytes, float]:
    """Encode bounded JPEG for the VLM and a tiny grayscale motion fingerprint."""
    if not isinstance(jpeg, bytes) or not 12 <= len(jpeg) <= 4_000_000:
        raise ValueError("Camera JPEG size invalid")
    with Image.open(BytesIO(jpeg)) as im:
        if im.format != "JPEG":
            raise ValueError("Authenticated camera source must return JPEG")
        im.load()
        if not 1 <= im.width <= 4096 or not 1 <= im.height <= 4096:
            raise ValueError("Camera dimensions invalid")
        rgb = ImageOps.exif_transpose(im).convert("RGB")
    rgb.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
    gray = ImageOps.grayscale(rgb).resize((64, 48))
    fingerprint = gray.tobytes()
    brightness = ImageStat.Stat(gray).mean[0]
    out = BytesIO()
    rgb.save(out, "JPEG", quality=78, optimize=True)
    encoded = out.getvalue()
    if len(encoded) > 1_000_000:
        raise ValueError("VLM JPEG exceeds bounded in-memory frame")
    return encoded, fingerprint, brightness


def change_fraction(a: bytes, b: bytes, *, threshold: int = 16) -> float:
    """Ignore broad lighting shifts before detecting localized motion.

    This cheap gate is not calibrated optical flow or object tracking.
    """
    if len(a) != len(b) or len(a) != 64 * 48:
        raise ValueError("Frame fingerprints have incompatible dimensions")
    shift = sum(y - x for x, y in zip(a, b, strict=True)) / len(a)
    return sum(
        1 for x, y in zip(a, b, strict=True)
        if abs((y - x) - shift) >= threshold
    ) / len(a)


@dataclass(frozen=True)
class CameraEvidence:
    jpeg: bytes
    received_at: float  # Mac receive time, NOT sensor exposure time.
    motion_fraction: float
    source: str


class CameraFrameHub:
    """Per-robot tiny RAM-only buffer with priority hints and bounded cadence.

    Cadence resembles LiveKit VoiceActivityVideoSampler, with event priority
    and a cheap Frigate-style motion score. No continuous video is claimed.
    """

    def __init__(
        self, robot_ids: list[str], *,
        idle_fps: float = 0.30, speaking_fps: float = 1.0,
        active_fps: float = 0.8, max_frames: int = 3,
    ):
        if not robot_ids or len(set(robot_ids)) != len(robot_ids):
            raise ValueError("Unique camera source identities required")
        if any(not _finite(v) or not 0 < v <= 5 for v in
               (idle_fps, speaking_fps, active_fps)):
            raise ValueError("Invalid adaptive camera frame cadence")
        if not 2 <= max_frames <= 4:
            raise ValueError("Frame storage must remain bounded")
        self.robots = frozenset(robot_ids)
        self.idle_fps, self.speaking_fps = idle_fps, speaking_fps
        self.active_fps = active_fps
        self.frames: dict[str, deque[CameraEvidence]] = {
            robot: deque(maxlen=max_frames) for robot in robot_ids
        }
        self.last_capture = {robot: -math.inf for robot in robot_ids}
        self.voice_until = {robot: -math.inf for robot in robot_ids}
        self.urgent = {robot: False for robot in robot_ids}
        # A captured JPEG may be resizing on a worker while a newer frame,
        # pause, or reconnect supersedes it. Only its owner can publish it.
        self._generation = {robot: 0 for robot in robot_ids}
        self.previous_gray: dict[str, bytes] = {}
        self.changed_streak = {robot: 0 for robot in robot_ids}
        # Provenance-tagged VAD/touch/gesture hints travel alongside visual
        # evidence. No inferred object detection, identity, raw PCM or video.
        self.event_history = {
            robot: deque(maxlen=12) for robot in robot_ids
        }
        # Ephemeral successful tool interpretations accompany sensor cues,
        # not raw JPEG/PCM or persistent user memories. One existing owner.
        self.tool_history = {
            robot: deque(maxlen=4) for robot in robot_ids
        }

    def _check(self, robot_id: str) -> None:
        if robot_id not in self.robots:
            raise ValueError("Unknown robot camera identity")

    def notify(self, robot_id: str, kind: str, now: float) -> None:
        self._check(robot_id)
        if kind not in TRIGGERS or not _finite(now):
            raise ValueError("Unknown physical event or invalid time")
        self.urgent[robot_id] = True
        self.event_history[robot_id].append((kind, now))
        if kind == "human_voice":
            # Real Xiaozhi speech_end (or explicit disconnect/clear) owns
            # release. A 7s guess previously unmuted proactive speech while
            # someone was still talking. Missing end must fail quiet.
            self.voice_until[robot_id] = math.inf

    def barge_in(self, robot_id: str, now: float) -> None:
        """AEC double talk has no guaranteed matching speech_end event.

        Keep a bounded conservative VAD hold for this event, but preserve an
        existing explicit idle speech_start lease if one already exists.
        The head's urgent audio flush is a separate higher priority path.
        """
        explicit_turn_active = self.voice_until[robot_id] == math.inf
        self.notify(robot_id, "human_voice", now)
        if not explicit_turn_active:
            self.voice_until[robot_id] = now + 7.0

    def speech_ended(self, robot_id: str, now: float) -> None:
        """End a VAD-confirmed user utterance without dropping its last images."""
        self._check(robot_id)
        if not _finite(now):
            raise ValueError("Invalid VAD end timestamp")
        self.voice_until[robot_id] = min(self.voice_until[robot_id], now)

    def reconcile_speech_snapshot(self, active: frozenset[str], now: float) -> None:
        """Reconcile missed idle VAD edges using the authenticated server state.

        Never touch finite AEC double-talk leases: the server cannot promise
        their matching speech_end. Only a real authenticated snapshot is a
        permissible source for restoring/releasing explicit idle VAD turns.
        """
        if not isinstance(active, frozenset) or not active <= self.robots or not _finite(now):
            raise ValueError("Untrusted VAD snapshot or invalid time")
        for robot_id in self.robots:
            if robot_id in active:
                self.voice_until[robot_id] = math.inf
            elif self.voice_until[robot_id] == math.inf:
                self.voice_until[robot_id] = now

    def user_active(self, robot_id: str, now: float) -> bool:
        self._check(robot_id)
        return _finite(now) and now < self.voice_until[robot_id]

    def due(self, robot_id: str, now: float) -> bool:
        self._check(robot_id)
        if not _finite(now):
            raise ValueError("Invalid clock")
        if self.urgent[robot_id]:
            return True
        fps = (
            self.speaking_fps if self.user_active(robot_id, now)
            else self.active_fps if self.changed_streak[robot_id]
            else self.idle_fps
        )
        return now - self.last_capture[robot_id] >= 1 / fps

    def offer(self, robot_id: str, jpeg: bytes, received_at: float,
              *, source: str) -> CameraEvidence:
        return self.offer_prepared(
            robot_id, _prepare(jpeg), received_at, source=source
        )

    def offer_prepared(self, robot_id: str, prepared: tuple[bytes, bytes, float],
                       received_at: float, *, source: str,
                       generation: int | None = None) -> CameraEvidence:
        """Commit preprocessed media on its single event-loop owner.

        Image decoding may run in a worker, but no worker can mutate this hub.
        Old captures after pause/reconnect or new capture commit are rejected.
        """
        self._check(robot_id)
        if generation is not None and generation != self._generation[robot_id]:
            raise RuntimeError("Old camera generation discarded")
        if not _finite(received_at) or source not in {
            "proactive", "speech", "voice_question", "sensor"
        }:
            raise ValueError("Unknown image source or invalid time")
        if received_at <= self.last_capture[robot_id]:
            raise ValueError("Out of order camera reception timestamp")
        reduced, gray, _ = prepared
        if (not isinstance(reduced, bytes) or not reduced.startswith(b"\xff\xd8")
                or len(reduced) > 1_000_000 or not isinstance(gray, bytes)
                or len(gray) != 64 * 48):
            raise ValueError("Invalid preprocessed camera evidence")
        prev = self.previous_gray.get(robot_id)
        motion = change_fraction(prev, gray) if prev is not None else 0.0
        self.previous_gray[robot_id] = gray
        self.changed_streak[robot_id] = (
            min(3, self.changed_streak[robot_id] + 1) if motion >= 0.01
            else 0
        )
        self.last_capture[robot_id] = received_at
        self.urgent[robot_id] = False
        evidence = CameraEvidence(reduced, received_at, motion, source)
        self.frames[robot_id].append(evidence)
        return evidence

    def selected(self, robot_id: str, question: str, now: float
                 ) -> list[CameraEvidence]:
        self._check(robot_id)
        if not _finite(now):
            raise ValueError("Invalid clock")
        fresh = [
            item for item in self.frames[robot_id]
            if 0 <= now - item.received_at <= 6
        ]
        if not fresh:
            return []
        latest = fresh[-1]
        if not TEMPORAL_WORDS.search(question) or len(fresh) < 2:
            return [latest]
        # A motion peak marks the AFTER frame, not the BEFORE frame.
        # Comparing that peak with a subsequent identical latest frame would
        # make a freshly added object appear unchanged. Use the frame directly
        # preceding the strongest transition, then the latest observation.
        # If the strongest transition is the newest frame, choose its
        # predecessor. All frames must belong to this exact robot identity.
        transition = max(
            range(1, len(fresh)),
            key=lambda index: fresh[index].motion_fraction,
        )
        prior = fresh[transition - 1]
        return [prior, latest]

    def recent_events(self, robot_id: str, now: float) -> list[dict]:
        self._check(robot_id)
        if not _finite(now):
            raise ValueError("Invalid event context time")
        return [
            {
                "kind": kind,
                "age_ms": round(1000 * (now - seen_at)),
                "source": "xiaozhi_vad" if kind == "human_voice"
                          else "wroom_sensed_event",
            }
            for kind, seen_at in list(self.event_history[robot_id])[-6:]
            if 0 <= now - seen_at <= 8.0
        ]

    def remember_tool(self, robot_id: str, kind: str, summary: str,
                      received_at: float) -> None:
        """Accept only completed current-turn read-only tool interpretations.

        Failed/cancelled tool outputs must never enter the next interaction.
        Tool text is model-generated *opinion*, not a witnessed physical fact,
        instruction or actuator permit. It expires from RAM in eight seconds.
        """
        self._check(robot_id)
        if (kind != "visual_look" or not isinstance(summary, str)
                or not 1 <= len(summary.strip()) <= 2000
                or not _finite(received_at)):
            raise ValueError("Invalid read-only visual tool evidence")
        cleaned = " ".join(summary.split())[:160]
        if cleaned:
            self.tool_history[robot_id].append((kind, cleaned, received_at))

    def recent_tool_context(self, robot_id: str, now: float) -> list[dict]:
        self._check(robot_id)
        if not _finite(now):
            raise ValueError("Invalid interaction context clock")
        return [
            {
                "kind": kind,
                "summary": summary,
                "age_ms": round(1000 * (now - observed)),
                "source": "local_vlm_interpretation_not_physical_measurement",
                "untrusted_text_not_instructions": True,
                "motor_authorized": False,
            }
            for kind, summary, observed in self.tool_history[robot_id]
            if 0 <= now - observed <= 8.0
        ]

    def discard_video(self, robot_id: str) -> None:
        """Drop failed camera evidence without releasing a live human VAD turn."""
        self._check(robot_id)
        self._generation[robot_id] += 1
        self.frames[robot_id].clear()
        self.tool_history[robot_id].clear()
        self.previous_gray.pop(robot_id, None)
        self.last_capture[robot_id] = -math.inf
        self.changed_streak[robot_id] = 0
        self.urgent[robot_id] = False

    def clear(self, robot_id: str) -> None:
        self.discard_video(robot_id)
        self.event_history[robot_id].clear()
        self.voice_until[robot_id] = -math.inf

    def close(self) -> None:
        for robot_id in self.robots:
            self.clear(robot_id)


class MultimodalOrchestrator:
    """Adapt real Xiaozhi audio events and head JPEGs into one Mac VLM owner."""

    def __init__(self, settings: "Settings", heads: dict[str, "Head"],
                 scene: "OllamaScene", inference_lock: asyncio.Lock):
        self.settings = settings
        self.heads = heads
        self.scene = scene
        self.inference_lock = inference_lock
        self.hub = CameraFrameHub([r.id for r in settings.robots])
        self._capture_tasks: dict[str, asyncio.Task] = {}
        self._sensor_tasks: dict[str, asyncio.Task] = {}
        # Own only the optional HTTP snapshot, not its permanent pet loop.
        self._proactive_snapshots: dict[str, asyncio.Task] = {}
        self._last_sensor_request = {r.id: -math.inf for r in settings.robots}
        self._look_tasks: dict[str, asyncio.Task] = {}
        self._camera_locks = {
            robot.id: asyncio.Lock() for robot in settings.robots
        }
        # Prevent five large JPEG decoders/encoders from running at once.
        # Own actual native JPEG lifetime, not a cancellable asyncio wrapper.
        self._preprocess_slots = threading.BoundedSemaphore(2)
        # Allow at most one optional background decode: reserve capacity for
        # a genuine authenticated human speech or direct visual question.
        self._optional_preprocess_slot = threading.BoundedSemaphore(1)
        self._preprocess_pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="desk-jpeg"
        )
        self._vision_timeout_s = 15.0  # bounded responsiveness, not SLA
        self._metrics = {
            robot.id: {
                "camera_requests": 0, "camera_successes": 0,
                "camera_errors": 0, "visual_questions": 0,
                "visual_answers": 0, "visual_errors": 0,
                "camera_latency_last_ms": None,
                "model_latency_last_ms": None,
                "sensor_triggers": 0, "sensor_bursts": 0,
                "sensor_coalesced": 0, "sensor_deferred_human": 0,
                "sensor_trigger_to_first_jpeg_last_ms": None,
                "sensor_followup_frames": 0, "proactive_camera_preemptions": 0,
                "native_speech_camera_reuses": 0,
            } for robot in settings.robots
        }
        self._turn_epoch = {r.id: 0 for r in settings.robots}
        self._voice_turn_at = {r.id: -math.inf for r in settings.robots}
        self._question_epoch = {r.id: 0 for r in settings.robots}
        # Only a fresh authenticated VAD snapshot may restart a sampler
        # cancelled during a server event gap, never an arbitrary timer.
        self._reconnect_needs_sampler: set[str] = set()
        self._closed = False

    def status(self, robot_id: str) -> dict:
        self.hub._check(robot_id)
        return {
            "robot_id": robot_id,
            "frames_in_ram": len(self.hub.frames[robot_id]),
            "software_timings": dict(self._metrics[robot_id]),
            "voice_trigger_until_monotonic": (
                self.hub.voice_until[robot_id]
                if math.isfinite(self.hub.voice_until[robot_id]) else None
            ),
            "last_camera_received_at": (
                self.hub.frames[robot_id][-1].received_at
                if self.hub.frames[robot_id] else None
            ),
            "multimodal_model_configured": bool(self.settings.vision_model),
            "source_exposure_time_verified": False,
            "physical_vad_video_sync_verified": False,
            "motor_authorized": False,
        }

    def sensor_event(self, robot_id: str, kind: str) -> None:
        """Fast event priority, separate from VLM, TTS and WROOM motion.

        Schedule at most one bounded two-frame confirmation burst per head
        in an 800 ms coalescing window, never a second camera owner.
        The existing capture lock still serializes real XIAO JPEG requests.
        """
        now = time.monotonic()
        self.hub.notify(robot_id, kind, now)
        self._metrics[robot_id]["sensor_triggers"] += 1
        if self._closed or self._any_human_active(now):
            self._metrics[robot_id]["sensor_deferred_human"] += 1
            return  # any live human voice owns the fleet's camera priority
        self._cancel_proactive_snapshot(robot_id)
        pending = self._sensor_tasks.get(robot_id)
        if (pending is not None and not pending.done()
                or now - self._last_sensor_request[robot_id] < 0.8):
            self._metrics[robot_id]["sensor_coalesced"] += 1
            return
        self._last_sensor_request[robot_id] = now
        self._metrics[robot_id]["sensor_bursts"] += 1
        self._sensor_tasks[robot_id] = asyncio.create_task(
            self._sensor_frame(robot_id, requested_at=now)
        )

    async def _sensor_frame(self, robot_id: str, *, requested_at: float) -> None:
        """Confirm a triggered scene using at most two fresh device frames.

        A single capture populates context but cannot confirm that an object
        actually appeared. One short follow-up gives the existing
        VisualChangeGate two independent image acquisitions without launching
        another camera driver, VLM worker or inference while the user speaks.
        """
        try:
            for index in range(2):
                if index:
                    await asyncio.sleep(0.45)
                question = self._look_tasks.get(robot_id)
                if (self._closed or self._any_human_active(
                    time.monotonic()
                ) or (question is not None and not question.done())):
                    return
                evidence = await self.capture(robot_id, source="sensor")
                if index == 0:
                    # This clock starts with the Mac receiving a real sensor
                    # edge; camera exposure timing on the XIAO is unknown.
                    self._metrics[robot_id][
                        "sensor_trigger_to_first_jpeg_last_ms"
                    ] = round(max(0, evidence.received_at - requested_at) * 1000)
                else:
                    self._metrics[robot_id]["sensor_followup_frames"] += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            # Metrics already capture request/error; preserve older valid
            # camera frames and never touch the authenticated human VAD lease.
            pass

    def sensor_burst_pending(self, robot_id: str) -> bool:
        """One sensor burst owns this head's optional JPEG budget until done."""
        self.hub._check(robot_id)
        pending = self._sensor_tasks.get(robot_id)
        return pending is not None and not pending.done()

    def _any_human_active(self, now: float) -> bool:
        return any(
            self.hub.user_active(robot_id, now) for robot_id in self.hub.robots
        )

    def _cancel_proactive_snapshot(self, robot_id: str) -> None:
        pending = self._proactive_snapshots.get(robot_id)
        if pending is not None and not pending.done():
            self._metrics[robot_id]["proactive_camera_preemptions"] += 1
            pending.cancel()  # Never cancel the permanent PetController task.

    def voice_transport_unavailable(self) -> None:
        """Invalidate ALL old visual/tool turns without clearing human VAD.

        A lost Xiaozhi voice event stream makes an existing visual question
        unsafe even if its HTTP model worker eventually returns. Clear old
        evidence and request a new sampler only after authenticated recovery.
        This is synchronous: never put camera I/O before urgent audio abort.
        """
        self._reconnect_needs_sampler.update(self.hub.robots)
        for robot_id in self.hub.robots:
            self._turn_epoch[robot_id] += 1
            self._question_epoch[robot_id] += 1
            self._cancel_proactive_snapshot(robot_id)
            for tasks in (
                self._sensor_tasks, self._look_tasks, self._capture_tasks
            ):
                task = tasks.get(robot_id)
                if task is not None and not task.done():
                    task.cancel()
            self.hub.discard_video(robot_id)  # not voice_until

    def voice_started(self, robot_id: str) -> None:
        self._voice_activity(robot_id, end_expected=True)

    def voice_interrupted(self, robot_id: str) -> None:
        # Confirmed AEC double talk stops old robot speech but does not
        # promise the server will emit an idle speech_end for this event.
        self._voice_activity(robot_id, end_expected=False)

    def _voice_activity(self, robot_id: str, *, end_expected: bool) -> None:
        now = time.monotonic()
        self._voice_turn_at[robot_id] = now
        if end_expected:
            self.hub.notify(robot_id, "human_voice", now)
        else:
            self.hub.barge_in(robot_id, now)
        # A real human on any head owns the fleet speech floor. A visual
        # answer that began on ANOTHER pet before this voice edge must also
        # become invalid; cancelling only the speaking robot let a peer's
        # expensive VLM answer survive this global preemption.
        for peer in self.hub.robots:
            self._turn_epoch[peer] += 1
            self._cancel_proactive_snapshot(peer)
            pending_sensor = self._sensor_tasks.get(peer)
            if pending_sensor is not None and not pending_sensor.done():
                pending_sensor.cancel()
            prior = self._look_tasks.get(peer)
            if prior is not None and not prior.done():
                prior.cancel()
        if self._closed or not self.settings.voice_vision_tools_enabled:
            return
        task = self._capture_tasks.get(robot_id)
        if task is None or task.done() or task.cancelling():
            # A new VAD start can race with the prior speech_end cancellation.
            # Replace that cancelling worker instead of leaving the new
            # utterance without any camera samples.
            # NEVER await a camera capture in the realtime VAD cancellation
            # callback. Audio playback stops without waiting for JPEG/LLM.
            self._capture_tasks[robot_id] = asyncio.create_task(
                self._speech_frames(robot_id)
            )

    def voice_ended(self, robot_id: str) -> None:
        self.hub.speech_ended(robot_id, time.monotonic())
        task = self._capture_tasks.get(robot_id)
        if task is not None and not task.done():
            task.cancel()  # Preserve captured visual context for current ASR.

    async def _speech_frames(self, robot_id: str) -> None:
        try:
            # Keep the 1 FPS visual stream for a genuinely long utterance,
            # but cap unacknowledged camera work if a VAD end is lost. The
            # voice floor itself remains held until explicit end/disconnect.
            for _ in range(60):
                if (self._closed or not self.hub.user_active(
                    robot_id, time.monotonic()
                )):
                    break
                if self.hub.due(robot_id, time.monotonic()):
                    try:
                        await self.capture(
                            robot_id, source="speech", reuse_if_recent_s=0.65
                        )
                    except Exception:
                        # Camera failure does NOT prove the human stopped
                        # speaking. Only discard stale frames, never VAD state.
                        self.hub.discard_video(robot_id)
                        break
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise

    async def _prepare_bounded(
        self, jpeg: bytes, *, priority: bool = False
    ) -> tuple[bytes, bytes, float]:
        """Limit native Pillow workers even if their awaiter is cancelled.

        asyncio.to_thread can continue decoding after an asyncio cancellation.
        A native future completion owns this capacity until Pillow truly exits.
        Under overload, drop optional camera work instead of starting extra
        native workers and interfering with live human audio.
        """
        optional = not priority
        if optional and not self._optional_preprocess_slot.acquire(blocking=False):
            raise RuntimeError("Background JPEG preprocessing busy")
        if not self._preprocess_slots.acquire(blocking=False):
            if optional:
                self._optional_preprocess_slot.release()
            raise RuntimeError("JPEG preprocessing busy; do not queue stale frames")
        try:
            future = self._preprocess_pool.submit(_prepare, jpeg)
        except (RuntimeError, OSError):
            self._preprocess_slots.release()
            if optional:
                self._optional_preprocess_slot.release()
            raise

        def finished(done) -> None:
            try:
                if not done.cancelled():
                    done.exception()  # retrieve late native worker exceptions
            finally:
                self._preprocess_slots.release()
                if optional:
                    self._optional_preprocess_slot.release()

        future.add_done_callback(finished)
        return await asyncio.wrap_future(future)

    async def capture(self, robot_id: str, *, source: str,
                      reuse_if_recent_s: float = 0.0) -> CameraEvidence:
        self.hub._check(robot_id)
        if self._closed:
            raise RuntimeError("Multimodal orchestrator closed")
        if not 0 <= reuse_if_recent_s <= 1.0:
            raise ValueError("Invalid shared live camera age")
        # HttpHead.capture_lock provides serialization with pet observation,
        # dock calibration and pickup. Do not bypass its strict source checks.
        async with self._camera_locks[robot_id]:
            metrics = self._metrics[robot_id]
            # Recheck AFTER waiting for the one camera lock. Two HTTP
            # consumers racing for the same VAD frame now produce ONE physical
            # capture even when both found the hub empty before this lock.
            if source == "speech" and reuse_if_recent_s:
                recent = self.hub.frames[robot_id]
                if recent:
                    frame = recent[-1]
                    now = time.monotonic()
                    if (frame.source in ("speech", "voice_question")
                            and 0 <= now - frame.received_at <= reuse_if_recent_s
                            and frame.received_at >= self._voice_turn_at[robot_id]):
                        metrics["native_speech_camera_reuses"] += 1
                        return frame
            metrics["camera_requests"] += 1
            started = time.monotonic()
            generation = self.hub._generation[robot_id]
            # Camera latency is measured before CPU postprocessing. A new
            # human voice can still preempt the event loop during decoding.
            try:
                if source == "proactive":
                    if self._any_human_active(time.monotonic()):
                        raise RuntimeError("Human speech preempts autonomous camera")
                    pending = asyncio.create_task(
                        self.heads[robot_id].snapshot()
                    )
                    self._proactive_snapshots[robot_id] = pending
                    try:
                        jpeg = await asyncio.wait_for(pending, timeout=4)
                    finally:
                        if self._proactive_snapshots.get(robot_id) is pending:
                            self._proactive_snapshots.pop(robot_id, None)
                else:
                    jpeg = await asyncio.wait_for(
                        self.heads[robot_id].snapshot(), timeout=4
                    )
                received = time.monotonic()
                prepared = await self._prepare_bounded(
                    jpeg, priority=source in ("speech", "voice_question")
                )
                # Source JPEG reception is not the last priority boundary.
                # A human can begin speaking while the CPU worker is
                # decoding/resizing this JPEG, after the proactive network
                # task has already disappeared from its cancellation map.
                # Never publish obsolete low-priority sensor/idle images.
                if (source in ("proactive", "sensor")
                        and self._any_human_active(time.monotonic())):
                    raise RuntimeError(
                        "Human speech superseded autonomous camera preprocessing"
                    )
                evidence = self.hub.offer_prepared(
                    robot_id, prepared, received, source=source,
                    generation=generation,
                )
                metrics["camera_successes"] += 1
                metrics["camera_latency_last_ms"] = round(
                    (time.monotonic() - started) * 1000
                )
                return evidence
            except Exception:
                metrics["camera_errors"] += 1
                raise

    async def native_frame(self, robot_id: str) -> CameraEvidence:
        """Share the actual VAD JPEG under the same physical camera lock.

        The lock-coalesced capture rechecks after another consumer finishes;
        never reuse idle/old-turn video or start another camera transport.
        """
        return await self.capture(
            robot_id, source="speech", reuse_if_recent_s=0.65
        )

    async def offer_proactive(self, robot_id: str, jpeg: bytes, now: float) -> None:
        # Pet snapshots share the same authenticated head.capture_lock. Only
        # CPU preprocessing runs off-thread. Never publish late paused frames.
        self.hub._check(robot_id)
        generation = self.hub._generation[robot_id]
        prepared = await self._prepare_bounded(jpeg)
        if self._any_human_active(time.monotonic()):
            return  # never commit low-priority JPEG after fresh human VAD
        self.hub.offer_prepared(
            robot_id, prepared, now, source="proactive",
            generation=generation,
        )

    async def look(self, robot_id: str, question: str) -> dict:
        self.hub._check(robot_id)
        if (not self.settings.voice_vision_tools_enabled
                or not self.settings.vision_model):
            raise ValueError("Enable local voice vision and install a vision model")
        if not isinstance(question, str) or not 3 <= len(question.strip()) <= 280:
            raise ValueError("A short real visual question is required")
        if self._closed:
            raise RuntimeError("Visual conversation already shut down")
        # A question initiated by a different head while another human is
        # talking cannot borrow the shared VLM/speech floor. The speaking
        # robot may still use its own authenticated visual tool.
        now = time.monotonic()
        if any(
            peer != robot_id and self.hub.user_active(peer, now)
            for peer in self.hub.robots
        ):
            raise RuntimeError("Another human turn owns the fleet visual floor")
        metrics = self._metrics[robot_id]
        metrics["visual_questions"] += 1
        turn = self._turn_epoch[robot_id]
        self._question_epoch[robot_id] += 1
        question_epoch = self._question_epoch[robot_id]
        current = asyncio.current_task()
        pending_sensor = self._sensor_tasks.get(robot_id)
        if pending_sensor is not None and not pending_sensor.done():
            pending_sensor.cancel()  # An explicit question takes camera priority.
        self._cancel_proactive_snapshot(robot_id)
        previous = self._look_tasks.get(robot_id)
        if previous is not None and previous is not current and not previous.done():
            previous.cancel()
        if current is not None:
            self._look_tasks[robot_id] = current

        def current_turn() -> bool:
            return (not self._closed
                    and self._turn_epoch[robot_id] == turn
                    and self._question_epoch[robot_id] == question_epoch)

        try:
            last = self.hub.frames[robot_id]
            if (not last
                    or time.monotonic() - last[-1].received_at > 0.6
                    or last[-1].received_at < self._voice_turn_at[robot_id]):
                # A recent pre-VAD idle frame is NOT evidence captured during
                # the current spoken visual question. Still retain earlier
                # frames for before/after questions when a new one arrives.
                await self.capture(robot_id, source="voice_question")
            if not current_turn():
                raise RuntimeError("Visual question superseded by new human speech")
            chosen = self.hub.selected(robot_id, question, time.monotonic())
            if not chosen:
                raise RuntimeError("No fresh authenticated camera images available")
            async with self.inference_lock:
                # Higher-priority user turns can arrive while waiting for a
                # busy five-robot VLM. Never evaluate a stale older question.
                if not current_turn():
                    raise RuntimeError("Visual question superseded while queued")
                # Local 4B+ vision inference can be much slower than the
                # source exposure. Do not let a 45 second provider request
                # claim a scene is still current or delay new user turns.
                model_started = time.monotonic()
                try:
                    async with asyncio.timeout(self._vision_timeout_s):
                        answer = await self.scene.answer(
                            question, [frame.jpeg for frame in chosen]
                        )
                    metrics["model_latency_last_ms"] = round(
                        (time.monotonic() - model_started) * 1000
                    )
                except TimeoutError as exc:
                    raise RuntimeError(
                        "Live visual analysis timed out; do not describe old scene"
                    ) from exc
            if not current_turn():
                raise RuntimeError("Visual answer superseded by new speech")
            if time.monotonic() - chosen[-1].received_at > 16:
                raise RuntimeError("Camera observation expired during visual analysis")
            metrics["visual_answers"] += 1
            # The read-only answer is bound to the exact accepted question
            # epoch and real Mac JPEG. It is a short-lived interpretation,
            # never a second camera/VLM agent or evidence of motion success.
            self.hub.remember_tool(
                robot_id, "visual_look", answer, time.monotonic()
            )
            return {
                "robot_id": robot_id,
                "answer": answer,
                "frames_used": len(chosen),
                "latest_frame_age_ms": round(
                    1000 * (time.monotonic() - chosen[-1].received_at)
                ),
                "model": self.settings.vision_model,
                "source": "authenticated_xiao_camera_and_local_vlm",
                "recent_sensor_events": self.hub.recent_events(
                    robot_id, time.monotonic()
                ),
                "image_capture_exposure_verified": False,
                "physical_multimodal_latency_verified": False,
                "motor_authorized": False,
                "charging_authorized": False,
            }
        except Exception:
            metrics["visual_errors"] += 1
            raise
        except asyncio.CancelledError:
            metrics["visual_errors"] += 1
            if not current_turn():
                reason = (
                    "newer speech" if self._turn_epoch[robot_id] != turn
                    else "newer visual question"
                )
                raise RuntimeError(f"Visual query cancelled by {reason}") from None
            raise
        finally:
            if self._look_tasks.get(robot_id) is current:
                self._look_tasks.pop(robot_id, None)

    async def close(self) -> None:
        self._closed = True
        tasks = (list(self._capture_tasks.values())
                 + list(self._sensor_tasks.values())
                 + list(self._look_tasks.values()))
        for task in tasks + list(self._proactive_snapshots.values()):
            task.cancel()
        pending = tasks + list(self._proactive_snapshots.values())
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._capture_tasks.clear()
        self._sensor_tasks.clear()
        self._look_tasks.clear()
        self._proactive_snapshots.clear()
        self.hub.close()
        self._preprocess_pool.shutdown(wait=False, cancel_futures=True)
