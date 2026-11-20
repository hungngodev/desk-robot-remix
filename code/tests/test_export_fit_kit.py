"""Render candidate CAD parts reproducibly without claiming measured fit."""
import importlib.util
import shutil
import subprocess
from pathlib import Path
from struct import pack

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "code/scripts/export_fit_kit.py"


def module():
    spec = importlib.util.spec_from_file_location("desk_fit_kit", SCRIPT)
    source = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source)
    return source


def tetra_stl(*, flip_one_face: bool = False) -> bytes:
    vertices = ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))
    faces = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
    if flip_one_face:
        faces[0] = (0, 1, 2)
    data = bytearray(bytes(80) + len(faces).to_bytes(4, "little"))
    for face in faces:
        floats = [0.0, 0.0, 0.0]
        for index in face:
            floats.extend(vertices[index])
        data.extend(pack("<12fH", *floats, 0))
    return bytes(data)


def test_binary_stl_geometry_rejects_truncation_and_zero_triangles(tmp_path):
    source = module()
    output = tmp_path / "part.stl"
    output.write_bytes(b"nothing")
    with pytest.raises(ValueError, match="Truncated"):
        source.binary_stl_triangles(output)
    output.write_bytes(bytes(80) + (0).to_bytes(4, "little"))
    with pytest.raises(ValueError, match="Invalid"):
        source.binary_stl_triangles(output)
    output.write_bytes(bytes(80) + (2).to_bytes(4, "little") + bytes(50))
    with pytest.raises(ValueError, match="Invalid"):
        source.binary_stl_triangles(output)
    output.write_bytes(bytes(80) + (1).to_bytes(4, "little") + bytes(50))
    assert source.binary_stl_triangles(output) == 1
    with pytest.raises(ValueError, match="Degenerate"):
        source.closed_mesh_edges(output)
    # One geometrically valid triangle still has open boundary edges.
    triangle = bytes(80) + (1).to_bytes(4, "little") + pack(
        "<12fH", 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0,
    )
    output.write_bytes(triangle)
    with pytest.raises(ValueError, match="Open"):
        source.closed_mesh_edges(output)
    output.write_bytes(tetra_stl())
    assert source.binary_stl_triangles(output) == 4
    assert source.closed_mesh_edges(output) == 6
    output.write_bytes(tetra_stl(flip_one_face=True))
    with pytest.raises(ValueError, match="inconsistent"):
        source.closed_mesh_edges(output)
    # Two separately valid watertight solids are NOT a single fitted part.
    # Translation prevents sharing even one vertex between the tetrahedra.
    from struct import pack_into, unpack_from
    first = tetra_stl()[84:]
    second = bytearray(first)
    for triangle_index in range(4):
        for corner in range(3):
            x_offset = triangle_index * 50 + 12 + corner * 12
            old_x = unpack_from("<f", second, x_offset)[0]
            pack_into("<f", second, x_offset, old_x + 10.0)
    output.write_bytes(bytes(80) + (8).to_bytes(4, "little")
                       + first + second)
    with pytest.raises(ValueError, match="Disconnected STL mesh"):
        source.closed_mesh_edges(output)


