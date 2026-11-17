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
                remaining_vision_or_sensor_latency_ms=80.0,
                measured_travel_speed_mm_s=100.0)
    args.update(updates)
    return tool.evaluate(**args)


def test_exact_source_bracket_lens_is_below_minimum_if_mount_flush_to_desk():
    source = tool.verify_source_contract()
    assert source["lens_center_above_adapter_mount_mm"] == 13.5
    assert source["firmware_valid_min_mm"] == 30
    assert source["firmware_valid_max_mm"] == 1300
    low = evaluate()
    assert low["nominal_optical_floor_path_mm"] == 13.5
    assert not low["nominal_floor_in_firmware_valid_range"]
    assert not low["candidate_geometry_possible_on_paper"]
    assert not low["40_sensor_fleet_purchase_approved"]


def test_properly_raised_sensor_can_be_feasible_but_not_qualified():
    r = evaluate(chassis_mount_above_desk_mm=20.0)
    assert r["nominal_optical_floor_path_mm"] == 33.5
    assert r["nominal_floor_in_firmware_valid_range"]
    assert r["required_wheel_behind_sensor_mm"] == 28.0
    assert r["nominal_stopping_geometry_possible"]
    assert r["candidate_geometry_possible_on_paper"]
    assert not r["actual_dark_glossy_surface_and_edge_trials"]
    assert not r["sensor_mount_and_optical_alignment_physically_verified"]
    assert not r["40_sensor_fleet_purchase_approved"]


def test_late_braking_fails_even_with_feasible_lens_height():
    r = evaluate(chassis_mount_above_desk_mm=20.0,
                 measured_p95_stopping_distance_mm=40)
    assert r["nominal_floor_in_firmware_valid_range"]
    assert not r["nominal_stopping_geometry_possible"]
    assert not r["candidate_geometry_possible_on_paper"]


@pytest.mark.parametrize("kwargs", [
    {"chassis_mount_above_desk_mm": float("nan")},
    {"chassis_mount_above_desk_mm": True},
    {"chassis_mount_above_desk_mm": -1},
    {"optical_tilt_deg": 90},
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
