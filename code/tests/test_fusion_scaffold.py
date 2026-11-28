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
    """All sixteen optional fit references are preserved by the old GUI name.

    build_manifest() is a path plan only. The GUI run additionally verifies
    export_fit_kit's hash and unqualified flags before importing meshes.
    """
    source = load_script()
    assert len(source.FIT_REFERENCES) == 16
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
    assert len(names_paths) == (
        len(source.SOURCE_MESHES) + len(source.ADAPTER_NAMES)
        + len(source.FIT_REFERENCES)
    )
    assert len({name for name, _ in names_paths}) == len(names_paths)
    assert {path for _, path in names_paths} == {
        *(tmp_path / rel for _, rel in source.SOURCE_MESHES),
        *adapters,
        *fits,
    }
    # Only an optional candidate disappears when its file is absent;
    # a required source mesh must still fail hard.
    fits[-1].unlink()
    assert len(source.build_manifest(tmp_path)) == len(names_paths) - 1
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
    for rel in (*pinned, *canonical["SOURCE_ATTRIBUTION_GIT_BLOBS"]):
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

def test_power_and_dock_seat_measurements_are_separate_physical_inputs():
    """Do not collapse omitted power hardware or two seat switches into placeholders."""
    sheet = (ROOT / "docs/cad/FUSION_MEASUREMENT_SHEET.md").read_text(
        encoding="utf-8"
    )
    required = (
        "pack_body_w / pack_body_l / pack_body_h",
        "pack_connector_w / pack_connector_l / pack_connector_h",
        "pack_lead_free_l / pack_lead_awg / pack_lead_bend_r",
        "charger_w / charger_l / charger_h / charger_service_clearance",
        "boost_w / boost_l / boost_h / boost_thermal_clearance",
        "fuse_envelope / switch_envelope / power_strain_relief",
        "battery_service_clearance",
        "dock_seat_body / dock_seat_mount_pitch / dock_seat_hole_d",
        "dock_seat_fp / dock_seat_op / dock_seat_overtravel",
        "dock_seat_wire_clearance",
    )
    assert all(item in sheet for item in required)
    assert "Battery and charge/boost enclosure width / length / height" not in sheet
    assert "dock_seat_left / dock_seat_right / dock_seat_overtravel" not in sheet
    assert "Do not fabricate any blank measurement" in sheet

def test_cozmars_packaging_precedes_sparky_fallback_without_copying_unlicensed_cad():
    """Accepted packaging order keeps external Cozmars CAD out of our source tree."""
    guide = (ROOT / "docs/cad/FUSION_ONE_ROBOT_ASSEMBLY.md").read_text(
        encoding="utf-8"
    )
    cozmars = guide.index("## Cozmars packaging comparison before Sparky fallback")
    sparky = " ".join(guide.split()).index("insert the **Sparky v0.1** shell")
    assert cozmars < guide.index("**Sparky v0.1**")
    assert sparky > 0
    assert "515f980d4ee91f6a279406085f591b882254aad8" in guide
    assert "4ea3952fdc452081dfc711839e8b500e033a20ee" in guide
    assert "aabc2da472af675a90ad51e425bd576ba1d31383" in guide
    assert "contains no LICENSE file" in guide
    assert "Creative Commons Attribution NonCommercial ShareAlike" in guide
    assert "Do not copy its F3Z or STEP into this repository" in guide
    assert "Sparky therefore remains executable fallback geometry" in guide
    assert not (ROOT / "docs/cad/originals/cozmars-v2").exists()



def test_fusion_original_attribution_must_remain_with_pinned_meshes(tmp_path):
    import pytest

    canonical = load_script()._load()
    verify = canonical["verify_original_source_revisions"]
    records = canonical["SOURCE_ATTRIBUTION_GIT_BLOBS"]
    meshes = canonical["SOURCE_MESH_GIT_BLOBS"]
    expected_records = {
        (Path(rel).parent / "source.json").as_posix() for rel in meshes
    } | {"docs/cad/originals/sparky-head/LICENSE.md"}
    assert set(records) == expected_records
    for rel in (*meshes, *records):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / rel).read_bytes())
    assert verify(tmp_path) == meshes
    for rel in records:
        path = tmp_path / rel
        original = path.read_bytes()
        path.write_bytes(b'{"license": "MIT"}')
        with pytest.raises(ValueError, match="Original CAD attribution changed"):
            verify(tmp_path)
        path.unlink()
        with pytest.raises(FileNotFoundError, match="Missing original CAD attribution"):
            verify(tmp_path)
        path.write_bytes(original)
    assert verify(tmp_path) == meshes


