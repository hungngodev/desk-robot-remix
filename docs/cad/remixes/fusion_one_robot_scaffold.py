"""Fusion 360 script: import Desk Robot 01's REAL source STLs into components.

Fusion: Utilities > Scripts and Add-Ins. Save this script inside a cloned
desk-robot-remix/docs/cad/remixes directory. It creates a NEW design.
Source meshes have arbitrary coordinates; this does not align joints,
generate missing mounts, or certify any printed part or charging circuit.
"""
from pathlib import Path
from hashlib import sha1
import runpy
import traceback

SOURCE_MESHES = (
    ("01 Stepper Chassis", "docs/cad/originals/smars-stepper/SMARS_2BJY8-Chassis.stl"),
    ("02 Stepper Rear Wheel", "docs/cad/originals/smars-stepper/SMARS_28BYJ-48-RearWheel.stl"),
    ("03 Slave Wheel", "docs/cad/originals/smars/slave_wheel_SL.stl"),
    ("04 Track Link", "docs/cad/originals/smars/mechanical_track.stl"),
    ("05 Forklift E", "docs/cad/originals/forklift/fork_lift_e.stl"),
    ("06 Forklift F", "docs/cad/originals/forklift/fork_lift_f.stl"),
    ("07 Jaw Servo Case", "docs/cad/originals/gripper/servo_case_arm.stl"),
    ("08 Jaw Rack", "docs/cad/originals/gripper/arm_rack.stl"),
    ("09 Jaw Pinion", "docs/cad/originals/gripper/pinion_gear.stl"),
    ("10 Sparky Shell", "docs/cad/originals/sparky-head/sparky_shell.stl"),
    ("11 Sparky Collar", "docs/cad/originals/sparky-head/sparky_collar.stl"),
    ("12 Sparky Lid", "docs/cad/originals/sparky-head/sparky_lid.stl"),
)

ADAPTER_NAMES = (
    "head_bridge", "tof_adjustable", "oled_bezel", "speaker_grille",
    "fsr_jaw_pocket", "dock_tag_backplate", "wire_clip",
)

# These are unaligned dimensional references, NOT finished fitted components.
# export_fit_kit.py generates them from the same provisional SCAD sources.
FIT_REFERENCES = (
    ("Passive Dock Fit Only", "dock_stls/dock_passive_fit.stl"),
    ("Dock Entry Coupon Only", "dock_stls/dock_rail_entry_coupon.stl"),
    ("Unpowered IR Pair Spacing Coupon Only",
     "dock_stls/dock_ir_pair_position_coupon.stl"),
    ("Battery Tray Gauge Only", "fit_stls/battery_boost_tray.stl"),
    ("Contact Pocket Gauge Only", "fit_stls/dock_contact_recess_gauge.stl"),
    ("Jaw Reference Coupon Only", "fit_stls/jaw_calibration_coupon.stl"),
    ("Speaker Fit Gauge Only", "fit_stls/speaker_rect_fit_gauge.stl"),
    ("Unqualified 1cc Speaker Chamber Reference Only",
     "fit_stls/speaker_rear_chamber_reference.stl"),
    ("MG90S 0.15mm Case Coupon Only", "fit_stls/mg90s_fit_015.stl"),
    ("MG90S 0.30mm Case Coupon Only", "fit_stls/mg90s_fit_030.stl"),
    ("MG90S 0.45mm Case Coupon Only", "fit_stls/mg90s_fit_045.stl"),
    ("MG90S 0.60mm Case Coupon Only", "fit_stls/mg90s_fit_060.stl"),
    ("GY530 Sensor Fit Gauge Only", "fit_stls/vl53l0x_gy530_fit_gauge.stl"),
    ("GY530 35mm Optical Height Trial Only",
     "fit_stls/vl53l0x_gy530_height_trial_035.stl"),
    ("GY530 45mm Optical Height Trial Only",
     "fit_stls/vl53l0x_gy530_height_trial_045.stl"),
    ("GY530 55mm Optical Height Trial Only",
     "fit_stls/vl53l0x_gy530_height_trial_055.stl"),
)


