"""Fusion script: stage each original STL as its own named reference component.

Run inside Fusion > Utilities > Scripts and Add-Ins. Put the file in
docs/cad/remixes of your cloned robot repo. These meshes are deliberately
unaligned because original source coordinates are not assembly transforms.
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


def find_repository(script_path: Path) -> Path:
    for parent in (script_path.parent, *script_path.parents):
        if (parent / "docs/cad/originals/smars-stepper").is_dir():
            return parent
    raise FileNotFoundError(
        "Move script to cloned desk-robot-remix/docs/cad/remixes before running."
    )


def build_manifest(root: Path):
    originals = [(name, root / relative) for name, relative in SOURCE_MESHES]
    missing = [str(path) for _, path in originals if not path.is_file()]
    if missing:
        raise FileNotFoundError("Original STL files missing:\n" + "\n".join(missing))
    extras = [(f"Adapter {name}", root / "docs/cad/remixes/adapter_stls" / f"{name}.stl")
              for name in ADAPTER_NAMES]
    return originals + [(name, file) for name, file in extras if file.is_file()]


def run(context):
    import adsk.core
    import adsk.fusion

    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        manifest = build_manifest(find_repository(Path(__file__).resolve()))
        # Never overwrite or modify an existing user document.
        app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            raise RuntimeError("Fusion design is not active")
        # MeshBodies.add can import unitful meshes directly in direct modeling.
        design.designType = adsk.fusion.DesignTypes.DirectDesignType
        root = design.rootComponent
        for name, path in manifest:
            occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
            occ.component.name = name
            imported = occ.component.meshBodies.add(
                str(path), adsk.fusion.MeshUnits.MillimeterMeshUnit
            )
            if imported is None or imported.count == 0:
                raise RuntimeError("Failed to import mesh: " + str(path))
        ui.messageBox(
            f"Staged {len(manifest)} individual reference meshes.\n"
            "These are NOT aligned, mated or dimensionally verified. Ground "
            "the chassis; use Fusion Align and joints, then Inspect > "
            "Interference before printing the final assembly."
        )
    except Exception:
        ui.messageBox("Desk Robot Fusion scaffold failed:\n" + traceback.format_exc())
