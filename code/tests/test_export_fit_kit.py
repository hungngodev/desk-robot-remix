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
    # Distinct collinear vertices also have zero area. Merely checking
    # equality of STL corners is not enough to reject this invalid facet.
    zero_area = bytes(80) + (1).to_bytes(4, "little") + pack(
        "<12fH", 0, 0, 1, 0, 0, 0, 1, 1, 1, 2, 2, 2, 0,
    )
    output.write_bytes(zero_area)
    with pytest.raises(ValueError, match="Degenerate"):
        source.closed_mesh_edges(output)
    output.write_bytes(tetra_stl())
    assert source.binary_stl_triangles(output) == 4
    assert source.closed_mesh_edges(output) == 6
    assert source.mesh_bounds_mm(output) == {
        "minimum_mm": [0.0, 0.0, 0.0],
        "maximum_mm": [1.0, 1.0, 1.0],
        "dimensions_mm": [1.0, 1.0, 1.0],
    }
    # Flipping every facet preserves edge pairing, but turns the entire
    # printable volume inside out. Reject that case before slicing.
    inverted = bytearray(tetra_stl())
    for facet in range(4):
        start = 84 + facet * 50 + 12
        a = bytes(inverted[start:start + 12])
        b = bytes(inverted[start + 12:start + 24])
        inverted[start:start + 12] = b
        inverted[start + 12:start + 24] = a
    output.write_bytes(inverted)
    with pytest.raises(ValueError, match="Inverted or zero-volume"):
        source.closed_mesh_edges(output)
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
    # One corner touching another is also not a printable joined part.
    # Shift the second tetra to x+1: only the vertex (1,0,0) is shared.
    for triangle_index in range(4):
        for corner in range(3):
            x_offset = triangle_index * 50 + 12 + corner * 12
            old_x = unpack_from("<f", second, x_offset)[0]
            pack_into("<f", second, x_offset, old_x - 9.0)
    output.write_bytes(bytes(80) + (8).to_bytes(4, "little")
                       + first + second)
    with pytest.raises(ValueError, match="Disconnected STL mesh"):
        source.closed_mesh_edges(output)


