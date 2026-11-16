from __future__ import annotations

import asyncio
import re
import time
from typing import Protocol

import httpx

from .aux import validate_aux
from .dock_ir import validate_ir
from .config import RobotConfig, secret


class HeadError(RuntimeError):
    """A failed request may already have actuated: never automatically retry it."""


class Head(Protocol):
    async def command(self, command: str) -> dict: ...
    async def status(self) -> dict: ...
    async def aux_status(self) -> dict: ...
    async def ir_status(self) -> dict: ...
    async def snapshot(self) -> bytes: ...


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
        duration = int(values[2]) if len(values) == 3 else 250
        if -40 <= left <= 40 and -40 <= right <= 40 and 1 <= duration <= 250:
            return op
    if op in {"lift", "grip"} and len(tokens) == 2 and tokens[1].isdigit():
        if 60 <= int(tokens[1]) <= 120:
            return op
    raise ValueError("Command exceeds conservative bounds")


def expected_ack(command: str) -> str:
    op = validate_command(command)
    args = command.split()[1:]
    if op == "drive":
        left, right = map(int, args[:2])
        ms = int(args[2]) if len(args) == 3 else 250
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

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, chunk: bytes) -> list[tuple[bytes, tuple[int, int, int]]]:
        if not isinstance(chunk, bytes):
            raise ValueError("Invalid MJPEG network chunk")
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
                def decimal(name: str) -> int:
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
            if not (4 <= size <= 512 * 1024 and 0 <= boot <= 0xffffffff
                    and 1 <= sequence <= 0xffffffff and completed > 0):
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
            frames.append((frame, (boot, sequence, completed)))
            del self.buffer[:finish + 2]
        if len(self.buffer) > 512 * 1024 + 1024:
            raise ValueError("MJPEG buffer exceeds maximum size")
        return frames


class HttpHead:
    def __init__(
        self, config: RobotConfig, client: httpx.AsyncClient,
        *, strict_capture: bool = False
    ):
        self.config = config
        self.client = client
        self.lock = asyncio.Lock()
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
            response = await self.client.request(
                method,
                self.config.head_url.rstrip("/") + path,
                headers={"Authorization": f"Bearer {secret(self.config.token_env)}"},
                timeout=httpx.Timeout(3, connect=1),
                **kwargs,
            )
            response.raise_for_status()
            return response
        except (httpx.HTTPError, ValueError) as exc:
            raise HeadError(f"{self.config.id}: head request failed; no retry: {exc}") from exc

    async def command(self, command: str) -> dict:
        expected = expected_ack(command)
        async with self.lock:
            response = await self._request("POST", "/api/command", json={"command": command})
            data = response.json()
            reply = data.get("reply", "")
            if not data.get("ok") or data.get("robot_id") != self.config.id or reply != expected:
                raise HeadError("Unmatched or failed command ACK; movement not retried")
            return data

    async def status(self) -> dict:
        async with self.lock:
            data = (await self._request("GET", "/api/status")).json()
            if data.get("robot_id") != self.config.id:
                raise HeadError("Status robot identity mismatch")
            return data

    async def aux_status(self) -> dict:
        """Authenticate and validate all optional sensor provenance, never arm."""
        async with self.lock:
            data = (await self._request("GET", "/api/aux")).json()
            try:
                return validate_aux(data, self.config.id)
            except ValueError as exc:
                raise HeadError(str(exc)) from exc

    async def ir_status(self) -> dict:
        """Independent read-only terminal IR evidence from actual WROOM RMT."""
        async with self.lock:
            data = (await self._request("GET", "/api/ir")).json()
            try:
                return validate_ir(data, self.config.id)
            except ValueError as exc:
                raise HeadError(str(exc)) from exc

    def _accept_camera_identity(self, identity: tuple[int, int, int]) -> None:
        boot, sequence, completed = identity
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
        try:
            async with self.client.stream(
                "GET", url, headers=headers,
                timeout=httpx.Timeout(5, connect=1),
            ) as response:
                response.raise_for_status()
                if not response.headers.get("content-type", "").lower().startswith(
                    "multipart/x-mixed-replace; boundary=deskrobotframe"
                ):
                    raise HeadError("XIAO did not return MJPEG stream")
                reader = _MjpegFrames()
                async with self._stream_condition:
                    if generation != self._stream_generation:
                        raise HeadError("Superseded XIAO camera stream")
                    self._stream_connected = True
                    self._stream_condition.notify_all()
                async for chunk in response.aiter_bytes():
                    for jpeg, identity in reader.feed(chunk):
                        received = time.monotonic()
                        async with self._stream_condition:
                            if generation != self._stream_generation:
                                raise HeadError("Superseded XIAO camera stream")
                            self._accept_camera_identity(identity)
                            self._stream_latest = jpeg
                            self._stream_received_at = received
                            self._stream_version += 1
                            self._stream_condition.notify_all()
                        yield jpeg, received
        except (httpx.HTTPError, ValueError) as exc:
            raise HeadError("XIAO authenticated camera stream unavailable") from exc
        finally:
            async with self._stream_condition:
                if generation == self._stream_generation:
                    self._stream_connected = False
                    self._stream_latest = None
                    self._stream_condition.notify_all()

    async def snapshot(self) -> bytes:
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
                                or time.monotonic() - self._stream_received_at > 1
                            )):
                                await self._stream_condition.wait()
                            if not self._stream_connected:
                                raise HeadError("Camera stream lost during snapshot")
                            self._snapshot_version = self._stream_version
                            return self._stream_latest
                except TimeoutError as exc:
                    raise HeadError("No fresh camera frame on live stream") from exc
            if self._stream_required:
                raise HeadError("Continuous XIAO camera stream is not connected")
            response = await self._request("GET", "/api/camera.jpg")
            if not (4 <= len(response.content) <= 4_000_000
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
            if self.strict_capture or any(value is not None for value in values):
                if not all(value is not None and 1 <= len(value) <= 20
                           and value.isascii() and value.isdecimal()
                           for value in values):
                    raise HeadError("Camera completion metadata missing or malformed")
                boot, sequence, completed = map(int, values)
                if not 0 <= boot <= 0xffffffff or not 1 <= sequence <= 0xffffffff or completed <= 0:
                    raise HeadError("Camera completion metadata out of bounds")
                self._accept_camera_identity((boot, sequence, completed))
            return response.content
