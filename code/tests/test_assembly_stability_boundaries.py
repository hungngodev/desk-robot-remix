"""Analytic synthetic fixtures, not measured first robot geometry."""
import importlib.util
import math
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/screen_assembly_stability.py"
SPEC = importlib.util.spec_from_file_location("stability_boundaries", SCRIPT)
stability = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stability)


def record(half_track=30, head_mass=100, roll=0, pitch=0):
    data = stability.blank_template()
    data.update(required_static_edge_margin_mm=10, max_roll_deg=roll, max_pitch_deg=pitch)
    for pose in data["poses"]:
        pose["support_contacts_mm"] = [
            [-45, -half_track], [45, -half_track], [45, half_track], [-45, half_track],
        ]
        for part in pose["components"]:
            role = part["id"]
            part.update(mass_g=100, com_mm=[0, 0, 10])
            if role == "head_and_sense":
                part.update(mass_g=head_mass, com_mm=[0, 0, 100])
            if role == "payload" and pose["name"] in {"stowed_empty", "docked_stopped"}:
                part["mass_g"] = 0
    return data


@pytest.mark.parametrize("half_track,expected", [(9.9996, False), (10, True), (10.0004, True)])
def test_lateral_track_reserve_uses_unrounded_inclusive_boundary(half_track, expected):
    report = stability.screen(record(half_track=half_track))
    assert report["necessary_stability_on_paper"] is expected
    for pose in report["poses"]:
        assert pose["worst_tilt_static_margin_mm"] == 10
        assert pose["necessary_static_margin_on_paper"] is expected
    assert report["assembly_print_or_purchase_approved"] is False


@pytest.mark.parametrize("head_mass,expected_z,expected", [(100, 28, True), (500, 60, False)])
def test_head_mass_changes_roll_reserve_without_moving_fixed_head(head_mass, expected_z, expected):
    report = stability.screen(record(head_mass=head_mass, roll=20))
    stowed = next(p for p in report["poses"] if p["name"] == "stowed_empty")
    assert stowed["source_center_of_mass_mm"] == [0, 0, expected_z]
    # A centered rectangular base tips around the lateral edge; the requested
    # reserve is consumed before the gravity line actually leaves the base.
    expected_margin = 30 - expected_z * math.tan(math.radians(20))
    assert stowed["worst_tilt_static_margin_mm"] == pytest.approx(expected_margin, abs=0.0005)
    assert stowed["necessary_static_margin_on_paper"] is expected
    assert report["necessary_stability_on_paper"] is expected
    assert report["loaded_dynamic_turn_and_braking_stability_verified"] is False


@pytest.mark.parametrize("direction", [-1, 1])
def test_extended_jaw_and_payload_together_consume_longitudinal_reserve(direction):
    data = record()
    key = next(p for p in data["poses"] if p["name"] == "key_grasp_extended")
    for part in key["components"]:
        if part["id"] == "lift_and_gripper":
            part["com_mm"][0] = direction * 100
        if part["id"] == "payload":
            part["com_mm"][0] = direction * 140
    report = stability.screen(data)
    poses = {p["name"]: p for p in report["poses"]}
    assert poses["key_grasp_extended"]["source_center_of_mass_mm"][0] == direction * 40
    assert poses["key_grasp_extended"]["worst_tilt_static_margin_mm"] == 5
    assert poses["key_grasp_extended"]["necessary_static_margin_on_paper"] is False
    assert poses["stowed_empty"]["necessary_static_margin_on_paper"] is True
    assert report["necessary_stability_on_paper"] is False
    assert report["cliff_stop_and_motor_authorized"] is False
