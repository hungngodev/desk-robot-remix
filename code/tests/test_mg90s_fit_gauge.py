"""Physical MG90S fit coupons must reject misleading printable geometry."""
from pathlib import Path
from struct import unpack_from
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCAD = ROOT / "docs/cad/remixes/mg90s_pocket_fit_gauges.scad"


@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs OpenSCAD CLI")
def test_nominal_mg90s_four_cups_preserve_printable_bounds(tmp_path):
    output = tmp_path / "mg90s_four_cups.stl"
    result = subprocess.run([
        "openscad", "--export-format", "binstl",
        "-o", str(output), str(SCAD),
    ], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    blob = output.read_bytes()
    count = unpack_from("<I", blob, 80)[0]
    assert count > 0 and len(blob) == 84 + count * 50
    vertices = [
        unpack_from("<fff", blob, 84 + 50 * i + 12 + corner * 12)
        for i in range(count) for corner in range(3)
    ]
    bounds = tuple(
        round(max(p[axis] for p in vertices) -
              min(p[axis] for p in vertices), 2)
        for axis in range(3)
    )
    assert bounds == (136.0, 17.2, 8.0)


@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs OpenSCAD CLI")
@pytest.mark.parametrize("override,reason", [
    ("clearances_mm=[1.2]", "insufficient printable wall"),
    ("clearances_mm=[0.15,-0.30,0.45,0.6]", "positive"),
    ("clearances_mm=[0.15,0.30,0.45,1.6]", "positive"),
    ("spacing_mm=0", "printable separation"),
    ("total_height_mm=2.1", "Assertion"),
    ("wall_mm=2", "insufficient printable wall"),
])
def test_mg90s_invalid_overrides_cannot_print_misleading_coupons(
    tmp_path, override, reason,
):
    output = tmp_path / "bad.stl"
    result = subprocess.run([
        "openscad", "--export-format", "binstl", "-o", str(output),
        "-D", override, str(SCAD),
    ], capture_output=True, text=True, timeout=120)
    assert result.returncode != 0
    assert reason in result.stderr + result.stdout
