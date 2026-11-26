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


def clear_records():
    return [f'[{name!r}, [[[0,0,0],[1,1,1]]]]' for name in INTERFACES]


def render(tmp_path, *, swept="[[[3,0,0],[4,1,1]]]", keepouts=None):
    openscad = shutil.which("openscad")
    if not openscad:
        pytest.skip("OpenSCAD unavailable")
    if keepouts is None:
        keepouts = clear_records()
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


def assert_rejected(tmp_path, result, message):
    assert message in result.stderr
    output = tmp_path / "result.csg"
    assert not output.exists() or not output.read_text(encoding="utf-8").strip()


def test_clear_costume(tmp_path):
    result = render(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "ERROR:" not in result.stderr
    assert "cube" in (tmp_path / "result.csg").read_text()


@pytest.mark.parametrize("interface", INTERFACES)
def test_each_interface_rejects_touching_or_overlapping_sweep(tmp_path, interface):
    records = clear_records()
    records[INTERFACES.index(interface)] = f'[{interface!r}, [[[2,0,0],[3,1,1]]]]'
    result = render(tmp_path, keepouts=records)
    assert_rejected(tmp_path, result, f"Costume occlusion: {interface}")


@pytest.mark.parametrize("swept", ["[]", "[[[0,0,0],[0,1,1]]]", "[[[0,0],[1,1,1]]]"])
def test_invalid_sweep_fails_closed(tmp_path, swept):
    result = render(tmp_path, swept=swept)
    assert_rejected(tmp_path, result, "ERROR: Assertion")


def test_missing_interface_fails_closed(tmp_path):
    result = render(tmp_path, keepouts=[])
    assert_rejected(tmp_path, result, "Missing or extra costume keepout interfaces")


def test_multiple_swept_boxes_checked(tmp_path):
    result = render(tmp_path, swept="[[[3,0,0],[4,1,1]],[[0,0,0],[1,1,1]]]")
    assert_rejected(tmp_path, result, "Costume occlusion: camera")


@pytest.mark.parametrize("boxes", ["[]", "[[[1,0,0],[0,1,1]]]", "[[[0,0,0],[1,1,undef]]]"])
def test_missing_or_malformed_protected_volume(tmp_path, boxes):
    records = clear_records()
    records[0] = f'["camera", {boxes}]'
    result = render(tmp_path, keepouts=records)
    message = "Missing measured boxes" if boxes == "[]" else "Invalid keepout"
    assert_rejected(tmp_path, result, f"{message}: camera")


def test_duplicate_interface_does_not_replace_missing_lane(tmp_path):
    records = clear_records()
    records[1] = records[0]
    result = render(tmp_path, keepouts=records)
    assert_rejected(tmp_path, result, "Missing or misordered keepout: tof0")


def test_multiple_protected_boxes_checked(tmp_path):
    records = clear_records()
    records[-1] = '["amp_vent", [[[0,0,0],[1,1,1]], [[3,0,0],[4,1,1]]]]'
    result = render(tmp_path, keepouts=records)
    assert_rejected(tmp_path, result, "Costume occlusion: amp_vent")
