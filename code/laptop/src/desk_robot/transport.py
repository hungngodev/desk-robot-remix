from __future__ import annotations

import asyncio
import re
import time
from typing import Protocol

import httpx

from .aux import validate_aux
from .config import RobotConfig, secret
from .dock_ir import validate_ir
from .spatial_pose import PoseError, PoseFence, PoseReceipt
from .tof_optics import validate_optics

# HTTPX timeouts are per I/O phase, not a whole finite response deadline.
_REQUEST_DEADLINE_SECONDS = 3.0

# Sense emits signed int64 esp_timer_get_time() microseconds in both camera routes.
_MAX_CAMERA_COMPLETE_US = (1 << 63) - 1
# Bound time without a complete JPEG, not merely time without network bytes.
_MJPEG_FRAME_TIMEOUT_SECONDS = 3.0

# Wire contract: omitted duration uses the same bound as WROOM kMaxDriveMs.
MAX_DRIVE_DURATION_MS = 250


class HeadError(RuntimeError):
    """A failed request may already have actuated: never automatically retry it."""


class PoseUnsupported(HeadError):
    """The pose capability is absent or uses a different wire version."""


class Head(Protocol):
    async def command(self, command: str) -> dict: ...
    async def status(self) -> dict: ...
    async def aux_status(self) -> dict: ...
    async def optics_status(self) -> dict: ...
    async def ir_status(self) -> dict: ...
    async def pose_status(self) -> PoseReceipt: ...
    async def snapshot(self) -> bytes: ...


def _drive_duration_ms(args: list[str]) -> int:
    return int(args[2]) if len(args) == 3 else MAX_DRIVE_DURATION_MS


def validate_command(command: str) -> str:
    if (
        not isinstance(command, str)
        or len(command) > 95
        or not re.fullmatch(r"[a-z0-9 -]+", command)
    ):
        raise ValueError("Invalid command")
    tokens = command.split(" ")
    op = tokens[0]
    if op in {"ping", "status", "arm", "disarm", "stop", "halt", "keepalive"} and len(tokens) == 1:
        return op
    if op == "drive" and len(tokens) in (3, 4):
        values = tokens[1:]
        if not all(re.fullmatch(r"-?[0-9]{1,3}", x) for x in values):
            raise ValueError("drive arguments must be integers")
        left, right = map(int, values[:2])
        duration = _drive_duration_ms(values)
        if -40 <= left <= 40 and -40 <= right <= 40 and 1 <= duration <= MAX_DRIVE_DURATION_MS:
            return op
    if op in {"lift", "grip"} and len(tokens) == 2 and tokens[1].isdigit():
        if 60 <= int(tokens[1]) <= 120:
            return op
    raise ValueError("Command exceeds conservative bounds")


def drive_duration_ms(command: str) -> int:
    """Return the validated explicit or default wire duration of a drive command."""
    if validate_command(command) != "drive":
        raise ValueError("Expected a drive command")
    return _drive_duration_ms(command.split()[1:])


def expected_ack(command: str) -> str:
    op = validate_command(command)
    args = command.split()[1:]
    if op == "drive":
        left, right = map(int, args[:2])
        ms = _drive_duration_ms(args)
        return f"OK drive left={left} right={right} ms={ms}"
    if op in {"lift", "grip"}:
        return f"OK {op} angle={int(args[0])}"
    return f"OK {op}"


