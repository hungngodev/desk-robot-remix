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
    generated = sum(
        (ROOT / "docs/cad/remixes/adapter_stls" / (name + ".stl")).is_file()
        for name in source.ADAPTER_NAMES
    )
    assert len(manifest) == len(source.SOURCE_MESHES) + generated
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
    assert "verify_optional_fit_references(repo)" in implementation
    assert "MillimeterMeshUnit" in implementation
    assert "DirectDesignType" in implementation
    assert "occurrences.addNewComponent" in implementation
    assert "Inspect > Interference" in (
        ROOT / "docs/cad/FUSION_ONE_ROBOT_ASSEMBLY.md"
    ).read_text(encoding="utf-8")


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