# Immutable Git blob identifiers of the licensed ORIGINAL STL inputs.
# This detects source substitution before Fusion imports a different model.
# Git blob SHA1 hashes the bytes preceded by b"blob <length>\0".
# These revision checks are provenance, NOT installation/fit acceptance.
SOURCE_MESH_GIT_BLOBS = {
    "docs/cad/originals/smars-stepper/SMARS_2BJY8-Chassis.stl": "d7428a9ad9663446d1862061ce1e645f37039c2f",
    "docs/cad/originals/smars-stepper/SMARS_28BYJ-48-RearWheel.stl": "e4fcfb7cd884f29a0eb0a10a3bed7e1cdc1fc6fb",
    "docs/cad/originals/smars/slave_wheel_SL.stl": "b1a431a86029692711c77f15aadac358ff693276",
    "docs/cad/originals/smars/mechanical_track.stl": "3fa614ef1f0ca1c05ad7e4f6e4cc2c7020d35db4",
    "docs/cad/originals/forklift/fork_lift_e.stl": "83699aaaaa87efbeb3e2bd897156ff1069aef2e5",
    "docs/cad/originals/forklift/fork_lift_f.stl": "5b0c7409c889f65a020ee91b9ee28f6b37cf2301",
    "docs/cad/originals/gripper/servo_case_arm.stl": "121ecb2820b77903ffb2ce83c308d825aac135d7",
    "docs/cad/originals/gripper/arm_rack.stl": "fa8892f85c133218c597dc04ffabf3a4e91a3a1e",
    "docs/cad/originals/gripper/pinion_gear.stl": "fc306ad3a8695ae61667ba2769f3b5440839ca2d",
    "docs/cad/originals/sparky-head/sparky_shell.stl": "b0c95cf6eb8b313859b7af9efca25fe202ef49af",
    "docs/cad/originals/sparky-head/sparky_collar.stl": "da2a75ae5528542d34232182b5ecf99978c1691f",
    "docs/cad/originals/sparky-head/sparky_lid.stl": "e3859582ec094a1a256732852187bc71048c6796",
}


def verify_original_source_revisions(root: Path) -> dict[str, str]:
    """Fail before Fusion import when an original licensed STL was replaced.

    Preserve original author/license and exact geometry. Changing a source
    requires a deliberate reviewed revision, attribution and fit rerun.
    """
    paths = {rel for _, rel in SOURCE_MESHES}
    if paths != set(SOURCE_MESH_GIT_BLOBS):
        raise ValueError("Original CAD manifest and pinned sources disagree")
    verified = {}
    for rel, expected in SOURCE_MESH_GIT_BLOBS.items():
        path = root / rel
        if not path.is_file():
            raise FileNotFoundError(f"Missing original CAD source: {rel}")
        content = path.read_bytes()
        actual = sha1(
            b"blob " + str(len(content)).encode("ascii") + b"\0" + content
        ).hexdigest()
        if actual != expected:
            raise ValueError(f"Original licensed CAD source changed: {rel}")
        verified[rel] = actual
    return verified


def find_repo(script_path: Path) -> Path:
    for ancestor in (script_path.parent, *script_path.parents):
        if (ancestor / "docs/cad/originals/smars-stepper").is_dir():
            return ancestor
    raise FileNotFoundError(
        "Move the script inside your cloned desk-robot-remix repository"
    )


