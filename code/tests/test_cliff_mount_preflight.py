"""Host source/geometry safety contract for the 8 inexpensive VL53L0X lanes."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/cliff_mount_preflight.py"
spec = importlib.util.spec_from_file_location("cliff_mount_preflight", SCRIPT)
assert spec and spec.loader
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def evaluate(**updates):
    args = dict(chassis_mount_above_desk_mm=0.0, optical_tilt_deg=0.0,
                leading_wheel_behind_sensor_mm=45.0,
                measured_p95_stopping_distance_mm=10.0,
                measured_worst_stopping_distance_mm=10.0,
                remaining_vision_or_sensor_latency_ms=80.0,
                measured_travel_speed_mm_s=100.0)
    args.update(updates)
    return tool.evaluate(**args)


def test_exact_source_bracket_lens_is_below_minimum_if_mount_flush_to_desk():
    source = tool.verify_source_contract()
    assert source["lens_center_above_adapter_mount_mm"] == 11.15
    assert source["firmware_valid_min_mm"] == 30
    assert source["firmware_valid_max_mm"] == 1300
    assert source["manufacturer_system_fov_deg"] == 25.0
    low = evaluate()
    # Source and evaluated geometry must agree; reject a stale 18 mm PCB
    # assumption without weakening the 30 mm sensor-validity gate.
    assert low["nominal_optical_floor_path_mm"] == source[
        "lens_center_above_adapter_mount_mm"
    ]
    assert not low["nominal_floor_in_firmware_valid_range"]
    assert not low["candidate_geometry_possible_on_paper"]
    assert not low["40_sensor_fleet_purchase_approved"]


def test_properly_raised_sensor_can_be_feasible_but_not_qualified():
    r = evaluate(chassis_mount_above_desk_mm=20.0)
    assert r["nominal_optical_floor_path_mm"] == 31.15
    assert r["nominal_floor_in_firmware_valid_range"]
    # ST's 25 degree cone leaves a rearward floor sliver visible even
    # after a point-ray would have already crossed the edge.
    assert r["required_stopping_clearance_mm"] == 28.0
    assert r["rear_floor_return_setback_mm"] == pytest.approx(6.90579, abs=.001)
    assert r["effective_wheel_edge_lead_mm"] == pytest.approx(38.09421, abs=.001)
    assert r["required_wheel_behind_sensor_mm"] == pytest.approx(34.90579, abs=.001)
    assert r["full_fov_floor_path_in_valid_range"]
    assert r["nominal_stopping_geometry_possible"]
    assert r["worst_observed_stop_supplied"]
    assert r["candidate_geometry_possible_on_paper"]
    assert not r["actual_dark_glossy_surface_and_edge_trials"]
    assert not r["sensor_mount_and_optical_alignment_physically_verified"]
    assert not r["40_sensor_fleet_purchase_approved"]


def test_st_full_fov_rear_floor_echo_rejects_false_point_ray_pass():
    # A 32mm lead exceeds 28mm stopping clearance in a point ray
    # calculation, but the rearward cone still sees the desk afterwards.
    # Effective 25.09mm lead is too short: prevent a premature purchase.
    unsafe = evaluate(chassis_mount_above_desk_mm=20.0,
                      leading_wheel_behind_sensor_mm=32.0)
    assert unsafe["nominal_floor_in_firmware_valid_range"]
    assert unsafe["full_fov_floor_path_in_valid_range"]
    assert unsafe["required_stopping_clearance_mm"] == 28.0
    assert unsafe["effective_wheel_edge_lead_mm"] < 28.0
    assert not unsafe["nominal_stopping_geometry_possible"]
    assert not unsafe["candidate_geometry_possible_on_paper"]
    assert not unsafe["40_sensor_fleet_purchase_approved"]


def test_forward_tilt_full_cone_can_look_valid_on_axis_but_fail_off_axis():
    unsafe = evaluate(chassis_mount_above_desk_mm=20.0,
                      optical_tilt_deg=77.0)
    assert unsafe["nominal_floor_in_firmware_valid_range"]
    assert not unsafe["full_fov_floor_path_in_valid_range"]
    assert not unsafe["candidate_geometry_possible_on_paper"]


def test_wider_rear_floor_footprint_does_not_gain_false_wheel_clearance():
    near = evaluate(chassis_mount_above_desk_mm=20.0)
    tall = evaluate(chassis_mount_above_desk_mm=70.0)
    assert tall["rear_floor_return_setback_mm"] > near["rear_floor_return_setback_mm"]
    assert tall["required_wheel_behind_sensor_mm"] > near["required_wheel_behind_sensor_mm"]


def test_late_braking_fails_even_with_feasible_lens_height():
    r = evaluate(chassis_mount_above_desk_mm=20.0,
                 measured_p95_stopping_distance_mm=40,
                 measured_worst_stopping_distance_mm=40)
    assert r["nominal_floor_in_firmware_valid_range"]
    assert not r["nominal_stopping_geometry_possible"]
    assert not r["candidate_geometry_possible_on_paper"]


def test_p95_only_is_not_an_accepted_desk_edge_stopping_bound():
    result = evaluate(
        chassis_mount_above_desk_mm=20,
        measured_worst_stopping_distance_mm=None,
    )
    assert result["full_fov_floor_path_in_valid_range"]
    assert not result["worst_observed_stop_supplied"]
    assert not result["nominal_stopping_geometry_possible"]
    assert not result["candidate_geometry_possible_on_paper"]


def test_worst_observed_stop_rejects_faster_than_reported_p95():
    with pytest.raises(ValueError, match="Worst observed stop"):
        evaluate(chassis_mount_above_desk_mm=20,
                 measured_p95_stopping_distance_mm=20,
                 measured_worst_stopping_distance_mm=10)


def test_worst_observed_stop_controls_required_wheel_lead():
    # A 44mm sensor lead is feasible at the default 10mm p95,
    # but NOT at the measured 20mm worst stop plus latency and full FoV.
    p95_only = evaluate(chassis_mount_above_desk_mm=20,
                        leading_wheel_behind_sensor_mm=44,
                        measured_worst_stopping_distance_mm=None)
    worst = evaluate(chassis_mount_above_desk_mm=20,
                     leading_wheel_behind_sensor_mm=44,
                     measured_worst_stopping_distance_mm=20)
    assert worst["required_wheel_behind_sensor_mm"] == pytest.approx(
        p95_only["required_wheel_behind_sensor_mm"] + 10
    )
    assert not worst["candidate_geometry_possible_on_paper"]


def planar(**overrides):
    values = dict(
        left_wheel_mm_s=100.0, right_wheel_mm_s=100.0,
        track_width_mm=100.0,
        # Two drive-wheel contacts and a rear supporting caster.
        support_points_mm=[[0, -10], [0, 10], [-10, 0]],
        # Four existing downward optical lanes, NOT the side diagnostics.
        floor_sensor_points_mm=[[45, -10], [45, 10], [35, 0], [-45, 0]],
        chassis_mount_above_desk_mm=20.0,
        detection_latency_ms=80.0, measured_worst_braking_mm=10.0,
        engineering_margin_mm=10.0,
    )
    values.update(overrides)
    return tool.screen_planar_cliff_coverage(**values)


def test_forward_2d_contact_coverage_uses_st_25_degree_optical_rear_setback():
    result = planar()
    assert result["body_translation_mm_s"] == 100.0
    assert result["body_turn_rate_rad_s"] == 0.0
    assert result["manufacturer_fov_deg"] == 25.0
    assert result["nominal_fov_rear_footprint_mm"] == pytest.approx(6.90579, abs=.001)
    assert all(s["covered"] for s in result["support_checks"])
    assert result["necessary_planar_coverage_on_paper"]
    assert not result["fully_safe_cliff_operation_proven"]


def test_planar_lead_cannot_pass_if_floor_is_below_sensor_minimum_range():
    # With a flush adapter the 11.15 mm lens height is BELOW firmware's
    # 30 mm VL53L0X acceptance minimum. Large forward sensor lead must not
    # make a motion geometry report pass when no floor sample is accepted.
    result = planar(chassis_mount_above_desk_mm=0.0)
    assert all(c["covered"] for c in result["support_checks"])
    assert not result["nominal_full_fov_floor_in_valid_range"]
    assert not result["necessary_planar_coverage_on_paper"]
    assert not result["fully_safe_cliff_operation_proven"]


def test_planar_lead_cannot_pass_if_sensor_floor_exceeds_maximum_range():
    # Separate upper-range failure from low mounting height: both invalidate
    # the nominal optical prerequisite regardless of projected wheel lead.
    result = planar(
        chassis_mount_above_desk_mm=1300.0,
        # Keep the purely mechanical lead feasible despite the large optical
        # setback. This isolates the high-range failure instead of testing
        # a second, unrelated insufficient-lead failure at the same time.
        floor_sensor_points_mm=[[800, -10], [800, 10], [800, 0], [-800, 0]],
    )
    assert all(c["covered"] for c in result["support_checks"])
    assert not result["nominal_full_fov_floor_in_valid_range"]
    assert not result["necessary_planar_coverage_on_paper"]


def test_planar_feasible_mount_keeps_optical_prerequisite_explicit():
    result = planar(chassis_mount_above_desk_mm=20.0)
    assert result["nominal_full_fov_floor_in_valid_range"]
    assert result["necessary_planar_coverage_on_paper"]


def test_forward_safe_configuration_may_have_unsafe_reverse():
    reverse = planar(left_wheel_mm_s=-100, right_wheel_mm_s=-100)
    assert reverse["body_translation_mm_s"] == -100.0
    assert not reverse["necessary_planar_coverage_on_paper"]
    assert any(not s["covered"] for s in reverse["support_checks"])


def test_differential_drive_spin_moves_front_and_rear_supports_sideways():
    spin = planar(
        left_wheel_mm_s=-100, right_wheel_mm_s=100,
        support_points_mm=[[40, 0], [-40, 0], [0, 0]],
        floor_sensor_points_mm=[[40, 60], [-40, -60],
                                [40, -60], [-40, 60]],
    )
    assert spin["body_translation_mm_s"] == 0.0
    assert spin["body_turn_rate_rad_s"] == 2.0
    assert spin["support_checks"][0]["motion_mm_s"] == 80.0
    assert spin["support_checks"][0]["covered"]
    assert spin["support_checks"][1]["covered"]
    assert not spin["support_checks"][2]["requires_cliff_coverage"]
    assert spin["necessary_planar_coverage_on_paper"]

    # Same motor command, only forward/backward-aligned sensors. A pure
    # one-dimensional cliff check would miss the lateral edge sweep.
    missed = planar(
        left_wheel_mm_s=-100, right_wheel_mm_s=100,
        support_points_mm=[[40, 0], [-40, 0], [0, 0]],
    )
    assert not missed["necessary_planar_coverage_on_paper"]


def test_increasing_tilt_reduces_available_cliff_margin_on_a_turn_or_drive():
    safe = planar()
    tilted = planar(optical_tilt_deg=20)
    assert safe["necessary_planar_coverage_on_paper"]
    assert not tilted["necessary_planar_coverage_on_paper"]
    assert tilted["nominal_fov_rear_footprint_mm"] > (
        safe["nominal_fov_rear_footprint_mm"])


@pytest.mark.parametrize("update", [
    {"track_width_mm": 0},
    {"track_width_mm": 10**1000},
    {"support_points_mm": None},
    {"floor_sensor_points_mm": None},
    {"support_points_mm": [[1e308, 0], [0, 0], [0, 10]]},
    {"floor_sensor_points_mm": [[1e308, 0], [-1e308, 0],
                                [0, 1e308], [0, -1e308]]},
    {"left_wheel_mm_s": 1e308, "right_wheel_mm_s": 1e308},
    {"left_wheel_mm_s": 1e308, "right_wheel_mm_s": -1e308},
    {"left_wheel_mm_s": 10**1000},
    {"left_wheel_mm_s": 0, "right_wheel_mm_s": 0},
    {"optical_tilt_deg": 77.5},
    {"floor_sensor_points_mm": [[0,0]]},
    {"support_points_mm": [[0,0], [1,1]]},
    {"support_points_mm": [[0,0], [1,1], ["bad",0]]},
    {"qualified_lateral_sensor_coverage_mm": 1000},
    {"detection_latency_ms": 1e308, "left_wheel_mm_s": 1e308},
])
def test_planar_motion_contract_rejects_missing_or_malformed_geometry(update):
    with pytest.raises(ValueError):
        planar(**update)


@pytest.mark.parametrize("kwargs", [
    {"chassis_mount_above_desk_mm": float("nan")},
    {"chassis_mount_above_desk_mm": 10 ** 1000},
    {"remaining_vision_or_sensor_latency_ms": 10 ** 1000},
    {"remaining_vision_or_sensor_latency_ms": 1e308,
     "measured_travel_speed_mm_s": 1e308},
    {"chassis_mount_above_desk_mm": True},
    {"chassis_mount_above_desk_mm": -1},
    {"optical_tilt_deg": 90},
    {"optical_tilt_deg": 77.5},
    {"optical_tilt_deg": -5},
    {"leading_wheel_behind_sensor_mm": 0},
    {"remaining_vision_or_sensor_latency_ms": -1},
    {"measured_p95_stopping_distance_mm": -2},
    {"measured_travel_speed_mm_s": 0},
    {"engineering_margin_mm": float("inf")},
])
def test_bad_or_missing_evidence_never_passes(kwargs):
    with pytest.raises(ValueError):
        evaluate(**kwargs)
