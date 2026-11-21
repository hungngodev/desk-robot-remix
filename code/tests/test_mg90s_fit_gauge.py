"""Physical MG90S fit coupons must reject misleading printable geometry."""
import importlib.util
import shutil
import subprocess
from pathlib import Path
from struct import unpack_from

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
    assert bounds == (136.0, 17.8, 8.0)


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


@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs OpenSCAD CLI")
@pytest.mark.parametrize("part,mark_count,clearance_mm", [
    ("mg90s_fit_015", 1, 0.15),
    ("mg90s_fit_030", 2, 0.30),
    ("mg90s_fit_045", 3, 0.45),
    ("mg90s_fit_060", 4, 0.60),
])
def test_named_mg90s_coupons_have_integral_clearance_ticks(
    tmp_path, part, mark_count, clearance_mm,
):
    """Printed cups remain identifiable after separation from STL filenames."""
    output = tmp_path / (part + ".stl")
    result = subprocess.run([
        "openscad", "--export-format", "binstl", "-o", str(output),
        "-D", f'part="{part}"', str(SCAD),
    ], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    blob = output.read_bytes()
    triangles = unpack_from("<I", blob, 80)[0]
    assert triangles > 0 and len(blob) == 84 + triangles * 50
    vertices = [
        unpack_from("<fff", blob, 84 + 50 * i + 12 + corner * 12)
        for i in range(triangles) for corner in range(3)
    ]
    bounds = tuple(
        round(max(p[axis] for p in vertices) -
              min(p[axis] for p in vertices), 2)
        for axis in range(3)
    )
    # No extra bottom mass or pocket enlargement. Only the external
    # identification ticks protrude 0.6 mm beyond the original Y wall.
    assert bounds == (28.0, 17.8, 8.0)
    marked_edges = sorted({
        round(x, 2) for x, y, _ in vertices if abs(y + 0.6) < 0.002
    })
    expected = sorted(
        round(4 + 2.45 * tick + edge, 2)
        for tick in range(mark_count) for edge in (0, 1.5)
    )
    assert marked_edges == expected
    pocket_offset = 2.5 - clearance_mm / 2
    assert any(
        abs(x - pocket_offset) < 0.002 and
        abs(y - pocket_offset) < 0.002 and
        abs(z - 2.0) < 0.002
        for x, y, z in vertices
    )
    # The protrusions must fuse to the cup rather than creating loose
    # separate islands which the printer could silently omit.
    verifier = ROOT / "code/scripts/export_fit_kit.py"
    spec = importlib.util.spec_from_file_location("mg90s_fit_verifier", verifier)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.closed_mesh_edges(output) > 0
