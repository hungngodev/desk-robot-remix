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
        "contact_cad_source_sha256": tool.contact_constants()["source_sha256"],
        "seat_pair_spacing_mm": 98,
        # Synthetic candidate floor location, NOT an actual pogo contact.
        "contact_center_y_mm": 116,
        "robot_underside_z_at_stop_mm": 15,
        "required_contact_top_gap_mm": 2,
        **{
            f"{side}_{key}": value
            for side in ("left", "right")
            for key, value in {
                "switch_body_width_mm": 10,
                "switch_body_height_mm": 8,
                "switch_center_z_mm": 24,
                "ir_emitter_center_z_mm": 70,
                "operating_displacement_mm": 1.5,
                "planned_stop_displacement_mm": 2.0,
                "safe_total_displacement_mm": 2.5,
                "required_travel_reserve_mm": 0.2,
            }.items()
        },
    }


def test_source_cad_fixture_trial_cannot_approve_physical_dock():
    result = load().screen(example())
    assert result["source_only_layout_possible"]
    assert result["switch_pair_separately_located"]
    assert result["stop_displacement_inside_measured_travel"]
    assert result["ir_emitter_aperture_inside_backstop"]
    assert result["contact_floor_layout_possible"]
    assert result["unpowered_contact_floor_layout"][
        "physical_contact_mate_verified"
    ] is False
    assert result["unpowered_contact_floor_layout"][
        "electrical_contact_selected"
    ] is False
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
    ("left_switch_body_width_mm", 30),
    ("right_switch_center_z_mm", 89),
    ("left_ir_emitter_center_z_mm", 24),
    ("right_ir_emitter_center_z_mm", 110),
    ("left_planned_stop_displacement_mm", 2.5),
    ("right_required_travel_reserve_mm", 0.6),
    ("right_planned_stop_displacement_mm", 1.0),
    ("left_planned_stop_displacement_mm", 3.0),
    ("right_safe_total_displacement_mm", 1.6),
    ("contact_center_y_mm", 132),
    ("robot_underside_z_at_stop_mm", 10),
    ("required_contact_top_gap_mm", 1),
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
    ("left_switch_body_height_mm", True),
    ("right_switch_body_width_mm", 10**1000),
    ("left_switch_body_width_mm", float("nan")),
    ("right_switch_center_z_mm", -1),
    ("left_switch_center_z_mm", float("inf")),
    ("seat_pair_spacing_mm", None),
    ("contact_center_y_mm", 10**1000),
    ("required_contact_top_gap_mm", False),
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
    data["contact_cad_source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Stale unpowered contact"):
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
    assert g["backstop_front_y_mm"] == 133
    assert g["clear_channel_x_min_mm"] == 13
    assert g["clear_channel_x_max_mm"] == 113
    cg = load().contact_constants()
    assert cg["carrier_length_mm"] == 54
    assert cg["carrier_depth_mm"] == 25
    assert cg["carrier_height_mm"] == 9
    assert cg["electrical_contact_selected"] is False


def test_independent_right_switch_measurements_cannot_inherit_left_pass():
    source = load()
    datum = example()
    datum["right_switch_body_width_mm"] = 12
    good = source.screen(datum)
    assert good["source_only_layout_possible"]
    assert good["switches"][0]["source_body_x_mm"] == [9.0, 19.0]
    assert good["switches"][1]["source_body_x_mm"] == [106.0, 118.0]
    assert all(side["stop_displacement_inside_measured_travel"]
               for side in good["switches"])
    datum["right_safe_total_displacement_mm"] = 1.7
    bad = source.screen(datum)
    assert bad["switches"][0]["stop_displacement_inside_measured_travel"]
    assert not bad["switches"][1]["stop_displacement_inside_measured_travel"]
    assert not bad["source_only_layout_possible"]
    assert not bad["charging_authorized"]


def test_contact_floor_position_is_checked_against_source_geometry():
    result = load().screen(example())
    carrier = result["unpowered_contact_floor_layout"]
    assert carrier["source_carrier_x_mm"] == [36.0, 90.0]
    assert carrier["source_carrier_y_mm"] == [103.5, 128.5]
    assert carrier["source_carrier_top_z_mm"] == 12
    assert carrier["inside_clear_channel_with_2mm_margin"]
    assert carrier["ahead_of_backstop_with_2mm_margin"]
    assert carrier["under_measured_robot_with_required_gap"]
    assert not carrier["physical_contact_mate_verified"]


def test_contact_carrier_measured_floor_changes_do_not_grant_charge():
    source = load()
    data = example()
    data["contact_center_y_mm"] = 128
    bad_backstop = source.screen(data)
    assert not bad_backstop["contact_floor_layout_possible"]
    assert not bad_backstop["charging_authorized"]
    data = example()
    data["robot_underside_z_at_stop_mm"] = 13
    unsafe_height = source.screen(data)
    assert not unsafe_height["source_only_layout_possible"]
    assert not unsafe_height["contact_floor_layout_possible"]
    data = example()
    data["required_contact_top_gap_mm"] = 2.5
    safe = source.screen(data)
    assert safe["contact_floor_layout_possible"]
    assert not safe["charging_authorized"]
    assert not safe["unpowered_contact_floor_layout"][
        "electrical_contact_selected"
    ]


def test_contact_carrier_source_revision_or_dimensions_cannot_drift(tmp_path):
    source = load()
    old = source.CONTACT_CAD.read_text(encoding="utf-8")
    fake = tmp_path / "changed.scad"
    fake.write_text(old + "\n// changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Stale unpowered contact"):
        source.screen(example(), contact_cad=fake)
    fake.write_text(
        old.replace("contact_carrier_l = 54;",
                    "contact_carrier_l = 900;"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid unpowered contact"):
        source.contact_constants(fake)


def test_unpowered_contact_coupon_datum_parser_reads_current_source():
    """The source CSV style SCAD numbers must parse, not silently use a fallback."""
    source = load()
    constants = source.contact_constants()
    assert constants["carrier_length_mm"] == 54
    assert constants["carrier_depth_mm"] == 25
    assert constants["carrier_height_mm"] == 9
    assert len(constants["source_sha256"]) == 64
    assert constants["electrical_contact_selected"] is False


def test_source_pinned_blank_template_cannot_pass_as_measurement():
    source = load()
    form = source.blank_template(1)
    assert form["dock_id"] == 1
    assert form["cad_source_sha256"] == source.dock_constants()[
        "source_sha256"
    ]
    assert form["contact_cad_source_sha256"] == source.contact_constants()[
        "source_sha256"
    ]
    assert all(form[field] is None for field in source.NUMERICS)
    with pytest.raises(ValueError, match="finite measured"):
        source.screen(form)


def test_dock_template_cli_refuses_to_replace_previous_evidence(tmp_path):
    import subprocess
    import sys

    output = tmp_path / "dock01_measurements.json"
    cmd = [
        sys.executable, str(SCRIPT), "--template-for-dock", "1",
        "--output", str(output),
    ]
    ok = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert ok.returncode == 0, ok.stderr
    original = output.read_text(encoding="utf-8")
    import json

    form = json.loads(original)
    assert form == load().blank_template(1)
    refused = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert refused.returncode != 0
    assert "FileExistsError" in refused.stderr
    assert output.read_text(encoding="utf-8") == original
    rejected = subprocess.run(
        [sys.executable, str(SCRIPT), "--measurements", str(output)],
        capture_output=True, text=True, timeout=10,
    )
    assert rejected.returncode != 0
    assert "finite measured" in rejected.stderr