def test_render_all_candidates_with_one_source_and_unqualified_output(monkeypatch, tmp_path):
    source = module()
    folder = tmp_path / "docs/cad/remixes"
    folder.mkdir(parents=True)
    for name in ("one_robot_adapter_kit.scad", "remaining_fit_gauges.scad",
                 "speaker_rect_fit_gauge.scad", "vl53l0x_gy530_fit_gauge.scad",
                 "mg90s_pocket_fit_gauges.scad"):
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
        len(source.ADAPTERS) + len(source.GAUGES) + len(source.SPEAKER_FITS)
        + len(source.RANGER_FITS) + len(source.MG90S_FITS) + len(source.DOCKS)
    ) == 20
    assert len(report["parts"]) == 20
    assert (rendered / "adapter_stls/tof_adjustable.stl").is_file()
    assert (rendered / "fit_stls/dock_contact_recess_gauge.stl").is_file()
    assert (rendered / "fit_stls/speaker_rect_fit_gauge.stl").is_file()
    assert (rendered / "fit_stls/speaker_rear_chamber_reference.stl").is_file()
    assert all(
        (rendered / f"fit_stls/{name}.stl").is_file()
        for name in source.MG90S_FITS
    )
    assert (rendered / "fit_stls/vl53l0x_gy530_fit_gauge.stl").is_file()
    assert (rendered / "dock_stls/dock_passive_fit.stl").is_file()
    assert (rendered / "dock_stls/dock_rail_entry_coupon.stl").is_file()
    assert (rendered / "dock_stls/dock_ir_pair_position_coupon.stl").is_file()
    assert (rendered / "fit_kit_manifest.json").is_file()
    assert report["parts"][1]["quantity_per_robot"] == 8
    assert all(item["installed_quantity_per_robot"] == 0
               for item in report["parts"])
    assert next(item for item in report["parts"]
                if item["part"] == "dock_rail_entry_coupon")[
                    "temporary_fit_coupon"
                ] is True
    assert next(item for item in report["parts"]
                if item["part"] == "head_bridge")[
                    "temporary_fit_coupon"
                ] is False
    assert all(item["manifold_edges"] == 6 for item in report["parts"])
    assert all(item["bbox_mm"]["dimensions_mm"] == [1.0, 1.0, 1.0]
               for item in report["parts"])
    assert report["power_fit_scope"] == source.POWER_FIT_SCOPE
    assert report["power_fit_scope"] == {
        "part": "battery_boost_tray",
        "protected_pack_body_only": True,
        "includes_connector_and_leads": False,
        "includes_charger": False,
        "includes_boost": False,
        "includes_fuse_switch": False,
        "whole_power_stack_fit_verified": False,
    }
    assert report["source_chassis_battery_footprint"] == {
        "source_mesh_only": True,
        "physical_interior_fit_verified": False,
        "reference_chassis_available": False,
        "axis_aligned_packaging_possible": None,
        "flat_tray_any_yaw_impossible": None,
    }
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
    forged_scope = json.loads(original)
    forged_scope["power_fit_scope"]["includes_boost"] = True
    manifest.write_text(json.dumps(forged_scope))
    with pytest.raises(ValueError, match="Unsafe power fit scope"):
        source.verify_fit_kit(tmp_path, output_dir=rendered)
    manifest.write_text(original)
    forged_scope = json.loads(original)
    forged_scope["power_fit_scope"]["whole_power_stack_fit_verified"] = True
    manifest.write_text(json.dumps(forged_scope))
    with pytest.raises(ValueError, match="Unsafe power fit scope"):
        source.verify_fit_kit(tmp_path, output_dir=rendered)
    manifest.write_text(original)
    forged_bounds = json.loads(original)
    forged_bounds["parts"][0]["bbox_mm"]["dimensions_mm"][0] = 999.0
    manifest.write_text(json.dumps(forged_bounds))
    with pytest.raises(ValueError, match="STL bounds changed"):
        source.verify_fit_kit(tmp_path, output_dir=rendered)
    manifest.write_text(original)
    forged_screen = json.loads(original)
    forged_screen["source_chassis_battery_footprint"][
        "physical_interior_fit_verified"
    ] = True
    manifest.write_text(json.dumps(forged_screen))
    with pytest.raises(ValueError, match="footprint screen changed"):
        source.verify_fit_kit(tmp_path, output_dir=rendered)
    manifest.write_text(original)
    for field, forged in (("installed_quantity_per_robot", 1),
                          ("temporary_fit_coupon", False)):
        changed = json.loads(original)
        coupon = next(item for item in changed["parts"]
                      if item["part"] == "dock_rail_entry_coupon")
        coupon[field] = forged
        manifest.write_text(json.dumps(changed))
        with pytest.raises(ValueError, match="Unqualified installed CAD part"):
            source.verify_fit_kit(tmp_path, output_dir=rendered)
    manifest.write_text(original)
    for field, forged in (
        ("part", "qualified_chassis"),
        ("quantity_per_robot", 0),
        ("quantity_per_robot", True),
        ("quantity_per_robot", 20),
        ("units", "inches"),
    ):
        changed = json.loads(original)
        changed["parts"][0][field] = forged
        manifest.write_text(json.dumps(changed))
        with pytest.raises(ValueError, match="Altered CAD part identity"):
            source.verify_fit_kit(tmp_path, output_dir=rendered)
    duplicate = original.replace(
        '"hardware_fit_verified": false',
        '"hardware_fit_verified": true, "hardware_fit_verified": false', 1,
    )
    manifest.write_text(duplicate)
    with pytest.raises(ValueError, match="Duplicate fit kit manifest key"):
        source.verify_fit_kit(tmp_path, output_dir=rendered)
    manifest.write_text(original.replace('"quantity_per_robot": 1',
                                         '"quantity_per_robot": NaN', 1))
    with pytest.raises(ValueError, match="Nonfinite fit kit manifest number"):
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
                 "speaker_rect_fit_gauge.scad", "vl53l0x_gy530_fit_gauge.scad",
                 "mg90s_pocket_fit_gauges.scad"):
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
        + len(source.MG90S_FITS) + len(source.DOCKS)
    ) == 20
    assert (output / "adapter_stls/speaker_grille.stl").is_file()
    assert (output / "dock_stls/dock_passive_fit.stl").is_file()
    assert (output / "dock_stls/dock_rail_entry_coupon.stl").is_file()
    assert (output / "dock_stls/dock_ir_pair_position_coupon.stl").is_file()
    assert (output / "fit_stls/speaker_rear_chamber_reference.stl").is_file()
    assert all((output / f"fit_stls/{name}.stl").is_file()
               for name in source.MG90S_FITS)
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
    assert dimensions == (36.0, 32.0, 3.0)
    # Both the free outside edge and nominal speaker gasket/pocket boundary
    # must retain at least 2 mm around M2 bores. This is a paper + STL
    # geometric screen, NOT a physical fastening or water/air seal trial.
    border = 8.0
    edge = 3.5
    bore_radius = 2.35 / 2
    pocket_clearance = 0.35
    assert edge - bore_radius >= 2.0
    assert border - edge - bore_radius - pocket_clearance >= 2.0
    for assignment, message in (
        ("speaker_grille_border=6", "gasket/pocket printable web"),
        ("speaker_grille_hole_edge=2", "outside printable web"),
    ):
        invalid = subprocess.run([
            "openscad", "--export-format", "binstl",
            "-o", str(tmp_path / "invalid_grille.stl"),
            "-D", 'part="speaker_grille"', "-D", assignment, str(source),
        ], capture_output=True, text=True, timeout=60)
        assert invalid.returncode != 0
        assert message in invalid.stderr + invalid.stdout
    # A watertight frontal plate is still not the tested speaker baffle,
    # mounting gasket, sealed 1cc box, or electrical/thermal certification.


