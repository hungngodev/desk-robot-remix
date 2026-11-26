"""Execute the conservative G018/G024 OpenSCAD guard against synthetic geometry."""

import shutil
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "docs/cad/remixes/costume_keepouts.scad"
INTERFACES = (
    "camera", "tof0", "tof1", "tof2", "tof3", "tof4", "tof5", "tof6", "tof7",
    "pdm_mic", "speaker", "sense_vent", "wroom_vent", "amp_vent",
)


def render(tmp_path, *, swept="[[[3,0,0],[4,1,1]]]", keepouts=None):
    openscad = shutil.which("openscad")
    if not openscad:
        pytest.skip("OpenSCAD unavailable")
    if keepouts is None:
        keepouts = [f'[{name!r}, [[[0,0,0],[1,1,1]]]]' for name in INTERFACES]
    driver = tmp_path / "driver.scad"
    records = ",".join(keepouts).replace("'", '"')
    driver.write_text(
        f"use <{SOURCE.as_posix()}>\n"
        f"costume_keepout_guard({swept}, [{records}]) cube(1);\n",
        encoding="utf-8",
    )
    return subprocess.run(
        [openscad, "--hardwarnings", "-o", str(tmp_path / "result.csg"), str(driver)],
        capture_output=True, text=True, timeout=20, check=False,
    )


def test_clear_costume(tmp_path):
    result = render(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "ERROR:" not in result.stderr
    assert "cube" in (tmp_path / "result.csg").read_text()


@pytest.mark.parametrize("interface", INTERFACES)
def test_each_interface_rejects_touching_or_overlapping_sweep(tmp_path, interface):
    records = [f'[{name!r}, [[[0,0,0],[1,1,1]]]]' for name in INTERFACES]
    records[INTERFACES.index(interface)] = f'[{interface!r}, [[[2,0,0],[3,1,1]]]]'
    result = render(tmp_path, keepouts=records)
    assert f"Costume occlusion: {interface}" in result.stderr


@pytest.mark.parametrize("swept", ["[]", "[[[0,0,0],[0,1,1]]]", "[[[0,0],[1,1,1]]]"])
def test_invalid_sweep_fails_closed(tmp_path, swept):
    result = render(tmp_path, swept=swept)
    assert "ERROR: Assertion" in result.stderr


def test_missing_interface_fails_closed(tmp_path):
    result = render(tmp_path, keepouts=[])
    assert "Missing or extra costume keepout interfaces" in result.stderr


def test_multiple_swept_boxes_checked(tmp_path):
    result = render(tmp_path, swept="[[[3,0,0],[4,1,1]],[[0,0,0],[1,1,1]]]")
    assert "Costume occlusion: camera" in result.stderr
