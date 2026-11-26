"""Bounded voice + camera context for the existing Xiaozhi and Mac runtime.

Reuses LiveKit's VAD-adaptive frame cadence and Frigate's motion-first
inference strategy. These are algorithmic reuses, not new media transports.
Only the authenticated XIAO head supplies JPEGs. Frames live in RAM only,
are never persisted, never authorize motors and expire on disconnect/close.
"""
from __future__ import annotations

import asyncio
import math
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import aclosing
from dataclasses import dataclass
from io import BytesIO
from statistics import median
from typing import TYPE_CHECKING

from PIL import Image, ImageOps

if TYPE_CHECKING:
    from .config import Settings
    from .transport import Head
from .config import quiet_hours_active
from .operations import _bounded_head_reply
from .room_station import ROOM_OBSERVATION_SOURCE, STATION, RoomObservation, fresh_room_summary
from .sensor_event_contract import DIRECT_INTERACTION_KINDS, TRIGGERS  # public names
from .vision import OllamaScene

# Keep source-ID deduplication longer than the 30s visible ASR context.
# A saturated identity fence refuses new context rather than evicting live IDs.
_HEARD_REPLAY_SECONDS = 60.0
_HEARD_REPLAY_MAX_IDS = 1024
_VISUAL_FRAME_MAX_AGE_S = 6.0

TEMPORAL_WORDS = re.compile(
    r"\b(chang(?:e|ed|ing)|mov(?:e|ed|ing)|happen(?:ed|ing)?|"
    r"before|after|just|appear(?:ed)?|disappear(?:ed)?|"
    r"pick(?:ed)?|put|drop(?:ped)?)\b", re.I
)


def _finite(value: float) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False  # Huge Python integers cannot represent host timestamps.


def _frame_is_fresh(received_at: float, now: float, max_age: float) -> bool:
    """Compare Mac receipt age, never device exposure time."""
    return _finite(received_at) and 0 <= now - received_at <= max_age


def _admissible_mac_event_clock(value: float) -> bool:
    """Accept historical fixture times, never implausible future local receipts.

    A future VAD start could otherwise hold the human floor forever because
    the next real speech_end would compare older than that bogus start.
    """
    return _finite(value) and value <= time.monotonic() + 1


def _validate_camera_cue(source: object, trigger_kind: object = None) -> None:
    """Check source labels before acquisition or publishing any camera evidence."""
    if type(source) is not str or source not in {"proactive", "speech", "voice_question", "sensor"}:
        raise ValueError("Unknown image source or invalid time")
    if trigger_kind is not None and (
        source != "sensor" or type(trigger_kind) is not str or trigger_kind not in TRIGGERS
    ):
        raise ValueError("Only a real sensor burst can label its trigger")


def _validate_camera_raster(im: Image.Image) -> None:
    if im.format != "JPEG":
        raise ValueError("Authenticated camera source must return JPEG")
    if not 1 <= im.width <= 4096 or not 1 <= im.height <= 4096:
        raise ValueError("Camera dimensions invalid")


def _validate_prepared_raster(reduced: bytes, gray: bytes) -> None:
    if (not isinstance(reduced, bytes) or not 12 <= len(reduced) <= 1_000_000
            or not reduced.startswith(b"\xff\xd8") or not reduced.endswith(b"\xff\xd9")
            or not isinstance(gray, bytes) or len(gray) != 64 * 48):
        raise ValueError("Invalid preprocessed camera evidence")


def _prepare(jpeg: bytes, max_side: int = 768) -> tuple[bytes, bytes, float]:
    """Encode bounded JPEG for the VLM and a tiny grayscale motion fingerprint."""
    if not isinstance(jpeg, bytes) or not 12 <= len(jpeg) <= 4_000_000:
        raise ValueError("Camera JPEG size invalid")
    if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
        raise ValueError("Camera JPEG framing invalid")
    try:
        with Image.open(BytesIO(jpeg)) as im:
            # Reject oversized frames BEFORE allocating the RGB raster.
            _validate_camera_raster(im)
            im.load()
            # The decoded image is privately owned by this worker. Avoid
            # copying an already upright RGB raster before thumbnailing.
            ImageOps.exif_transpose(im, in_place=True)
            rgb = im if im.mode == "RGB" else im.convert("RGB")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        # Pillow can reject a malicious raster before our size guard runs.
        # Classify it as a bad frame, not a broken continuous connection.
        raise ValueError("Camera dimensions invalid") from exc
    rgb.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
    gray = ImageOps.grayscale(rgb).resize((64, 48))
    fingerprint = gray.tobytes()
    brightness = sum(fingerprint) / len(fingerprint)
    out = BytesIO()
    rgb.save(out, "JPEG", quality=78, optimize=True)
    encoded = out.getvalue()
    if len(encoded) > 1_000_000:
        raise ValueError("VLM JPEG exceeds bounded in-memory frame")
    return encoded, fingerprint, brightness


def _lighting_transform(a: bytes, b: bytes) -> tuple[float, float, bool]:
    count = len(a)
    sum_a, sum_b = sum(a), sum(b)
    sum_aa = sum(x * x for x in a)
    sum_bb = sum(y * y for y in b)
    sum_ab = sum(x * y for x, y in zip(a, b, strict=True))
    variance_a = count * sum_aa - sum_a * sum_a
    variance_b = count * sum_bb - sum_b * sum_b
    covariance = count * sum_ab - sum_a * sum_b
    gain = 1.0
    fitted = False
    if (variance_a > count * count * 30
            and variance_b > count * count * 30
            and covariance > 0
            and covariance * covariance >= 0.90 * variance_a * variance_b):
        candidate_gain = covariance / variance_a
        if 0.55 <= candidate_gain <= 2.5:
            gain = candidate_gain
            fitted = True
    if not fitted:
        # A local occlusion must not shift the inferred brightness of every
        # unchanged pixel. The median additive residual is robust to a
        # minority of changed pixels when an affine fit is unreliable.
        return gain, median(y - x for x, y in zip(a, b, strict=True)), fitted
    return gain, (sum_b - gain * sum_a) / count, fitted


def _scene_change_mask(a: bytes, b: bytes, gain: float, offset: float,
                       threshold: int, *, clamp: bool = False) -> bytes:
    """Encode significant residual direction: 0 unchanged, 1 brighter, 2 darker."""
    residuals = (
        y - (min(255, max(0, gain * x + offset)) if clamp else gain * x + offset)
        for x, y in zip(a, b, strict=True)
    )
    return bytes(1 if delta >= threshold else 2 if delta <= -threshold else 0
                 for delta in residuals)


def scene_change_mask(a: bytes, b: bytes, *, threshold: int = 16) -> bytes:
    """Ignore broad lighting shifts while retaining signed localized changes."""
    if len(a) != len(b) or len(a) != 64 * 48:
        raise ValueError("Frame fingerprints have incompatible dimensions")
    count = len(a)
    gain, offset, _ = _lighting_transform(a, b)
    changed = _scene_change_mask(a, b, gain, offset, threshold)
    if changed.count(0) == count or not any(
        (y <= 8 or y >= 247) and x != y for x, y in zip(a, b, strict=True)
    ):
        return changed
    # Newly clipped highlights/shadows bias an ordinary affine fit. Refit
    # only when at least half the corresponding samples remain measurable.
    # Score ALL pixels, including saturated ones, against the clamped model;
    # never blanket-mask clipping (a real dark object can cover a bright pixel).
    pairs = [
        (x, y) for x, y in zip(a, b, strict=True)
        if 8 < x < 247 and 8 < y < 247
    ]
    if len(pairs) < count // 2:
        return changed
    valid_a, valid_b = map(bytes, zip(*pairs, strict=True))
    gain, offset, fitted = _lighting_transform(valid_a, valid_b)
    if not fitted:
        return changed
    clipped = _scene_change_mask(a, b, gain, offset, threshold, clamp=True)
    return clipped if clipped.count(0) > changed.count(0) else changed


def change_fraction(a: bytes, b: bytes, *, threshold: int = 16) -> float:
    """Cheap exposure-compensated motion score, not calibrated optical flow."""
    mask = scene_change_mask(a, b, threshold=threshold)
    return (len(mask) - mask.count(0)) / len(mask)


@dataclass(frozen=True)
class CameraEvidence:
    jpeg: bytes
    received_at: float  # Mac receive time, NOT sensor exposure time.
    motion_fraction: float
    source: str
    trigger_kind: str | None = None  # Scheduling cause, NOT object recognition.
    # Device-local capture completion receipt; NOT Mac-time exposure proof.
    source_identity: tuple[int, int, int] | None = None


# Keep the stream's cheap motion admission consistent with the pet's
# two-frame VisualChangeGate minimum. Higher thresholds hide small keys
# before semantic relevance can be considered.
_STREAM_VISUAL_CHANGE_MIN_FRACTION = 0.008