def test_selected_gy530_board_outline_matches_provisional_eight_mount_brackets():
    """Do not silently keep the old 14x18 placeholder after selecting the SKU."""
    board = (ROOT / "docs/cad/remixes/vl53l0x_gy530_fit_gauge.scad").read_text()
    mounts = (ROOT / "docs/cad/remixes/one_robot_adapter_kit.scad").read_text()
    assert "SEN-19-006" in board and "SEN-19-006" in mounts
    assert "board_x = 10.5;" in board
    assert "board_y = 13.3;" in board
    assert "tof_pcb_w=10.5;" in mounts
    assert "tof_pcb_h=13.3;" in mounts
    assert "Lens center, holes, connector overhang and true mounting height UNMEASURED" in mounts


@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs OpenSCAD CLI")
def test_nonenergized_contact_gauge_refuses_overlap_with_m3_bores(tmp_path):
    """Keep real printed mounting material between the pocket and bolt bore."""
    source = ROOT / "docs/cad/remixes/remaining_fit_gauges.scad"
    good = tmp_path / "contact_good.stl"
    base = [
        "openscad", "--export-format", "binstl",
        "-D", 'part="dock_contact_recess_gauge"',
    ]
    subprocess.run(
        [*base, "-o", str(good), str(source)],
        check=True, capture_output=True, text=True, timeout=90,
    )
    assert module().closed_mesh_edges(good) > 0
    for too_close in ("38", "39"):
        bad = tmp_path / ("contact_bad_" + too_close + ".stl")
        completed = subprocess.run(
            [*base, "-D", f"contact_centers_mm={too_close}",
             "-o", str(bad), str(source)],
            capture_output=True, text=True, timeout=90,
        )
        assert "Contact recess would intersect or thin" in (
            completed.stderr + completed.stdout
        )
        # An OpenSCAD error may leave a file; never treat it as a print
        # candidate if the parameter assertion was raised.


@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs OpenSCAD CLI")
@pytest.mark.parametrize(("override", "expected"), [
    ("contact_pocket_depth_mm=8", "insufficient insulated floor"),
    ("contact_carrier_w=7", "breaches side wall"),
])
def test_contact_gauge_refuses_unsafe_floor_or_side_web(tmp_path, override, expected):
    source = ROOT / "docs/cad/remixes/remaining_fit_gauges.scad"
    output = tmp_path / "unsafe_contact.stl"
    command = [
        "openscad", "--export-format", "binstl",
        "-D", 'part="dock_contact_recess_gauge"',
        "-D", override, "-o", str(output), str(source),
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=90,
    )
    assert expected in result.stderr + result.stdout


def test_gy530_bracket_does_not_drill_unmeasured_pcb_holes_through_optics():
    """The 10.5mm pilot PCB cannot fit prior overlapping 6mm M2 slots."""
    source = (ROOT / "docs/cad/remixes/one_robot_adapter_kit.scad").read_text()
    assert "tof_pcb_w=10.5;" in source
    assert "No fake GY-530 PCB screw holes" in source
    assert "for(x=[-tof_pcb_w/2+2,tof_pcb_w/2-2])" not in source
    assert "This is an aperture/angle reference ONLY" in source
    assert 'else if(part=="tof_adjustable")' in source

