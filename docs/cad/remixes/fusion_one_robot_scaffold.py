"""Fusion 360 script: import Desk Robot 01's REAL source STLs into components.

Fusion: Utilities > Scripts and Add-Ins. Save this script inside a cloned
desk-robot-remix/docs/cad/remixes directory. It creates a NEW design.
Source meshes have arbitrary coordinates; this does not align joints,
generate missing mounts, or certify any printed part or charging circuit.
"""
from pathlib import Path
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
    ("Battery Tray Gauge Only", "fit_stls/battery_boost_tray.stl"),
    ("Contact Pocket Gauge Only", "fit_stls/dock_contact_recess_gauge.stl"),
    ("Jaw Reference Coupon Only", "fit_stls/jaw_calibration_coupon.stl"),
    ("Speaker Fit Gauge Only", "fit_stls/speaker_rect_fit_gauge.stl"),
    ("GY530 Sensor Fit Gauge Only", "fit_stls/vl53l0x_gy530_fit_gauge.stl"),
)


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


def run(context):
    import adsk.core
    import adsk.fusion

    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        repo = find_repo(Path(__file__).resolve())
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
            "adapters to caliper measurements before printing."
        )
    except Exception:
        ui.messageBox("Desk robot Fusion import failure:\\n" + traceback.format_exc())
