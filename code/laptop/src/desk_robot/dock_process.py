"""Supervised, single-flight AprilTag subprocesses with an idle warm spare."""
from __future__ import annotations

import asyncio
import base64
import json
import math
import sys
import time
from dataclasses import asdict

from .dock_vision import DockCameraCalibration, DockPose, detect_apriltag

FRAME_AGE_S = 0.20
_REAP_S = 0.15
_START_S = 2.0
_MAX_JPEG = 512000
_MAX_REQUEST = 700000
_MAX_REPLY = 4096


class DockDetectorBusy(RuntimeError):
    """No safely available native detector; never queue a camera frame."""


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("Duplicate AprilTag IPC field")
        fields[key] = value
    return fields


def _worker_main() -> None:
    # Import the optional native library only inside the isolated process.
    import cv2

    cv2.setNumThreads(1)
    cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11))
    print("ready", flush=True)
    while line := sys.stdin.buffer.readline(_MAX_REQUEST + 1):
        if len(line) > _MAX_REQUEST or not line.endswith(b"\n"):
            return
        try:
            request = json.loads(line, object_pairs_hook=_unique_fields)
            jpeg = base64.b64decode(request["jpeg"], validate=True)
            calibration = request["calibration"]
            if isinstance(calibration.get("distortion_coeffs"), list):
                calibration["distortion_coeffs"] = tuple(calibration["distortion_coeffs"])
            pose = detect_apriltag(
                jpeg, DockCameraCalibration(**calibration), captured_at=request["captured_at"],
            )
            result = {"id": request["id"], "pose": asdict(pose) if pose is not None else None}
            print(json.dumps(result, allow_nan=False), flush=True)
            del jpeg, calibration, pose, request, line
        except Exception:
            # No image, calibration or exception text escapes to logs. The
            # parent rejects EOF and retires this process before serving again.
            return


