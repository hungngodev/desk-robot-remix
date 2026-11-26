"""Guard native-scale source geometry and the provisional Fusion import contract."""

import ast
import re
import struct
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[2]
CAD = ROOT / "docs/cad"
# Independent source-coordinate envelopes, not assembled or measured dimensions.
# Do not rescale individual gears, tracks or shells to make a coupon fit.
STL_SIZES = {
    "smars/chassis_-SL.stl": (78, 70, 33),
    "smars/slave_wheel_SL.stl": (21.0434, 32.5219, 32.5219),
    "smars/mechanical_track.stl": (16, 17.35, 6),
    "smars-stepper/SMARS_2BJY8-Chassis.stl": (58.0015, 86.1942, 41.5885),
    "smars-stepper/SMARS_28BYJ-48-RearWheel.stl": (21.0434, 32.5219, 32.5219),
    "forklift/fork_lift_e.stl": (46.1566, 30, 11.8),
    "forklift/fork_lift_f.stl": (34, 38, 14.3),
    "gripper/servo_case_arm.stl": (36, 29.5, 64.7644),
    "gripper/arm_rack.stl": (36.333, 8.6, 27.497),
    "gripper/pinion_gear.stl": (14.16, 4.8, 13.225),
    "sparky-head/sparky_shell.stl": (55.9658, 51.9658, 53.9829),
    "sparky-head/sparky_collar.stl": (56, 52, 6),
    "sparky-head/sparky_lid.stl": (51.4, 47.4, 4),
}
SCAD_SOURCES = (
    "one_robot_adapter_kit.scad",
    "dock/dock_passive_fit.scad",
    "mg90s_pocket_fit_gauges.scad",
    "vl53l0x_gy530_fit_gauge.scad",
    "speaker_rect_fit_gauge.scad",
    "remaining_fit_gauges.scad",
)


def _assert_native_dimensions(vertices, expected):
    axes = tuple(zip(*vertices, strict=True))
    assert len(axes) == 3
    sizes = tuple(max(axis) - min(axis) for axis in axes)
    assert sizes == pytest.approx(expected, abs=0.002, rel=0)


def _stl_vertices(data):
    # The original Sparky release contains ASCII STL, unlike SMARS/Bluino.
    if len(data) >= 84 and len(data) == 84 + 50 * struct.unpack_from("<I", data, 80)[0]:
        for face in struct.iter_unpack("<12fH", data[84:]):
            yield from (face[3:6], face[6:9], face[9:12])
    else:
        for vertex in re.findall(rb"(?m)^\s*vertex\s+(\S+)\s+(\S+)\s+(\S+)\s*$", data):
            yield tuple(map(float, vertex))


@pytest.mark.parametrize("factor", [0.1, 10, 1 / 25.4, 25.4])
def test_native_dimension_guard_rejects_unit_conversion(factor):
    expected = (16, 17.35, 6)
    _assert_native_dimensions([(0, 0, 0), expected], expected)
    with pytest.raises(AssertionError):
        _assert_native_dimensions([(0, 0, 0), tuple(v * factor for v in expected)], expected)


@pytest.mark.parametrize("binary", [False, True])
def test_stl_vertex_reader_supports_both_source_formats(binary):
    vertices = (0, 0, 0, 16, 17.35, 6, 0, 17.35, 0)
    if binary:
        data = bytes(80) + struct.pack("<I12fH", 1, 0, 0, 0, *vertices, 0)
    else:
        data = b"solid sample\n vertex 0 0 0\n vertex 16 17.35 6\n vertex 0 17.35 0\n"
    _assert_native_dimensions(_stl_vertices(data), (16, 17.35, 6))


@pytest.mark.parametrize("relative,expected", STL_SIZES.items())
def test_original_stl_native_size(relative, expected):
    _assert_native_dimensions(_stl_vertices((CAD / "originals" / relative).read_bytes()), expected)


def test_eva_reference_uses_millimeters():
    # 3MF declares units, unlike STL. EVA is a reference, not an active import.
    with ZipFile(CAD / "originals/eva-head/EVA-Robot.3mf") as archive:
        model = ET.fromstring(archive.read("3D/3dmodel.model"))
    assert model.get("unit", "millimeter") == "millimeter"
    vertices = [tuple(float(v.attrib[a]) for a in "xyz") for v in model.findall(".//{*}vertex")]
    _assert_native_dimensions(vertices, (74, 48, 48.8))


def test_fusion_import_requests_millimeters():
    source = (CAD / "remixes/fusion_one_robot_scaffold.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [
        node for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "add"
        and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "meshBodies"
    ]
    assert len(imports) == 1
    assert ast.unparse(imports[0].args[1]) == "adsk.fusion.MeshUnits.MillimeterMeshUnit"


@pytest.mark.parametrize("relative", SCAD_SOURCES)
def test_fit_scad_does_not_import_scaled_upstream_meshes(relative):
    source = (CAD / "remixes" / relative).read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S)
    # The exporter stages standalone SCAD sources; adding an import/include
    # requires explicit dependency provenance and a new unit contract.
    assert not re.search(r"\b(?:import|include|use)\s*[(<]", code)
