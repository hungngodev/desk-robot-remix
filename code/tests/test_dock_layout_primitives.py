"""Source-pinned dock paper geometry must follow the printable primitives."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "code/scripts/screen_dock_seat_mechanics.py"


def load():
    spec = importlib.util.spec_from_file_location("dock_layout", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("old,new", [
    ("[inner_wall_x, entry_flare_run_mm]", "[inner_wall_x, 40]"),
    ("[inner_wall_x - guide_wall_mm, entry_flare_run_mm]",
     "[inner_wall_x - guide_wall_mm, 40]"),
    ("translate([x, ir_coupon_height_mm/2, -0.1])",
     "translate([x, ir_coupon_height_mm/2 + 1, -0.1])"),
    ("d=ir_probe_bore_d_mm);", "d=ir_probe_bore_d_mm + 1);"),
])
def test_changed_printable_primitives_are_not_silently_screened(tmp_path, old, new):
    tool = load()
    raw = tool.CAD.read_text(encoding="utf-8")
    assert raw.count(old) == 1
    changed = tmp_path / "drift.scad"
    changed.write_text(raw.replace(old, new), encoding="utf-8")
    with pytest.raises(ValueError, match="Missing or changed dock CAD primitive"):
        tool.dock_constants(changed)


def test_nominal_funnel_and_flat_coupon_datums():
    g = load().dock_constants()
    assert g["entry_flare_half_angle_deg"] == pytest.approx(10.713123, abs=1e-5)
    assert g["ir_coupon_center_y_mm"] == 8
