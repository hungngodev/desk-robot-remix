"""Screen the provisional speaker grille, not installed acoustic performance."""

import math
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "docs/cad/remixes/one_robot_adapter_kit.scad"
pytestmark = pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs OpenSCAD CLI")


def render(tmp_path, *overrides):
    output = tmp_path / "grille.stl"
    command = ["openscad", "--export-format", "binstl", "-o", str(output),
               "-D", 'part="speaker_grille"']
    for override in overrides:
        command.extend(["-D", override])
    result = subprocess.run([*command, str(SOURCE)], capture_output=True, text=True,
                            timeout=60, check=False)
    return result, output


def test_nominal_grille_open_area_excludes_mounting_bores(tmp_path):
    result, output = render(tmp_path)
    assert result.returncode == 0, result.stderr
    data = output.read_bytes()
    count = struct.unpack_from("<I", data, 80)[0]
    top_area = 0.0
    for i in range(count):
        triangle = struct.unpack_from("<12fH", data, 84 + 50*i)
        ax, ay, az, bx, by, bz, cx, cy, cz = triangle[3:12]
        if az == bz == cz == 3:
            top_area += abs((bx-ax)*(cy-ay) - (by-ay)*(cx-ax))/2
    # OpenSCAD cylinders use a 48-sided polygon, not a perfect circle.
    polygon_factor = 48 * math.sin(2*math.pi/48) / 2
    fastener_area = 4 * polygon_factor * (2.35/2)**2
    acoustic_area = 36*32 - top_area - fastener_area
    assert acoustic_area == pytest.approx(15 * polygon_factor * 1.2**2, abs=0.05)
    assert acoustic_area / (20*16) >= 0.20


@pytest.mark.parametrize(("diameter", "message"), [
    (2.0, "nominal aperture ratio below 20 percent"),
    (3.8, "aperture ligament below 1.3 mm"),
])
def test_grille_rejects_reduced_area_or_overlapping_holes(tmp_path, diameter, message):
    result, output = render(tmp_path, f"speaker_grille_aperture_d={diameter}")
    assert message in result.stderr
    assert not output.exists()