def test_render_all_candidates_with_one_source_and_unqualified_output(monkeypatch, tmp_path):
    source = module()
    folder = tmp_path / "docs/cad/remixes"
    folder.mkdir(parents=True)
    for name in ("one_robot_adapter_kit.scad", "remaining_fit_gauges.scad",
                 "speaker_rect_fit_gauge.scad", "vl53l0x_gy530_fit_gauge.scad"):
        (folder / name).write_text("cube([1,1,1]);\n")
    (folder / "dock").mkdir()
    (folder / "dock/dock_passive_fit.scad").write_text("cube([1,1,1]);\n")
    monkeypatch.setattr(source.shutil, "which", lambda _command: "/usr/bin/openscad")
    commands = []

    def fake_render(command, **kwargs):
        commands.append(command)
        assert kwargs["check"] and kwargs["timeout"] <= 180
        assert "--export-format" in command and "binstl" in command
        out = Path(command[command.index("-o") + 1])
        out.write_bytes(tetra_stl())
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(source.subprocess, "run", fake_render)
    rendered = tmp_path / "rendered"
    report = source.export_kit(tmp_path, output_dir=rendered)
    assert len(commands) == (
        len(source.ADAPTERS) + len(source.GAUGES) + len(source.SPEAKER_FITS) + len(source.RANGER_FITS) + len(source.DOCKS)
    ) == 14
    assert len(report["parts"]) == 14
    assert (rendered / "adapter_stls/tof_adjustable.stl").is_file()
    assert (rendered / "fit_stls/dock_contact_recess_gauge.stl").is_file()
    assert (rendered / "fit_stls/speaker_rect_fit_gauge.stl").is_file()
    assert (rendered / "fit_stls/vl53l0x_gy530_fit_gauge.stl").is_file()
    assert (rendered / "dock_stls/dock_passive_fit.stl").is_file()
    assert (rendered / "dock_stls/dock_rail_entry_coupon.stl").is_file()
    assert (rendered / "fit_kit_manifest.json").is_file()
    assert report["parts"][1]["quantity_per_robot"] == 8
    assert all(item["manifold_edges"] == 6 for item in report["parts"])
    assert source.verify_fit_kit(tmp_path, output_dir=rendered) == report
    # A modified JSON receipt must never promote a reversible fit kit
    # to a physically qualified assembly, energized dock, or licensed product.
    import json
    manifest = rendered / "fit_kit_manifest.json"
    original = manifest.read_text()
    for unsafe_flag in (
        "hardware_fit_verified", "full_printable_assembly_verified",
        "dock_charge_contacts_approved", "commercial_manufacture_authorized",
    ):
        edited = dict(report, **{unsafe_flag: True})
        manifest.write_text(json.dumps(edited))
        with pytest.raises(ValueError, match="Unsafe fit kit provenance flags"):
            source.verify_fit_kit(tmp_path, output_dir=rendered)
    manifest.write_text(original)
    assert all(item["units"] == "mm" for item in report["parts"])
    assert all(len(item["source_sha256"]) == 64 for item in report["parts"])
    assert all(len(item["mesh_sha256"]) == 64 for item in report["parts"])
    from hashlib import sha256
    for item in report["parts"]:
        assert sha256((tmp_path / item["source"]).read_bytes()).hexdigest() == item["source_sha256"]
        assert sha256((rendered / item["location"]).read_bytes()).hexdigest() == item["mesh_sha256"]
    source_path = tmp_path / report["parts"][0]["source"]
    original_source = source_path.read_bytes()
    source_path.write_bytes(original_source + b"// altered source\n")
    with pytest.raises(ValueError, match="SCAD source changed"):
        source.verify_fit_kit(tmp_path, output_dir=rendered)
    source_path.write_bytes(original_source)
    mesh_path = rendered / "dock_stls/dock_rail_entry_coupon.stl"
    mesh_path.write_bytes(mesh_path.read_bytes() + b"stale")
    with pytest.raises(ValueError, match="STL changed"):
        source.verify_fit_kit(tmp_path, output_dir=rendered)
    for key in (
        "hardware_fit_verified", "full_printable_assembly_verified",
        "dock_charge_contacts_approved", "commercial_manufacture_authorized",
    ):
        assert report[key] is False


def test_failed_cad_render_never_publishes_partial_parts(monkeypatch, tmp_path):
    source = module()
    folder = tmp_path / "docs/cad/remixes"
    folder.mkdir(parents=True)
    for name in ("one_robot_adapter_kit.scad", "remaining_fit_gauges.scad",
                 "speaker_rect_fit_gauge.scad", "vl53l0x_gy530_fit_gauge.scad"):
        (folder / name).write_text("cube([1,1,1]);\n")
    (folder / "dock").mkdir()
    (folder / "dock/dock_passive_fit.scad").write_text("cube([1,1,1]);\n")
    monkeypatch.setattr(source.shutil, "which", lambda _command: "/usr/bin/openscad")
    tries = 0

    def fail_after_one(command, **_kwargs):
        nonlocal tries
        tries += 1
        if tries == 2:
            raise subprocess.CalledProcessError(1, command)
        Path(command[command.index("-o") + 1]).write_bytes(tetra_stl())

    monkeypatch.setattr(source.subprocess, "run", fail_after_one)
    output = tmp_path / "rendered"
    output.mkdir()
    (output / "fit_kit_manifest.json").write_text("stale evidence")
    with pytest.raises(subprocess.CalledProcessError):
        source.export_kit(tmp_path, output_dir=output)
    assert not list(output.rglob("*.stl"))
    assert not (output / "fit_kit_manifest.json").exists()



