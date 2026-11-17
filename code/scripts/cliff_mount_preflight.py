"""Desk edge VL53L0X sensor geometry and stopping-envelope paper preflight.

Reuses the actual 13.5mm lens center implied by the CC0 source OpenSCAD
adapter and the existing firmware validity range, not a new ToF driver.
A paper feasibility check is NOT a physical cliff calibration or permission
to enable local motors. All inputs concerning mounted robot must be measured.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAD = ROOT / "docs/cad/remixes/one_robot_adapter_kit.scad"
TOF = ROOT / "code/firmware/body/lib/TofBus/TofBus.cpp"


def verify_source_contract() -> dict:
    """Detect critical CAD or driver changes rather than silently assuming them."""
    import re
    scad = CAD.read_text(encoding="utf-8")
    source = TOF.read_text(encoding="utf-8")
    match = re.findall(r"^tof_pcb_h\s*=\s*(\d+(?:\.\d+)?)\s*;", scad, re.M)
    if len(match) != 1 or not math.isfinite(float(match[0])):
        raise ValueError("Missing or ambiguous ToF bracket height")
    if "face_z=tof_pcb_h+7;" not in scad or "face_z/2+1" not in scad:
        raise ValueError("CAD lens position changed; update check")
    accepted = re.findall(r"distance\s*>=\s*(\d+)\s*&&\s*distance\s*<=\s*(\d+)", source)
    if len(accepted) != 1:
        raise ValueError("VL53L0X firmware source threshold changed")
    min_mm, max_mm = map(int, accepted[0])
    return {
        "lens_center_above_adapter_mount_mm": (float(match[0]) + 7.0) / 2.0 + 1.0,
        "firmware_valid_min_mm": min_mm,
        "firmware_valid_max_mm": max_mm,
    }


def evaluate(*, chassis_mount_above_desk_mm: float, optical_tilt_deg: float,
             leading_wheel_behind_sensor_mm: float,
             measured_p95_stopping_distance_mm: float,
             remaining_vision_or_sensor_latency_ms: float,
             measured_travel_speed_mm_s: float,
             engineering_margin_mm: float = 10.0) -> dict:
    vals = (chassis_mount_above_desk_mm, optical_tilt_deg,
            leading_wheel_behind_sensor_mm, measured_p95_stopping_distance_mm,
            remaining_vision_or_sensor_latency_ms, measured_travel_speed_mm_s,
            engineering_margin_mm)
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) for v in vals):
        raise ValueError("Every geometry value must be a finite measured number")
    if (chassis_mount_above_desk_mm < 0
            or not 0 <= optical_tilt_deg < 80
            or leading_wheel_behind_sensor_mm <= 0
            or measured_p95_stopping_distance_mm < 0
            or remaining_vision_or_sensor_latency_ms < 0
            or measured_travel_speed_mm_s <= 0
            or engineering_margin_mm < 0):
        raise ValueError("Invalid cliff sensor clearance or stopping envelope")
    baseline = verify_source_contract()
    height = chassis_mount_above_desk_mm + baseline[
        "lens_center_above_adapter_mount_mm"]
    slant = height / math.cos(math.radians(optical_tilt_deg))
    optical_feasible = (baseline["firmware_valid_min_mm"] <= slant <=
                        baseline["firmware_valid_max_mm"])
    stopping = (measured_p95_stopping_distance_mm
                + remaining_vision_or_sensor_latency_ms
                * measured_travel_speed_mm_s / 1000.0
                + engineering_margin_mm)
    clearance_ok = leading_wheel_behind_sensor_mm > stopping
    return {
        **baseline,
        "nominal_lens_above_desk_mm": height,
        "nominal_optical_floor_path_mm": slant,
        "nominal_floor_in_firmware_valid_range": optical_feasible,
        "required_wheel_behind_sensor_mm": stopping,
        "wheel_behind_sensor_mm": leading_wheel_behind_sensor_mm,
        "nominal_stopping_geometry_possible": clearance_ok,
        "candidate_geometry_possible_on_paper": optical_feasible and clearance_ok,
        "actual_dark_glossy_surface_and_edge_trials": False,
        "sensor_mount_and_optical_alignment_physically_verified": False,
        "40_sensor_fleet_purchase_approved": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mount-above-desk-mm", type=float, required=True)
    parser.add_argument("--tilt-deg", type=float, required=True)
    parser.add_argument("--sensor-ahead-of-wheel-mm", type=float, required=True)
    parser.add_argument("--measured-stopping-mm", type=float, required=True)
    parser.add_argument("--latency-ms", type=float, required=True)
    parser.add_argument("--speed-mm-s", type=float, required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate(
        chassis_mount_above_desk_mm=args.mount_above_desk_mm,
        optical_tilt_deg=args.tilt_deg,
        leading_wheel_behind_sensor_mm=args.sensor_ahead_of_wheel_mm,
        measured_p95_stopping_distance_mm=args.measured_stopping_mm,
        remaining_vision_or_sensor_latency_ms=args.latency_ms,
        measured_travel_speed_mm_s=args.speed_mm_s,
    ), indent=2))


if __name__ == "__main__":
    main()
