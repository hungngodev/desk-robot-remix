"""Keep the passive seating screen tied to the actual CAD construction."""

import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CAD = ROOT / "docs/cad/remixes/dock/dock_passive_fit.scad"
SCRIPT = ROOT / "code/scripts/screen_dock_seat_mechanics.py"


def _geometry_reader():
    spec = importlib.util.spec_from_file_location("screen_dock_seat", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.dock_constants


def test_nominal_and_parameterized_stop_primitives_are_supported(tmp_path):
    source = CAD.read_text(encoding="utf-8")
    read_geometry = _geometry_reader()
    nominal = read_geometry(CAD)
    assert nominal["backstop_front_y_mm"] == 133
    assert nominal["backstop_brace_front_y_mm"] == 125
    assert nominal["source_sha256"] == hashlib.sha256(CAD.read_bytes()).hexdigest()

    original = "backstop_brace_depth_mm = 8;"
    assert source.count(original) == 1
    changed = tmp_path / "dock.scad"
    changed.write_text(source.replace(original, "backstop_brace_depth_mm = 9;"), encoding="utf-8")
    assert read_geometry(changed) == {
        **nominal,
        "backstop_brace_front_y_mm": 124,
        "source_sha256": hashlib.sha256(changed.read_bytes()).hexdigest(),
    }


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
        ("[inner_wall_x, guide_run_mm]",
         "[inner_wall_x+1, guide_run_mm]", "rail profile"),
        ("d=ir_probe_bore_d_mm);", "d=ir_probe_bore_d_mm+1);", "IR coupon aperture"),
    ],
)
def test_cad_primitives_cannot_drift_while_parameters_stay_unchanged(
    tmp_path, original, replacement, primitive,
):
    source = CAD.read_text(encoding="utf-8")
    assert source.count(original) == 1
    changed = tmp_path / "dock.scad"
    changed.write_text(source.replace(original, replacement), encoding="utf-8")
    with pytest.raises(ValueError, match=f"^Missing or changed dock CAD primitive: {primitive}$"):
        _geometry_reader()(changed)


@pytest.mark.parametrize("decoy", ["line comment", "block comment", "string", "duplicate"])
def test_backstop_requires_exactly_one_active_primitive(tmp_path, decoy):
    source = CAD.read_text(encoding="utf-8")
    original = (
        "translate([0,backstop_front_y_mm,base_thickness_mm])\n"
        "                cube([outside_width_mm,backstop_thickness_mm,backstop_height_mm]);"
    )
    assert source.count(original) == 1
    if decoy == "line comment":
        replacement = "\n".join("// " + line for line in original.splitlines())
    elif decoy == "block comment":
        replacement = f"/* {original} */"
    elif decoy == "string":
        single_line = " ".join(original.splitlines())
        replacement = f'echo("{single_line}");'
    else:
        replacement = f"{original}\n{original}"
    changed = tmp_path / "dock.scad"
    changed.write_text(source.replace(original, replacement), encoding="utf-8")
    with pytest.raises(ValueError, match="^Missing or changed dock CAD primitive: backstop$"):
        _geometry_reader()(changed)
