"""Keep the passive seating screen tied to the actual CAD construction."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CAD = ROOT / "docs/cad/remixes/dock/dock_passive_fit.scad"
SCRIPT = ROOT / "code/scripts/screen_dock_seat_mechanics.py"


def _validator():
    spec = importlib.util.spec_from_file_location("screen_dock_seat", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._require_dock_layout_primitives


def test_nominal_and_parameterized_stop_primitives_are_supported():
    source = CAD.read_text(encoding="utf-8")
    validate = _validator()
    validate(source)
    validate(source.replace("backstop_brace_depth_mm = 8;", "backstop_brace_depth_mm = 9;"))


@pytest.mark.parametrize(
    "original,replacement,primitive",
    [
        ("translate([0,backstop_front_y_mm,base_thickness_mm])",
         "translate([0,backstop_front_y_mm-1,base_thickness_mm])", "backstop"),
        ("translate([0,backstop_brace_front_y_mm,base_thickness_mm])",
         "translate([0,backstop_brace_front_y_mm-1,base_thickness_mm])", "brace"),
        ("cube([outside_width_mm,backstop_brace_depth_mm,backstop_brace_height_mm]);",
         "cube([outside_width_mm,backstop_brace_depth_mm,backstop_brace_height_mm+3]);",
         "brace"),
        ("translate([outside_width_mm,0,base_thickness_mm])",
         "translate([outside_width_mm-1,0,base_thickness_mm])", "rail assembly"),
        ("cube([outside_width_mm, base_length_mm, base_thickness_mm]);",
         "cube([outside_width_mm, base_length_mm, base_thickness_mm+1]);",
         "rail assembly"),
    ],
)
def test_cad_primitives_cannot_drift_while_parameters_stay_unchanged(
    original, replacement, primitive,
):
    source = CAD.read_text(encoding="utf-8")
    assert source.count(original) == 1
    changed = source.replace(original, replacement)
    with pytest.raises(ValueError, match=f"Missing or changed dock CAD primitive: {primitive}"):
        _validator()(changed)
