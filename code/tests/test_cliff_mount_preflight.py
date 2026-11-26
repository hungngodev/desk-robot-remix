"""Host source/geometry safety contract for the 8 inexpensive VL53L0X lanes."""
import importlib.util
import math
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
    assert source["source_aperture_axis_parallel_to_base"]
    assert not source["source_flat_base_points_optics_downward"]
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
    # Feasible only if the adapter is actually oriented to point downward.
    # A flat-mounted source bracket's Y-axis aperture is not a floor ranger.
    assert r["candidate_geometry_possible_on_paper"]
    assert r["source_aperture_axis_parallel_to_base"]
    assert not r["source_flat_base_points_optics_downward"]
    assert not r["downward_optical_axis_reorientation_physically_verified"]
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
    assert result["reference_bracket_requires_downward_reorientation"]
    assert not result["mounted_axis_physically_verified"]


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
    {"floor_sensor_points_mm": [[45, -10], [45, 10], [35, 0], [35, 0]]},
    {"support_points_mm": [[0, -10], [0, 10], [0, 10]]},
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


def test_planar_cli_matches_function_and_preserves_physical_hold(tmp_path):
    import json
    import subprocess
    import sys

    cmd = [sys.executable, str(SCRIPT)]
    blank = subprocess.run(
        [*cmd, "--planar-template"], capture_output=True, text=True, check=True,
    )
    record = json.loads(blank.stdout)
    assert record == tool.planar_measurement_template()
    assert record["left_wheel_mm_s"] is None
    assert record["floor_sensor_points_mm"] == []
    path = tmp_path / "planar.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    missing = subprocess.run(
        [*cmd, "--planar-measurements", str(path)],
        capture_output=True, text=True,
    )
    assert missing.returncode != 0
    record.update(
        left_wheel_mm_s=100.0, right_wheel_mm_s=100.0,
        track_width_mm=100.0,
        support_points_mm=[[0, -10], [0, 10], [-10, 0]],
        floor_sensor_points_mm=[[45, -10], [45, 10], [35, 0], [-45, 0]],
        chassis_mount_above_desk_mm=20.0, detection_latency_ms=80.0,
        measured_worst_braking_mm=10.0, optical_tilt_deg=0.0,
    )
    for speed in (100.0, -100.0):
        record["left_wheel_mm_s"] = record["right_wheel_mm_s"] = speed
        path.write_text(json.dumps(record), encoding="utf-8")
        completed = subprocess.run(
            [*cmd, "--planar-measurements", str(path)],
            capture_output=True, text=True, check=True,
        )
        result = json.loads(completed.stdout)
        assert result == tool.screen_planar_record(record)
        assert result["necessary_planar_coverage_on_paper"] is (speed > 0)
        assert not result["fully_safe_cliff_operation_proven"]
    # The same normal entry point also reaches the spin calculation.
    record.update(
        left_wheel_mm_s=-100.0, right_wheel_mm_s=100.0,
        support_points_mm=[[40, 0], [-40, 0], [0, 0]],
        floor_sensor_points_mm=[[40, 60], [-40, -60], [40, -60], [-40, 60]],
    )
    path.write_text(json.dumps(record), encoding="utf-8")
    spin = subprocess.run(
        [*cmd, "--planar-measurements", str(path)],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(spin.stdout)["body_turn_rate_rad_s"] == 2.0
    assert json.loads(spin.stdout)["necessary_planar_coverage_on_paper"]
    record["coordinate_frame"] = "body_x_left_y_forward"
    path.write_text(json.dumps(record), encoding="utf-8")
    wrong = subprocess.run(
        [*cmd, "--planar-measurements", str(path)],
        capture_output=True, text=True,
    )
    assert wrong.returncode != 0
    mixed = subprocess.run(
        [*cmd, "--planar-template", "--tilt-deg", "0"],
        capture_output=True, text=True,
    )
    assert mixed.returncode != 0
    duplicate = json.dumps(record).replace(
        '"track_width_mm": 100.0', '"track_width_mm": 100.0, "track_width_mm": 80.0'
    )
    path.write_text(duplicate, encoding="utf-8")
    rejected = subprocess.run(
        [*cmd, "--planar-measurements", str(path)],
        capture_output=True, text=True,
    )
    assert rejected.returncode != 0
    assert "Duplicate planar measurement field" in rejected.stderr


def test_legacy_straight_drive_cli_remains_available():
    import json
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--mount-above-desk-mm", "20",
         "--tilt-deg", "0", "--sensor-ahead-of-wheel-mm", "45",
         "--measured-worst-stopping-mm", "10", "--latency-ms", "80",
         "--speed-mm-s", "100"],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(completed.stdout) == evaluate(
        chassis_mount_above_desk_mm=20.0
    )


