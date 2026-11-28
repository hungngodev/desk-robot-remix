"""Check head selection without importing Blender or touching saved CAD."""

import ast
import re
import struct
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "code/scripts/render_product_concept.py"


def _head_selection(*, optimize=-1):
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    start = next(i for i, node in enumerate(tree.body)
                 if isinstance(node, ast.Assign)
                 and ast.unparse(node.targets[0]) == "chassis.location.z")
    end = next(i for i, node in enumerate(tree.body)
               if isinstance(node, ast.FunctionDef) and node.name == "box")
    return compile(
        ast.Module(body=tree.body[start + 1:end], type_ignores=[]),
        str(SCRIPT), "exec", optimize=optimize,
    )


def test_rounded_head_never_opens_or_records_eva(tmp_path):
    calls = []
    shell = SimpleNamespace()

    def stl(path, name, material):
        calls.append(path)
        return shell, [56, 52, 54]

    scope = {"args": SimpleNamespace(head="sparky"), "ROOT": tmp_path,
             "stl": stl, "ivory": None}
    exec(_head_selection(), scope)
    assert calls == [tmp_path / "docs/cad/originals/sparky-head/sparky_shell.stl"]
    assert scope["head_dims"] == [56, 52, 54]
    assert shell.location == (0, -0.007, 0.050)


def test_eva_dimensions_follow_transformed_mesh_vertices(tmp_path):
    path = tmp_path / "docs/cad/originals/eva-head/EVA-Robot.3mf"
    path.parent.mkdir(parents=True)
    model = """<model xmlns="urn:test" unit="millimeter"><resources>
      <object id="1"><mesh><vertices>
        <vertex x="0" y="0" z="0"/><vertex x="80" y="0" z="12"/>
        <vertex x="0" y="60" z="50"/>
      </vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object>
      <object id="2"><mesh><vertices>
        <vertex x="-1" y="-2" z="-3"/><vertex x="1" y="1" z="1"/>
        <vertex x="2" y="2" z="2"/>
      </vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object>
    </resources></model>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("3D/3dmodel.model", model)
    sources, meshes = [], []
    scope = {"args": SimpleNamespace(head="eva"), "ROOT": tmp_path,
             "source_record": sources.append, "mesh": lambda *args: meshes.append(args),
             "ivory": None, "ET": ET, "zipfile": zipfile}
    exec(_head_selection(), scope)
    assert sources == [path]
    assert len(meshes) == 2
    assert scope["head_dims"] == [62, 81, 53]


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("unit", [' unit="inch"', ""])
def test_eva_rejects_missing_or_wrong_units(tmp_path, optimize, unit):
    path = tmp_path / "docs/cad/originals/eva-head/EVA-Robot.3mf"
    path.parent.mkdir(parents=True)
    model = f"""<model xmlns="urn:test"{unit}><resources>
      <object id="1"><mesh><vertices>
        <vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/>
        <vertex x="0" y="1" z="0"/>
      </vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object>
    </resources></model>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("3D/3dmodel.model", model)
    meshes = []
    scope = {"args": SimpleNamespace(head="eva"), "ROOT": tmp_path,
             "source_record": lambda path: None, "mesh": lambda *args: meshes.append(args),
             "ivory": None, "ET": ET, "zipfile": zipfile}
    with pytest.raises(ValueError, match="3MF must declare millimeter units"):
        exec(_head_selection(optimize=optimize), scope)
    assert meshes == []


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("data", [b"vertex 0 0 0\n" * 4, bytes(84)])
def test_stl_rejects_incomplete_or_empty_triangles(tmp_path, optimize, data):
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    node = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "stl")
    meshes = []
    scope = {"source_record": lambda path: None, "mesh": lambda *args: meshes.append(args),
             "re": re, "struct": struct}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SCRIPT), "exec",
                 optimize=optimize), scope)
    path = tmp_path / "invalid.stl"
    path.write_bytes(data)
    with pytest.raises(ValueError, match="STL must contain complete triangles"):
        scope["stl"](path, "invalid", None)
    assert meshes == []
