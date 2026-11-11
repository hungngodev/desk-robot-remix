"""Real camera docking observation without a motor or charger permission."""
from __future__ import annotations

import asyncio
import json
import math
import time

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


async def observe_actual_dock(head, robot) -> dict:
    """Real head JPEG in, real marker pose out. No movement is possible here.

    Time is captured at Mac JPEG receipt, not falsely claimed camera exposure.
    No drive, servo, arm or charge tools are imported or called.
    """
    try:
        calib, target = load_real_dock_calibration(robot.dock_calibration)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return {
            "robot_id": robot.id, "phase": "hold",
            "reason": f"Dock calibration required: {exc}",
            "source": "not_calibrated", "motor_authorized": False,
            "charging_authorized": False, "physical_acceptance_pass": False,
        }
    jpeg = await asyncio.wait_for(head.snapshot(), timeout=3.0)
    received_at = time.monotonic()
    pose = detect_apriltag(jpeg, calib, captured_at=received_at)
    assessment = assess_dock(pose, now=received_at, target_distance_mm=target)
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
