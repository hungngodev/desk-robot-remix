"""Desk edge VL53L0X sensor geometry and stopping-envelope paper preflight.

Recomputes the lens center offset from the selected GY-530 CC0 OpenSCAD
bracket and the existing firmware validity range, not a new ToF driver.
The current 13.3mm PCB envelope yields 11.15mm lens-center height above
the adapter mounting datum; the physical carrier/lens position is unmeasured.
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
    # The current upright front face is pierced ALONG local Y:
    # rotate([90,0,0]) maps the cylinder's initial Z axis to Y. When the
    # bracket's base sits flat, the nominal aperture looks horizontally,
    # NOT down toward the desk. The paper floor path is conditional on a
    # separate physically measured reorientation/placement.
    aperture = scad.split("module tof_adjustable()", 1)[1].split(
        "module oled_bezel()", 1
    )[0]
    if 'rotate([90,0,0])' not in aperture:
        raise ValueError("ToF source aperture axis changed; update mount model")
    accepted = re.findall(r"distance\s*>=\s*(\d+)\s*&&\s*distance\s*<=\s*(\d+)", source)
    if len(accepted) != 1:
        raise ValueError("VL53L0X firmware source threshold changed")
    min_mm, max_mm = map(int, accepted[0])
    return {
        "lens_center_above_adapter_mount_mm": (float(match[0]) + 7.0) / 2.0 + 1.0,
        "firmware_valid_min_mm": min_mm,
        "firmware_valid_max_mm": max_mm,
        "manufacturer_system_fov_deg": ST_SYSTEM_FOV_DEG,
        "source_aperture_axis_parallel_to_base": True,
        "source_flat_base_points_optics_downward": False,
    }


def evaluate(*, chassis_mount_above_desk_mm: float, optical_tilt_deg: float,
             leading_wheel_behind_sensor_mm: float,
             measured_p95_stopping_distance_mm: float,
             remaining_vision_or_sensor_latency_ms: float,
             measured_travel_speed_mm_s: float,
             engineering_margin_mm: float = 10.0,
             measured_worst_stopping_distance_mm: float | None = None) -> dict:
    # The historical p95 parameter is kept for existing diagnostics but
    # MUST NOT authorize a desk-edge geometry. A 95th percentile ignores
    # the slowest 5% of stopping trials. Accept only a separately named
    # observed worst-case distance with a nondecreasing bound.
    vals = (chassis_mount_above_desk_mm, optical_tilt_deg,
            leading_wheel_behind_sensor_mm, measured_p95_stopping_distance_mm,
            remaining_vision_or_sensor_latency_ms, measured_travel_speed_mm_s,
            engineering_margin_mm)
    if any(not _finite_real(v) for v in vals):
        raise ValueError("Every geometry value must be a finite measured number")
    worst_supplied = measured_worst_stopping_distance_mm is not None
    if worst_supplied and (
            not _finite_real(measured_worst_stopping_distance_mm)
            or measured_worst_stopping_distance_mm <
            measured_p95_stopping_distance_mm):
        raise ValueError("Worst observed stop must be finite and at least p95")
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
    stopping = ((measured_worst_stopping_distance_mm if worst_supplied
                 else measured_p95_stopping_distance_mm)
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
        "worst_observed_stop_supplied": worst_supplied,
        "nominal_stopping_geometry_possible": clearance_ok and worst_supplied,
        "candidate_geometry_possible_on_paper": (
            full_cone_range_ok and clearance_ok and worst_supplied
        ),
        "actual_dark_glossy_surface_and_edge_trials": False,
        "sensor_mount_and_optical_alignment_physically_verified": False,
        "downward_optical_axis_reorientation_physically_verified": False,
        "40_sensor_fleet_purchase_approved": False,
    }


def screen_planar_cliff_coverage(
    *, left_wheel_mm_s: float, right_wheel_mm_s: float,
    track_width_mm: float, support_points_mm: list,
    floor_sensor_points_mm: list, chassis_mount_above_desk_mm: float,
    detection_latency_ms: float, measured_worst_braking_mm: float,
    engineering_margin_mm: float = 10.0,
    optical_tilt_deg: float = 0.0,
    qualified_lateral_sensor_coverage_mm: float = 0.0,
) -> dict:
    """Necessary planar motion coverage for all 4 floor sensors.

    Differential drive kinematics from IEEE RAS University:
    v=(vR+vL)/2 and omega=(vR-vL)/track.
    At chassis point (x,y): point velocity=(v-omega*y, omega*x).
    Project each sensor AHEAD of a moving support point along its actual
    tangent. A laterally distant sensor cannot protect an unrelated wheel.
    Ref: https://www.ieee-ras.org/ras-university/?ras_page=docs%2Fchap2_sensing%2Fsensors-and-sensing

    This is a conservative NECESSARY paper screen, not proof that any
    floor sensor can see a partial cliff scene or that the robot can brake.
    """
    scalar = (left_wheel_mm_s, right_wheel_mm_s, track_width_mm,
              chassis_mount_above_desk_mm, detection_latency_ms,
              measured_worst_braking_mm, engineering_margin_mm,
              optical_tilt_deg, qualified_lateral_sensor_coverage_mm)
    if any(not _finite_real(x) for x in scalar):
        raise ValueError("Motion, geometry and qualification inputs must be finite")
    if (track_width_mm <= 0 or chassis_mount_above_desk_mm < 0
            or not 0 <= optical_tilt_deg < 90 - ST_SYSTEM_FOV_DEG / 2
            or detection_latency_ms < 0 or measured_worst_braking_mm < 0
            or engineering_margin_mm < 0
            or qualified_lateral_sensor_coverage_mm < 0):
        raise ValueError("Invalid differential drive dimensions or stop budget")
    if (not isinstance(floor_sensor_points_mm, (list, tuple))
            or not isinstance(support_points_mm, (list, tuple))
            or len(floor_sensor_points_mm) != 4 or len(support_points_mm) < 3):
        raise ValueError("Need four floor sensors and every supporting contact")
    for point in [*support_points_mm, *floor_sensor_points_mm]:
        if (not isinstance(point, (list, tuple)) or len(point) != 2
                or any(not _finite_real(c) for c in point)
                # A desk robot cannot have a valid body coordinate a full
                # kilometre from its origin. This is input sanitation, not
                # an assumed enclosure size or an optical clearance.
                or any(abs(c) > 1_000_000 for c in point)):
            raise ValueError("Each measured chassis point needs plausible finite x,y")

    # Four entries must represent four distinct mounted optical centers.
    # Repeated support points likewise cannot replace omitted contacts.
    if len(set(map(tuple, floor_sensor_points_mm))) != len(floor_sensor_points_mm):
        raise ValueError("Duplicate floor sensor coordinates")
    if len(set(map(tuple, support_points_mm))) != len(support_points_mm):
        raise ValueError("Duplicate support contact coordinates")

    baseline = verify_source_contract()
    h = (chassis_mount_above_desk_mm
         + baseline["lens_center_above_adapter_mount_mm"])
    # Motion coverage is not meaningful if the actual floor cannot produce
    # an in-range reading across the nominal ST optical cone. This separate
    # gate prevents a mechanically plausible wheel lead from masquerading
    # as a usable cliff detector with a lens below firmware's 30 mm minimum.
    half_fov = ST_SYSTEM_FOV_DEG / 2
    near_angle = max(0.0, optical_tilt_deg - half_fov)
    far_angle = optical_tilt_deg + half_fov
    near_range = h / math.cos(math.radians(near_angle))
    far_range = h / math.cos(math.radians(far_angle))
    full_fov_range_ok = (
        math.isfinite(near_range) and math.isfinite(far_range)
        and baseline["firmware_valid_min_mm"] <= near_range
        and far_range <= baseline["firmware_valid_max_mm"]
    )
    # Until orientation of each mounted sensor is physically measured,
    # include the entire worst radial reach of a tilted FoV as potential
    # late tabletop support, rather than claiming early edge discovery.
    fov_rear_setback = h * math.tan(math.radians(
        optical_tilt_deg + ST_SYSTEM_FOV_DEG / 2))
    # A vendor FoV alone does not guarantee lateral recognition. Default 0
    # until a qualified actual surface/footprint measurement is supplied.
    nominal_lateral_radius = h * math.tan(math.radians(ST_SYSTEM_FOV_DEG / 2))
    if (not math.isfinite(fov_rear_setback)
            or not math.isfinite(nominal_lateral_radius)
            or qualified_lateral_sensor_coverage_mm > nominal_lateral_radius):
        raise ValueError("Cliff optical coverage exceeds finite manufacturer geometry")
    v = (left_wheel_mm_s + right_wheel_mm_s) / 2
    omega = (right_wheel_mm_s - left_wheel_mm_s) / track_width_mm
    if not math.isfinite(v) or not math.isfinite(omega):
        raise ValueError("Differential wheel speed overflow")
    cases = []
    active = 0
    for index, (x, y) in enumerate(support_points_mm):
        dx_dt, dy_dt = v - omega * y, omega * x
        speed = math.hypot(dx_dt, dy_dt)
        if not math.isfinite(speed):
            raise ValueError("Support contact speed overflow")
        if speed == 0:
            cases.append({"support_index": index, "motion_mm_s": 0.0,
                          "requires_cliff_coverage": False, "covered": True})
            continue
        active += 1
        ux, uy = dx_dt / speed, dy_dt / speed
        projected_leads = [
            (sx - x)*ux + (sy - y)*uy
            for sx, sy in floor_sensor_points_mm
            if abs((sx - x)*uy - (sy - y)*ux)
               <= qualified_lateral_sensor_coverage_mm
        ]
        best_lead = max(projected_leads) if projected_leads else None
        if any(not math.isfinite(lead) for lead in projected_leads):
            raise ValueError("Projected floor sensor lead overflow")
        required = (measured_worst_braking_mm + engineering_margin_mm
                    + speed * detection_latency_ms / 1000
                    + fov_rear_setback)
        if not all(math.isfinite(z) for z in
                   (speed, required, fov_rear_setback)):
            raise ValueError("Turning geometry or latency overflow")
        cases.append({
            "support_index": index, "motion_mm_s": speed,
            "requires_cliff_coverage": True,
            "best_sensor_lead_mm": best_lead,
            "required_sensor_lead_mm": required,
            "covered": best_lead is not None and best_lead > required,
        })
    if active == 0:
        raise ValueError("Evaluate a moving command, not a stationary robot")
    return {
        "body_translation_mm_s": v,
        "body_turn_rate_rad_s": omega,
        "manufacturer_fov_deg": ST_SYSTEM_FOV_DEG,
        "conservative_tilt_deg": optical_tilt_deg,
        "nominal_fov_rear_footprint_mm": fov_rear_setback,
        "nominal_full_fov_floor_in_valid_range": full_fov_range_ok,
        "support_checks": cases,
        "necessary_planar_coverage_on_paper": (
            full_fov_range_ok and all(c["covered"] for c in cases)
        ),
        "actual_surface_and_motor_faults_verified": False,
        "reference_bracket_requires_downward_reorientation": True,
        "mounted_axis_physically_verified": False,
        "fully_safe_cliff_operation_proven": False,
    }


PLANAR_COORDINATE_FRAME = "body_x_forward_y_left"
PLANAR_MEASUREMENT_FIELDS = (
    "left_wheel_mm_s", "right_wheel_mm_s", "track_width_mm",
    "support_points_mm", "floor_sensor_points_mm",
    "chassis_mount_above_desk_mm", "detection_latency_ms",
    "measured_worst_braking_mm", "engineering_margin_mm",
    "optical_tilt_deg", "qualified_lateral_sensor_coverage_mm",
)


def planar_measurement_template() -> dict:
    """Blank physical measurement record for one proposed command."""
    return {
        "coordinate_frame": PLANAR_COORDINATE_FRAME,
        **dict.fromkeys(PLANAR_MEASUREMENT_FIELDS),
        "support_points_mm": [],
        "floor_sensor_points_mm": [],
        "engineering_margin_mm": 10.0,
        "qualified_lateral_sensor_coverage_mm": 0.0,
    }


def _unique_planar_fields(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate planar measurement field")
        result[key] = value
    return result


def _reject_planar_constant(token: str) -> None:
    raise ValueError("Nonfinite planar measurement: " + token)


def screen_planar_record(record: object) -> dict:
    if (not isinstance(record, dict)
            or set(record) != {"coordinate_frame", *PLANAR_MEASUREMENT_FIELDS}
            or record["coordinate_frame"] != PLANAR_COORDINATE_FRAME):
        raise ValueError("Exact planar measurement fields and body frame required")
    return {
        "coordinate_frame": PLANAR_COORDINATE_FRAME,
        **screen_planar_cliff_coverage(**{
            key: record[key] for key in PLANAR_MEASUREMENT_FIELDS
        }),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    planar = parser.add_mutually_exclusive_group()
    planar.add_argument("--planar-template", action="store_true",
                        help="Print blank measurements for one wheel command")
    planar.add_argument("--planar-measurements", type=Path,
                        help="Screen the measured planar JSON record")
    parser.add_argument("--mount-above-desk-mm", type=float)
    parser.add_argument("--tilt-deg", type=float)
    parser.add_argument("--sensor-ahead-of-wheel-mm", type=float)
    parser.add_argument("--measured-worst-stopping-mm", type=float,
                        help="Highest observed loaded stop, never p95 alone")
    parser.add_argument("--latency-ms", type=float)
    parser.add_argument("--speed-mm-s", type=float)
    args = parser.parse_args()
    scalar = (args.mount_above_desk_mm, args.tilt_deg,
              args.sensor_ahead_of_wheel_mm, args.measured_worst_stopping_mm,
              args.latency_ms, args.speed_mm_s)
    if args.planar_template or args.planar_measurements is not None:
        if any(value is not None for value in scalar):
            parser.error("Do not mix planar and straight-drive measurements")
        if args.planar_template:
            print(json.dumps(planar_measurement_template(), indent=2))
        else:
            record = json.loads(
                args.planar_measurements.read_text(encoding="utf-8"),
                object_pairs_hook=_unique_planar_fields,
                parse_constant=_reject_planar_constant,
            )
            print(json.dumps(screen_planar_record(record), indent=2))
        return
    if any(value is None for value in scalar):
        parser.error("All six straight-drive measurements are required")
    print(json.dumps(evaluate(
        chassis_mount_above_desk_mm=args.mount_above_desk_mm,
        optical_tilt_deg=args.tilt_deg,
        leading_wheel_behind_sensor_mm=args.sensor_ahead_of_wheel_mm,
        measured_p95_stopping_distance_mm=args.measured_worst_stopping_mm,
        measured_worst_stopping_distance_mm=args.measured_worst_stopping_mm,
        remaining_vision_or_sensor_latency_ms=args.latency_ms,
        measured_travel_speed_mm_s=args.speed_mm_s,
    ), indent=2))


if __name__ == "__main__":
    main()