@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs OpenSCAD CLI")
def test_low_cost_gy530_sensor_envelope_coupon_watertight(tmp_path):
    """The fixed $1.76 SKU nominal XY is not verified for holes, lens, or PCB."""
    from struct import unpack_from
    scad = ROOT / "docs/cad/remixes/vl53l0x_gy530_fit_gauge.scad"
    content = scad.read_text()
    assert "SEN-19-006" in content
    assert "board_x = 10.5;" in content
    assert "board_y = 13.3;" in content
    target = tmp_path / "gy530.stl"
    subprocess.run(["openscad", "--export-format", "binstl", "-o",
                    str(target), str(scad)], check=True, timeout=60)
    assert module().closed_mesh_edges(target) > 0
    data = target.read_bytes()
    n = unpack_from("<I", data, 80)[0]
    coords = [unpack_from("<3f", data, 84 + i*50 + 12 + j*12)
              for i in range(n) for j in range(3)]
    width = max(x[0] for x in coords) - min(x[0] for x in coords)
    length = max(x[1] for x in coords) - min(x[1] for x in coords)
    assert 15 < width < 16
    assert 17 < length <= 18.1


@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs OpenSCAD CLI")
def test_exact_2w_rectangular_speaker_coupon_is_watertight_and_unqualified(tmp_path):
    """Manufacturer dimensions produce a printable fit TEST, not final acoustics."""
    from struct import unpack_from
    source = ROOT / "docs/cad/remixes/speaker_rect_fit_gauge.scad"
    text = source.read_text(encoding="utf-8")
    assert "CS20-02P110-04-1X" in text
    assert "speaker_l=20;" in text and "speaker_w=16;" in text
    assert "speaker_h=4.7;" in text
    output = tmp_path / "speaker.stl"
    subprocess.run([
        "openscad", "--export-format", "binstl", "-o",
        str(output), str(source),
    ], check=True, timeout=60)
    assert module().closed_mesh_edges(output) > 0
    blob = output.read_bytes()
    triangles = unpack_from("<I", blob, 80)[0]
    points = [
        unpack_from("<3f", blob, 84 + i*50 + 12 + j*12)
        for i in range(triangles) for j in range(3)
    ]
    bounds = [
        max(vertex[axis] for vertex in points) -
        min(vertex[axis] for vertex in points) for axis in range(3)
    ]
    assert 24.0 < bounds[0] < 27.0
    assert 20.0 < bounds[1] < 23.0
    assert 7.0 <= bounds[2] < 9.0


@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs OpenSCAD CLI")
def test_passive_dock_tag_registration_mesh_stays_watertight_and_centered(tmp_path):
    """Real CGAL render checks the unpowered paper AprilTag mounting pocket."""
    from struct import unpack_from

    source = ROOT / "docs/cad/remixes/dock/dock_passive_fit.scad"
    output = tmp_path / "dock.stl"
    subprocess.run([
        "openscad", "--export-format", "binstl", "-o",
        str(output), str(source),
    ], check=True, timeout=60)
    assert module().closed_mesh_edges(output) > 0
    blob = output.read_bytes()
    triangle_count = unpack_from("<I", blob, 80)[0]
    assert triangle_count >= 20
    assert len(blob) == 84 + 50 * triangle_count
    vertices = [
        unpack_from("<3f", blob, 84 + i * 50 + 12 + j * 12)
        for i in range(triangle_count) for j in range(3)
    ]
    xyz = list(zip(*vertices, strict=True))
    bounds = tuple((min(axis), max(axis)) for axis in xyz)
    assert bounds == ((0.0, 126.0), (0.0, 138.0), (0.0, 93.0))
    # 60 mm printed tag + 5 mm white margin/side + 0.6 mm paper
    # clearance/side, centered horizontally in the 126 mm backstop.
    for expected in (27.4, 98.6):
        assert any(abs(x - expected) < 0.02 for x in xyz[0])
    assert any(abs(y - 133.8) < 0.02 for y in xyz[1])
    for expected in (16.0, 87.2):
        assert any(abs(z - expected) < 0.02 for z in xyz[2])