@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs OpenSCAD CLI")
def test_apriltag_backplate_has_printable_mount_web_and_through_bores(tmp_path):
    """CGAL mesh verifies the four real through holes, including the rear rib.

    The old 80 mm plate with 76 mm hole centers left just 0.325 mm of edge
    web, and the rear two holes stopped inside a 12 mm reinforcement.
    """
    import re
    from struct import unpack_from

    cad = ROOT / "docs/cad/remixes/one_robot_adapter_kit.scad"
    source = cad.read_text(encoding="utf-8")

    def scalar(name):
        match = re.search(
            r"^" + re.escape(name) + r"\s*=\s*([0-9.]+)\s*;",
            source, re.M,
        )
        assert match is not None, name
        return float(match.group(1))

    pitch = scalar("dock_mount_spacing")
    bore = scalar("m3_clearance_d")
    minimum_web = scalar("dock_tag_edge_web_mm")
    output = tmp_path / "dock_tag_backplate.stl"
    subprocess.run(
        ["openscad", "--export-format", "binstl", "-o", str(output),
         "-D", 'part="dock_tag_backplate"', str(cad)],
        check=True, capture_output=True, text=True, timeout=60,
    )
    assert module().closed_mesh_edges(output) > 0
    mesh = output.read_bytes()
    count = unpack_from("<I", mesh, 80)[0]
    faces = [
        tuple(unpack_from("<3f", mesh, 84 + 50 * i + 12 + 12 * j)
              for j in range(3))
        for i in range(count)
    ]
    xs = [vertex[0] for face in faces for vertex in face]
    ys = [vertex[1] for face in faces for vertex in face]
    # Check the exported mesh, not the SCAD author's intended expression.
    assert (max(xs) - min(xs) - pitch - bore) / 2 >= minimum_web - 0.01
    assert (max(ys) - min(ys) - pitch - bore) / 2 >= minimum_web - 0.01

    def blocks_vertical_bore(x, y, face):
        """Does a triangle fill any point on the bolt's centerline?"""
        (ax, ay, _), (bx, by, _), (cx, cy, _) = face
        determinant = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(determinant) < 1e-8:
            return False
        u = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / determinant
        v = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / determinant
        return min(u, v, 1 - u - v) > 1e-6

    for x in (-pitch / 2, pitch / 2):
        for y in (-pitch / 2, pitch / 2):
            assert not any(blocks_vertical_bore(x, y, face)
                           for face in faces), (x, y)