def floor_mount_records():
    return [dict(r, lens_height_mm=32, tilt_deg=0, min_mm=30, max_mm=45)
            for r in tool.floor_mount_template()]


def test_individual_floor_mounts_never_certify_live_detection():
    result = tool.screen_floor_mounts(floor_mount_records())
    assert result["all_floor_mounts_possible_on_paper"]
    assert not result["live_sensor_detection_verified"]
    assert not result["fully_safe_cliff_operation_proven"]


@pytest.mark.parametrize("changes, reason", [
    ({"lens_height_mm": 20}, "floor_path_outside_configured_thresholds"),
    ({"tilt_deg": 77.5}, "invalid_mounting_angle"),
    ({"min_mm": 29}, "invalid_floor_thresholds"),
    ({"max_mm": 31}, "floor_path_outside_configured_thresholds"),
    ({"min_mm": 40, "max_mm": 35}, "invalid_floor_thresholds"),
    ({"lens_height_mm": True}, "invalid_lens_height"),
    ({"tilt_deg": 10**1000}, "invalid_mounting_angle"),
    ({"lens_height_mm": 1e308, "tilt_deg": 70}, "floor_path_overflow"),
])
def test_individual_floor_mount_failure_identifies_lane(changes, reason):
    records = floor_mount_records()
    records[2].update(changes)
    result = tool.screen_floor_mounts(records)
    assert not result["all_floor_mounts_possible_on_paper"]
    assert result["floor_sensor_checks"][2]["failures"] == [reason]
    assert all(result["floor_sensor_checks"][i]["mount_possible_on_paper"]
               for i in (0, 1, 3))


def test_floor_mount_missing_duplicate_and_nonfloor_channels():
    records = floor_mount_records()
    missing = tool.screen_floor_mounts(records[1:])
    assert missing["missing_floor_channels"] == [0]
    assert not missing["all_floor_mounts_possible_on_paper"]
    with pytest.raises(ValueError, match="Duplicate floor sensor channel 1"):
        tool.screen_floor_mounts(records + [records[1]])
    for invalid in (True, 4, 7, 0.0):
        with pytest.raises(ValueError, match="Invalid downward floor sensor channel"):
            tool.screen_floor_mounts([dict(records[0], channel=invalid)])


def test_floor_mount_cli_reports_individual_threshold_failure(tmp_path):
    import json
    import subprocess
    import sys

    cmd = [sys.executable, str(SCRIPT)]
    template = subprocess.run(
        [*cmd, "--floor-mount-template"], capture_output=True, text=True, check=True,
    )
    assert json.loads(template.stdout) == tool.floor_mount_template()
    records = floor_mount_records()
    records[3]["max_mm"] = 31
    path = tmp_path / "floor.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    result = subprocess.run(
        [*cmd, "--floor-mount-measurements", str(path)],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == tool.screen_floor_mounts(records)


@pytest.mark.parametrize("height, setback", [(35, 7.7593), (45, 9.9763), (55, 12.1932)])
def test_measured_lens_height_uses_no_adapter_offset(height, setback):
    result = evaluate(chassis_mount_above_desk_mm=None, measured_lens_above_desk_mm=height)
    assert result["lens_height_source"] == "measured_lens_input"
    assert result["nominal_optical_floor_path_mm"] == height
    assert result["rear_floor_return_setback_mm"] == pytest.approx(setback, abs=0.001)
    assert result["full_fov_floor_path_in_valid_range"]
    assert not result["sensor_mount_and_optical_alignment_physically_verified"]
    assert not result["40_sensor_fleet_purchase_approved"]


def test_measured_below_firmware_minimum_cannot_gain_adapter_offset():
    result = evaluate(chassis_mount_above_desk_mm=None, measured_lens_above_desk_mm=29.9)
    assert result["nominal_optical_floor_path_mm"] == 29.9
    assert not result["full_fov_floor_path_in_valid_range"]
    assert not result["candidate_geometry_possible_on_paper"]
    assert evaluate(chassis_mount_above_desk_mm=29.9)["candidate_geometry_possible_on_paper"]


@pytest.mark.parametrize("height", [0, -1, True, float("nan"), float("inf"), 10**1000])
def test_invalid_measured_lens_height_rejected(height):
    with pytest.raises(ValueError):
        evaluate(chassis_mount_above_desk_mm=None, measured_lens_above_desk_mm=height)