def _stage_full_fusion_repo(tmp_path: Path, *, include_fits: bool = False):
    canonical = load_script()._load()
    for rel in (*canonical["SOURCE_MESH_GIT_BLOBS"], *canonical["SOURCE_ATTRIBUTION_GIT_BLOBS"]):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / rel).read_bytes())
    script_copy = tmp_path / "code/scripts/export_fit_kit.py"
    script_copy.parent.mkdir(parents=True, exist_ok=True)
    script_copy.write_text(
        (ROOT / "code/scripts/export_fit_kit.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    if include_fits:
        fit = tmp_path / "docs/cad/remixes/fit_stls/battery_boost_tray.stl"
        fit.parent.mkdir(parents=True, exist_ok=True)
        fit.write_bytes(b"stale fit stl")
    return canonical


def _fake_adsk_modules():
    from types import ModuleType, SimpleNamespace

    events = []
    messages = []
    imported_meshes = []

    class FakeMatrix3D:
        @staticmethod
        def create():
            matrix = ("identity-matrix",)
            return matrix

    class FakeOccurrences:
        def addNewComponent(self, transform):
            events.append(("addNewComponent", transform))
            comp = SimpleNamespace(name=None, meshBodies=None)

            class FakeMeshBodies:
                def add(self, path_str, unit):
                    imported_meshes.append((comp.name, path_str, unit))
                    events.append(("meshBodies.add", comp.name, unit))
                    return SimpleNamespace(count=1)

            comp.meshBodies = FakeMeshBodies()
            return SimpleNamespace(component=comp)

    design_obj = SimpleNamespace(
        designType=None,
        rootComponent=SimpleNamespace(occurrences=FakeOccurrences()),
    )

    class FakeDocuments:
        def add(self, doc_type):
            events.append(("documents.add", doc_type))
            return design_obj

    class FakeUI:
        def messageBox(self, msg):
            messages.append(msg)

    app_obj = SimpleNamespace(
        documents=FakeDocuments(),
        activeProduct=design_obj,
        userInterface=FakeUI(),
    )

    adsk_mod = ModuleType("adsk")
    core_mod = ModuleType("adsk.core")
    fusion_mod = ModuleType("adsk.fusion")
    core_mod.Application = SimpleNamespace(get=lambda: app_obj)
    core_mod.DocumentTypes = SimpleNamespace(FusionDesignDocumentType="FusionDesignDocumentType")
    core_mod.Matrix3D = FakeMatrix3D
    fusion_mod.Design = SimpleNamespace(cast=lambda product: product)
    fusion_mod.DesignTypes = SimpleNamespace(DirectDesignType="DirectDesignType")
    fusion_mod.MeshUnits = SimpleNamespace(MillimeterMeshUnit="MillimeterMeshUnit")
    adsk_mod.core = core_mod
    adsk_mod.fusion = fusion_mod
    return {
        "adsk": adsk_mod,
        "adsk.core": core_mod,
        "adsk.fusion": fusion_mod,
    }, events, messages, imported_meshes


def test_fusion_run_verifies_attribution_and_optional_fit_before_creating_document(
    tmp_path, monkeypatch,
):
    import sys

    _stage_full_fusion_repo(tmp_path)
    adsk_modules, events, messages, imported = _fake_adsk_modules()
    for name, mod in adsk_modules.items():
        monkeypatch.setitem(sys.modules, name, mod)

    wrapper = load_script()
    scaffold_ns = wrapper._load()
    call_order = []
    orig_verify_orig = scaffold_ns["verify_original_source_revisions"]
    orig_jaw = scaffold_ns["jaw_topology_warning"]
    orig_verify_fit = scaffold_ns["verify_optional_fit_references"]

    def spy_verify_orig(repo):
        call_order.append("verify_original_source_revisions")
        return orig_verify_orig(repo)

    def spy_jaw(repo):
        call_order.append("jaw_topology_warning")
        return orig_jaw(repo)

    def spy_verify_fit(repo):
        call_order.append("verify_optional_fit_references")
        return orig_verify_fit(repo)

    # Test canonical run() via module globals patched in-place.
    run_fn = scaffold_ns["run"]
    run_fn.__globals__["find_repo"] = lambda _p: tmp_path
    run_fn.__globals__["verify_original_source_revisions"] = spy_verify_orig
    run_fn.__globals__["jaw_topology_warning"] = spy_jaw
    run_fn.__globals__["verify_optional_fit_references"] = spy_verify_fit

    # Ensure documents.add cannot execute until attribution + fit checks finish.
    orig_doc_add = adsk_modules["adsk.core"].Application.get().documents.add

    def traced_doc_add(doc_type):
        call_order.append("documents.add")
        return orig_doc_add(doc_type)

    adsk_modules["adsk.core"].Application.get().documents.add = traced_doc_add
    run_fn(None)

    assert call_order == [
        "verify_original_source_revisions",
        "jaw_topology_warning",
        "verify_optional_fit_references",
        "documents.add",
    ]
    assert len(imported) == 12
    assert all(unit == "MillimeterMeshUnit" for _, _, unit in imported)
    assert all(
        ev[1] == ("identity-matrix",) for ev in events if ev[0] == "addNewComponent"
    )
    assert len(messages) == 1
    assert "No candidate kit imported; physical packaging is unqualified." in messages[0]
    assert "JAW TOPOLOGY HOLD:" in messages[0]

    # Also invoke the legacy wrapper entrypoint end-to-end with failing fit receipt.
    fit_dir = tmp_path / "docs/cad/remixes/fit_stls"
    fit_dir.mkdir(parents=True, exist_ok=True)
    (fit_dir / "battery_boost_tray.stl").write_bytes(b"stale unverified fit")
    events.clear()
    imported.clear()
    messages.clear()

    orig_load = wrapper._load

    def loaded_with_staged_root():
        ns = orig_load()
        ns["run"].__globals__["find_repo"] = lambda _p: tmp_path
        return ns

    monkeypatch.setattr(wrapper, "_load", loaded_with_staged_root)
    wrapper.run(None)
    assert not any(ev[0] == "documents.add" for ev in events)
    assert imported == []
    assert len(messages) == 1
    assert "Desk robot Fusion import failure:" in messages[0]