class DetectorPool:
    """One submitted JPEG globally, at most two owned child processes.

    The standby receives no JPEG until promoted. A failed request is never
    retried, even on a ready spare. All methods belong to the Mac event loop.
    """

    def __init__(self, command: tuple[str, ...] | None = None):
        self._command = command or (sys.executable, "-m", "desk_robot.dock_process")
        self._ready: list[asyncio.subprocess.Process] = []
        self._owned: set[asyncio.subprocess.Process] = set()
        self._warming: asyncio.Task | None = None
        self._active: asyncio.Task | None = None
        self._active_retiring = False
        self._closing = False
        self._faulted = False
        self._retry_at = 0.0
        self._sequence = 0
        self._close_task: asyncio.Task | None = None

    @staticmethod
    def _kill(process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass

    async def _retire(self, process: asyncio.subprocess.Process) -> None:
        try:
            self._kill(process)
            # Drain pipes as well as waiting: Process.wait alone can deadlock
            # when the child filled its stdout pipe before being killed.
            await asyncio.wait_for(process.communicate(), _REAP_S)
        except Exception:
            self._faulted = True
            raise DockDetectorBusy("AprilTag process retirement unconfirmed") from None
        self._owned.discard(process)
        if process in self._ready:
            self._ready.remove(process)

    async def _start_one(self) -> None:
        process = await asyncio.create_subprocess_exec(
            *self._command, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=_MAX_REPLY,
        )
        self._owned.add(process)
        try:
            if self._closing:
                raise RuntimeError("AprilTag worker closing")
            assert process.stdout is not None
            greeting = await asyncio.wait_for(process.stdout.readline(), _START_S)
            if greeting != b"ready\n" or self._closing:
                raise RuntimeError("AprilTag worker not ready")
            self._ready.append(process)
        except BaseException:
            await self._retire(process)
            raise

    async def _warm(self, count: int) -> None:
        results = await asyncio.gather(
            *(self._start_one() for _ in range(count)), return_exceptions=True,
        )
        if any(isinstance(result, BaseException) for result in results):
            self._retry_at = time.monotonic() + 1.0
        elif len(self._owned) < 2:
            asyncio.get_running_loop().call_soon(self._schedule_warm)

    def _schedule_warm(self) -> None:
        if (self._closing or self._faulted or time.monotonic() < self._retry_at
                or (self._warming is not None and not self._warming.done())):
            return
        count = 2 - len(self._owned)
        if count > 0:
            self._warming = asyncio.create_task(self._warm(count))

    async def prewarm(self) -> None:
        """Prepare both processes before acquiring any camera receipt."""
        self._schedule_warm()
        if self._warming is not None:
            await asyncio.shield(self._warming)

    async def _request(self, jpeg: bytes, camera: DockCameraCalibration,
                       captured_at: float, sequence: int) -> DockPose | None:
        if time.monotonic() - captured_at >= FRAME_AGE_S:
            raise TimeoutError("Stale AprilTag frame")
        process = self._ready.pop(0)
        try:
            if process.returncode is not None:
                raise RuntimeError("AprilTag worker exited")
            payload = json.dumps({
                "id": sequence, "jpeg": base64.b64encode(jpeg).decode("ascii"),
                "calibration": asdict(camera), "captured_at": captured_at,
            }, allow_nan=False).encode("ascii") + b"\n"
            if len(payload) > _MAX_REQUEST:
                raise ValueError("AprilTag request too large")
            assert process.stdin is not None and process.stdout is not None
            # Include serialization, pipe backpressure and native inference
            # in the original receipt's deadline, not a fresh timeout.
            async with asyncio.timeout_at(asyncio.get_running_loop().time() + max(
                0.0, FRAME_AGE_S - (time.monotonic() - captured_at),
            )):
                if time.monotonic() - captured_at >= FRAME_AGE_S:
                    raise TimeoutError("Stale AprilTag frame")
                process.stdin.write(payload)
                await process.stdin.drain()
                raw = await process.stdout.readline()
                if not raw.endswith(b"\n") or len(raw) > _MAX_REPLY:
                    raise ValueError("Invalid AprilTag reply framing")
                reply = json.loads(raw, object_pairs_hook=_unique_fields)
                if (type(reply) is not dict or set(reply) != {"id", "pose"}
                        or type(reply["id"]) is not int or reply["id"] != sequence):
                    raise ValueError("Invalid AprilTag reply identity")
                pose = reply["pose"]
                if pose is not None:
                    if type(pose) is not dict or set(pose) != {
                        "x_mm", "y_mm", "z_mm", "reprojection_error_px", "captured_at",
                    }:
                        raise ValueError("Invalid AprilTag pose fields")
                    pose = DockPose(**pose)
                    if pose.captured_at != captured_at:
                        raise ValueError("AprilTag reply capture timestamp changed")
                    if not 30 <= pose.z_mm <= 2000 or pose.reprojection_error_px > 3:
                        raise ValueError("AprilTag reply outside detector pose envelope")
                if time.monotonic() - captured_at >= FRAME_AGE_S:
                    raise TimeoutError("Stale AprilTag result")
            self._ready.insert(0, process)
            return pose
        except BaseException:
            # A timeout can enter retirement before any caller cancellation.
            # Keep the active slot until the native owner is confirmed reaped.
            self._active_retiring = True
            try:
                await self._retire(process)
            finally:
                self._active_retiring = False
            raise

    def _completed(self, task: asyncio.Task) -> None:
        if not task.cancelled():
            task.exception()
        if self._active is task:
            self._active = None
        self._schedule_warm()

    async def detect(self, jpeg: bytes, camera: DockCameraCalibration, *,
                     captured_at: float) -> DockPose | None:
        if self._closing or self._faulted or self._active is not None:
            raise DockDetectorBusy("AprilTag worker busy, closing or retirement unconfirmed")
        if (type(jpeg) is not bytes or not 0 < len(jpeg) <= _MAX_JPEG
                or type(camera) is not DockCameraCalibration
                or type(captured_at) not in (int, float)):
            raise ValueError("Invalid AprilTag request")
        try:
            age = time.monotonic() - captured_at
        except OverflowError:
            raise ValueError("Invalid AprilTag capture clock") from None
        if not math.isfinite(age) or not 0 <= age < FRAME_AGE_S:
            raise TimeoutError("Stale AprilTag frame")
        self._schedule_warm()
        if not self._ready:
            raise DockDetectorBusy("AprilTag process warming; request a fresh frame")
        self._sequence += 1
        task = asyncio.create_task(self._request(jpeg, camera, captured_at, self._sequence))
        self._active = task
        task.add_done_callback(self._completed)
        try:
            pose = await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.done() and not task.cancelling() and not self._active_retiring:
                task.cancel()
            raise
        if self._closing or not 0 <= time.monotonic() - captured_at < FRAME_AGE_S:
            raise TimeoutError("Stale or retired AprilTag result")
        return pose

    async def close(self) -> None:
        self._closing = True
        if self._close_task is None or self._close_task.done():
            self._close_task = asyncio.create_task(self._close_owned())
            self._close_task.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        await asyncio.shield(self._close_task)

    async def _close_owned(self) -> None:
        active = self._active
        if (active is not None and not active.done() and not active.cancelling()
                and not self._active_retiring):
            active.cancel()
        # Kill warming/idle children immediately as well. Active owner and
        # warm tasks perform their own pipe draining before we retire leftovers.
        for process in self._owned:
            try:
                self._kill(process)
            except OSError:
                self._faulted = True
        if active is not None:
            await asyncio.shield(asyncio.gather(active, return_exceptions=True))
        if self._warming is not None:
            await asyncio.shield(self._warming)
        for process in tuple(self._owned):
            try:
                await self._retire(process)
            except DockDetectorBusy:
                # Continue retiring other children even if one OS reap fails.
                pass
        if self._owned:
            raise DockDetectorBusy("AprilTag process retirement unconfirmed")


if __name__ == "__main__":
    _worker_main()