def build_manifest(root: Path):
    paths = [(name, root / rel) for name, rel in SOURCE_MESHES]
    missing = [str(path) for _, path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing source mesh:\\n" + "\\n".join(missing))
    adapters = [
        ("Adapter " + name, root / "docs/cad/remixes/adapter_stls" / (name + ".stl"))
        for name in ADAPTER_NAMES
    ]
    fits = [
        (name, root / "docs/cad/remixes" / relative)
        for name, relative in FIT_REFERENCES
    ]
    return (paths
            + [(name, path) for name, path in adapters if path.is_file()]
            + [(name, path) for name, path in fits if path.is_file()])


def verify_optional_fit_references(root: Path) -> dict | None:
    """Reject stale generated STLs and return verified source-only geometry."""
    remixes = root / "docs/cad/remixes"
    generated = [
        remixes / "adapter_stls" / (name + ".stl")
        for name in ADAPTER_NAMES
    ] + [remixes / relative for _, relative in FIT_REFERENCES]
    if not any(path.is_file() for path in generated):
        return None
    checker = root / "code/scripts/export_fit_kit.py"
    return runpy.run_path(str(checker))["verify_fit_kit"](
        root, output_dir=remixes
    )


def packaging_warning(verified_fit_kit: dict | None) -> str:
    """Tell the Fusion builder whether reference chassis packaging is blocked.

    Even an apparent XY bounding fit CANNOT grant print, power or motion
    qualification. The original stepper chassis mesh has no interior cavity
    or measured pack, rail, servo and wiring assembly coordinates.
    """
    if verified_fit_kit is None:
        return "No candidate kit imported; physical packaging is unqualified."
    power_scope = verified_fit_kit.get("power_fit_scope")
    if (not isinstance(power_scope, dict)
            or power_scope.get("protected_pack_body_only") is not True
            or power_scope.get("includes_connector_and_leads") is not False
            or power_scope.get("includes_charger") is not False
            or power_scope.get("includes_boost") is not False
            or power_scope.get("includes_fuse_switch") is not False
            or power_scope.get("whole_power_stack_fit_verified") is not False):
        raise ValueError("Unverified Fusion power fit scope")
    screen = verified_fit_kit.get("source_chassis_battery_footprint")
    if not isinstance(screen, dict) or screen.get(
        "physical_interior_fit_verified"
    ) is not False:
        raise ValueError("Unverified Fusion battery packaging provenance")
    if screen.get("flat_tray_any_yaw_impossible") is True:
        return (
            "BATTERY PACKAGING CONFLICT: the body-only pack coupon has a physical XY span "
            "longer than the original SMARS chassis outer XY diagonal. "
            "Rotating the coupon flat cannot fix this; redesign the complete power stack "
            "without dropping protection and verify the full power assembly "
            "before final printing."
        )
    if screen.get("axis_aligned_packaging_possible") is False:
        return (
            "BATTERY PACKAGING CONFLICT at 0/90 degrees. Other planar "
            "angles and actual internal clearances are not qualified."
        )
    if screen.get("axis_aligned_packaging_possible") is True:
        return (
            "Battery body-only coupon passed only a source outer bounding screen; "
            "leads, charger, boost, fuse/switch, internal clearance and physical fit remain OPEN."
        )
    return "Original chassis reference unavailable; battery footprint not checked."


def jaw_topology_warning(root: Path) -> str:
    """Reuse the strict STL checker; leave original meshes untouched."""
    checker = root / "code/scripts/export_fit_kit.py"
    check = runpy.run_path(str(checker))["closed_mesh_edges"]
    failures = []
    for _, relative in SOURCE_MESHES:
        if not relative.startswith("docs/cad/originals/gripper/"):
            continue
        try:
            check(root / relative)
        except ValueError as exc:
            failures.append(str(exc))
    if failures:
        return (
            "JAW TOPOLOGY HOLD: " + "; ".join(failures)
            + ". Import as unaligned references only. Repair a separate "
            "attributed copy and recheck tooth profile, shaft and rack fit "
            "before conversion, slicing or printing."
        )
    return (
        "Jaw meshes passed only the source topology screen; actual backlash, "
        "horn travel and loaded silicone contact remain unqualified."
    )


def run(context):
    import adsk.core
    import adsk.fusion

    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        repo = find_repo(Path(__file__).resolve())
        verify_original_source_revisions(repo)
        jaw_warning = jaw_topology_warning(repo)
        fit_receipt = verify_optional_fit_references(repo)
        sources = build_manifest(repo)
        app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        if design is None:
            raise RuntimeError("Cannot create a Fusion design")
        design.designType = adsk.fusion.DesignTypes.DirectDesignType
        component = design.rootComponent
        for name, path in sources:
            occurrence = component.occurrences.addNewComponent(
                adsk.core.Matrix3D.create()
            )
            occurrence.component.name = name
            mesh = occurrence.component.meshBodies.add(
                str(path), adsk.fusion.MeshUnits.MillimeterMeshUnit
            )
            if mesh is None or mesh.count == 0:
                raise RuntimeError("Cannot import STL: " + str(path))
        ui.messageBox(
            f"Imported {len(sources)} separate unaligned mesh components.\\n"
            "Dock and fit gauges, when available, are labeled unqualified references. "
            "This is not the finished robot. Align shaft centers and gears, "
            "validate track compatibility and inspect collisions. Then model "
            "adapters to caliper measurements before printing.\\n"
            + packaging_warning(fit_receipt) + "\n" + jaw_warning
        )
    except Exception:
        ui.messageBox("Desk robot Fusion import failure:\\n" + traceback.format_exc())
