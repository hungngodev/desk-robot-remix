"""Source-level invariants for the unpowered passive docking fit coupon.

These checks do not qualify printed dimensions or powered charging.
"""
import re
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[2]
    / "docs/cad/remixes/dock/dock_passive_fit.scad"
)


def test_dock_rail_preserves_selected_straight_channel_and_entry_flare():
    source = SOURCE.read_text()
    def value(name):
        match = re.search(r"^" + re.escape(name) + r"\s*=\s*([0-9.]+)\s*;", source, re.M)
        assert match is not None, name
        return float(match.group(1))

    track = value("track_outer_width_mm")
    clearance = value("side_clearance_each_mm")
    wall = value("guide_wall_mm")
    margin = value("wall_outside_margin_mm")
    flare = value("entry_flare_each_mm")
    assert wall > 0 and margin >= flare
    channel = track + 2 * clearance
    inner_x = wall + margin
    outside = channel + 2 * inner_x
    # Geometric clearance is between opposing rail INNER faces.
    assert abs((outside - 2 * inner_x) - channel) < 1e-6
    # At y=0 both rail faces shift OUTWARD equally, preserving wall thickness.
    assert "[inner_wall_x - guide_wall_mm - entry_flare_each_mm, 0]" in source
    assert "[inner_wall_x - entry_flare_each_mm, 0]" in source
    assert "[inner_wall_x, 37]" in source
    assert "[inner_wall_x - guide_wall_mm, 37]" in source
    assert (outside - 2 * (inner_x - flare)) > channel
    assert "intersection()" in source
    assert "dock_rail_entry_coupon()" in source


def test_dock_geometry_remains_explicitly_passive():
    source = SOURCE.read_text()
    assert "never an energized charging cradle" in source
    assert "Nominal dimensions are an example, not measured robot fit" in source
    assert "no AprilTag, stop or charging contacts" in source


def test_dock_mesh_clearances_with_openscad(tmp_path):
    """Measure actual exported triangles, not only matching SCAD expressions."""
    import shutil
    import struct
    import subprocess
    import pytest

    openscad = shutil.which("openscad")
    if not openscad:
        pytest.skip("OpenSCAD not installed on this runner")
    target = tmp_path / "entry.stl"
    subprocess.run(
        [openscad, "--export-format", "binstl", "-o", str(target),
         "-D", 'part="dock_rail_entry_coupon"', str(SOURCE)],
        check=True, capture_output=True, text=True, timeout=180,
    )
    data = target.read_bytes()
    count = struct.unpack_from("<I", data, 80)[0]
    assert count > 0 and len(data) == 84 + 50 * count
    points = [
        struct.unpack_from("<fff", data, 84 + 50 * i + 12 + 12 * corner)
        for i in range(count)
        for corner in range(3)
    ]
    lows = [min(vertex[axis] for vertex in points) for axis in range(3)]
    highs = [max(vertex[axis] for vertex in points) for axis in range(3)]
    assert lows == [0, 0, 0]
    assert highs == [126, 48, 15]
    # Above the base, the left and right rails must form a 114 mm
    # entry mouth and a 100 mm straight travel channel at the taper end.
    for y, expected_x in (
        (0, [1, 6, 120, 125]),
        (37, [8, 13, 113, 118]),
    ):
        xs = sorted({
            round(x, 3) for x, yy, z in points
            if abs(yy - y) < 0.001 and z > 3.001
        })
        assert xs == expected_x
    assert 120 - 6 == 114
    assert 113 - 13 == 100