class CameraFrameHub:
    """Per-robot tiny RAM-only buffer with priority hints and bounded cadence.

    Cadence resembles LiveKit VoiceActivityVideoSampler, with event priority
    and a cheap Frigate-style motion score. No continuous video is claimed.
    """

    def __init__(
        self, robot_ids: list[str], *,
        idle_fps: float = 0.30, speaking_fps: float = 1.0,
        active_fps: float = 0.8, max_frames: int = 3,
        room_settings: "Settings | None" = None,
    ):
        if (not robot_ids or any(type(robot_id) is not str for robot_id in robot_ids)
                or len(set(robot_ids)) != len(robot_ids)):
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
        self.voice_started_at = {robot: -math.inf for robot in robot_ids}
        # Qwen Live Harness defers unsolicited context/speech until quiet
        # after the human turn. This does not pretend speaker DMA stopped.
        self.quiet_until = {robot: -math.inf for robot in robot_ids}
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
        # Past physical edges remain relevant during a longer conversation.
        # Never treat these historical events as live actuator readings.
        self.situation_edges = {robot: {} for robot in robot_ids}
        # A local WROOM disarm must not be evicted by a dozen routine touch
        # edges within its eight-second context lifetime. This is a cached
        # observation timestamp, never an independent motion authority.
        self.latest_safety_fault = {robot: -math.inf for robot in robot_ids}
        self.latest_safety_fault_detail: dict[str, str | None] = {
            robot: None for robot in robot_ids
        }
        # One direct-contact cue survives routine sensor chatter for the same
        # original eight-second TTL. It does not grant speech or motion.
        self.latest_direct_interaction: dict[str, tuple[str, float] | None] = {
            robot: None for robot in robot_ids
        }
        # Ephemeral successful tool interpretations accompany sensor cues,
        # not raw JPEG/PCM or persistent user memories. One existing owner.
        self.tool_history = {
            robot: deque(maxlen=5) for robot in robot_ids
        }
        # Keep only the pet's actual transmitted text, not fake "heard"
        # playback evidence. Unlike a VLM guess this can survive the NEXT
        # human VAD, so a reply to the pet has useful short-term context.
        self.spoken_history = {
            robot: deque(maxlen=3) for robot in robot_ids
        }
        # Native text receipts identify one actually transmitted response.
        self.native_spoken_ids = {
            robot: deque(maxlen=12) for robot in robot_ids
        }
        # The 12-entry displayed receipt cache is not an idempotency fence:
        # a burst of new sent responses must not admit an old response again
        # while its authenticated five-second source window remains live.
        self.native_spoken_seen: dict[str, dict[str, float]] = {
            robot: {} for robot in robot_ids
        }
        # Completed model ASR is short-lived turn context, not durable memory.
        # Each robot's words remain isolated and deduped by source item ID.
        self.heard_history = {
            robot: deque(maxlen=4) for robot in robot_ids
        }
        # An ASR receipt stays seen even after the four content slots roll
        # over or voice transport clears the transient display. Each pet has
        # its own bounded monotonic replay window with fail-closed capacity.
        self.heard_seen_ids: dict[str, dict[str, float]] = {
            robot: {} for robot in robot_ids
        }
        # Retractions must outlive the short ASR history slot, otherwise
        # a replayed authenticated event can resurrect operator-deleted text.
        self.revoked_heard_ids = {
            robot: deque(maxlen=128) for robot in robot_ids
        }
        # One shared, volatile USB measurement; NEVER copied to any pet memory
        # or treated as an eyewitness, VAD, tool receipt or motor permit.
        self.shared_room: RoomObservation | None = None
        self._room_settings = room_settings
        self._shared_room_grant: int | None = None
        self._room_connection_epoch: int = 0
        self._shared_room_epoch: int | None = None

    def _room_grant(self) -> tuple[bool, int | None]:
        """Keep production USB evidence within its original room opt-in."""
        settings = self._room_settings
        if settings is None or getattr(settings, "mode", None) != "hardware":
            return True, None  # Standalone/simulation hub has no hardware grant.
        epoch = getattr(settings, "room_station_consent_generation", None)
        allowed = (
            getattr(settings, "room_station_context_enabled", False) is True
            and type(epoch) is int and epoch >= 0
        )
        return allowed, epoch if allowed else None

    def invalidate_room(self, *, epoch: int | None = None) -> int:
        """Clear cached shared room state on USB disconnect or shutdown."""
        self.shared_room = None
        self._shared_room_grant = None
        self._shared_room_epoch = None
        self._room_connection_epoch = (
            max(self._room_connection_epoch + 1, epoch)
            if epoch is not None else self._room_connection_epoch + 1
        )
        return self._room_connection_epoch

    def remember_room(
        self, observation: RoomObservation, *, epoch: int | None = None,
        grant_generation: int | None = None,
    ) -> None:
        if (not isinstance(observation, RoomObservation)
                or not _admissible_mac_event_clock(observation.received_at)):
            raise ValueError("Room provenance must come from validated USB source")
        # A typed in-process observation still cannot promote itself into
        # an actuator, charger, identity source or another sensor channel.
        if (observation.source != ROOM_OBSERVATION_SOURCE
                or observation.station_id != STATION
                or observation.motion_authorized is not False
                or observation.charging_authorized is not False
                or observation.person_identified is not False):
            raise ValueError("Room provenance must remain read-only and anonymous")
        if epoch is None:
            epoch = getattr(self, "_room_connection_epoch", 0)
        if epoch != getattr(self, "_room_connection_epoch", 0):
            return  # Reject delayed callback from disconnected serial epoch.
        allowed, grant = self._room_grant()
        if not allowed or (grant_generation is not None and grant_generation != grant):
            return  # Never admit a shared observation under a different grant.
        previous = self.shared_room
        if previous is not None and observation.received_at <= previous.received_at:
            return  # An older asynchronous serial callback cannot regress state.
        self.shared_room = observation
        self._shared_room_grant = grant
        self._shared_room_epoch = epoch

    def _check(self, robot_id: str) -> None:
        if type(robot_id) is not str or robot_id not in self.robots:
            raise ValueError("Unknown robot camera identity")

    def notify(
        self, robot_id: str, kind: str, now: float, *, detail: str | None = None,
    ) -> None:
        self._check(robot_id)
        if type(kind) is not str or kind not in TRIGGERS or not _admissible_mac_event_clock(now):
            raise ValueError("Unknown physical event or invalid time")
        if detail is not None and (
            not isinstance(detail, str)
            or not re.fullmatch(r"[a-z0-9_]{1,64}", detail)
        ):
            detail = None
        self.urgent[robot_id] = True
        self.event_history[robot_id].append((kind, now))
        if kind in DIRECT_INTERACTION_KINDS:
            previous = self.latest_direct_interaction[robot_id]
            if previous is None or now >= previous[1]:
                self.latest_direct_interaction[robot_id] = (kind, now)
        # Only situational cues survive a long utterance. Routine contact
        # and the separately owned WROOM safety-fault event retain their
        # original short TTL; neither may be resurrected as a new warning.
        if kind in {
            "handling_tilt", "handling_shake", "side_object",
            "nearby_object", "ambient_shift", "nfc_tag",
        }:
            past = self.situation_edges[robot_id]
            past[kind] = max(now, past.get(kind, -math.inf))
            if len(past) > 12:
                del past[min(past, key=past.get)]
        if kind == "safety_fault":
            prior_at = self.latest_safety_fault[robot_id]
            if now >= prior_at:
                self.latest_safety_fault[robot_id] = now
                self.latest_safety_fault_detail[robot_id] = detail
        if kind == "human_voice":
            self.voice_started_at[robot_id] = max(self.voice_started_at[robot_id], now)
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
        if not _admissible_mac_event_clock(now):
            raise ValueError("Invalid VAD end timestamp")
        # An old speech_end can arrive after a newer authenticated speech_start.
        # Never release the newer human floor on that stale end event.
        if now < self.voice_started_at[robot_id]:
            return
        self.voice_until[robot_id] = min(self.voice_until[robot_id], now)
        # Delayed duplicate speech_end must not shorten a newer quiet hold.
        self.quiet_until[robot_id] = max(self.quiet_until[robot_id], now + 0.8)

    def spontaneous_floor_busy(self, now: float) -> bool:
        """No unsolicited pet speech until 800ms after the latest human VAD.

        This is a conservative conversational pause, not a physical speaker
        playback acknowledgement or a permission to move the robot.
        """
        if not _finite(now):
            raise ValueError("Invalid floor clock")
        return any(
            self.user_active(robot_id, now) or now < self.quiet_until[robot_id]
            for robot_id in self.robots
        )

    def reconcile_speech_snapshot(self, active: frozenset[str], now: float) -> None:
        """Reconcile missed idle VAD edges using the authenticated server state.

        Never touch finite AEC double-talk leases: the server cannot promise
        their matching speech_end. Only a real authenticated snapshot is a
        permissible source for restoring/releasing explicit idle VAD turns.
        """
        if (not isinstance(active, frozenset) or not active <= self.robots
                or not _admissible_mac_event_clock(now)):
            raise ValueError("Untrusted VAD snapshot or invalid time")
        for robot_id in self.robots:
            if robot_id in active:
                if self.voice_until[robot_id] != math.inf:
                    # This trusted snapshot may be the first evidence of a
                    # human turn after reconnect. Bind its recovered start to
                    # this lease, so a late earlier speech_end cannot clear it.
                    # Do not shift the epoch on repeated active snapshots.
                    self.voice_started_at[robot_id] = max(
                        self.voice_started_at[robot_id], now
                    )
                self.voice_until[robot_id] = math.inf
            elif self.voice_until[robot_id] == math.inf:
                # A real monitor snapshot can recover a missed speech_end,
                # but should not let unsolicited speech start immediately.
                self.voice_until[robot_id] = now
                self.quiet_until[robot_id] = max(self.quiet_until[robot_id], now + 0.8)

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
        self._check(robot_id)
        _validate_camera_cue(source)
        return self.offer_prepared(
            robot_id, _prepare(jpeg), received_at, source=source
        )

    def offer_prepared(self, robot_id: str, prepared: tuple[bytes, bytes, float],
                       received_at: float, *, source: str,
                       generation: int | None = None,
                       trigger_kind: str | None = None,
                       source_identity: tuple[int, int, int] | None = None
                       ) -> CameraEvidence:
        """Commit preprocessed media on its single event-loop owner.

        Image decoding may run in a worker, but no worker can mutate this hub.
        Old captures after pause/reconnect or new capture commit are rejected.
        """
        self._check(robot_id)
        if generation is not None and (
            type(generation) is not int or generation != self._generation[robot_id]
        ):
            raise RuntimeError("Old camera generation discarded")
        # Camera receipts are stamped on this Mac, not on a remote clock.
        # Even a subsecond future receipt can poison the ordering cursor.
        if not _finite(received_at) or received_at > time.monotonic():
            raise ValueError("Unknown image source or invalid time")
        _validate_camera_cue(source, trigger_kind)
        if received_at <= self.last_capture[robot_id]:
            raise ValueError("Out of order camera reception timestamp")
        if source_identity is not None and (
            type(source_identity) is not tuple or len(source_identity) != 3
            or any(type(value) is not int for value in source_identity)
            or not 0 <= source_identity[0] <= 0xffffffff
            or not 1 <= source_identity[1] <= 0xffffffff
            or not 1 <= source_identity[2] <= 0xffffffffffffffff
        ):
            raise ValueError("Invalid device camera completion identity")
        reduced, gray, _ = prepared
        _validate_prepared_raster(reduced, gray)
        prev = self.previous_gray.get(robot_id)
        motion = change_fraction(prev, gray) if prev is not None else 0.0
        self.previous_gray[robot_id] = gray
        self.changed_streak[robot_id] = (
            min(3, self.changed_streak[robot_id] + 1) if motion >= _STREAM_VISUAL_CHANGE_MIN_FRACTION
            else 0
        )
        self.last_capture[robot_id] = received_at
        self.urgent[robot_id] = False
        evidence = CameraEvidence(reduced, received_at, motion, source,
                                  trigger_kind, source_identity)
        self.frames[robot_id].append(evidence)
        return evidence

    def selected(self, robot_id: str, question: str, now: float
                 ) -> list[CameraEvidence]:
        self._check(robot_id)
        if not _finite(now):
            raise ValueError("Invalid clock")
        fresh = [
            item for item in self.frames[robot_id]
            if _frame_is_fresh(item.received_at, now, _VISUAL_FRAME_MAX_AGE_S)
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
        events = [
            (kind, stamp) for kind, stamp in self.event_history[robot_id]
            if 0 <= now - stamp <= 8.0
        ]
        # The small voice-context tool and the full timeline must agree on
        # physical safety priority. A burst of petting must not hide a local
        # WROOM disarm, and an authenticated human VAD must not disappear
        # behind six lower-value sensor edges either.
        fault_at = self.latest_safety_fault[robot_id]
        if (0 <= now - fault_at <= 8.0
                and not any(k == "safety_fault" and t == fault_at
                            for k, t in events)):
            events.append(("safety_fault", fault_at))
        voice_at = self.voice_started_at[robot_id]
        if (0 <= now - voice_at <= 8.0
                and not any(k == "human_voice" and t == voice_at
                            for k, t in events)):
            events.append(("human_voice", voice_at))
        direct = self.latest_direct_interaction[robot_id]
        if direct is not None and 0 <= now - direct[1] <= 8 and direct not in events:
            events.append(direct)
        events.sort(key=lambda event: event[1])
        required: set[int] = set()
        for required_kind in ("safety_fault", "human_voice"):
            for index in range(len(events) - 1, -1, -1):
                if events[index][0] == required_kind:
                    required.add(index)
                    break
        if direct is not None and direct in events:
            required.add(events.index(direct))
        for index in range(len(events) - 1, -1, -1):
            if len(required) >= 6:
                break
            required.add(index)
        fault_detail = self.latest_safety_fault_detail.get(robot_id)
        return [
            {
                "kind": events[i][0],
                "age_ms": round(1000 * (now - events[i][1])),
                "source": ("xiaozhi_vad" if events[i][0] == "human_voice"
                           else "wroom_sensed_event"),
                **(
                    {"fault_detail": fault_detail}
                    if events[i][0] == "safety_fault" and fault_detail is not None
                    else {}
                ),
            }
            for i in sorted(required)
        ]

    def remember_tool(self, robot_id: str, kind: str, summary: str,
                      received_at: float) -> None:
        """Accept only completed current-turn read-only tool interpretations.

        Failed/cancelled tool outputs must never enter the next interaction.
        Visual answers are model guesses; status/job receipts are read-only
        Mac observations. None proves physical acceptance or grants motion.
        Visual guesses expire after eight seconds; status after thirty.
        """
        self._check(robot_id)
        if (type(kind) is not str or kind not in {
                "visual_look", "robot_status", "pickup_status",
                "sensor_telemetry", "memory_recall",
            }
                or not isinstance(summary, str)
                or not 1 <= len(summary.strip()) <= 2000
                or not _finite(received_at)):
            raise ValueError("Invalid read-only tool evidence")
        # Receipt stamps are local Mac monotonic time, not untrusted device
        # clocks. A far-future completion would otherwise occupy this kind's
        # latest-only slot and reject every subsequent genuine tool result.
        if received_at > time.monotonic() + 1:
            raise ValueError("Future read-only tool receipt clock")
        cleaned = " ".join(summary.split())[:160]
        if cleaned:
            # Repeated status queries are not independent events: keep one
            # latest receipt per tool kind so they cannot evict a pickup or
            # visual result from the shared small context buffer.
            entries = self.tool_history[robot_id]
            # An older async completion must not evict a newer receipt.
            if any(old_kind == kind and old_stamp >= received_at
                   for old_kind, _, old_stamp in entries):
                return
            for previous in tuple(entries):
                if previous[0] == kind:
                    entries.remove(previous)
            entries.append((kind, cleaned, received_at))

    def recent_tool_context(self, robot_id: str, now: float) -> list[dict]:
        self._check(robot_id)
        if not _finite(now):
            raise ValueError("Invalid interaction context clock")
        return [
            {
                "kind": kind,
                "summary": summary,
                "age_ms": round(1000 * (now - observed)),
                "source": (
                    "local_vlm_interpretation_not_physical_measurement"
                    if kind == "visual_look" else
                    "private_opt_in_memory_retrieval_not_current_observation"
                    if kind == "memory_recall" else
                    "mac_read_only_telemetry_not_physical_acceptance"
                ),
                "untrusted_text_not_instructions": True,
                "motor_authorized": False,
            }
            for kind, summary, observed in self.tool_history[robot_id]
            if 0 <= now - observed <= (
                8.0 if kind == "visual_look" else 30.0
            )
        ]

    def remember_spoken(
        self, robot_id: str, text: str, sent_at: float, *,
        source: str = "mac_tts_transmitted_not_speaker_playback_ack",
    ) -> None:
        """Bounded sent audio text, never proof of acoustic playback."""
        self._check(robot_id)
        if (not isinstance(text, str) or not 1 <= len(text.strip()) <= 280
                or "\x00" in text or not _admissible_mac_event_clock(sent_at)
                or type(source) is not str or source not in {
                    "mac_tts_transmitted_not_speaker_playback_ack",
                    "native_model_text_opus_sent_playback_unverified",
                }):
            raise ValueError("Invalid actual transmitted pet speech")
        self.spoken_history[robot_id].append(
            (" ".join(text.split())[:200], sent_at, source)
        )

    def remember_native_spoken(
        self, robot_id: str, event_id: str, text: str, sent_at: float,
    ) -> bool:
        """Deduplicate native model text associated with sent head Opus."""
        self._check(robot_id)
        if (not isinstance(event_id, str)
                or re.fullmatch(r"omni_sent_[0-9a-f]{12}_[0-9a-f]{20}", event_id)
                    is None):
            raise ValueError("Invalid native sent audio receipt")
        # A duplicate event ID must not bypass validation of the supplied
        # text. Reject NUL, blank and overlong speech before the idempotent
        # replay fence, just as we already validate receipt timestamps.
        if (not isinstance(text, str) or not 1 <= len(text.strip()) <= 200
                or "\x00" in text):
            raise ValueError("Invalid native model sent speech text")
        # A replayed event ID is harmless only when its attached timestamp
        # remains valid. Validate source time BEFORE idempotent deduplication:
        # otherwise an attacker or misbehaving voice bridge could replay a
        # previously accepted ID with an ancient or future timestamp and get
        # a misleading HTTP 200 rather than an invalid-receipt rejection.
        mac_now = time.monotonic()
        if not _finite(sent_at) or not 0 <= mac_now - sent_at <= 5:
            raise ValueError("Stale or future native audio receipt")
        seen = self.native_spoken_seen[robot_id]
        # Identity retention uses the host admission clock, never a
        # replay-provided timestamp. Reconnect and display overflow cannot
        # make the same transmitted response into new conversational text.
        while seen:
            oldest = next(iter(seen))
            if mac_now - seen[oldest] <= 5:
                break
            del seen[oldest]
        if event_id in seen:
            return False
        if len(seen) >= 256:
            return False  # Never evict a still-live source ID to accept new text.
        self.remember_spoken(
            robot_id, text, sent_at,
            source="native_model_text_opus_sent_playback_unverified",
        )
        self.native_spoken_ids[robot_id].append(event_id)
        seen[event_id] = mac_now
        return True

    def remember_heard(self, robot_id: str, event_id: str, transcript: str,
                       received_at: float) -> bool:
        """Keep completed model ASR in per-pet RAM for one short conversation.

        Caller authentication, transcript consent and durable SQLite storage
        are separate API concerns. ASR is uncertain and never commands motion.
        """
        self._check(robot_id)
        if (not isinstance(event_id, str) or not 1 <= len(event_id) <= 96
                or not event_id.isascii() or not isinstance(transcript, str)
                or not 1 <= len(transcript.strip()) <= 240
                or "\x00" in transcript or not _finite(received_at)):
            raise ValueError("Invalid native ASR turn evidence")
        # A future Mac receipt could remain dormant and later reappear as
        # a new human request. Keep historical ASR only within its normal TTL.
        mac_now = time.monotonic()
        if received_at > mac_now + 1:
            raise ValueError("Future native ASR receipt clock")
        seen = self.heard_seen_ids[robot_id]
        # Insertion order is first-admission order, using the host monotonic
        # clock rather than untrusted transcript text or source timestamps.
        while seen:
            oldest = next(iter(seen))
            if mac_now - seen[oldest] <= _HEARD_REPLAY_SECONDS:
                break
            del seen[oldest]
        if (event_id in self.revoked_heard_ids[robot_id]
                or event_id in seen):
            return False
        # Do not evict a still-live ID under flood; losing a new uncertain
        # transcript is safer than replaying an old operator request.
        if len(seen) >= _HEARD_REPLAY_MAX_IDS:
            return False
        self.heard_history[robot_id].append(
            (event_id, " ".join(transcript.split())[:240], received_at)
        )
        seen[event_id] = mac_now
        return True

    def heard_revoked(self, robot_id: str, event_id: str) -> bool:
        """Read the local replay fence before accepting delayed ASR context."""
        self._check(robot_id)
        return isinstance(event_id, str) and event_id in self.revoked_heard_ids[robot_id]

    def discard_heard(self, robot_id: str, event_id: str) -> None:
        """Retract one ASR event and block its old source ID from replay."""
        self._check(robot_id)
        if (not isinstance(event_id, str) or not 1 <= len(event_id) <= 96
                or not event_id.isascii()):
            raise ValueError("Invalid native ASR retraction identity")
        revoked = self.revoked_heard_ids[robot_id]
        if event_id not in revoked:
            revoked.append(event_id)
        entries = self.heard_history[robot_id]
        self.heard_history[robot_id] = deque(
            (item for item in entries if item[0] != event_id),
            maxlen=entries.maxlen,
        )

    def interaction_timeline(self, robot_id: str, now: float,
                             *, limit: int = 10) -> list[dict]:
        """One ordered, bounded Mac view of authenticated multimodal cues.

        The camera is sampled continuously by its existing owner, but raw
        JPEGs and PCM never travel through this JSON context. Evidence from a
        sensor, Mac JPEG receipt and completed model tool has a different
        source label and remains nonauthoritative for physical actions.
        """
        self._check(robot_id)
        if not _finite(now) or type(limit) is not int or not 1 <= limit <= 16:
            raise ValueError("Invalid interaction timeline clock or limit")
        items = []
        room = self.shared_room
        allowed, grant = self._room_grant()
        epoch_ok = getattr(self, "_shared_room_epoch", None) == getattr(
            self, "_room_connection_epoch", 0
        )
        if (allowed and grant == self._shared_room_grant and epoch_ok
                and room is not None and 0 <= now - room.received_at <= 12):
            content = fresh_room_summary(room, now=now)
            if content is not None:
                items.append((room.received_at, {
                    "channel": "room_station",
                    "kind": "shared_room_raw_measurement",
                    "age_ms": round(1000 * (now - room.received_at)),
                    "source": room.source,
                    "content": content,
                    "shared_not_robot_eyewitness": True,
                    "identity_verified": False,
                    "physical_action_verified": False,
                }))
        fault_detail = self.latest_safety_fault_detail.get(robot_id)
        for kind, stamp in self.event_history[robot_id]:
            if 0 <= now - stamp <= 8:
                item = {
                    "channel": "human_voice" if kind == "human_voice" else "sensor",
                    "kind": kind,
                    "age_ms": round(1000 * (now - stamp)),
                    "source": "authenticated_xiaozhi_vad" if kind == "human_voice"
                              else "wroom_event",
                    "content": None,
                    "physical_action_verified": False,
                }
                if kind == "safety_fault" and fault_detail is not None:
                    item["fault_detail"] = fault_detail
                items.append((stamp, item))
        # Keep original ages visible when an old tilt or nearby object
        # may explain the conversation. This is NOT a live sensor state.
        for kind, stamp in self.situation_edges[robot_id].items():
            age = now - stamp
            if 8 < age <= 60:
                items.append((stamp, {
                    "channel": "sensor_history", "kind": kind,
                    "age_ms": round(1000 * age),
                    "source": "wroom_event_history",
                    "historical_not_current": True,
                    "physical_action_verified": False,
                }))
        # The generic bounded event deque can overflow during a sensor burst.
        # Preserve one authentic local fault until its original TTL expires,
        # but never fabricate another observation or extend the timestamp.
        fault_at = self.latest_safety_fault[robot_id]
        if (0 <= now - fault_at <= 8
                and not any(kind == "safety_fault" and stamp == fault_at
                            for kind, stamp in self.event_history[robot_id])):
            item = {
                "channel": "sensor", "kind": "safety_fault",
                "age_ms": round(1000 * (now - fault_at)),
                "source": "wroom_event", "content": None,
                "physical_action_verified": False,
            }
            if fault_detail is not None:
                item["fault_detail"] = fault_detail
            items.append((fault_at, item))
        # A fresh direct interaction must not be displaced by background
        # sensors before the model's modality budget even sees it.
        direct = self.latest_direct_interaction[robot_id]
        if (direct is not None and 0 <= now - direct[1] <= 8
                and direct not in self.event_history[robot_id]):
            kind, stamp = direct
            items.append((stamp, {
                "channel": "sensor", "kind": kind,
                "age_ms": round(1000 * (now - stamp)),
                "source": "wroom_event", "content": None,
                "physical_action_verified": False,
            }))
        # Keep the authenticated voice-start edge for its original short TTL
        # even if routine sensor traffic filled the shared deque. This is
        # audio event provenance, not a new ASR guess or a speech permit.
        voice_at = self.voice_started_at[robot_id]
        if (0 <= now - voice_at <= 8
                and not any(kind == "human_voice" and stamp == voice_at
                            for kind, stamp in self.event_history[robot_id])):
            items.append((voice_at, {
                "channel": "human_voice", "kind": "human_voice",
                "age_ms": round(1000 * (now - voice_at)),
                "source": "authenticated_xiaozhi_vad", "content": None,
                "physical_action_verified": False,
            }))
        for frame in self.frames[robot_id]:
            if 0 <= now - frame.received_at <= 6:
                camera_item = {
                    "channel": "camera",
                    "kind": frame.source,
                    "age_ms": round(1000 * (now - frame.received_at)),
                    "source": "authenticated_xiao_jpeg_received_by_mac",
                    "trigger_kind": frame.trigger_kind,
                    "motion_fraction": round(frame.motion_fraction, 4),
                    "content": None,  # never put JPEG bytes or guessed objects here
                    "exposure_timestamp_verified": False,
                    "physical_action_verified": False,
                }
                if frame.source_identity is not None:
                    boot, sequence, complete_us = frame.source_identity
                    camera_item.update({
                        "source_boot": boot,
                        "source_frame_sequence": sequence,
                        "source_capture_complete_us": complete_us,
                        "source_clock_not_aligned_to_mac": True,
                    })
                items.append((frame.received_at, camera_item))
        for kind, summary, stamp in self.tool_history[robot_id]:
            if 0 <= now - stamp <= (
                8 if kind == "visual_look" else 30
            ):
                items.append((stamp, {
                    "channel": "tool",
                    "kind": kind,
                    "age_ms": round(1000 * (now - stamp)),
                    "source": (
                        "local_vlm_interpretation" if kind == "visual_look"
                        else "private_opt_in_memory_tool_receipt"
                        if kind == "memory_recall" else "mac_read_only_tool_receipt"
                    ),
                    "content": summary,
                    "untrusted_text_not_instructions": True,
                    "physical_action_verified": False,
                }))
        # The short visible VAD cue may expire before ASR history does.
        # Its persistent per-robot timestamp still fences prior-turn intent.
        for _event_id, transcript, stamp in self.heard_history[robot_id]:
            if stamp >= voice_at and 0 <= now - stamp <= 30:
                items.append((stamp, {
                    "channel": "human_transcript",
                    "kind": "model_asr_completed",
                    "age_ms": round(1000 * (now - stamp)),
                    # Exact trusted Mac monotonic source time; the rounded
                    # age is only UI presentation and cannot fence consent.
                    "source_at": stamp,
                    "source": "native_model_estimated_asr",
                    "content": transcript,
                    "transcription_verified": False,
                    "speaker_identity_verified": False,
                    "physical_action_verified": False,
                }))
        for said, stamp, source in self.spoken_history[robot_id]:
            if 0 <= now - stamp <= 30:
                items.append((stamp, {
                    "channel": "robot_speech",
                    "kind": "own_utterance",
                    "age_ms": round(1000 * (now - stamp)),
                    "source": source,
                    "content": said,
                    "playback_verified": False,
                    "physical_action_verified": False,
                }))
        items.sort(key=lambda item: item[0])
        if len(items) <= limit:
            return [entry for _, entry in items]
        # The camera can submit six frames during a human turn. Selecting
        # only the last N events would silently erase a real touch, a
        # completed vision tool result or the pet's last spoken line.
        # Retain each present modality's LATEST event, then use remaining
        # capacity for recent detail. Never turn a frame into a sighting.
        modalities = ("human_voice", "human_transcript", "tool",
                      "sensor", "room_station", "robot_speech",
                      "sensor_history", "camera")
        required: set[int] = set()
        # A physical WROOM safety fault outranks optional camera, idle pet
        # remarks and routine sensor events in ANY bounded timeline. Without
        # reserving it here, a newer touch could replace the sole sensor
        # slot and erase a still-live, latched local disarm from the brain.
        # This is context ordering only: the WROOM has already stopped and
        # no model may use this evidence to rearm or issue a movement.
        for index in range(len(items) - 1, -1, -1):
            entry = items[index][1]
            if (entry["channel"] == "sensor"
                    and entry["kind"] == "safety_fault"):
                required.add(index)
                break
        # Reserve the active human turn and its completed tool kinds before
        # low-value camera or playback-unverified cues consume the timeline.
        # The WROOM safety fault above always retains the first slot.
        for channel in ("human_voice", "human_transcript"):
            if len(required) >= limit:
                break
            for index in range(len(items) - 1, -1, -1):
                if items[index][1]["channel"] == channel:
                    required.add(index)
                    break
        # An old receipt can still be historical context, but it cannot
        # consume a priority slot for a newer authenticated human VAD.
        current_voice_at = self.voice_started_at[robot_id]
        seen_tools: set[str] = set()
        for index in range(len(items) - 1, -1, -1):
            if len(required) >= limit:
                break
            stamp, entry = items[index]
            if (entry["channel"] == "tool"
                    and stamp >= current_voice_at
                    and entry["kind"] not in seen_tools):
                required.add(index)
                seen_tools.add(entry["kind"])
        # Keep an earlier clause from the same human utterance after the
        # distinct tool receipts it may have requested have been reserved.
        if len(required) < limit and any(
            items[i][1]["channel"] == "human_transcript" for i in required
        ):
            for index in range(len(items) - 1, -1, -1):
                if (index not in required
                        and items[index][1]["channel"] == "human_transcript"
                        and items[index][0] >= current_voice_at):
                    required.add(index)
                    break
        # Keep one deliberate interaction after current human/tool evidence
        # but before routine sensor or shared room telemetry.
        if len(required) < limit:
            for index in range(len(items) - 1, -1, -1):
                entry = items[index][1]
                if (entry["channel"] == "sensor"
                        and entry["kind"] in DIRECT_INTERACTION_KINDS):
                    required.add(index)
                    break
        # Preserve the last event from other modalities when room remains.
        # An older tool from before this VAD gets normal historical priority.
        for channel in modalities[2:]:
            if len(required) >= limit:
                break
            for index in range(len(items) - 1, -1, -1):
                if items[index][1]["channel"] == channel:
                    required.add(index)
                    break
        selected = set(required)
        for index in range(len(items) - 1, -1, -1):
            if len(selected) >= limit:
                break
            selected.add(index)
        selected_entries = [dict(items[index][1]) for index in sorted(selected)]
        # The composer cannot warn about a result it never receives. Attach
        # bounded internal omission metadata to a retained ASR clause, not a
        # fake completed tool receipt or a new instruction-bearing channel.
        current_tools = {
            entry["kind"] for stamp, entry in items
            if entry["channel"] == "tool" and stamp >= current_voice_at
        }
        included_tools = {
            entry["kind"] for entry in selected_entries
            if entry["channel"] == "tool"
        }
        omitted_tools = sorted(current_tools - included_tools)
        if omitted_tools:
            for entry in reversed(selected_entries):
                if entry["channel"] == "human_transcript":
                    entry["omitted_current_tool_kinds"] = omitted_tools
                    break
        return selected_entries

    def discard_memory_tools(self, robot_id: str) -> None:
        """Retract cached private recall after operator memory correction."""
        self._check(robot_id)
        entries = self.tool_history[robot_id]
        self.tool_history[robot_id] = deque(
            (entry for entry in entries if entry[0] != "memory_recall"),
            maxlen=entries.maxlen,
        )

    def discard_visual_tools(self, robot_id: str) -> None:
        """Expire visual guesses without erasing independent read-only facts."""
        self._check(robot_id)
        tools = self.tool_history[robot_id]
        self.tool_history[robot_id] = deque(
            (entry for entry in tools if entry[0] != "visual_look"),
            maxlen=tools.maxlen,
        )

    def discard_video(self, robot_id: str) -> None:
        """Drop failed camera evidence without releasing a live human VAD turn."""
        self._check(robot_id)
        self._generation[robot_id] = self._generation.get(robot_id, 0) + 1
        self.frames[robot_id].clear()
        self.discard_visual_tools(robot_id)
        # An image/voice-monitor outage invalidates camera interpretations,
        # not an actual line already transmitted by the Mac speaker owner.
        # Spoken text retains its own 30s TTL and is not playback proof.
        self.previous_gray.pop(robot_id, None)
        self.last_capture[robot_id] = -math.inf
        self.changed_streak[robot_id] = 0
        self.urgent[robot_id] = False

    def clear(self, robot_id: str) -> None:
        self.discard_video(robot_id)
        self.tool_history[robot_id].clear()
        self.spoken_history[robot_id].clear()
        self.native_spoken_ids[robot_id].clear()
        self.native_spoken_seen[robot_id].clear()
        self.heard_history[robot_id].clear()
        # Do not clear heard_seen_ids or retractions on session/display loss:
        # a delayed old native HTTP receipt must remain idempotent.
        self.event_history[robot_id].clear()
        self.situation_edges[robot_id].clear()
        self.latest_safety_fault[robot_id] = -math.inf
        self.latest_safety_fault_detail[robot_id] = None
        self.latest_direct_interaction[robot_id] = None
        self.voice_started_at[robot_id] = -math.inf
        self.voice_until[robot_id] = -math.inf
        self.quiet_until[robot_id] = -math.inf

    def close(self) -> None:
        self.invalidate_room()
        for robot_id in self.robots:
            self.clear(robot_id)


class MultimodalOrchestrator:
    """Adapt real Xiaozhi audio events and head JPEGs into one Mac VLM owner."""

    def __init__(self, settings: "Settings", heads: dict[str, "Head"],
                 scene: "OllamaScene", inference_lock: asyncio.Lock):
        self.settings = settings
        # One observed camera grant per pet. A rapid OFF/ON must invalidate
        # cached JPEGs once without clearing valid frames from the new grant.
        self._camera_grants = {
            r.id: getattr(settings, "camera_consent_generation", None)
            for r in settings.robots
        }
        # Synthetic/legacy policies lack an epoch, so an observed OFF edge
        # still needs to revoke cached JPEGs without repeated invalidation.
        self._camera_consent_last_enabled = {
            r.id: bool(settings.voice_vision_tools_enabled)
            for r in settings.robots
        }
        self.heads = heads
        self.scene = scene
        self.inference_lock = inference_lock
        self.preempt_background_vision = None  # Existing PetController VLM task owner.
        self.begin_direct_vision = None
        self.end_direct_vision = None
        self.hub = CameraFrameHub(
            [r.id for r in settings.robots], room_settings=settings,
        )
        self._capture_tasks: dict[str, asyncio.Task] = {}
        # One persistent XIAO JPEG feed per head; no second camera or model.
        self._stream_tasks: dict[str, asyncio.Task] = {}
        # Watches operator grant changes without opening a second camera feed.
        self._stream_supervisors: dict[str, asyncio.Task] = {}
        # Model subscribers observe selected images without polling Mac HTTP
        # or opening another camera capture. Condition has no media history.
        self._model_frame_conditions = {
            r.id: asyncio.Condition() for r in settings.robots
        }
        self._model_frame_versions = {r.id: 0 for r in settings.robots}
        self._last_stream_sample = {r.id: -math.inf for r in settings.robots}
        self._camera_boots: dict[str, int] = {}
        self._sensor_tasks: dict[str, asyncio.Task] = {}
        # Own only the optional HTTP snapshot, not its permanent pet loop.
        self._proactive_snapshots: dict[str, asyncio.Task] = {}
        # A timed out adapter can ignore cancellation. Preserve ownership of
        # its real physical read even after the caller releases camera_lock.
        self._head_snapshot_tasks: dict[str, asyncio.Task] = {}
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
        self._preprocess_futures: set[Future[tuple[bytes, bytes, float]]] = set()
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
                "sensor_stream_reuses": 0,
                "sensor_trigger_to_first_jpeg_last_ms": None,
                "sensor_followup_frames": 0, "proactive_camera_preemptions": 0,
                "native_speech_camera_reuses": 0,
                "stream_frames_received": 0, "stream_frames_selected": 0,
                "stream_frames_skipped": 0, "stream_reconnects": 0,
                "stream_sensor_priority_frames": 0,
            } for robot in settings.robots
        }
        self._turn_epoch = {r.id: 0 for r in settings.robots}
        self._voice_turn_at = {r.id: -math.inf for r in settings.robots}
        self._last_fleet_human_turn_at = -math.inf
        self._question_epoch = {r.id: 0 for r in settings.robots}
        # Only a fresh authenticated VAD snapshot may restart a sampler
        # cancelled during a server event gap, never an arbitrary timer.
        self._reconnect_needs_sampler: set[str] = set()
        self._closed = False
        self._camera_revocation_callback: Callable[[Settings], None] | None = (
            self._camera_revoked
        )
        subscribe = getattr(settings, "register_camera_revocation", None)
        if callable(subscribe):
            subscribe(self._camera_revocation_callback)

    def status(self, robot_id: str) -> dict:
        self.hub._check(robot_id)
        return {
            "robot_id": robot_id,
            "camera_stream_task_active": (
                robot_id in self._stream_tasks
                and not self._stream_tasks[robot_id].done()
            ),
            "camera_stream_connected": bool(
                getattr(self.heads[robot_id], "_stream_connected", False)
            ),
            "camera_stream_physically_qualified": False,
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

    def _camera_revoked(self, settings: Settings) -> None:
        """Purge every pet's queued visual evidence at the operator opt-out."""
        if self._closed or settings is not self.settings:
            return
        for robot_id in self.hub.robots:
            self._camera_grant_valid(robot_id, self._camera_grants[robot_id])

    def _camera_grant_valid(self, robot_id: str, origin: int | None) -> bool:
        """Reject old media grants and invalidate their cached JPEGs once.

        The setting's generation advances on every opt-out, even when the
        operator immediately opts back in before an awaited decode finishes.
        Synthetic legacy policies without an epoch retain their old behavior.
        """
        current = getattr(self.settings, "camera_consent_generation", None)
        enabled = bool(self.settings.voice_vision_tools_enabled)
        if (current != self._camera_grants[robot_id]
                or (not enabled and self._camera_consent_last_enabled[robot_id])):
            self._camera_grants[robot_id] = current
            self.hub.discard_video(robot_id)
        self._camera_consent_last_enabled[robot_id] = enabled
        return enabled and current == origin

    def _scheduled_camera_quiet(self, source: str) -> bool:
        return source in ("sensor", "proactive") and quiet_hours_active(
            getattr(self.settings, "pet_quiet_hours", None)
        )

    def stream_owns_camera(self, robot_id: str) -> bool:
        """One live visual worker owns acquisition, including reconnects."""
        self.hub._check(robot_id)
        task = self._stream_tasks.get(robot_id)
        return task is not None and not task.done()

    async def native_live_frames(self, robot_id: str):
        """Push real selected JPEGs to one authorized proactive model reader.

        Stream selection belongs to Mac and Xiaozhi. The model subscriber
        never opens a physical capture, and no raw frames are retained beyond
        the existing bounded in-memory hub. A slow subscriber skips frames.
        """
        self.hub._check(robot_id)
        condition = self._model_frame_conditions[robot_id]
        version = self._model_frame_versions[robot_id]
        last_delivered = float("-inf")
        camera_grant = getattr(self.settings, "camera_consent_generation", None)
        while not self._closed and self._camera_grant_valid(robot_id, camera_grant):
            async with condition:
                try:
                    await asyncio.wait_for(condition.wait_for(
                        lambda version=version: (self._model_frame_versions[robot_id] > version
                                 or self._closed
                                 or not self.settings.voice_vision_tools_enabled
                                 or getattr(self.settings, "camera_consent_generation", None)
                                    != camera_grant)
                    # Settings is operator-controlled but does not emit an
                    # asyncio.Condition notification on mutation. Recheck
                    # consent at most 100ms later even in a completely
                    # static room with no selected camera frames.
                    ), timeout=0.1)
                except TimeoutError:
                    continue
                if self._closed or not self._camera_grant_valid(robot_id, camera_grant):
                    return
                version = self._model_frame_versions[robot_id]
            # Sensor confirmation can enter the same three-frame ring
            # between stream publication and waking this subscriber.
            # Native duplex only accepts actual stream speech/proactive
            # sources; never close its video feed over a sensor burst.
            frame = next((
                item for item in reversed(self.hub.frames[robot_id])
                if item.source in ("speech", "proactive")
            ), None)
            if (not self._camera_grant_valid(robot_id, camera_grant)):
                return
            if (frame is not None and frame.received_at > last_delivered
                    and _frame_is_fresh(frame.received_at, time.monotonic(), 1.0)):
                last_delivered = frame.received_at
                yield frame

    async def wait_for_proactive_frame(
        self, robot_id: str, after: float | None, *, timeout_s: float = 1.2
    ) -> bool:
        """Wake the existing pet observer on a real pushed visual receipt.

        This does not poll the camera, allocate another frame buffer or call
        the model. Use the same condition as the native live subscriber.
        Every source and generation check still happens in the pet observer.
        """
        self.hub._check(robot_id)
        condition = self._model_frame_conditions[robot_id]
        latest = after if after is not None else -math.inf
        camera_grant = getattr(self.settings, "camera_consent_generation", None)

        def ready() -> bool:
            return (self._closed or not self.settings.voice_vision_tools_enabled
                    or getattr(self.settings, "camera_consent_generation", None)
                       != camera_grant
                    or any(
                        frame.source == "proactive" and frame.received_at > latest
                        for frame in self.hub.frames[robot_id]
                    ))

        async with condition:
            try:
                await asyncio.wait_for(
                    condition.wait_for(ready), timeout=timeout_s
                )
            except TimeoutError:
                return False
            # A cached frame is not permission to observe after opt out.
            return (not self._closed and self._camera_grant_valid(robot_id, camera_grant)
                    and any(
                        frame.source == "proactive" and frame.received_at > latest
                        for frame in self.hub.frames[robot_id]
                    ))

    def start_streams(self) -> None:
        """Own the one persistent visual feed whenever camera consent is on.

        Not a separate controller. The permanent pet loop still decides if
        selected change evidence is worth a model call or a spoken reaction.
        """
        if self._closed:
            return
        for robot_id, head in self.heads.items():
            if not callable(getattr(head, "stream_frames", None)):
                continue
            # Hardware visual consent requires a real running feed. Never
            # quietly turn an outage into the old periodic snapshot design.
            require_stream = getattr(head, "require_stream", None)
            if self.settings.voice_vision_tools_enabled and callable(require_stream):
                require_stream()
            supervisor = self._stream_supervisors.get(robot_id)
            if supervisor is not None and not supervisor.done():
                continue
            worker = self._stream_tasks.get(robot_id)
            grant = getattr(self.settings, "camera_consent_generation", None)
            if self.settings.voice_vision_tools_enabled and (
                worker is None or worker.done()
            ):
                self._stream_tasks[robot_id] = asyncio.create_task(
                    self._consume_stream(robot_id, head, camera_grant=grant)
                )
            self._stream_supervisors[robot_id] = asyncio.create_task(
                self._supervise_stream_grants(robot_id, head, admitted_grant=grant)
            )

    async def _supervise_stream_grants(
        self, robot_id: str, head, *, admitted_grant: int | None,
    ) -> None:
        """Restart a newly consented stream only after the old MJPEG lease ends.

        The observer handles authorization, not images. Rapid OFF/ON still
        revokes the old worker; cancellation-resistant work keeps camera
        ownership until its async generator actually closes.
        """
        while not self._closed:
            await asyncio.sleep(0.05)
            if self._closed:
                return
            grant = getattr(self.settings, "camera_consent_generation", None)
            enabled = bool(self.settings.voice_vision_tools_enabled)
            worker = self._stream_tasks.get(robot_id)
            if grant != admitted_grant or not enabled:
                self._camera_grant_valid(robot_id, admitted_grant)
                if worker is not None and not worker.done():
                    if not worker.cancelling():
                        worker.cancel()
                    # Never overlap a cancellation-resistant HTTP lease.
                    continue
                admitted_grant = grant
            if not enabled:
                continue
            if worker is None or worker.done():
                if worker is not None and not worker.cancelled():
                    worker.exception()  # Observe unexpected worker errors.
                if not self._camera_grant_valid(robot_id, admitted_grant):
                    continue
                require_stream = getattr(head, "require_stream", None)
                if callable(require_stream):
                    try:
                        require_stream()
                    except Exception:
                        # An unsupported head must not silently fall back to snapshots.
                        self._metrics[robot_id]["stream_reconnects"] += 1
                        await asyncio.sleep(1.0)
                        continue
                self._last_stream_sample[robot_id] = -math.inf
                self._stream_tasks[robot_id] = asyncio.create_task(
                    self._consume_stream(robot_id, head, camera_grant=admitted_grant)
                )

    def _sync_camera_boot(self, robot_id: str) -> None:
        """Retire cached visual evidence when the authenticated head reboots."""
        identity = getattr(self.heads.get(robot_id), "_last_camera", None)
        if identity is None:
            return
        boot = identity[0]
        previous = self._camera_boots.get(robot_id)
        if boot == previous:
            return
        self._camera_boots[robot_id] = boot
        if previous is not None or self.hub.frames[robot_id]:
            self.hub.discard_video(robot_id)
            self._last_stream_sample[robot_id] = -math.inf

    async def _consume_stream(
        self, robot_id: str, head, *, camera_grant: int | None,
    ) -> None:
        """Drain continuous JPEGs; drop excess frames instead of queuing them.

        Frigate-style cheap frame comparison stays on the Mac. Only selected
        snapshots enter the existing three-frame RAM ring and VisualChangeGate.
        Voice/model requests still reuse this same authenticated source.
        """
        failures = 0
        while not self._closed and self.settings.voice_vision_tools_enabled:
            if not self._camera_grant_valid(robot_id, camera_grant):
                return
            try:
                # Closing the consumer must promptly release the head's sole
                # MJPEG HTTP lease, especially on live visual opt out. Plain
                # async-for does not guarantee an async generator is closed
                # before a return from the enclosing coroutine.
                async with aclosing(head.stream_frames()) as stream:
                    async for jpeg, received in stream:
                        # HttpHead validated the frame's device source header.
                        # Snapshot its clock before Pillow yields the loop.
                        source_identity = getattr(head, "_last_camera", None)
                        if self._closed or not self._camera_grant_valid(robot_id, camera_grant):
                            return
                        self._sync_camera_boot(robot_id)
                        failures = 0  # Healthy frames reset reconnection backoff.
                        metrics = self._metrics[robot_id]
                        metrics["stream_frames_received"] += 1
                        # Camera feed can be 4 FPS while cheap motion sampling is
                        # at most 2 FPS. No frame means no model work; no queue
                        # grows while Mac inference is busy.
                        now = time.monotonic()
                        # The head supplies MAC receipt times, not device clocks.
                        # Validate before storing the sampler cursor: a future
                        # timestamp would otherwise suppress every later real
                        # frame, while NaN would disable cadence filtering.
                        if (not _frame_is_fresh(received, now, _VISUAL_FRAME_MAX_AGE_S)
                                or received <= self._last_stream_sample[robot_id]):
                            metrics["stream_frames_skipped"] += 1
                            continue
                        local_speech = self.hub.user_active(robot_id, now)
                        # Another robot's human voice has priority for inference
                        # and the speaker, NOT a license to blind this robot.
                        # Continue lighter passive observation across the fleet.
                        sample_gap = (
                            1.0 if self._any_human_active(now) and not local_speech
                            else 0.5
                        )
                        # A fresh physical touch/cliff/handling edge deserves
                        # the next ALREADY streamed frame, even within the
                        # ordinary 500 ms idle sampling gap. Reuse the existing
                        # video feed instead of opening /api/camera.jpg. Do not
                        # accelerate inference or interfere with active human VAD.
                        recent_sensor_edge = (
                            self.hub.urgent[robot_id]
                            and not self._scheduled_camera_quiet("sensor")
                            and not self._any_human_active(now)
                            and any(
                                kind != "human_voice"
                                and 0 <= received - event_at <= 0.8
                                for kind, event_at in
                                self.hub.event_history[robot_id]
                            )
                        )
                        # The cheap video gate must keep observing at its
                        # bounded sample rate even when no earlier scene
                        # change has been detected. Applying the hub's
                        # 0.3 FPS *inference* cadence here blinds it to a
                        # briefly present object that appears after bootstrap.
                        # Expensive model comparisons remain separately
                        # guarded by PetController.VisualChangeGate and its
                        # salience, freshness and speech priority rules.
                        if (not recent_sensor_edge
                                and received - self._last_stream_sample[robot_id]
                                < sample_gap):
                            metrics["stream_frames_skipped"] += 1
                            continue
                        self._last_stream_sample[robot_id] = received
                        source = "speech" if local_speech else "proactive"
                        turn = self._turn_epoch[robot_id]
                        generation = self.hub._generation[robot_id]
                        try:
                            prepared = await self._prepare_bounded(
                                jpeg, priority=source == "speech"
                            )
                        except (RuntimeError, ValueError, OSError):
                            # A malformed or truncated JPEG is a bad FRAME, not
                            # a dead camera connection. Preserve the continuous
                            # stream and allow the next legitimate frame through.
                            # A true stream transport failure is still handled
                            # by the outer reconnect loop.
                            metrics["stream_frames_skipped"] += 1
                            continue
                        if not self._camera_grant_valid(robot_id, camera_grant):
                            # Opt out, including a rapid OFF/ON during Pillow,
                            # permanently cancels this old stream session.
                            return
                        # A slow Pillow worker can finish after this source
                        # frame's one-second live-video freshness window.
                        # Do not revive an obsolete scene, even if its receipt
                        # was valid before the asynchronous decode began.
                        if not _frame_is_fresh(received, time.monotonic(), 1.0):
                            metrics["stream_frames_skipped"] += 1
                            continue
                        if (self._closed or turn != self._turn_epoch[robot_id]
                                or generation != self.hub._generation[robot_id]
                                or (source == "proactive"
                                    and received <= self._last_fleet_human_turn_at)):
                            metrics["stream_frames_skipped"] += 1
                            continue
                        # Keep the inexpensive 2 FPS visual comparison
                        # alive after warmup, even when the long idle model
                        # cadence has not elapsed. A brief new desk object
                        # must reach the pet's scene gate before it vanishes.
                        # Identical/static images need not enter the shared
                        # three-frame context ring or wake native subscribers
                        # until the ordinary adaptive heartbeat is due.
                        # This uses the ALREADY decoded 64x48 gray image,
                        # never another head snapshot, video thread or VLM.
                        # Preserve one stable confirmation after an actual
                        # pixel transition. The semantic pet VisualChangeGate
                        # needs two changed observations against its baseline;
                        # dropping this frame would suppress an appearing key.
                        # The hub clears changed_streak on that confirmation,
                        # so subsequent static frames retain their cheap skip.
                        if (not recent_sensor_edge
                                and len(self.hub.frames[robot_id]) >= 2
                                and not self.hub.due(robot_id, received)
                                and self.hub.changed_streak[robot_id] == 0):
                            earlier = self.hub.previous_gray.get(robot_id)
                            if (earlier is not None
                                    and change_fraction(earlier, prepared[1])
                                    < _STREAM_VISUAL_CHANGE_MIN_FRACTION):
                                metrics["stream_frames_skipped"] += 1
                                continue
                        try:
                            self.hub.offer_prepared(
                                robot_id, prepared, received, source=source,
                                generation=generation,
                                source_identity=source_identity,
                            )
                        except (RuntimeError, ValueError):
                            metrics["stream_frames_skipped"] += 1
                        else:
                            metrics["stream_frames_selected"] += 1
                            # An attempted urgent frame that failed JPEG decoding
                            # must never masquerade as successful sensor context.
                            if recent_sensor_edge:
                                metrics["stream_sensor_priority_frames"] += 1
                            async with self._model_frame_conditions[robot_id]:
                                self._model_frame_versions[robot_id] += 1
                                self._model_frame_conditions[robot_id].notify_all()
                if self._closed:
                    break
                raise RuntimeError("XIAO camera stream ended")
            except asyncio.CancelledError:
                raise
            except Exception:
                failures += 1
                self._metrics[robot_id]["stream_reconnects"] += 1
                # Camera loss is not permission to touch the WROOM motor or
                # release an authenticated voice floor. Old frames expire.
                self.hub.discard_video(robot_id)
                await asyncio.sleep(min(8, 2 ** min(failures - 1, 3)))
            else:
                failures = 0

    def sensor_event(
        self, robot_id: str, kind: str, received_at: float | None = None,
        *, detail: str | None = None,
    ) -> None:
        """Fast event priority, separate from VLM, TTS and WROOM motion.

        Schedule at most one bounded two-frame confirmation burst per head
        in an 800 ms coalescing window, never a second camera owner.
        The existing capture lock still serializes real XIAO JPEG requests.
        """
        now = time.monotonic()
        stamp = now if received_at is None else received_at
        self.hub._check(robot_id)
        if (type(kind) is not str or kind not in TRIGGERS
                or not _finite(stamp) or stamp > now):
            raise ValueError("Unknown physical event or invalid receipt time")
        # Do not resurrect an edge after its existing eight-second live TTL.
        # PetController still retains independently timestamped attention and memory.
        if now - stamp > 8:
            return
        self.hub.notify(robot_id, kind, stamp, detail=detail)
        self._metrics[robot_id]["sensor_triggers"] += 1
        if self._scheduled_camera_quiet("sensor"):
            return  # Preserve the physical event, but do not request a camera burst.
        if self._closed or self._any_human_active(now):
            self._metrics[robot_id]["sensor_deferred_human"] += 1
            return  # any live human voice owns the fleet's camera priority
        # Local WROOM sensor and fault evidence is independent of camera consent.
        # Never turn a touch or cliff edge into a legacy snapshot opt-in.
        if (getattr(self.settings, "mode", "hardware") == "hardware"
                and not self.settings.voice_vision_tools_enabled):
            return
        self._cancel_proactive_snapshot(robot_id)
        # The selected Sense hardware runs one *continuous* authenticated
        # MJPEG stream. A sensor edge labels RAM context immediately; the next
        # streamed frame already reaches the pet's visual change gate. Starting
        # a second /camera.jpg "confirmation burst" races that same physical
        # sensor and returns busy, even when the stream temporarily reconnects.
        # Keep snapshot confirmation only for test/legacy heads without a
        # persistent feed. Stream outage must fail closed, not trigger pulls.
        if self.stream_owns_camera(robot_id):
            pending = self._sensor_tasks.get(robot_id)
            if pending is not None and not pending.done():
                pending.cancel()
            self._metrics[robot_id]["sensor_stream_reuses"] += 1
            return
        pending = self._sensor_tasks.get(robot_id)
        if (pending is not None and not pending.done()
                or now - self._last_sensor_request[robot_id] < 0.8):
            self._metrics[robot_id]["sensor_coalesced"] += 1
            return
        self._last_sensor_request[robot_id] = now
        self._metrics[robot_id]["sensor_bursts"] += 1
        self._sensor_tasks[robot_id] = asyncio.create_task(
            self._sensor_frame(
                robot_id, requested_at=stamp, trigger_kind=kind,
                camera_grant=getattr(self.settings, "camera_consent_generation", None),
            )
        )

    async def _sensor_frame(self, robot_id: str, *, requested_at: float,
                            trigger_kind: str, camera_grant: int | None) -> None:
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
                # A new grant cannot authorize the original sensor edge.
                if (getattr(self.settings, "mode", "hardware") == "hardware"
                        and not self._camera_grant_valid(robot_id, camera_grant)):
                    return
                if self._scheduled_camera_quiet("sensor"):
                    return
                question = self._look_tasks.get(robot_id)
                if (self._closed or self._any_human_active(
                    time.monotonic()
                ) or (question is not None and not question.done())):
                    return
                evidence = await self.capture(
                    robot_id, source="sensor", trigger_kind=trigger_kind
                )
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
            # A lost authenticated voice session invalidates its tool turn,
            # unlike a camera-only outage that preserves nonvisual readings.
            self.hub.tool_history[robot_id].clear()
            # Transport loss ends provenance for native audio transcripts,
            # even when their 30-second display TTL has not yet elapsed.
            self.hub.heard_history[robot_id].clear()

    def voice_started(self, robot_id: str) -> None:
        self.prepare_human_turn(robot_id, end_expected=True)
        self.start_speech_frames(robot_id)

    def voice_interrupted(self, robot_id: str) -> None:
        # AEC double talk has no guaranteed matching speech_end.
        self.prepare_human_turn(robot_id, end_expected=False)
        self.start_speech_frames(robot_id)

    def prepare_human_turn(self, robot_id: str, *, end_expected: bool) -> int:
        """Immediately fence camera/old tools before awaiting slow audio STOP.

        The authenticated Mac VAD callback calls this synchronously, then
        urgently flushes the ONE Xiaozhi speech owner. No JPEG is scheduled
        until that higher-priority stop has returned.
        """
        now = time.monotonic()
        self._voice_turn_at[robot_id] = now
        self._last_fleet_human_turn_at = now
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
            # Invalidate stale camera interpretations across the fleet.
            # A human speaking to another pet must not erase this pet's
            # independent completed pickup, status or private memory facts.
            if peer == robot_id:
                self.hub.tool_history[peer].clear()
            else:
                self.hub.discard_visual_tools(peer)
            self._cancel_proactive_snapshot(peer)
            # The fallback speech sampler owns the previous turn too. Cancel
            # it before the slow audio STOP so start_speech_frames can replace
            # it even when an AEC edge arrives without a preceding speech_end.
            sampler = self._capture_tasks.get(peer)
            if (sampler is not None and not sampler.done()
                    and not sampler.cancelling()):
                sampler.cancel()
            pending_sensor = self._sensor_tasks.get(peer)
            if pending_sensor is not None and not pending_sensor.done():
                pending_sensor.cancel()
            prior = self._look_tasks.get(peer)
            if prior is not None and not prior.done():
                prior.cancel()
        # The caller must not activate camera work for a superseded human turn
        # after awaiting an older, slow device speaker STOP.
        return self._turn_epoch[robot_id]

    def prepared_turn_epoch(self, robot_id: str) -> int:
        """Read the final turn token after a batch of fleet VAD starts."""
        self.hub._check(robot_id)
        return self._turn_epoch[robot_id]

    def start_speech_frames(
        self, robot_id: str, *, prepared_epoch: int | None = None,
    ) -> None:
        """Start optional VAD JPEGs only for a still-current prepared turn."""
        self.hub._check(robot_id)
        if prepared_epoch is not None and prepared_epoch != self._turn_epoch[robot_id]:
            return
        if (self._closed or not self.settings.voice_vision_tools_enabled
                or not self.hub.user_active(robot_id, time.monotonic())):
            return
        if self.stream_owns_camera(robot_id):
            # This head already provides continuous live frames. VAD changes
            # the selected frame priority, not physical acquisition. Starting
            # an old one-FPS snapshot poller would duplicate that same JPEG.
            return
        task = self._capture_tasks.get(robot_id)
        if task is None or task.done() or task.cancelling():
            # A new VAD start can race with the prior speech_end cancellation.
            # Replace that cancelling worker instead of leaving the new
            # utterance without any camera samples.
            # NEVER await a camera capture in the realtime VAD cancellation
            # callback. Audio playback stops without waiting for JPEG/LLM.
            self._capture_tasks[robot_id] = asyncio.create_task(
                self._speech_frames(
                    robot_id, self._turn_epoch[robot_id],
                    camera_grant=getattr(self.settings, "camera_consent_generation", None),
                )
            )

    def voice_ended(self, robot_id: str) -> None:
        self.hub.speech_ended(robot_id, time.monotonic())
        task = self._capture_tasks.get(robot_id)
        if task is not None and not task.done():
            task.cancel()  # Preserve captured visual context for current ASR.

    async def _speech_frames(
        self, robot_id: str, turn: int, *, camera_grant: int | None,
    ) -> None:
        try:
            # Keep the 1 FPS visual stream for a genuinely long utterance,
            # but cap unacknowledged camera work if a VAD end is lost. The
            # voice floor itself remains held until explicit end/disconnect.
            for _ in range(60):
                if (self._closed or turn != self._turn_epoch[robot_id]
                        or not self._camera_grant_valid(robot_id, camera_grant)
                        or not self.hub.user_active(
                            robot_id, time.monotonic()
                        )):
                    break
                if self.hub.due(robot_id, time.monotonic()):
                    try:
                        await self.capture(
                            robot_id, source="speech", reuse_if_recent_s=0.65
                        )
                        if turn != self._turn_epoch[robot_id]:
                            return  # Older cancelled sampler cannot own a new VAD turn.
                    except RuntimeError as exc:
                        if turn != self._turn_epoch[robot_id]:
                            return  # Obsolete failure cannot clear new frames.
                        # A cancelled lower-priority sensor snapshot can still
                        # be the sole real device reader for one more event-loop
                        # tick. The strict single-owner gate must not kill the
                        # current human VAD camera sampler permanently. Retry
                        # ONLY that bounded ownership contention, without
                        # launching a second physical capture or reviving an
                        # older conversation generation.
                        if str(exc) == "Previous XIAO camera snapshot still in flight":
                            await asyncio.sleep(0.05)
                            continue
                        self.hub.discard_video(robot_id)
                        break
                    except Exception:
                        if turn != self._turn_epoch[robot_id]:
                            return  # Obsolete failure cannot clear new frames.
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
        if self._closed:
            raise RuntimeError("Camera orchestration is closed")
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

        # Keep native futures independent of cancelled asyncio awaiters.
        # Only the event-loop owner mutates this bounded registry.
        self._preprocess_futures = {
            worker for worker in self._preprocess_futures if not worker.done()
        }
        self._preprocess_futures.add(future)

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

    async def _head_snapshot(
        self, robot_id: str, *, source: str,
    ) -> tuple[bytes, float, tuple[int, int, int] | None]:
        """One real device read until its task exits, even after a timeout."""
        camera_grant = getattr(self.settings, "camera_consent_generation", None)
        previous = self._head_snapshot_tasks.get(robot_id)
        if previous is not None:
            if not previous.done() and source in ("speech", "voice_question"):
                # Human VAD cancels a lower-priority sensor snapshot without
                # waiting for its underlying XIAO driver to unwind. Give that
                # *existing physical owner* a bounded chance to exit before
                # starting the new speech frame. This wait is in the JPEG
                # worker only, never on the urgent audio STOP/VAD callback.
                # An uncooperative old driver still fails closed: absolutely
                # no overlapping physical camera requests are permitted.
                await asyncio.wait({previous}, timeout=0.25)
            if not previous.done():
                raise RuntimeError("Previous XIAO camera snapshot still in flight")
            self._head_snapshot_tasks.pop(robot_id, None)

        async def read_snapshot():
            # The child can start after the parent last checked consent.
            if (getattr(self.settings, "mode", "hardware") == "hardware"
                    and not self._camera_grant_valid(robot_id, camera_grant)):
                raise RuntimeError("Camera consent revoked before device capture")
            if self._scheduled_camera_quiet(source):
                raise RuntimeError("Scheduled quiet hours block speculative camera capture")
            head = self.heads[robot_id]
            receipt = getattr(head, "snapshot_receipt", None)
            if callable(receipt):
                return await receipt()
            # Legacy adapters have no authenticated device clock.
            jpeg = await head.snapshot()
            return jpeg, time.monotonic(), None

        task = asyncio.create_task(read_snapshot())
        self._head_snapshot_tasks[robot_id] = task
        # Observe late adapter failures; obsolete frames are never published.
        task.add_done_callback(
            lambda finished: None if finished.cancelled()
            else finished.exception()
        )
        if source == "proactive":
            self._proactive_snapshots[robot_id] = task
        try:
            return await _bounded_head_reply(
                task, seconds=4.0,
                timeout_message=(
                    "Live proactive camera timed out"
                    if source == "proactive" else "Live human camera timed out"
                ),
            )
        finally:
            if self._proactive_snapshots.get(robot_id) is task:
                self._proactive_snapshots.pop(robot_id, None)
            # Preserve incomplete work as the one physical camera owner.
            if task.done() and self._head_snapshot_tasks.get(robot_id) is task:
                self._head_snapshot_tasks.pop(robot_id, None)

    async def capture(self, robot_id: str, *, source: str,
                      reuse_if_recent_s: float = 0.0,
                      trigger_kind: str | None = None) -> CameraEvidence:
        self.hub._check(robot_id)
        _validate_camera_cue(source, trigger_kind)
        if not _finite(reuse_if_recent_s) or not 0 <= reuse_if_recent_s <= 1.0:
            raise ValueError("Invalid shared live camera age")
        camera_grant = getattr(self.settings, "camera_consent_generation", None)
        if self._closed:
            raise RuntimeError("Multimodal orchestrator closed")
        if (getattr(self.settings, "mode", "hardware") == "hardware"
                and not self._camera_grant_valid(robot_id, camera_grant)):
            raise RuntimeError("Camera consent revoked for capture")
        if self._scheduled_camera_quiet(source):
            raise RuntimeError("Scheduled quiet hours block speculative camera capture")
        if (source == "proactive"
                and (pending := self._look_tasks.get(robot_id)) is not None
                and not pending.done()):
            raise RuntimeError("Explicit human look owns this camera")
        # Keep the request's original conversation ownership while queued.
        # Waiting for a camera lock does not admit a new human turn.
        turn = self._turn_epoch[robot_id]
        question = self._question_epoch[robot_id]
        # HttpHead.capture_lock provides serialization with pet observation,
        # dock calibration and pickup. Do not bypass its strict source checks.
        async with self._camera_locks[robot_id]:
            if self._closed:
                raise RuntimeError("Multimodal orchestrator closed")
            if (turn != self._turn_epoch[robot_id]
                    or question != self._question_epoch[robot_id]):
                raise RuntimeError("Camera capture superseded by newer conversation turn")
            if (getattr(self.settings, "mode", "hardware") == "hardware"
                    and not self._camera_grant_valid(robot_id, camera_grant)):
                raise RuntimeError("Camera consent revoked for capture")
            if (source == "proactive"
                    and (pending := self._look_tasks.get(robot_id)) is not None
                    and not pending.done()):
                raise RuntimeError("Explicit human look owns this camera")
            self._sync_camera_boot(robot_id)
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
                            and _frame_is_fresh(frame.received_at, now, reuse_if_recent_s)
                            and frame.received_at >= self._voice_turn_at[robot_id]):
                        metrics["native_speech_camera_reuses"] += 1
                        return frame
            metrics["camera_requests"] += 1
            started = time.monotonic()
            generation = self.hub._generation[robot_id]
            # Camera latency is measured before CPU postprocessing. A new
            # human voice can still preempt the event loop during decoding.
            try:
                if source == "proactive" and self._any_human_active(time.monotonic()):
                    raise RuntimeError("Human speech preempts autonomous camera")
                jpeg, received, source_identity = await self._head_snapshot(
                    robot_id, source=source
                )
                if self._closed:
                    raise RuntimeError("Multimodal orchestrator closed")
                prepared = await self._prepare_bounded(
                    jpeg, priority=source in ("speech", "voice_question")
                )
                if self._closed:
                    raise RuntimeError("Multimodal orchestrator closed")
                # Source JPEG reception is not the last priority boundary.
                # A human can begin speaking while the CPU worker is
                # decoding/resizing this JPEG, after the proactive network
                # task has already disappeared from its cancellation map.
                # Never publish obsolete low-priority sensor/idle images.
                # A native speech JPEG is also an asynchronous tool result.
                # Its API request is not owned by _capture_tasks, so cancelling
                # that sampler on reconnect or a newer VAD is insufficient:
                # old HTTP/decode work must never repopulate the emptied hub.
                if (getattr(self.settings, "mode", "hardware") == "hardware"
                        and not self._camera_grant_valid(robot_id, camera_grant)):
                    # A short OFF/ON during JPEG I/O or Pillow remains revoked
                    # for this request even when the current boolean is True.
                    raise RuntimeError("Camera consent revoked for capture")
                if self._scheduled_camera_quiet(source):
                    raise RuntimeError("Scheduled quiet hours block speculative camera capture")
                if (self._turn_epoch[robot_id] != turn
                        or self._question_epoch[robot_id] != question):
                    raise RuntimeError(
                        "Camera capture superseded by newer conversation turn"
                    )
                if (source in ("proactive", "sensor")
                        and self._any_human_active(time.monotonic())):
                    raise RuntimeError(
                        "Human speech preempts autonomous camera preprocessing"
                    )
                # Apply the same receipt-age limit as the continuous stream.
                # A blocked JPEG worker must not revive a stale snapshot.
                if not _frame_is_fresh(received, time.monotonic(), 1.0):
                    raise RuntimeError("Camera snapshot expired during preprocessing")
                self._sync_camera_boot(robot_id)
                current_identity = getattr(self.heads[robot_id], "_last_camera", None)
                if (source_identity is not None and current_identity is not None
                        and source_identity[0] != current_identity[0]):
                    raise RuntimeError("Camera snapshot belongs to a retired boot")
                if generation != self.hub._generation[robot_id]:
                    raise RuntimeError("Old camera generation discarded")
                if (source in ("speech", "voice_question")
                        and received < self._voice_turn_at[robot_id]):
                    raise RuntimeError("Camera snapshot predates current human turn")
                # The continuous reader may have admitted this exact frame
                # during preprocessing. Reuse it without relabeling its source.
                recent = self.hub.frames[robot_id]
                if (source_identity is not None and recent
                        and recent[-1].received_at == received
                        and recent[-1].source_identity == source_identity):
                    evidence = recent[-1]
                else:
                    evidence = self.hub.offer_prepared(
                        robot_id, prepared, received, source=source,
                        generation=generation, trigger_kind=trigger_kind,
                        source_identity=source_identity,
                    )
                metrics["camera_successes"] += 1
                metrics["camera_latency_last_ms"] = round(
                    (time.monotonic() - started) * 1000
                )
                return evidence
            except Exception:
                metrics["camera_errors"] += 1
                raise

    def latest_fleet_human_turn_at(self) -> float:
        """When the last authenticated human started speaking to ANY pet."""
        return self._last_fleet_human_turn_at

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
        camera_grant = getattr(self.settings, "camera_consent_generation", None)
        # An external JPEG is not consent: mirror the continuous Sense stream.
        if not self._camera_grant_valid(robot_id, camera_grant):
            return
        if not _frame_is_fresh(now, time.monotonic(), 1.0):
            return
        generation = self.hub._generation[robot_id]
        turn = self._turn_epoch[robot_id]
        question = self._question_epoch[robot_id]
        prepared = await self._prepare_bounded(jpeg)
        if not self._camera_grant_valid(robot_id, camera_grant):
            # An old JPEG cannot enter the regranted scene after Pillow.
            return
        if not _frame_is_fresh(now, time.monotonic(), 1.0):
            return
        if (self._any_human_active(time.monotonic())
                or self._turn_epoch[robot_id] != turn
                or self._question_epoch[robot_id] != question
                or now < self._last_fleet_human_turn_at):
            # External pet capture may finish just as an entire human VAD
            # episode begins and ends. Receipt and generation both matter.
            return
        self.hub.offer_prepared(
            robot_id, prepared, now, source="proactive",
            generation=generation,
        )

    async def look(self, robot_id: str, question: str) -> dict:
        self.hub._check(robot_id)
        if (not self.settings.voice_vision_tools_enabled
                or not self.settings.vision_model):
            raise ValueError("Enable local voice vision and install a vision model")
        # A newly granted question must never borrow a JPEG buffered under
        # the previous grant, even if no camera task saw the brief opt out.
        self._camera_grant_valid(
            robot_id, getattr(self.settings, "camera_consent_generation", None)
        )
        # Consent revocation is permanent for this request, even after regrant.
        camera_consent_generation = getattr(
            self.settings, "camera_consent_generation", None
        )
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
        # Reserve the shared VLM until the direct question is completely
        # resolved or cancelled. One-time preemption alone lets a new
        # background comparison queue during the slow JPEG capture.
        begin, end = self.begin_direct_vision, self.end_direct_vision
        reserved = callable(begin) and callable(end)
        if reserved:
            begin()
        else:
            preempt = self.preempt_background_vision
            if callable(preempt):
                preempt()
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
            self._sync_camera_boot(robot_id)
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
            self._sync_camera_boot(robot_id)
            chosen = self.hub.selected(robot_id, question, time.monotonic())
            if not chosen:
                raise RuntimeError("No fresh authenticated camera images available")
            # Camera-only loss preserves the human turn but invalidates its frames.
            camera_generation = self.hub._generation[robot_id]
            async with self.inference_lock:
                # Higher-priority user turns can arrive while waiting for a
                # busy five-robot VLM. Never evaluate a stale older question.
                if not current_turn():
                    raise RuntimeError("Visual question superseded while queued")
                # The grant can change while the fleet inference lock is held
                # by another pet. Never dispatch old-grant JPEGs to the model.
                if not self._camera_grant_valid(robot_id, camera_consent_generation):
                    raise RuntimeError("Camera consent revoked while queued")
                self._sync_camera_boot(robot_id)
                if camera_generation != self.hub._generation[robot_id]:
                    raise RuntimeError("Camera evidence invalidated while queued")
                # Local 4B+ vision inference can be much slower than the
                # source exposure. Do not let a 45 second provider request
                # claim a scene is still current or delay new user turns.
                model_started = time.monotonic()
                # Both images of a temporal comparison must still be fresh.
                if not all(
                    _frame_is_fresh(frame.received_at, model_started, _VISUAL_FRAME_MAX_AGE_S)
                    for frame in chosen
                ):
                    raise RuntimeError("Camera observation expired while queued")
                # The oldest selected image limits the whole inference budget.
                # A provider timeout is not permission to describe expired JPEGs.
                remaining = min(
                    self._vision_timeout_s,
                    min(frame.received_at + _VISUAL_FRAME_MAX_AGE_S for frame in chosen)
                    - model_started,
                )
                if remaining <= 0:
                    raise RuntimeError("Camera observation expired while queued")
                try:
                    # An alternate VLM client may swallow cancellation after
                    # the deadline. Its late response must not retain the
                    # common inference lock or become a new human answer.
                    def admit_answer() -> bool:
                        self._sync_camera_boot(robot_id)
                        now = time.monotonic()
                        return (
                            current_turn()
                            and self._camera_grant_valid(robot_id, camera_consent_generation)
                            and camera_generation == self.hub._generation[robot_id]
                            and all(
                                _frame_is_fresh(frame.received_at, now, _VISUAL_FRAME_MAX_AGE_S)
                                for frame in chosen
                            )
                        )

                    images = [frame.jpeg for frame in chosen]
                    # The real adapter decodes off-thread. Recheck the exact
                    # request grant at its final model submission boundary.
                    if isinstance(self.scene, OllamaScene):
                        request = self.scene.answer(question, images, admit=admit_answer)
                    else:
                        request = self.scene.answer(question, images)
                    answer = await _bounded_head_reply(
                        request,
                        seconds=remaining,
                        timeout_message="Live visual analysis timed out",
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
            if not self.settings.voice_vision_tools_enabled:
                # Revoking consent during the slow model call must not
                # publish a private scene guess into Mac memory or a reply.
                raise RuntimeError("Camera consent revoked during visual analysis")
            if (camera_consent_generation is not None
                    and getattr(self.settings, "camera_consent_generation", None)
                    != camera_consent_generation):
                raise RuntimeError("Camera consent revoked during visual analysis")
            self._sync_camera_boot(robot_id)
            if camera_generation != self.hub._generation[robot_id]:
                raise RuntimeError("Camera evidence invalidated during visual analysis")
            completed_at = time.monotonic()
            if not all(
                _frame_is_fresh(frame.received_at, completed_at, _VISUAL_FRAME_MAX_AGE_S)
                for frame in chosen
            ):
                raise RuntimeError("Camera observation expired during visual analysis")
            metrics["visual_answers"] += 1
            # The read-only answer is bound to the exact accepted question
            # epoch and real Mac JPEG. It is a short-lived interpretation,
            # never a second camera/VLM agent or evidence of motion success.
            self.hub.remember_tool(
                robot_id, "visual_look", answer, completed_at
            )
            return {
                "robot_id": robot_id,
                "answer": answer,
                "frames_used": len(chosen),
                "latest_frame_age_ms": round(
                    1000 * (completed_at - chosen[-1].received_at)
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
            if reserved:
                end()

    async def close(self) -> None:
        self._closed = True
        self._camera_revocation_callback = None
        registries = (
            self._capture_tasks, self._stream_tasks, self._stream_supervisors,
            self._sensor_tasks, self._look_tasks, self._proactive_snapshots,
            self._head_snapshot_tasks,
        )
        tasks = {task for registry in registries for task in registry.values()}
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()

        # Shut admission before awaiting any worker. Cancelling an asyncio
        # wrapper does not terminate a running native Pillow decode.
        self._preprocess_pool.shutdown(wait=False, cancel_futures=True)
        native_waiters = [
            asyncio.wrap_future(worker)
            for worker in self._preprocess_futures if not worker.done()
        ]
        for waiter in native_waiters:
            waiter.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
        # One deadline for all asyncio and native workers, not one per pet.
        waiters = tasks.union(native_waiters)
        if waiters:
            await asyncio.wait(waiters, timeout=0.5)

        def retire(owner, robot_id, task):
            if not task.cancelled():
                task.exception()
            if owner.get(robot_id) is task:
                owner.pop(robot_id, None)

        # Preserve unfinished owners and observe their terminal exceptions.
        for registry in registries:
            for robot_id, task in tuple(registry.items()):
                if task.done():
                    retire(registry, robot_id, task)
                else:
                    task.add_done_callback(
                        lambda done, rid=robot_id, owner=registry: retire(owner, rid, done)
                    )
        self.hub.close()
        self._preprocess_futures = {
            worker for worker in self._preprocess_futures if not worker.done()
        }
        unfinished = sum(not task.done() for task in tasks)
        if unfinished or self._preprocess_futures:
            raise TimeoutError(
                f"Camera shutdown unconfirmed: {unfinished} async workers and "
                f"{len(self._preprocess_futures)} native JPEG workers still active"
            )
