"""Provisional jaw coupon geometry, never physical force qualification."""
import math
import re
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "docs/cad/remixes/one_robot_adapter_kit.scad"


def _parameter(name):
    match = re.search(r"^" + re.escape(name) + r"\s*=\s*([0-9.]+)\s*;", SOURCE.read_text(), re.M)
    assert match is not None, name
    return float(match.group(1))


def test_fsr_reference_envelope_and_contact_stack():
    diameter = _parameter("fsr_d")
    tail = _parameter("fsr_tail_w_mm")
    clearance = _parameter("fit_xy")
    radius = (diameter + clearance) / 2
    half_tail = (tail + clearance) / 2
    plane = _parameter("fsr_grip_plane_mm")
    stack = _parameter("fsr_stack_h_mm")
    relief = _parameter("fsr_rim_relief_mm")
    base = _parameter("fsr_base_h_mm")
    assert diameter >= 18.3 and tail >= 7.62 and clearance >= 0.35
    assert 1.5 <= plane - stack <= base < plane - relief < plane
    assert stack > 0.51 + relief
    assert math.hypot(radius - 2, half_tail) < radius * math.cos(math.pi / 48)


def _render(tmp_path, *overrides):
    executable = shutil.which("openscad")
    if executable is None:
        pytest.skip("OpenSCAD not installed on this runner")
    target = tmp_path / "jaw.stl"
    command = [executable, "--export-format", "binstl", "-o", str(target),
               "-D", 'part="fsr_jaw_pocket"']
    for override in overrides:
        command.extend(["-D", override])
    return target, subprocess.run(command + [str(SOURCE)], capture_output=True,
                                  text=True, timeout=120)


def _surface_height(faces, x, y):
    """Highest horizontal triangle at XY, with inclusive barycentric edges."""
    heights = []
    for a, b, c in faces:
        if abs(a[2] - b[2]) > 1e-5 or abs(a[2] - c[2]) > 1e-5:
            continue
        denominator = (b[1]-c[1])*(a[0]-c[0]) + (c[0]-b[0])*(a[1]-c[1])
        if abs(denominator) < 1e-8:
            continue
        u = ((b[1]-c[1])*(x-c[0]) + (c[0]-b[0])*(y-c[1])) / denominator
        v = ((c[1]-a[1])*(x-c[0]) + (a[0]-c[0])*(y-c[1])) / denominator
        if min(u, v, 1-u-v) >= -1e-6:
            heights.append(a[2])
    assert heights, (x, y)
    return max(heights)


def test_fsr_mesh_has_continuous_supported_tail_and_relieved_rim(tmp_path):
    target, result = _render(tmp_path)
    assert result.returncode == 0, result.stderr
    data = target.read_bytes()
    count = struct.unpack_from("<I", data, 80)[0]
    assert count > 0 and len(data) == 84 + count * 50
    faces = [tuple(struct.unpack_from("<fff", data, 84 + 50*i + 12 + 12*j)
                   for j in range(3)) for i in range(count)]
    radius = (_parameter("fsr_d") + _parameter("fit_xy")) / 2
    half_tail = (_parameter("fsr_tail_w_mm") + _parameter("fit_xy")) / 2
    plate_half = (_parameter("fsr_d") + _parameter("fsr_plate_extra_mm")) / 2
    plane = _parameter("fsr_grip_plane_mm")
    floor = plane - _parameter("fsr_stack_h_mm")
    rim = plane - _parameter("fsr_rim_relief_mm")
    # Sensor center and near its edge must rest on the same flat floor.
    for x, y in ((0, 0), (0, radius - 0.4), (radius - 0.4, 0)):
        assert _surface_height(faces, x, y) == pytest.approx(floor, abs=.001)
    # Both tail edges must have an uninterrupted floor, all the way past the rim.
    for x in (-half_tail + 0.15, half_tail - 0.15):
        for y in (-radius + 2.1, -radius, -radius - 1, -plate_half + 0.2):
            assert _surface_height(faces, x, y) == pytest.approx(floor, abs=.001)
    # The rigid rim stays below the provisional silicone contact plane.
    assert _surface_height(faces, radius + .5, 0) == pytest.approx(rim, abs=.001)
    assert rim < plane


@pytest.mark.parametrize("override,reason", [
    ("fsr_d=12", "FSR402 reference body or tail clearance undersized"),
    ("fsr_tail_w_mm=3.5", "FSR402 reference body or tail clearance undersized"),
    ("fsr_stack_h_mm=3", "FSR stack must retain a supported floor and relieved rigid rim"),
    ("fsr_rim_relief_mm=0", "FSR stack must retain a supported floor and relieved rigid rim"),
])
def test_fsr_invalid_geometry_is_rejected(tmp_path, override, reason):
    target, result = _render(tmp_path, override)
    assert reason in result.stderr + result.stdout
    assert not target.exists()
