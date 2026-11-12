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
    script = SCRIPT.read_text()
    assert "MillimeterMeshUnit" in script
    assert "DirectDesignType" in script
    assert "occurrences.addNewComponent" in script
    assert "Interference" in script