class _MjpegFrames:
    """Bounded parser for Espressif style multipart JPEG, not an image decoder.

    Network chunks do not align with part headers or JPEG boundaries. Parse
    exact Content-Length and camera identity before publishing any image.
    Reject oversized headers, payloads, missing EOI, and malformed framing.
    """

    boundary = b"--deskrobotframe\r\n"

    def __init__(self, expected_robot_id: str | None = None):
        self.buffer = bytearray()
        self.expected_robot_id = expected_robot_id

    def feed(self, chunk: bytes) -> list[tuple[bytes, tuple[int, int, int]]]:
        # Retain the bounded batch helper for unit callers.
        return list(self.iter_feed(chunk))

    def iter_feed(self, chunk: bytes):
        """Yield verified parts without retaining a whole network batch."""
        if not isinstance(chunk, bytes):
            raise ValueError("Invalid MJPEG network chunk")
        # The per-part 512 KiB limit does not cap a *single* network batch.
        # Refuse a multi-megabyte burst BEFORE parsing any frame while
        # holding the shared stream lock. A healthy 4 FPS source fits.
        if len(chunk) > 4 * 1024 * 1024:
            raise ValueError("Oversized MJPEG network batch")
        total_parts = 0
        for offset in range(0, len(chunk), 64 * 1024):
            for frame in self._feed_bounded_chunk(chunk[offset:offset + 64 * 1024]):
                total_parts += 1
                if total_parts > 32:
                    raise ValueError("Oversized MJPEG frame count")
                yield frame

    def _feed_bounded_chunk(self, chunk: bytes) -> list[tuple[bytes, tuple[int, int, int]]]:
        self.buffer.extend(chunk)
        frames = []
        while self.buffer:
            if len(self.buffer) < len(self.boundary):
                if not self.boundary.startswith(self.buffer):
                    raise ValueError("Invalid MJPEG part boundary")
                break
            if not self.buffer.startswith(self.boundary):
                raise ValueError("Invalid MJPEG part boundary")
            end = self.buffer.find(b"\r\n\r\n", len(self.boundary))
            if end < 0:
                if len(self.buffer) > 512:
                    raise ValueError("Oversized MJPEG part headers")
                break
            if end > 512:
                raise ValueError("Oversized MJPEG part headers")
            try:
                lines = bytes(self.buffer[len(self.boundary):end]).decode("ascii").split("\r\n")
                headers = {}
                for line in lines:
                    name, value = line.split(": ", 1)
                    key = name.lower()
                    if key in headers:
                        raise ValueError("Duplicate MJPEG part header")
                    headers[key] = value
                if headers.get("content-type") != "image/jpeg":
                    raise ValueError("MJPEG part is not JPEG")
                def decimal(name: str, headers=headers) -> int:
                    value = headers[name]
                    if not 1 <= len(value) <= 20 or not value.isascii() or not value.isdecimal():
                        raise ValueError("Invalid MJPEG numeric header")
                    return int(value)
                size = decimal("content-length")
                boot = decimal("x-desk-camera-boot")
                sequence = decimal("x-desk-camera-sequence")
                completed = decimal("x-desk-camera-complete-us")
            except (UnicodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError("Malformed MJPEG part headers") from exc
            # Keep a wrong robot ID distinguishable from corrupt transport
            # framing. Wrong-pet frames are never admitted to the vision hub.
            identity = headers.get("x-desk-camera-robot-id")
            if (not isinstance(identity, str)
                    or re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", identity) is None):
                raise ValueError("MJPEG camera robot identity missing or malformed")
            if (self.expected_robot_id is not None
                    and identity != self.expected_robot_id):
                raise ValueError("MJPEG camera robot identity mismatch")
            if not (4 <= size <= 512 * 1024 and 0 <= boot <= 0xffffffff
                    and 1 <= sequence <= 0xffffffff
                    and 1 <= completed <= _MAX_CAMERA_COMPLETE_US):
                raise ValueError("MJPEG source bounds invalid")
            start = end + 4
            finish = start + size
            if len(self.buffer) < finish + 2:
                break
            frame = bytes(self.buffer[start:finish])
            if (not frame.startswith(b"\xff\xd8")
                    or not frame.endswith(b"\xff\xd9")
                    or self.buffer[finish:finish + 2] != b"\r\n"):
                raise ValueError("MJPEG frame incomplete")
            # Tiny but valid parts must not expand one bounded socket read
            # into unbounded parser work on the shared audio/vision loop.
            if len(frames) >= 32:
                raise ValueError("Oversized MJPEG frame count")
            frames.append((frame, (boot, sequence, completed)))
            del self.buffer[:finish + 2]
        if len(self.buffer) > 512 * 1024 + 1024:
            raise ValueError("MJPEG buffer exceeds maximum size")
        return frames


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    """Refuse ambiguous fields at every depth of an authenticated receipt."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate authenticated head JSON field")
        result[key] = value
    return result


def _response_object(response: httpx.Response) -> dict:
    """Never treat malformed authenticated JSON as an unexpected server fault."""
    try:
        data = response.json(object_pairs_hook=_unique_json_object)
    except ValueError as exc:
        raise HeadError("Malformed authenticated head JSON response") from exc
    if not isinstance(data, dict):
        raise HeadError("Malformed authenticated head JSON object")
    return data


class HttpHead:
    # These operations cannot create a new moving/armed session. Only an
    # acknowledged terminal HALT clears an uncertain command outcome.
    _RECOVERY_COMMANDS = frozenset({"ping", "status", "stop", "disarm", "halt"})
    supports_dispatch_check = True

    def __init__(
        self, config: RobotConfig, client: httpx.AsyncClient,
        *, strict_capture: bool = False
    ):
        self.config = config
        self.pose_fence = PoseFence(config.id)
        self.client = client
        self.lock = asyncio.Lock()
        self.command_lock = asyncio.Lock()
        self._command_generation = 0
        self._command_uncertain = False
        self.capture_lock = asyncio.Lock()
        self.strict_capture = strict_capture
        self._last_camera: tuple[int, int, int] | None = None
        self._retired_camera_boots: set[int] = set()
        self._stream_connected = False
        self._stream_generation = 0
        self._stream_required = False
        self._stream_condition = asyncio.Condition()
        self._stream_latest: bytes | None = None
        self._stream_received_at = 0.0
        self._stream_version = 0
        self._snapshot_version = 0

    def require_stream(self) -> None:
        """Visual mode is continuous, never silently demoted to JPEG polling."""
        self._stream_required = True

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            async with asyncio.timeout(_REQUEST_DEADLINE_SECONDS):
                response = await self.client.request(
                    method,
                    self.config.head_url.rstrip("/") + path,
                    headers={"Authorization": f"Bearer {secret(self.config.token_env)}"},
                    timeout=httpx.Timeout(3, connect=1),
                    # Never inherit shared-client redirect behavior for a
                    # device bearer or a physical command recipient.
                    follow_redirects=False,
                    **kwargs,
                )
            response.raise_for_status()
            return response
        except (httpx.HTTPError, ValueError, TimeoutError) as exc:
            raise HeadError(f"{self.config.id}: head request failed; no retry: {exc}") from exc

    async def _ordered_command(
        self, command: str, expected: str, generation: int,
        *, dispatch_check=None,
    ) -> dict:
        # Retire queued control after either terminal HALT or uncertain writes.
        async with self.command_lock:
            if generation != self._command_generation:
                raise HeadError("Command superseded by WROOM transport fence")
            self._check_command_recovery(command)
            if dispatch_check is not None:
                dispatch_check()
            try:
                response = await self._request(
                    "POST", "/api/command", json={"command": command}
                )
                data = _response_object(response)
                reply = data.get("reply", "")
                if (data.get("ok") is not True
                        or data.get("robot_id") != self.config.id
                        or reply != expected):
                    raise HeadError("Unmatched or failed command ACK; movement not retried")
            except (Exception, asyncio.CancelledError):
                # Cancellation or failure AFTER admission cannot prove that a
                # remote write did not execute. Fence before releasing either
                # lock, without invalidating an already queued newer HALT.
                if command not in {"ping", "status"}:
                    self._command_uncertain = True
                    if generation == self._command_generation:
                        self._command_generation += 1
                raise
            if generation != self._command_generation:
                raise HeadError("Command receipt superseded by terminal WROOM HALT")
            if command == "halt":
                self._command_uncertain = False
            return data

    def _check_command_recovery(self, command: str) -> None:
        if self._command_uncertain and command not in self._RECOVERY_COMMANDS:
            raise HeadError("WROOM command outcome unconfirmed; require acknowledged HALT")

    async def command(self, command: str, *, dispatch_check=None) -> dict:
        expected = expected_ack(command)
        if command == "halt":
            # Retire already queued commands immediately. An in-flight POST
            # must finish before HALT so its late ARM cannot undo the disarm.
            # HALT never waits for a stalled status GET or camera request.
            self._command_uncertain = True
            self._command_generation += 1
            return await self._ordered_command(
                command, expected, self._command_generation
            )
        # A command submitted during pending recovery must not become valid
        # just because a later HALT succeeds while the command is queued.
        self._check_command_recovery(command)
        generation = self._command_generation
        async with self.lock:
            return await self._ordered_command(
                command, expected, generation, dispatch_check=dispatch_check,
            )

    async def face_event(self, event: str) -> None:
        """Send an explicitly bounded cosmetic face cue to THIS robot's head.

        This is not an actuator, speech, wake, or motor command. The head
        validates the same per-device bearer token as the other endpoints.
        """
        if (type(event) is not str or event not in {
            "person_detected", "mood:neutral", "mood:happy",
            "mood:thinking", "mood:surprised",
        }):
            raise ValueError("Unsupported cosmetic face event")
        response = await self._request(
            "POST", "/api/face", json={"event": event}
        )
        data = _response_object(response)
        reply = ("person cue queued" if event == "person_detected"
                 else "mood cue queued")
        if (data.get("ok") is not True or data.get("robot_id") != self.config.id
                or data.get("reply") != reply):
            raise HeadError("Cosmetic face cue not acknowledged by this robot")

    async def status(self) -> dict:
        async with self.lock:
            generation = self._command_generation
            try:
                data = _response_object(await self._request("GET", "/api/status"))
                if data.get("robot_id") != self.config.id:
                    raise HeadError("Status robot identity mismatch")
                return data
            except (HeadError, asyncio.CancelledError):
                # A lost body read also means queued keepalives cannot prove
                # continuity. Preserve a newer or already pending HALT.
                if generation == self._command_generation and not self._command_uncertain:
                    self._command_uncertain = True
                    self._command_generation += 1
                raise

    async def pose_status(self) -> PoseReceipt:
        """Read authenticated v1 odometry without giving it any motion permit.

        Body timestamps are not Mac timestamps. The fence compares sample
        duration against receipt duration and requires a separate map anchor.
        Old head firmware can omit this endpoint without breaking status.
        """
        async with self.lock:
            try:
                request_started_at = time.monotonic()
                try:
                    response = await self._request("GET", "/api/pose")
                except HeadError as exc:
                    cause = exc.__cause__
                    if (isinstance(cause, httpx.HTTPStatusError)
                            and cause.response.status_code in (404, 501)):
                        raise PoseUnsupported("Pose unsupported by head/body firmware") from exc
                    raise
                data = _response_object(response)
                version = data.get("v")
                # Foreign identities and malformed version types are not
                # legitimate capability negotiation.
                if (data.get("robot_id") == self.config.id
                        and type(version) is int and 0 <= version <= 0xffffffff
                        and version != 1):
                    raise PoseUnsupported("Pose unsupported wire version")
                return self.pose_fence.observe(
                    data, time.monotonic(), request_started_at=request_started_at,
                )
            except PoseUnsupported:
                self.pose_fence.invalidate("pose_unsupported")
                raise
            except PoseError as exc:
                raise HeadError(f"Rejected pose receipt: {exc}") from exc
            except BaseException:
                self.pose_fence.invalidate("pose_transport_unavailable")
                raise

    async def audio_reference_status(self) -> dict:
        """Read device AEC reference integrity, never infer audible playback.

        The original Sense codec owns both microphone and speaker. This
        endpoint exposes bounded monotonic counters only, not PCM or TTS
        progress. A head cannot self-certify acoustic qualification.
        """
        data = _response_object(await self._request("GET", "/api/audio.reference"))
        counters = (
            "reference_underflow_reads", "reference_overwrite_reads",
            "discarded_stale_writes", "short_output_writes",
            "microphone_frames_read", "speaker_frames_accepted",
        )
        if (data.get("robot_id") != self.config.id
                or type(data.get("boot")) is not int
                or not 0 <= data["boot"] <= 0xffffffff
                or any(type(data.get(key)) is not int
                       or not 0 <= data[key] <= 0xffffffff
                       for key in counters)
                or type(data.get("reference_integrity_failed")) is not bool
                or type(data.get("microphone_privacy_muted")) is not bool
                or type(data.get("microphone_privacy_epoch")) is not int
                or not 0 <= data["microphone_privacy_epoch"] <= 0xffffffff
                or type(data.get("aec_delay_config_ms")) is not int
                or not 0 <= data["aec_delay_config_ms"] <= 250
                or data.get("speaker_playback_verified") is not False
                or data.get("aec_physically_qualified") is not False):
            raise HeadError("Untrusted Sense AEC reference diagnostics")
        return data


    async def aux_status(self) -> dict:
        """Authenticate and validate all optional sensor provenance, never arm."""
        async with self.lock:
            data = _response_object(await self._request("GET", "/api/aux"))
            try:
                return validate_aux(data, self.config.id)
            except ValueError as exc:
                raise HeadError(str(exc)) from exc

    async def optics_status(self) -> dict:
        """Same conversion VL53L0X ambient/signal diagnostics, read only."""
        async with self.lock:
            data = _response_object(await self._request("GET", "/api/optics"))
            try:
                return validate_optics(data, self.config.id)
            except ValueError as exc:
                raise HeadError(str(exc)) from exc

    async def ir_status(self) -> dict:
        """Independent read-only terminal IR evidence from actual WROOM RMT."""
        async with self.lock:
            data = _response_object(await self._request("GET", "/api/ir"))
            try:
                return validate_ir(
                    data, self.config.id,
                    expected_dock_id=self.config.dock_beacon_id,
                )
            except ValueError as exc:
                raise HeadError(str(exc)) from exc

    async def camera_identity(self, dock_receipt: tuple | None = None) -> str:
        """Verify the initialized XIAO sensor against an authentic frame boot.

        The offline camera calibration cannot authorize docking simply by
        naming an OV module. This read-only endpoint uses Espressif's actual
        sensor PID and the same boot nonce as the accepted JPEG receipt.
        """
        async with self.lock:
            data = _response_object(
                await self._request("GET", "/api/camera.identity")
            )
        if data.get("robot_id") != self.config.id:
            raise HeadError("Camera identity robot mismatch")
        pid = data.get("camera_sensor_pid")
        expected_raw = {"OV2640": 0x26, "OV3660": 0x3660, "OV5640": 0x5640}
        if (type(pid) is not str or pid not in expected_raw
                or type(data.get("camera_pid_raw")) is not int
                or data["camera_pid_raw"] != expected_raw[pid]):
            raise HeadError("Camera sensor PID mismatch or unsupported sensor")
        boot = data.get("boot")
        if type(boot) is not int or not 0 <= boot <= 0xffffffff:
            raise HeadError("Invalid camera identity boot")
        if dock_receipt is not None:
            await self.dock_receipt_current(dock_receipt, expected_boot=boot)
        elif self._last_camera is None or boot != self._last_camera[0]:
            raise HeadError("Camera identity boot differs from accepted JPEG")
        return pid

    async def dock_receipt_current(
        self, receipt: tuple, *, expected_boot: int | None = None
    ) -> None:
        """Recheck the selected JPEG's original boot after any awaited work.

        The live stream may have published another frame or reconnected while
        HTTP identity, AprilTag detection, IR, or body status was pending.
        """
        async with self._stream_condition:
            self.dock_receipt_current_now(receipt, expected_boot=expected_boot)

    def dock_receipt_current_now(
        self, receipt: tuple, *, expected_boot: int | None = None
    ) -> None:
        """Check selected camera provenance without yielding the event loop."""
        if (not isinstance(receipt, tuple) or len(receipt) != 4
                or not isinstance(receipt[0], bytes)
                or type(receipt[1]) not in (int, float)
                or not 0 <= time.monotonic() - receipt[1] <= 0.20
                or not isinstance(receipt[2], tuple) or len(receipt[2]) != 3
                or any(type(n) is not int for n in receipt[2])
                or not 0 <= receipt[2][0] <= 0xffffffff
                or not 1 <= receipt[2][1] <= 0xffffffff
                or not 1 <= receipt[2][2] <= _MAX_CAMERA_COMPLETE_US
                or type(receipt[3]) is not int or receipt[3] < 1):
            raise HeadError("Invalid or expired selected dock JPEG provenance")
        boot = receipt[2][0]
        # All live camera state belongs to this event loop. A synchronous
        # dispatch callback must not await between this check and POST admission.
        if (not self._stream_connected
                or receipt[3] != self._stream_generation
                or self._last_camera is None
                or self._last_camera[0] != boot
                or boot in self._retired_camera_boots
                or (expected_boot is not None and expected_boot != boot)):
            raise HeadError("Dock JPEG boot changed during camera identity check")

    def _accept_camera_identity(self, identity: tuple[int, int, int]) -> None:
        boot, sequence, completed = identity
        if (type(completed) is not int
                or not 1 <= completed <= _MAX_CAMERA_COMPLETE_US):
            raise HeadError("Camera completion metadata out of bounds")
        earlier = self._last_camera
        if boot in self._retired_camera_boots:
            # A reconnect must not replay an earlier Sense boot as if it
            # were a new scene. This also protects genuine long-lived MJPEG
            # subscriptions from stale frames delivered after a reboot.
            raise HeadError("Camera returned retired boot frame metadata")
        if earlier is not None and earlier[0] != boot:
            # Never evict old boot IDs merely to accept a ninth unexpected
            # reset. That would make delayed old images valid again. A fresh
            # operator-created head session is required after this limit.
            if len(self._retired_camera_boots) >= 8:
                raise HeadError("Camera reboot history exhausted; reset observation session")
            self._retired_camera_boots.add(earlier[0])
        elif earlier and (
            sequence <= earlier[1] or completed <= earlier[2]
        ):
            raise HeadError("Camera returned stale or replayed frame metadata")
        self._last_camera = identity

    async def stream_frames(self):
        """Consume one persistent authenticated XIAO MJPEG feed.

        The Mac is the one remote frame reader. Other users of snapshot()
        reuse distinct fresh stream frames rather than opening another
        physical camera capture.
        """
        url = self.config.head_url.rstrip("/") + "/api/camera.mjpg"
        headers = {"Authorization": f"Bearer {secret(self.config.token_env)}"}
        async with self._stream_condition:
            self._stream_generation += 1
            generation = self._stream_generation
            self._stream_connected = False
            self._stream_latest = None
            self._stream_condition.notify_all()
        # Source completion and Mac arrival run on different monotonic
        # clocks. Only compare DELTAS within this one connected stream;
        # never interpret an absolute ESP32 timestamp as Mac wall time.
        clock_reference_identity = None
        clock_reference_received = None
        try:
            async with self.client.stream(
                "GET", url, headers=headers,
                # Four frames per second is the head ceiling. A stalled
                # stream must not retain a raw camera lease for the default
                # five second HTTP read timeout after live consent changes.
                # Healthy frames still share this one persistent connection.
                timeout=httpx.Timeout(5, connect=1, read=1.5),
                # Camera media and its bearer never move to another URL.
                follow_redirects=False,
            ) as response:
                response.raise_for_status()
                if not response.headers.get("content-type", "").lower().startswith(
                    "multipart/x-mixed-replace; boundary=deskrobotframe"
                ):
                    raise HeadError("XIAO did not return MJPEG stream")
                reader = _MjpegFrames(expected_robot_id=self.config.id)
                async with self._stream_condition:
                    if generation != self._stream_generation:
                        raise HeadError("Superseded XIAO camera stream")
                    self._stream_connected = True
                    self._stream_condition.notify_all()
                chunks = response.aiter_bytes()
                loop = asyncio.get_running_loop()
                deadline = loop.time() + _MJPEG_FRAME_TIMEOUT_SECONDS
                while True:
                    # HTTPX read timeouts restart for each received chunk.
                    # Partial headers or JPEG bytes must not renew this lease.
                    try:
                        if loop.time() >= deadline:
                            raise TimeoutError
                        async with asyncio.timeout_at(deadline):
                            chunk = await anext(chunks)
                    except StopAsyncIteration:
                        break
                    except TimeoutError as exc:
                        raise HeadError("No complete MJPEG frame before deadline") from exc
                    # Record receipt at the network boundary, not later as a
                    # slow consumer iterates several older frames in a batch.
                    received = time.monotonic()
                    # Validate every source identity, but only surface the
                    # newest image in a coalesced network read. This prevents
                    # slow vision consumers from working through stale scenes.
                    latest = None
                    latest_identity = None
                    async with self._stream_condition:
                        if generation != self._stream_generation:
                            raise HeadError("Superseded XIAO camera stream")
                        for jpeg, identity in reader.iter_feed(chunk):
                            self._accept_camera_identity(identity)
                            latest = jpeg
                            latest_identity = identity
                        if latest is not None:
                            if (clock_reference_identity is None
                                    or clock_reference_identity[0] != latest_identity[0]
                                    or clock_reference_received is None):
                                clock_reference_identity = latest_identity
                                clock_reference_received = received
                            else:
                                network_elapsed = received - clock_reference_received
                                source_elapsed = (
                                    latest_identity[2] - clock_reference_identity[2]
                                ) / 1_000_000
                                lag = network_elapsed - source_elapsed
                                # Keep the best relative offset for this boot
                                # and connection, not the previous frame.
                                # Otherwise small delays accumulate unnoticed.
                                # This is not a synchronized exposure clock.
                                if lag > 0.5:
                                    raise HeadError(
                                        "Buffered stale camera frame after stream backlog"
                                    )
                                if lag < 0:
                                    clock_reference_identity = latest_identity
                                    clock_reference_received = received
                            self._stream_latest = latest
                            self._stream_received_at = received
                            self._stream_version += 1
                            self._stream_condition.notify_all()
                    if latest is not None:
                        yield latest, received
                        # Do not charge the caller's frame processing time to
                        # network acquisition; only a complete frame renews it.
                        deadline = loop.time() + _MJPEG_FRAME_TIMEOUT_SECONDS
                if reader.buffer:
                    raise HeadError("Truncated MJPEG part at end of stream")
        except (httpx.HTTPError, ValueError) as exc:
            raise HeadError(f"XIAO authenticated camera stream unavailable: {exc}") from exc
        finally:
            async with self._stream_condition:
                if generation == self._stream_generation:
                    self._stream_connected = False
                    self._stream_latest = None
                    self._stream_condition.notify_all()

    async def snapshot_for_dock(self) -> tuple[bytes, float, tuple[int, int, int], int]:
        """Only a very recent authenticated MJPEG receipt may guide docking.

        Never initiate a separate still capture when the live stream is down.
        This does not establish true camera exposure latency or authorize motors.
        """
        if not self._stream_connected:
            raise HeadError("Dock observation needs connected live camera stream")
        return await self.snapshot(
            max_stream_age_seconds=0.20, require_live_stream=True,
            include_stream_receipt=True, include_stream_identity=True,
        )

    async def snapshot_receipt(self) -> tuple[bytes, float, tuple[int, int, int] | None]:
        """Return JPEG, original Mac receipt, and unaligned Sense completion identity."""
        return await self.snapshot(include_camera_receipt=True)

    async def snapshot(
        self, *, max_stream_age_seconds: float = 1.0,
        require_live_stream: bool = False,
        include_stream_receipt: bool = False,
        include_stream_identity: bool = False,
        include_camera_receipt: bool = False,
    ) -> bytes | tuple:
        if (type(max_stream_age_seconds) not in (int, float)
                or not 0 < max_stream_age_seconds <= 1.0
                or type(require_live_stream) is not bool
                or type(include_stream_receipt) is not bool
                or type(include_stream_identity) is not bool
                or type(include_camera_receipt) is not bool
                or (include_camera_receipt and include_stream_receipt)
                or (include_stream_identity and not include_stream_receipt)
                or (include_stream_receipt and not require_live_stream)):
            raise ValueError("Invalid camera stream receipt age limit")

        # Separate camera serialization: concurrent Mac pet/pickup callers must
        # not trip the Sense single-capture worker or block body keepalives.
        async with self.capture_lock:
            if self._stream_connected:
                # Require a distinct fresh camera receipt for every physical
                # observation. A stale last frame is not a second capture.
                try:
                    async with asyncio.timeout(2):
                        async with self._stream_condition:
                            while (self._stream_connected and (
                                self._stream_latest is None
                                or self._stream_version <= self._snapshot_version
                                or not 0 <= time.monotonic() - self._stream_received_at
                                    <= max_stream_age_seconds
                            )):
                                await self._stream_condition.wait()
                            if not self._stream_connected:
                                raise HeadError("Camera stream lost during snapshot")
                            self._snapshot_version = self._stream_version
                            if include_camera_receipt:
                                return (
                                    self._stream_latest, self._stream_received_at,
                                    self._last_camera,
                                )
                            if include_stream_receipt:
                                # The selected JPEG, boot, sequence, and
                                # stream generation are one immutable receipt.
                                if include_stream_identity:
                                    if self._last_camera is None:
                                        raise HeadError("Dock frame has no source identity")
                                    return (
                                        self._stream_latest, self._stream_received_at,
                                        self._last_camera, self._stream_generation,
                                    )
                                return self._stream_latest, self._stream_received_at
                            return self._stream_latest
                except TimeoutError as exc:
                    raise HeadError("No fresh camera frame on live stream") from exc
            if self._stream_required or require_live_stream:
                raise HeadError("Continuous XIAO camera stream is not connected")
            generation = self._stream_generation
            response = await self._request("GET", "/api/camera.jpg")
            received = time.monotonic()
            identity = None
            # The still request may have started before streaming was
            # enabled. Never relabel a new stream's cached JPEG with its
            # standalone completion metadata, even after a failed reconnect.
            if (generation != self._stream_generation
                    or self._stream_connected or self._stream_required):
                raise HeadError("Standalone camera capture superseded by live stream")
            # Both the Sense snapshot producer and MJPEG parser cap JPEG
            # payloads at 512 KiB. Do not let a legacy HTTP still bypass
            # that same camera evidence bound.
            if not (4 <= len(response.content) <= 512 * 1024
                    and response.content.startswith(b"\xff\xd8")
                    and response.content.endswith(b"\xff\xd9")):
                # A camera HTTP response with only a valid SOI can be
                # truncated during capture/transport. Refuse it BEFORE
                # advancing boot/sequence evidence or sending it to a VLM,
                # dock detector or pickup planner.
                raise HeadError("Camera did not return a bounded complete JPEG")
            names = (
                "X-Desk-Camera-Boot", "X-Desk-Camera-Sequence",
                "X-Desk-Camera-Complete-Us",
            )
            values = [response.headers.get(name) for name in names]
            camera_robot = response.headers.get("X-Desk-Camera-Robot-Id")
            if (self.strict_capture or camera_robot is not None
                    or any(value is not None for value in values)):
                # Bind each still capture to its flashed physical head ID
                # before advancing camera boot or sequence evidence.
                if camera_robot != self.config.id:
                    raise HeadError("Camera robot identity mismatch or missing")
                if not all(value is not None and 1 <= len(value) <= 20
                           and value.isascii() and value.isdecimal()
                           for value in values):
                    raise HeadError("Camera completion metadata missing or malformed")
                boot, sequence, completed = map(int, values)
                if (not 0 <= boot <= 0xffffffff
                        or not 1 <= sequence <= 0xffffffff
                        or not 1 <= completed <= _MAX_CAMERA_COMPLETE_US):
                    raise HeadError("Camera completion metadata out of bounds")
                identity = (boot, sequence, completed)
                self._accept_camera_identity(identity)
            if include_camera_receipt:
                return response.content, received, identity
            return response.content
