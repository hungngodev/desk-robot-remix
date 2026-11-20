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
    # Do not lock the fit check to the provisional 96 mm track example.
    # Measured robot widths must be able to change without disabling tests.
    source = SOURCE.read_text()
    def parameter(name):
        match = re.search(
            r"^" + re.escape(name) + r"\s*=\s*([0-9.]+)\s*;",
            source, re.M,
        )
        assert match is not None, name
        return float(match.group(1))

    width = parameter("track_outer_width_mm")
    clearance = parameter("side_clearance_each_mm")
    wall = parameter("guide_wall_mm")
    margin = parameter("wall_outside_margin_mm")
    flare = parameter("entry_flare_each_mm")
    base = parameter("base_thickness_mm")
    height = parameter("guide_height_mm")
    coupon_length = parameter("entry_coupon_length_mm")
    inner_x = wall + margin
    outside = width + 2 * clearance + 2 * inner_x
    assert all(abs(a - b) < 0.01 for a, b in zip(
        lows, (0, 0, 0), strict=True,
    ))
    assert all(abs(a - b) < 0.01 for a, b in zip(
        highs, (outside, coupon_length, base + height), strict=True,
    ))
    # At y=0 both inner guide faces flare OUTWARD. Beyond the flare,
    # each wall must have its original thickness and measured clearance.
    for y, left_inner in (
        (0, inner_x - wall - flare),
        (37, inner_x - wall),
    ):
        expected = [
            left_inner,
            left_inner + wall,
            outside - left_inner - wall,
            outside - left_inner,
        ]
        xs = sorted({
            round(x, 3) for x, yy, z in points
            if abs(yy - y) < 0.001 and z > base + 0.001
        })
        assert len(xs) == 4
        assert all(abs(a - b) < 0.01 for a, b in zip(
            xs, expected, strict=True,
        ))
        assert abs((xs[2] - xs[1]) - (
            width + 2 * clearance + (2 * flare if y == 0 else 0)
        )) < 0.01


def test_real_track_measurement_override_preserves_rail_clearance(tmp_path):
    """A custom measured track width changes the guide, not rail thickness."""
    import shutil
    import struct
    import subprocess

    import pytest

    executable = shutil.which("openscad")
    if executable is None:
        pytest.skip("OpenSCAD not installed")
    output = tmp_path / "measured_track_entry.stl"
    subprocess.run([
        executable, "--export-format", "binstl", "-o", str(output),
        "-D", 'part="dock_rail_entry_coupon"',
        "-D", "track_outer_width_mm=112", str(SOURCE),
    ], check=True, capture_output=True, text=True, timeout=180)
    blob = output.read_bytes()
    faces = struct.unpack_from("<I", blob, 80)[0]
    assert len(blob) == 84 + faces * 50
    points = [
        struct.unpack_from("<fff", blob, 84 + i * 50 + 12 + j * 12)
        for i in range(faces) for j in range(3)
    ]
    assert max(p[0] for p in points) == 142
    for y, expected in ((0, (1, 6, 136, 141)),
                        (37, (8, 13, 129, 134))):
        xs = sorted({
            round(x, 3) for x, yy, z in points
            if abs(yy - y) < .001 and z > 3.001
        })
        assert xs == list(expected)
    # Measured 112 mm tracks + 2 mm each side gives 116 mm straight opening.
    assert 129 - 13 == 116
