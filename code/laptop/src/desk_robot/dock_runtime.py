"""Real camera docking observation without a motor or charger permission."""
from __future__ import annotations

import asyncio
import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .dock_vision import DockCameraCalibration, DockPose, assess_dock, detect_apriltag

# Keep the native future itself as the worker lifetime owner. An asyncio wrapper
# can be cancelled during shutdown while the C detector is still running.
_DETECTOR_SLOT = threading.BoundedSemaphore(1)
_DETECTOR_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="desk-apriltag")


def load_real_dock_calibration(path) -> tuple[DockCameraCalibration, float]:
    if path is None:
        raise ValueError("No dock calibration configured")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("measured") is not True:
        raise ValueError("Dock camera geometry is not physically measured")
    props = ("fx", "fy", "cx", "cy", "tag_side_mm", "marker_id")
    if any(key not in data for key in props):
        raise ValueError("Dock calibration lacks measured camera parameters")
    calibration = DockCameraCalibration(
        **{key: data[key] for key in props},
        distortion_coeffs=(
            tuple(data["distortion_coeffs"])
            if isinstance(data.get("distortion_coeffs"), list)
            else data.get("distortion_coeffs")
        ),
        image_width_px=data.get("image_width_px"),
        image_height_px=data.get("image_height_px"),
        camera_sensor_pid=data.get("camera_sensor_pid"),
        mount_lateral_offset_mm=data.get("mount_lateral_offset_mm"),
        mount_yaw_deg=data.get("mount_yaw_deg"),
    )
    target = data.get("target_distance_mm")
    if type(target) not in (float, int) or not 50 <= target <= 500 or not math.isfinite(target):
        raise ValueError("Dock stopping distance is not calibrated")
    return calibration, float(target)


def _hold(robot_id: str, *, reason: str, source: str) -> dict:
    """Return a non-authorizing diagnostic for failed dock observation."""
    return {
        "robot_id": robot_id, "phase": "hold", "reason": reason,
        "source": source, "pose": None,
        "motor_authorized": False, "charging_authorized": False,
        "physical_acceptance_pass": False,
    }


class DockDetectorBusy(RuntimeError):
    """The shared native AprilTag worker is still busy."""


async def detect_bounded(jpeg: bytes, calibration: DockCameraCalibration, *,
                         captured_at: float):
    """The sole AprilTag worker for read-only vision AND permitted approach.

    Cancellation of an asyncio awaiter cannot stop an active native C call.
    Its concurrent future, not a coroutine, retains the single global slot.
    No camera observation itself ever authorizes motors or charging.
    """
    if not _DETECTOR_SLOT.acquire(blocking=False):
        raise DockDetectorBusy("Dock marker detector still busy")
    try:
        work = _DETECTOR_POOL.submit(
            detect_apriltag, jpeg, calibration, captured_at=captured_at
        )
    except Exception:
        # Executor submission may fail before a Future owns the slot.
        _DETECTOR_SLOT.release()
        raise

    def finish_detection(done) -> None:
        try:
            if not done.cancelled():
                done.exception()  # Retrieve late native detector failures.
        finally:
            _DETECTOR_SLOT.release()

    work.add_done_callback(finish_detection)
    # Shield only the asyncio awaiter. On timeout the native detector is
    # allowed to finish, and holds the slot until its real completion.
    return await asyncio.wait_for(
        asyncio.shield(asyncio.wrap_future(work)), timeout=2.0
    )


async def observe_actual_dock(head, robot) -> dict:
    """Real head JPEG in, real marker pose out. No movement is possible here.

    Time is captured at Mac JPEG receipt, not falsely claimed camera exposure.
    No drive, servo, arm or charge tools are imported or called.
    """
    try:
        calib, target = load_real_dock_calibration(robot.dock_calibration)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return _hold(robot.id, reason=f"Dock calibration required: {exc}", source="not_calibrated")
    try:
        # The native AprilTag slot must not be occupied by an alternate
        # head snapshot that suppresses coroutine cancellation indefinitely.
        from .controller import _bounded_head_reply
        jpeg = await _bounded_head_reply(
            head.snapshot(), seconds=3.0,
            timeout_message="Dock diagnostic camera snapshot timeout",
        )
    except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError) as exc:
        return _hold(robot.id, reason=f"Dock camera unavailable: {type(exc).__name__}", source="head_snapshot_failed")
    # Reject malformed or oversized snapshots before occupying the sole native
    # AprilTag worker. Match the native detector's 512000-byte bound.
    if (not isinstance(jpeg, bytes) or len(jpeg) < 4 or len(jpeg) > 512000
            or not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9")):
        return _hold(robot.id, reason="Invalid dock JPEG", source="head_snapshot_invalid")
    received_at = time.monotonic()
    try:
        pose = await detect_bounded(jpeg, calib, captured_at=received_at)
    except DockDetectorBusy:
        return _hold(
            robot.id, reason="Dock marker detector still busy",
            source="apriltag_detector_busy",
        )
    except Exception as exc:
        # Native OpenCV raises cv2.error (not RuntimeError) on malformed
        # calibration/decoder state. An observation failure never grants rights.
        # Do not catch BaseException: cancellation must still propagate.
        return _hold(
            robot.id,
            reason=f"Dock marker detection unavailable: {type(exc).__name__}",
            source="apriltag_detection_failed",
        )
    # A corrupted native adapter result must not escape as a plausible dock
    # phase or crash the observer after the detector worker has completed.
    if pose is not None and not isinstance(pose, DockPose):
        return _hold(
            robot.id, reason="Dock marker detector returned invalid pose",
            source="apriltag_detection_failed",
        )
    # Receipt timestamp is not the end of OpenCV computation. A slow or
    # stalled detector cannot authorize a now-stale dock observation.
    assessment = assess_dock(pose, now=time.monotonic(), target_distance_mm=target)
    return {
        "robot_id": robot.id, "phase": assessment.phase,
        "reason": assessment.reason,
        "source": "head_jpeg_observed_on_mac_receipt",
        "pose": (
            {
                "x_mm": pose.x_mm, "y_mm": pose.y_mm, "z_mm": pose.z_mm,
                "reprojection_error_px": pose.reprojection_error_px,
            } if pose is not None else None
        ),
        "motor_authorized": False,
        "charging_authorized": False,
        "physical_acceptance_pass": False,
    }
