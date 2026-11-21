"""No nominal seat switch carrier may silently authorize dock charging."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "code/scripts/screen_dock_seat_mechanics.py"


def load():
    spec = importlib.util.spec_from_file_location("screen_dock_seat", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def example():
    tool = load()
    source = tool.dock_constants()
    return {
        "dock_id": 1,
        "cad_source_sha256": source["source_sha256"],
        "seat_pair_spacing_mm": 98,
        "switch_body_width_mm": 10,
        "switch_body_height_mm": 8,
        "switch_center_z_mm": 24,
        "ir_emitter_center_z_mm": 70,
        "operating_displacement_mm": 1.5,
        "planned_stop_displacement_mm": 2.0,
        "safe_total_displacement_mm": 2.5,
        "required_travel_reserve_mm": 0.2,
    }


def test_source_cad_fixture_trial_cannot_approve_physical_dock():
    result = load().screen(example())
    assert result["source_only_layout_possible"]
    assert result["switch_pair_separately_located"]
    assert result["stop_displacement_inside_measured_travel"]
    assert result["ir_emitter_aperture_inside_backstop"]
    assert len(result["switches"]) == 2
    assert all(s["within_backstop_with_2mm_web"] for s in result["switches"])
    assert all(s["avoids_apriltag_paper_with_2mm_gap"] for s in result["switches"])
    assert all(s["avoids_nominal_ir_hole_with_2mm_gap"]
               for s in result["switches"])
    for forbidden in (
        "normally_closed_polarity_physically_tested",
        "switch_bounce_and_faults_physically_tested",
        "actual_carrier_depth_and_wire_clearance_tested",
        "physical_dock_seating_qualified", "charging_authorized",
    ):
        assert result[forbidden] is False


@pytest.mark.parametrize("field,value", [
    ("seat_pair_spacing_mm", 55),
    ("switch_body_width_mm", 30),
    ("switch_center_z_mm", 89),
    ("ir_emitter_center_z_mm", 24),
    ("ir_emitter_center_z_mm", 110),
    ("planned_stop_displacement_mm", 2.5),
    ("required_travel_reserve_mm", 0.6),
    ("planned_stop_displacement_mm", 1.0),
    ("planned_stop_displacement_mm", 3.0),
    ("safe_total_displacement_mm", 1.6),
])
def test_interference_or_overtravel_is_rejected_on_paper(field, value):
    datum = example()
    datum[field] = value
    result = load().screen(datum)
    assert not result["source_only_layout_possible"]
    assert not result["charging_authorized"]


@pytest.mark.parametrize("field,value", [
    ("dock_id", 6),
    ("dock_id", True),
    ("switch_body_height_mm", True),
    ("switch_body_width_mm", 10**1000),
    ("switch_body_width_mm", float("nan")),
    ("switch_center_z_mm", -1),
    ("switch_center_z_mm", float("inf")),
    ("seat_pair_spacing_mm", None),
])
def test_bad_measured_switch_inputs_fail_closed(field, value):
    data = example()
    data[field] = value
    with pytest.raises(ValueError):
        load().screen(data)


def test_stale_source_revision_and_unexpected_measurement_rejected(tmp_path):
    data = example()
    data["cad_source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Stale dock CAD"):
        load().screen(data)
    data = example()
    data["guessed_clearance_mm"] = 6
    with pytest.raises(ValueError, match="missing or unexpected"):
        load().screen(data)
    wrong = tmp_path / "copied.scad"
    wrong.write_bytes(load().CAD.read_bytes() + b"\n// changed source\n")
    with pytest.raises(ValueError, match="Stale dock CAD"):
        load().screen(example(), cad=wrong)


def test_printer_source_and_switch_screen_share_real_pocket_width():
    g = load().dock_constants()
    assert g["backstop_width_mm"] == 126
    assert g["tag_paper_x_min_mm"] == pytest.approx(27.4)
    assert g["tag_paper_x_max_mm"] == pytest.approx(98.6)
    assert g["ir_pair_spacing_mm"] == 98
    assert g["ir_hole_radius_mm"] == 2.75
