"""Static manifest checks; running Fusion's GUI and MeshBodies.add is a separate test."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "docs/cad/remixes/fusion_assembly_scaffold.py"


def load_script():
    spec = importlib.util.spec_from_file_location("robot_fusion_scaffold", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fusion_source_manifest_is_complete_and_not_a_fake_assembly():
    source = load_script()
    assert len(source.SOURCE_MESHES) == 12
    assert len(source.ADAPTER_NAMES) == 7
    assert len(set(name for name, _ in source.SOURCE_MESHES)) == 12
    assert all((ROOT / path).is_file() for _, path in source.SOURCE_MESHES)
    assert source.find_repository(SCRIPT) == ROOT
    # The generated adapter kit may exist after running the supported export
    # command. Tests must not fail merely because a user built the STLs.
    manifest = source.build_manifest(ROOT)
    adapter_candidates = sum(
        (ROOT / "docs/cad/remixes/adapter_stls" / (name + ".stl")).is_file()
        for name in source.ADAPTER_NAMES
    )
    fit_candidates = sum(
        (ROOT / "docs/cad/remixes" / rel).is_file()
        for _, rel in source.FIT_REFERENCES
    )
    assert len(manifest) == (
        len(source.SOURCE_MESHES) + adapter_candidates + fit_candidates
    )
    assert all(path.is_file() for _, path in manifest)
    # The legacy entrypoint delegates to ONE canonical Fusion implementation.
    # Test the real mesh importer rather than demanding duplicate API code
    # inside the compatibility wrapper.
    wrapper = SCRIPT.read_text(encoding="utf-8")
    implementation = SCRIPT.with_name("fusion_one_robot_scaffold.py").read_text(
        encoding="utf-8"
    )
    canonical = source._load()
    assert "fusion_one_robot_scaffold.py" in wrapper
    assert 'return _load()["run"](context)' in wrapper
    assert source.SOURCE_MESHES == canonical["SOURCE_MESHES"]
    assert source.ADAPTER_NAMES == canonical["ADAPTER_NAMES"]
    assert source.FIT_REFERENCES == canonical["FIT_REFERENCES"]
    assert "verify_optional_fit_references(repo)" in implementation
    assert "MillimeterMeshUnit" in implementation
    assert "DirectDesignType" in implementation
    assert "occurrences.addNewComponent" in implementation
    # The guide wraps this Fusion command across Markdown source lines.
    # Normalize whitespace instead of treating ordinary formatting as a
    # missing physical interference check.
    assembly = (
        ROOT / "docs/cad/FUSION_ONE_ROBOT_ASSEMBLY.md"
    ).read_text(encoding="utf-8")
    assert "Inspect > Interference" in " ".join(assembly.split())


def test_mechanical_sheet_never_approves_premium_ranger_or_mismatched_pack():
    """Mechanical shopping gate needs the current generic sensor and real fit."""
    sheet = (ROOT / "docs/cad/FUSION_MEASUREMENT_SHEET.md").read_text(
        encoding="utf-8"
    )
    gauge = (ROOT / "docs/cad/remixes/remaining_fit_gauges.scad").read_text(
        encoding="utf-8"
    )
    assert "VL53L0X GY-530" in sheet
    assert "VL53L4CD" not in sheet
    # The former 68 mm coupon could not hold the candidate 86 mm pack
    # body. We now reject that undersize, while NEVER claiming full power
    # assembly fit, lead bend, safe charging or mounting qualification.
    assert "candidate_pack_body_l_mm = 86;" in gauge
    assert "power_l = 86;" in gauge
    assert "power_l >= candidate_pack_body_l_mm" in gauge
    assert "86 mm" in sheet and "68 mm" in sheet
    assert "undersized" in sheet
    assert "unqualified" in sheet


def test_exported_candidate_fits_survive_legacy_fusion_entrypoint(tmp_path):
    """All thirteen optional fit references are preserved by the old GUI name.

    build_manifest() is a path plan only. The GUI run additionally verifies
    export_fit_kit's hash and unqualified flags before importing meshes.
    """
    source = load_script()
    assert len(source.FIT_REFERENCES) == 13
    for _, rel in source.SOURCE_MESHES:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"source mesh fixture")
    adapters = [
        tmp_path / "docs/cad/remixes/adapter_stls" / (name + ".stl")
        for name in source.ADAPTER_NAMES
    ]
    fits = [
        tmp_path / "docs/cad/remixes" / rel
        for _, rel in source.FIT_REFERENCES
    ]
    for path in adapters + fits:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"generated candidate fixture")
    names_paths = source.build_manifest(tmp_path)
    assert len(names_paths) == 12 + 7 + 13
    assert len({name for name, _ in names_paths}) == len(names_paths)
    assert {path for _, path in names_paths} == {
        *(tmp_path / rel for _, rel in source.SOURCE_MESHES),
        *adapters,
        *fits,
    }
    # Only an optional candidate disappears when its file is absent;
    # a required source mesh must still fail hard.
    fits[-1].unlink()
    assert len(source.build_manifest(tmp_path)) == 31
    (tmp_path / source.SOURCE_MESHES[0][1]).unlink()
    try:
        source.build_manifest(tmp_path)
    except FileNotFoundError as exc:
        assert "Missing source mesh" in str(exc)
    else:
        raise AssertionError("Missing original chassis must fail closed")


def test_fusion_gui_exposes_protected_pack_source_footprint_block():
    """Verified CAD conflicts cannot disappear inside a successful mesh import."""
    canonical = load_script()._load()
    warning = canonical["packaging_warning"]
    blocked = {
        "source_chassis_battery_footprint": {
            "source_mesh_only": True,
            "physical_interior_fit_verified": False,
            "reference_chassis_available": True,
            "reference_chassis_xy_mm": [58.002, 86.194],
            "candidate_tray_xy_mm": [107.6, 40.6],
            "axis_aligned_packaging_possible": False,
            "flat_tray_any_yaw_impossible": True,
        },
        "power_fit_scope": {
            "part": "battery_boost_tray",
            "protected_pack_body_only": True,
            "includes_connector_and_leads": False,
            "includes_charger": False,
            "includes_boost": False,
            "includes_fuse_switch": False,
            "whole_power_stack_fit_verified": False,
        },
    }
    assert "BATTERY PACKAGING CONFLICT" in warning(blocked)
    assert "Rotating the coupon flat cannot fix this" in warning(blocked)
    assert "before final printing" in warning(blocked)
    possible = {
        "source_chassis_battery_footprint": {
            **blocked["source_chassis_battery_footprint"],
            "axis_aligned_packaging_possible": True,
            "flat_tray_any_yaw_impossible": False,
        },
        "power_fit_scope": blocked["power_fit_scope"],
    }
    assert "physical fit remain OPEN" in warning(possible)
    assert "unqualified" in warning(None)
    import pytest
    with pytest.raises(ValueError, match="provenance"):
        warning({
            "source_chassis_battery_footprint": {
                "physical_interior_fit_verified": True,
                "axis_aligned_packaging_possible": True,
            },
            "power_fit_scope": blocked["power_fit_scope"],
        })
    with pytest.raises(ValueError, match="power fit scope"):
        warning({
            "source_chassis_battery_footprint": blocked[
                "source_chassis_battery_footprint"
            ],
            "power_fit_scope": {
                **blocked["power_fit_scope"],
                "includes_boost": True,
            },
        })


def test_original_licensed_fusion_meshes_are_revision_pinned(tmp_path):
    """The real 12 upstream meshes cannot drift without a reviewed revision."""
    canonical = load_script()._load()
    verify = canonical["verify_original_source_revisions"]
    pinned = canonical["SOURCE_MESH_GIT_BLOBS"]
    assert len(pinned) == len(canonical["SOURCE_MESHES"]) == 12
    assert verify(ROOT) == pinned
    for rel in pinned:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / rel).read_bytes())
    assert verify(tmp_path) == pinned
    first = tmp_path / canonical["SOURCE_MESHES"][0][1]
    first.write_bytes(first.read_bytes() + b"tampered mesh")
    import pytest
    with pytest.raises(ValueError, match="Original licensed CAD source changed"):
        verify(tmp_path)
    first.unlink()
    with pytest.raises(FileNotFoundError, match="Missing original CAD source"):
        verify(tmp_path)
