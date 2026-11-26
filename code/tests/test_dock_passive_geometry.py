"""Source-level invariants for the unpowered passive docking fit coupon.

These checks do not qualify printed dimensions or powered charging.
"""
import re
from pathlib import Path

import pytest

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
    assert (0 < value("entry_flare_run_mm") < value("entry_coupon_length_mm")
            < value("guide_run_mm"))
    assert "[inner_wall_x, entry_flare_run_mm]" in source
    assert "[inner_wall_x - guide_wall_mm, entry_flare_run_mm]" in source
    assert (outside - 2 * (inner_x - flare)) > channel
    assert "intersection()" in source
    assert "dock_rail_entry_coupon()" in source


def test_dock_geometry_remains_explicitly_passive():
    source = SOURCE.read_text()
    assert "never an energized charging cradle" in source
    assert "Nominal dimensions are an example, not measured robot fit" in source
    assert "no AprilTag, stop or charging contacts" in source


@pytest.mark.parametrize("flare_run_override", [None, 37.5, 20])
def test_dock_mesh_clearances_with_openscad(tmp_path, flare_run_override):
    """Measure actual exported triangles, not only matching SCAD expressions."""
    import shutil
    import struct
    import subprocess

    openscad = shutil.which("openscad")
    if not openscad:
        pytest.skip("OpenSCAD not installed on this runner")
    source = SOURCE.read_text()
    cad = SOURCE
    if flare_run_override is not None:
        source, replacements = re.subn(
            r"^entry_flare_run_mm\s*=\s*[0-9.]+\s*;",
            f"entry_flare_run_mm = {flare_run_override};", source, flags=re.M,
        )
        assert replacements == 1
        cad = tmp_path / "changed_entry.scad"
        cad.write_text(source, encoding="utf-8")
    target = tmp_path / "entry.stl"
    subprocess.run(
        [openscad, "--export-format", "binstl", "-o", str(target),
         "-D", 'part="dock_rail_entry_coupon"', str(cad)],
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
    flare_run = parameter("entry_flare_run_mm")
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
        (flare_run, inner_x - wall),
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
    source = SOURCE.read_text()
    def value(name):
        match = re.search(r"^" + re.escape(name) + r"\s*=\s*([0-9.]+)\s*;", source, re.M)
        assert match is not None, name
        return float(match.group(1))

    clearance = value("side_clearance_each_mm")
    wall = value("guide_wall_mm")
    margin = value("wall_outside_margin_mm")
    flare = value("entry_flare_each_mm")
    flare_run = value("entry_flare_run_mm")
    base = value("base_thickness_mm")
    channel = 112 + 2 * clearance
    inner_x = wall + margin
    outside = channel + 2 * inner_x
    assert max(p[0] for p in points) == pytest.approx(outside, abs=0.01)
    for y, left_outer in ((0, margin - flare), (flare_run, margin)):
        expected = (left_outer, left_outer + wall,
                    outside - left_outer - wall, outside - left_outer)
        xs = sorted({
            round(x, 3) for x, yy, z in points
            if abs(yy - y) < .001 and z > base + .001
        })
        assert xs == pytest.approx(expected, abs=0.01)
        # A wider entry is not the final seated lateral clearance.
        assert xs[2] - xs[1] == pytest.approx(
            channel + (2 * flare if y == 0 else 0), abs=0.01,
        )


def test_passive_dock_beacon_pair_coupon_preserves_tag_quiet_zone(tmp_path):
    """Real STL triangles prove two open, symmetric unpowered trial holes."""
    import shutil
    import struct
    import subprocess

    openscad = shutil.which("openscad")
    if openscad is None:
        pytest.skip("OpenSCAD not installed")
    output = tmp_path / "ir_pair.stl"
    subprocess.run([
        openscad, "--export-format", "binstl", "-o", str(output),
        "-D", 'part="dock_ir_pair_position_coupon"', str(SOURCE),
    ], check=True, capture_output=True, text=True, timeout=120)
    data = output.read_bytes()
    n = struct.unpack_from("<I", data, 80)[0]
    assert n > 0 and len(data) == 84 + 50*n
    faces = [
        tuple(struct.unpack_from("<fff", data, 84+50*i+12+12*j)
              for j in range(3)) for i in range(n)
    ]
    vertices = [p for face in faces for p in face]
    assert tuple(min(p[k] for p in vertices) for k in range(3)) == (0, 0, 0)
    assert tuple(max(p[k] for p in vertices) for k in range(3)) == (
        126, 16, 3
    )
    # The full CSG top surface should not bridge over either opening.
    def top_face_covers(x, y, triangle):
        a, b, c = triangle
        if not all(abs(p[2]-3) < .001 for p in triangle):
            return False
        denominator = ((b[1]-c[1])*(a[0]-c[0])
                       + (c[0]-b[0])*(a[1]-c[1]))
        if abs(denominator) < 1e-8:
            return False
        u = ((b[1]-c[1])*(x-c[0]) + (c[0]-b[0])*(y-c[1]))/denominator
        v = ((c[1]-a[1])*(x-c[0]) + (a[0]-c[0])*(y-c[1]))/denominator
        return min(u, v, 1-u-v) > 1e-6
    for x in (14, 112):
        assert not any(top_face_covers(x, 8, face) for face in faces)
        # Verify parameter-derived 32-segment bore rims exist on BOTH top (z=3)
        # and bottom (z=0) faces with nominal radius 2.75 mm (+/- 0.01 mm),
        # rejecting blind bores or undersized openings.
        top_rim = {
            (round(p[0], 3), round(p[1], 3))
            for p in vertices
            if abs(p[2] - 3.0) < 1e-4
            and abs(((p[0] - x) ** 2 + (p[1] - 8.0) ** 2) ** 0.5 - 2.75) <= 0.01
        }
        bottom_rim = {
            (round(p[0], 3), round(p[1], 3))
            for p in vertices
            if abs(p[2] - 0.0) < 1e-4
            and abs(((p[0] - x) ** 2 + (p[1] - 8.0) ** 2) ** 0.5 - 2.75) <= 0.01
        }
        assert len(top_rim) >= 32 and len(bottom_rim) >= 32, (
            x, len(top_rim), len(bottom_rim),
        )
        assert not any(
            all(abs(p[2] - 0.0) < 1e-4 for p in face) and
            ((sum(p[0] for p in face) / 3 - x) ** 2 + (sum(p[1] for p in face) / 3 - 8.0) ** 2) ** 0.5 < 2.74
            for face in faces
        )
    # A too-close transmitter spacing would carve into the tag white margin.
    invalid = subprocess.run([
        openscad, "--export-format", "binstl", "-o",
        str(tmp_path / "bad.stl"), "-D",
        'part="dock_ir_pair_position_coupon"', "-D",
        "ir_pair_spacing_mm=65", str(SOURCE),
    ], capture_output=True, text=True, timeout=120)
    assert "IR aperture overlaps AprilTag quiet paper margin" in (
        invalid.stderr + invalid.stdout
    )


def test_dock_shell_print_commands_use_one_continuation_escape():
    """Copying each two-line OpenSCAD command must pass the -D argument."""
    guide = SOURCE.parent / "README.md"
    commands = [
        line for line in guide.read_text(encoding="utf-8").splitlines()
        if line.startswith("openscad --export-format")
    ]
    assert len(commands) == 2
    assert all(line.endswith(chr(92)) and
               not line.endswith(chr(92) * 2) for line in commands)
    assert 'part="dock_rail_entry_coupon"' in guide.read_text()
    assert 'part="dock_ir_pair_position_coupon"' in guide.read_text()


def test_dock_assembly_requires_independent_seating_and_ir_measurements():
    """Optical beacon placement must not silently imply dock electrical seating."""
    root = Path(__file__).resolve().parents[2]
    sheet = (root / "docs/cad/FUSION_MEASUREMENT_SHEET.md").read_text(
        encoding="utf-8"
    )
    guide = (root / "docs/cad/FUSION_ONE_ROBOT_ASSEMBLY.md").read_text(
        encoding="utf-8"
    )
    assert "dock_ir_spacing" in sheet and "ir_left_z" in sheet
    assert "ir_right_z" in sheet and "ir_yaw" in sheet
    assert "dock_seat_left" in sheet and "dock_seat_right" in sheet
    assert "dock_seat_overtravel" in sheet
    assert "dock_ir_pair_position_coupon" in guide
    assert "## Repeatable unpowered coupon trial record" in sheet
    for required_term in (
        "MG90S",
        "GY-530",
        "Challenge speaker",
        "dock rail entry",
        "Slicer profile",
        "Allowed error rationale",
        "Postprocessing state",
    ):
        assert required_term in sheet, required_term
    assert "two electrically independent fail-closed seat switches" in guide
    assert "decoded IR are not seat" in guide


def test_full_dock_mesh_taper_and_stop_planes(tmp_path):
    """Measure the passive rail angle and both actual stop-face planes."""
    import math
    import shutil
    import struct
    import subprocess

    executable = shutil.which("openscad")
    if executable is None:
        pytest.skip("OpenSCAD not installed")
    source = SOURCE.read_text(encoding="utf-8")

    def value(name):
        match = re.search(rf"^{name}\s*=\s*([0-9.]+)\s*;", source, re.M)
        assert match is not None, name
        return float(match.group(1))

    output = tmp_path / "full_dock.stl"
    subprocess.run(
        [executable, "--export-format", "binstl", "-o", str(output), str(SOURCE)],
        check=True, capture_output=True, text=True, timeout=180,
    )
    data = output.read_bytes()
    count = struct.unpack_from("<I", data, 80)[0]
    assert count > 0 and len(data) == 84 + 50 * count
    faces = [
        tuple(struct.unpack_from("<fff", data, 84 + 50 * i + 12 + 12 * j)
              for j in range(3)) for i in range(count)
    ]
    floor = value("base_thickness_mm")
    run = value("entry_flare_run_mm")
    flare = value("entry_flare_each_mm")
    widths = []
    for y in (0, run):
        xs = sorted({round(x, 4) for face in faces for x, yy, z in face
                     if abs(yy - y) < 0.001 and z > floor + 0.001})
        assert len(xs) == 4
        widths.append(xs[2] - xs[1])
    measured_angle = math.degrees(math.atan2((widths[0] - widths[1]) / 2, run))
    assert measured_angle == pytest.approx(math.degrees(math.atan2(flare, run)), abs=0.01)
    width = value("track_outer_width_mm") + 2 * (
        value("side_clearance_each_mm") + value("guide_wall_mm")
        + value("wall_outside_margin_mm")
    )
    stop = value("base_length_mm") - value("backstop_thickness_mm")
    brace = stop - value("backstop_brace_depth_mm")
    brace_height = value("backstop_brace_height_mm")
    paper = value("tag_black_side_mm") + 2 * (
        value("tag_white_margin_each_mm") + value("tag_paper_slack_each_mm")
    )
    # Project triangles on each front plane onto X/Z. The low brace is the
    # first nominal obstruction; the higher wall has a tag pocket cutout.
    for plane, expected_area in (
        (brace, width * brace_height),
        (stop, width * (value("backstop_height_mm") - brace_height) - paper**2),
    ):
        area = 0.0
        for a, b, c in faces:
            if all(abs(p[1] - plane) < 0.001 for p in (a, b, c)):
                area += abs((b[0] - a[0]) * (c[2] - a[2])
                            - (c[0] - a[0]) * (b[2] - a[2])) / 2
        assert area == pytest.approx(expected_area, abs=0.1), plane
