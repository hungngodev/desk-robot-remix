"""Real camera docking observation without a motor or charger permission."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import math
import time
import threading

# Keep the native future itself as the worker lifetime owner. An asyncio wrapper
# can be cancelled during shutdown while the C detector is still running.
_DETECTOR_SLOT = threading.BoundedSemaphore(1)
_DETECTOR_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="desk-apriltag")

from .dock_vision import DockCameraCalibration, assess_dock, detect_apriltag


def load_real_dock_calibration(path) -> tuple[DockCameraCalibration, float]:
    if path is None:
        raise ValueError("No dock calibration configured")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("measured") is not True:
        raise ValueError("Dock camera geometry is not physically measured")
    props = ("fx", "fy", "cx", "cy", "tag_side_mm", "marker_id")
    if any(key not in data for key in props):
        raise ValueError("Dock calibration lacks measured camera parameters")
    calibration = DockCameraCalibration(**{key: data[key] for key in props})
    target = data.get("target_distance_mm")
    if type(target) not in (float, int) or not math.isfinite(target) or not 50 <= target <= 500:
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


async def observe_actual_dock(head, robot) -> dict:
    """Real head JPEG in, real marker pose out. No movement is possible here.

    Time is captured at Mac JPEG receipt, not falsely claimed camera exposure.
    No drive, servo, arm or charge tools are imported or called.
    """
    try:
        calib, target = load_real_dock_calibration(robot.dock_calibration)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return _hold(robot.id, reason=f"Dock calibration required: {exc}", source="not_calibrated")
    try:
        jpeg = await asyncio.wait_for(head.snapshot(), timeout=3.0)
    except (OSError, ConnectionError, TimeoutError) as exc:
        return _hold(robot.id, reason=f"Dock camera unavailable: {type(exc).__name__}", source="head_snapshot_failed")
    received_at = time.monotonic()
    if not _DETECTOR_SLOT.acquire(blocking=False):
        return _hold(robot.id, reason="Dock marker detector still busy", source="apriltag_detector_busy")

    # ThreadPoolExecutor.submit returns the *native* concurrent future.
    # Its completion cannot precede the worker's actual exit, unlike the
    # cancellable asyncio task returned by asyncio.to_thread.
    try:
        work = _DETECTOR_POOL.submit(
            detect_apriltag, jpeg, calib, captured_at=received_at
        )
    except (RuntimeError, OSError) as exc:
        _DETECTOR_SLOT.release()  # Dispatch failed: no native worker exists.
        return _hold(
            robot.id,
            reason=f"Dock marker dispatch unavailable: {type(exc).__name__}",
            source="apriltag_detection_failed",
        )

    def finish_detection(done) -> None:
        try:
            if not done.cancelled():
                done.exception()  # Retrieve late native detector failures.
        finally:
            _DETECTOR_SLOT.release()

    work.add_done_callback(finish_detection)
    try:
        # A timeout or observer cancellation only abandons the *await*.
        # Even if event-loop shutdown cancels this wrapper, the semaphore is
        # held until the concurrent future completes or cancels pre-dispatch.
        pose = await asyncio.wait_for(
            asyncio.shield(asyncio.wrap_future(work)), timeout=2.0
        )
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        return _hold(robot.id, reason=f"Dock marker detection unavailable: {type(exc).__name__}", source="apriltag_detection_failed")
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
