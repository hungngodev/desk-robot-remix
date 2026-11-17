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
# ST DS11555 Rev 6, section 6.1 specifies 25 degree SYSTEM field of view.
# It is not a point ray. A sliver of floor visible at the rear of this cone
# may remain a plausible echo after the central ray has crossed the edge.
ST_SYSTEM_FOV_DEG = 25.0


def _finite_real(value: object) -> bool:
    # int is unbounded in Python: math.isfinite(10**1000) raises
    # OverflowError. Malformed host/CLI telemetry must fail closed.
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


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
        "manufacturer_system_fov_deg": ST_SYSTEM_FOV_DEG,
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
    if any(not _finite_real(v) for v in vals):
        raise ValueError("Every geometry value must be a finite measured number")
    if (chassis_mount_above_desk_mm < 0
            # The forward cone extremity must intersect the floor. A beam
            # at or above the horizon has no finite horizontal footprint.
            or not 0 <= optical_tilt_deg < 90 - ST_SYSTEM_FOV_DEG / 2
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
    half_fov = ST_SYSTEM_FOV_DEG / 2
    rear_angle = optical_tilt_deg - half_fov
    front_angle = optical_tilt_deg + half_fov
    # Geometric full-cone envelope: ST's published ranging tables assume
    # the WHOLE 25-degree field is covered. Near a desk edge this assumption
    # is violated. Do not treat an unchanged range from a partial floor
    # footprint as permission to keep moving.
    near_angle = max(0.0, rear_angle)
    nearest_slant = height / math.cos(math.radians(near_angle))
    farthest_slant = height / math.cos(math.radians(front_angle))
    center_range_ok = (baseline["firmware_valid_min_mm"] <= slant <=
                       baseline["firmware_valid_max_mm"])
    full_cone_range_ok = (
        baseline["firmware_valid_min_mm"] <= nearest_slant
        and farthest_slant <= baseline["firmware_valid_max_mm"]
    )
    # Worst case: floor remains at the rear rim of the optical cone even
    # after the center ray has crossed the tabletop edge. For forward
    # tilted sensors we conservatively credit NO additional forward lead.
    rear_floor_setback = max(
        0.0, -height * math.tan(math.radians(rear_angle))
    )
    stopping = (measured_p95_stopping_distance_mm
                + remaining_vision_or_sensor_latency_ms
                * measured_travel_speed_mm_s / 1000.0
                + engineering_margin_mm)
    required_physical_lead = stopping + rear_floor_setback
    effective_lead = leading_wheel_behind_sensor_mm - rear_floor_setback
    if any(not math.isfinite(v) for v in (
            height, slant, nearest_slant, farthest_slant,
            rear_floor_setback, stopping, required_physical_lead,
            effective_lead)):
        raise ValueError("Geometry computation overflowed its safe range")
    clearance_ok = leading_wheel_behind_sensor_mm > required_physical_lead
    return {
        **baseline,
        "nominal_lens_above_desk_mm": height,
        "nominal_optical_floor_path_mm": slant,
        "nominal_floor_in_firmware_valid_range": center_range_ok,
        "full_fov_nearest_floor_path_mm": nearest_slant,
        "full_fov_farthest_floor_path_mm": farthest_slant,
        "full_fov_floor_path_in_valid_range": full_cone_range_ok,
        "rear_floor_return_setback_mm": rear_floor_setback,
        "effective_wheel_edge_lead_mm": effective_lead,
        "required_stopping_clearance_mm": stopping,
        "required_wheel_behind_sensor_mm": required_physical_lead,
        "wheel_behind_sensor_mm": leading_wheel_behind_sensor_mm,
        "nominal_stopping_geometry_possible": clearance_ok,
        "candidate_geometry_possible_on_paper": full_cone_range_ok and clearance_ok,
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