def test_selected_protected_pack_body_cannot_be_silently_undersized(tmp_path):
    """The current 86 mm candidate body cannot use the old 68 mm tray."""
    source = ROOT / "docs/cad/remixes/remaining_fit_gauges.scad"
    text = source.read_text(encoding="utf-8")
    assert "candidate_pack_body_l_mm = 86;" in text
    assert "power_l = 86;" in text
    assert "power_l >= candidate_pack_body_l_mm" in text
    if not shutil.which("openscad"):
        pytest.skip("OpenSCAD not installed for negative gauge render")
    output = tmp_path / "undersized_pack.stl"
    result = subprocess.run(
        ["openscad", "--export-format", "binstl", "-o", str(output),
         "-D", 'part="battery_boost_tray"', "-D", "power_l=68",
         str(source)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0
    assert "Battery tray shorter than selected candidate pack body" in (
        result.stdout + result.stderr
    )
    assert not output.exists() or output.stat().st_size == 0


@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs OpenSCAD CLI")
def test_actual_source_chassis_cannot_contain_86mm_tray_on_axis(tmp_path):
    """Source STL versus actual OpenSCAD tray triangles, not a CAD drawing."""
    script = module()
    chassis = ROOT / (
        "docs/cad/originals/smars-stepper/SMARS_2BJY8-Chassis.stl"
    )
    assert chassis.is_file()
    output = tmp_path / "fit_stls/battery_boost_tray.stl"
    output.parent.mkdir(parents=True)
    subprocess.run([
        "openscad", "--export-format", "binstl", "-o", str(output),
        "-D", 'part="battery_boost_tray"',
        str(ROOT / "docs/cad/remixes/remaining_fit_gauges.scad"),
    ], check=True, capture_output=True, text=True, timeout=120)
    screen = script.reference_body_footprint_screen(ROOT, tmp_path)
    assert screen["reference_chassis_available"] is True
    assert screen["source_mesh_only"] is True
    assert screen["physical_interior_fit_verified"] is False
    assert max(screen["candidate_tray_xy_mm"]) > max(
        screen["reference_chassis_xy_mm"]
    )
    assert screen["axis_aligned_packaging_possible"] is False
    assert screen["flat_tray_any_yaw_impossible"] is True
    assert screen["chassis_outer_xy_diagonal_mm"] < max(
        screen["candidate_tray_xy_mm"]
    )


def test_flat_tray_diagonal_bound_distinguishes_rotation_from_impossibility(tmp_path):
    """A yaw-independent impossibility proof must not reject any mere 90deg miss.

    We synthesize closed tetra meshes with exact XY coordinate bounds. These
    are geometry unit fixtures, never representations of the real robot.
    """
    from struct import pack_into, unpack_from

    source = module()
    root = tmp_path / "repo"
    chassis = root / (
        "docs/cad/originals/smars-stepper/SMARS_2BJY8-Chassis.stl"
    )
    candidate = tmp_path / "out/fit_stls/battery_boost_tray.stl"
    chassis.parent.mkdir(parents=True)
    candidate.parent.mkdir(parents=True)

    def scaled_tetra(x_mm, y_mm):
        blob = bytearray(tetra_stl())
        for face in range(4):
            for corner in range(3):
                start = 84 + 50 * face + 12 + 12 * corner
                x, y = unpack_from("<ff", blob, start)
                pack_into("<ff", blob, start, x * x_mm, y * y_mm)
        return bytes(blob)

    chassis.write_bytes(scaled_tetra(58, 86))
    candidate.write_bytes(scaled_tetra(90, 10))
    uncertain = source.reference_body_footprint_screen(root, candidate.parents[1])
    assert uncertain["axis_aligned_packaging_possible"] is False
    assert uncertain["flat_tray_any_yaw_impossible"] is False
    assert uncertain["physical_interior_fit_verified"] is False
    candidate.write_bytes(scaled_tetra(110, 10))
    excluded = source.reference_body_footprint_screen(root, candidate.parents[1])
    assert excluded["flat_tray_any_yaw_impossible"] is True
    assert excluded["axis_aligned_packaging_possible"] is False
    candidate.write_bytes(scaled_tetra(50, 80))
    possible_on_axes = source.reference_body_footprint_screen(
        root, candidate.parents[1]
    )
    assert possible_on_axes["axis_aligned_packaging_possible"] is True
    assert possible_on_axes["flat_tray_any_yaw_impossible"] is False
    assert possible_on_axes["physical_interior_fit_verified"] is False


def test_protected_pack_audit_tracks_active_fit_coupon_dimensions():
    """The buying audit must not keep the retired 68 mm battery tray claim."""
    scad = (
        ROOT / "docs/cad/remixes/remaining_fit_gauges.scad"
    ).read_text(encoding="utf-8")
    audit = (
        ROOT / "docs/hardware/2026-11-17-protected-pack-and-connector-audit.md"
    ).read_text(encoding="utf-8")

    def scalar(name):
        prefix = name + " = "
        line = next(
            line for line in scad.splitlines()
            if line.strip().startswith(prefix)
        )
        return float(line.split("=", 1)[1].split(";", 1)[0].strip())

    dims = tuple(scalar(name) for name in ("power_l", "power_w", "power_h"))
    assert dims == (86.0, 35.0, 14.0)
    assert "86 x 35 x 14 mm" in audit
    assert "Current 86 x 35 x 14 nominal pack cavity" in audit
    assert "Current 68 x 35 x 14 nominal tray" not in audit
    assert "length 86 mm before wire relief exceeds 68 mm" not in audit
    assert "70 mm leads, bend radius" in audit
    assert "107.6 x 40.6 mm" in audit



@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs OpenSCAD CLI")
def test_speaker_rear_chamber_reference_retains_conservative_air_budget(tmp_path):
    """A closed rear pocket and gasket land are necessary, never sufficient."""
    scad = ROOT / "docs/cad/remixes/speaker_rect_fit_gauge.scad"
    adapter = ROOT / "docs/cad/remixes/one_robot_adapter_kit.scad"
    speaker_text = scad.read_text(encoding="utf-8")
    grille_text = adapter.read_text(encoding="utf-8")
    assert "speaker_chamber_border=8;" in speaker_text
    assert "speaker_grille_border=8;" in grille_text
    assert "speaker_chamber_hole_edge=3.5;" in speaker_text
    assert "speaker_grille_hole_edge=3.5;" in grille_text
    assert "speaker_chamber_bolt_d=2.35;" in speaker_text
    assert "m2_clearance_d=2.35;" in grille_text
    output = tmp_path / "rear.stl"
    subprocess.run([
        "openscad", "--export-format", "binstl", "-o", str(output),
        "-D", 'part="speaker_rear_chamber_reference"', str(scad),
    ], check=True, capture_output=True, text=True, timeout=120)
    verifier = module()
    assert verifier.closed_mesh_edges(output) > 0
    box = verifier.mesh_bounds_mm(output)
    assert box["dimensions_mm"] == [36.0, 32.0, 11.4]
    inner_l, inner_w, depth = 20.7, 16.7, 9.0
    conservative_air_mm3 = inner_l * inner_w * depth - 20 * 16 * 4.7
    assert conservative_air_mm3 >= 1000
    for override, message in (
        ("speaker_chamber_depth=6", "nominal net air volume below 1cc"),
        ("speaker_chamber_hole_edge=2", "bolt breaches outer wall"),
        ("speaker_chamber_border=6", "bolt breaches gasket land"),
    ):
        bad = subprocess.run([
            "openscad", "--export-format", "binstl",
            "-o", str(tmp_path / "invalid_rear.stl"),
            "-D", 'part="speaker_rear_chamber_reference"',
            "-D", override, str(scad),
        ], capture_output=True, text=True, timeout=90)
        assert bad.returncode != 0
        assert message in bad.stderr + bad.stdout

def test_adapter_readme_fit_reference_count_tracks_exporter():
    """Builder print counts must follow the exporter instead of stale prose."""
    source = module()
    readme = (
        ROOT / "docs/cad/remixes/one_robot_adapter_kit_README.md"
    ).read_text(encoding="utf-8")
    fit_count = (
        len(source.GAUGES)
        + len(source.SPEAKER_FITS)
        + len(source.MG90S_FITS)
        + len(source.RANGER_FITS)
        + len(source.DOCKS)
    )
    assert len(source.MG90S_FITS) == 4
    assert fit_count == 13
    assert f"current **{fit_count}** provisional fit references" in readme
    assert f"up to {fit_count} provisional dock, battery, contact" in readme
    assert "up to nine provisional" not in readme



def test_printer_build_volume_screen_preserves_unknown_orientations_and_safety():
    """A small or large printer cannot implicitly qualify a physical build."""
    screen = module().screen_print_bed_fit
    report = {"parts": [
        {"location": "fit_stls/speaker_rear_chamber_reference.stl",
         "bbox_mm": {"dimensions_mm": [36.0, 32.0, 11.4]}},
        {"location": "dock_stls/dock_passive_fit.stl",
         "bbox_mm": {"dimensions_mm": [126.0, 138.0, 93.0]}},
    ]}
    large = screen(report, (150, 160, 150))
    assert all(p["fits_source_bounds_flat_at_zero_or_ninety_deg"]
               for p in large["parts"])
    assert not large["physical_printer_or_material_qualified"]
    assert not any(p["other_orientation_or_support_fit_qualified"]
                   for p in large["parts"])
    tight = screen(report, (100, 100, 100))
    assert tight["parts"][0]["fits_source_bounds_flat_at_zero_or_ninety_deg"]
    assert not tight["parts"][1]["fits_source_bounds_flat_at_zero_or_ninety_deg"]
    # A 138 mm physical span fits within the 141 mm plate diagonal, so
    # reject a false claim that EVERY planar yaw is impossible.
    assert not tight["parts"][1]["flat_yaw_impossible_by_plate_diagonal"]
    small = screen(report, (70, 70, 75))
    assert small["parts"][1]["flat_yaw_impossible_by_plate_diagonal"]
    assert small["parts"][1]["flat_height_exceeds_build_volume"]


@pytest.mark.parametrize("printer", [
    (0, 100, 100), (True, 100, 100), (float("nan"), 100, 100),
    (float("inf"), 100, 100), (100, -1, 100),
    (100, 100), "100x100x100", (100, 100, 10**1000),
])
def test_print_screen_rejects_bad_build_volume(printer):
    with pytest.raises(ValueError, match="Printer X/Y/Z"):
        module().screen_print_bed_fit({"parts": []}, printer)


def test_print_screen_rejects_forged_or_missing_mesh_dimensions():
    screen = module().screen_print_bed_fit
    for dims in (None, [-1, 10, 10], [True, 10, 10],
                 [float("inf"), 10, 10], [10, 10], [0, 10, 10]):
        with pytest.raises(ValueError, match="STL build envelope"):
            screen({"parts": [{"location": "fit_stls/a.stl",
                               "bbox_mm": {"dimensions_mm": dims}}]},
                   (180, 180, 180))