def test_lens_height_datum_is_exclusive():
    with pytest.raises(ValueError, match="exactly one"):
        evaluate(measured_lens_above_desk_mm=35)
    with pytest.raises(ValueError, match="exactly one"):
        evaluate(chassis_mount_above_desk_mm=None)
    legacy = evaluate(chassis_mount_above_desk_mm=20)
    assert legacy["lens_height_source"] == "nominal_adapter_offset"
    assert legacy["nominal_optical_floor_path_mm"] == 31.15


def test_measured_lens_cli_preserves_datum_and_rejects_conflicts():
    import json
    import subprocess
    import sys

    cmd = [sys.executable, str(SCRIPT), "--lens-above-desk-mm", "35",
           "--tilt-deg", "0", "--sensor-ahead-of-wheel-mm", "45",
           "--measured-worst-stopping-mm", "10", "--latency-ms", "80",
           "--speed-mm-s", "100"]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert json.loads(completed.stdout) == evaluate(
        chassis_mount_above_desk_mm=None, measured_lens_above_desk_mm=35)
    for conflicting in (["--mount-above-desk-mm", "20"], ["--planar-template"],
                        ["--floor-mount-template"]):
        rejected = subprocess.run([*cmd, *conflicting], capture_output=True, text=True)
        assert rejected.returncode == 2


@pytest.mark.parametrize("height, tilt, setback", [
    (31.15, 0, 6.9057887),
    (33.5, 0, 7.4267712),
    (31.15, 20, 19.8447386),
])
def test_unsigned_tilt_uses_worst_rearward_azimuth(height, tilt, setback):
    args = dict(chassis_mount_above_desk_mm=None,
                measured_lens_above_desk_mm=height, optical_tilt_deg=tilt)
    required = 28 + height * math.tan(math.radians(tilt + 12.5))
    result = evaluate(**args, leading_wheel_behind_sensor_mm=required)
    assert result["rear_floor_return_setback_mm"] == pytest.approx(setback, abs=0.001)
    assert result["required_wheel_behind_sensor_mm"] == pytest.approx(required)
    assert not result["candidate_geometry_possible_on_paper"]
    assert evaluate(**args, leading_wheel_behind_sensor_mm=required + 0.001)[
        "candidate_geometry_possible_on_paper"]
    assert not result["40_sensor_fleet_purchase_approved"]


def test_source_contract_follows_firmware_decoder(monkeypatch, tmp_path):
    decoder = tmp_path / "TofResult.h"
    source = tool.TOF_RESULT.read_text(encoding="utf-8")
    decoder.write_text(source.replace("distance >= 30U", "distance >= 31U"), encoding="utf-8")
    monkeypatch.setattr(tool, "TOF_RESULT", decoder)
    assert tool.verify_source_contract()["firmware_valid_min_mm"] == 31
    decoder.write_text(source.replace("distance <= 1300U", "distance <= 20U"), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid VL53L0X firmware range"):
        tool.verify_source_contract()


def test_source_contract_requires_live_decoder_call(monkeypatch, tmp_path):
    driver = tmp_path / "TofBus.cpp"
    source = tool.TOF.read_text(encoding="utf-8")
    driver.write_text(
        source.replace("decode_tof_result(result)", "other(result)"), encoding="utf-8",
    )
    monkeypatch.setattr(tool, "TOF", driver)
    with pytest.raises(ValueError, match="VL53L0X firmware decoder changed"):
        tool.verify_source_contract()


@pytest.mark.parametrize("speed, possible", [(219.0, True), (220.0, False)])
def test_measured_peak_speed_changes_33_5mm_lens_clearance(speed, possible):
    result = evaluate(chassis_mount_above_desk_mm=None, measured_lens_above_desk_mm=33.5,
                      measured_travel_speed_mm_s=speed)
    assert result["rear_floor_return_setback_mm"] == pytest.approx(7.4267712)
    assert result["required_wheel_behind_sensor_mm"] == pytest.approx(
        20 + 0.08 * speed + 33.5 * math.tan(math.radians(12.5))
    )
    assert result["candidate_geometry_possible_on_paper"] is possible
    assert not result["40_sensor_fleet_purchase_approved"]

@pytest.mark.parametrize("model", ["VL53L4CD", "VL6180X", "TCRT5000"])
@pytest.mark.parametrize("old", ["<VL53L0X.h>", "VL53L0X devices_"])
def test_source_contract_rejects_other_driver(monkeypatch, tmp_path, model, old):
    header = tmp_path / "TofBus.h"
    source = tool.TOF_HEADER.read_text(encoding="utf-8")
    header.write_text(source.replace(old, old.replace("VL53L0X", model)), encoding="utf-8")
    monkeypatch.setattr(tool, "TOF_HEADER", header)
    with pytest.raises(ValueError, match="VL53L0X driver identity changed"):
        tool.verify_source_contract()