@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs real OpenSCAD CLI")
def test_passive_dock_low_material_entry_coupon_matches_full_guide(tmp_path):
    """Test rail clearance before committing to the full 93mm-high dock."""
    from struct import unpack_from

    source = ROOT / "docs/cad/remixes/dock/dock_passive_fit.scad"
    output = tmp_path / "entry.stl"
    subprocess.run([
        "openscad", "--export-format", "binstl", "-o", str(output),
        "-D", 'part="dock_rail_entry_coupon"', str(source),
    ], check=True, timeout=60)
    assert module().closed_mesh_edges(output) > 0
    blob = output.read_bytes()
    n = unpack_from("<I", blob, 80)[0]
    vertices = [
        unpack_from("<3f", blob, 84 + i * 50 + 12 + j * 12)
        for i in range(n) for j in range(3)
    ]
    bounds = tuple(
        (min(v[axis] for v in vertices), max(v[axis] for v in vertices))
        for axis in range(3)
    )
    assert bounds == ((0.0, 126.0), (0.0, 48.0), (0.0, 15.0))
    # 96mm tracks + 2mm clearance per side. Entry mouth is wider.
    for y, expected_x in ((0.0, (6.0, 120.0)),
                          (37.0, (13.0, 113.0))):
        for x in expected_x:
            assert any(abs(v[0] - x) < 0.01 and
                       abs(v[1] - y) < 0.01 for v in vertices)
    # Passing a fit print does not authorize powered docking.


@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs real OpenSCAD CLI")
def test_real_openscad_renders_provisional_source_parts(tmp_path):
    source = module()
    output = tmp_path / "rendered"
    report = source.export_kit(ROOT, output_dir=output)
    assert len(report["parts"]) == (
        len(source.ADAPTERS) + len(source.GAUGES)
        + len(source.SPEAKER_FITS) + len(source.RANGER_FITS)
        + len(source.DOCKS)
    ) == 14
    assert (output / "adapter_stls/speaker_grille.stl").is_file()
    assert (output / "dock_stls/dock_passive_fit.stl").is_file()
    assert (output / "dock_stls/dock_rail_entry_coupon.stl").is_file()
    for item in report["parts"]:
        assert source.binary_stl_triangles(output / item["location"]) > 0
    assert report["full_printable_assembly_verified"] is False


@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs OpenSCAD CLI")
def test_current_2w_rectangular_front_grille_renders(tmp_path):
    """Active speaker front plate must not silently revert to a 20mm circle."""
    from struct import unpack_from

    source = ROOT / "docs/cad/remixes/one_robot_adapter_kit.scad"
    text = source.read_text(encoding="utf-8")
    assert "CS20-02P110-04-1X" in text
    assert "speaker_l=20;" in text and "speaker_w=16;" in text
    assert "speaker_h=4.7;" in text
    assert "speaker_od=20;" not in text
    output = tmp_path / "rect_front.stl"
    subprocess.run([
        "openscad", "--export-format", "binstl", "-o", str(output),
        "-D", 'part="speaker_grille"', str(source),
    ], check=True, timeout=60)
    assert module().closed_mesh_edges(output) > 0
    blob = output.read_bytes()
    triangles = unpack_from("<I", blob, 80)[0]
    points = [
        unpack_from("<3f", blob, 84 + i * 50 + 12 + j * 12)
        for i in range(triangles) for j in range(3)
    ]
    dimensions = tuple(round(max(v[k] for v in points)
                             - min(v[k] for v in points), 2)
                       for k in range(3))
    assert dimensions == (32.0, 28.0, 3.0)
    # A watertight frontal plate is still not the tested speaker baffle,
    # mounting gasket, sealed 1cc box, or electrical/thermal certification.
