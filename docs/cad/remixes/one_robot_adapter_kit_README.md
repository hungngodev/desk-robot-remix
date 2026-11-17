# Printable one-robot adapter kit

## Reproducible prototype STL export

From the repository root, with OpenSCAD installed:

```sh
python3 code/scripts/export_fit_kit.py
```

This renders the seven existing adapter candidates to
`docs/cad/remixes/adapter_stls/` for the Fusion scaffold and the
three existing power, docking and jaw fit gauges to
`docs/cad/remixes/fit_stls/`. Each STL is exported in deterministic binary
format, checked for nonzero triangles and exact file length, and listed in
`docs/cad/remixes/fit_kit_manifest.json`. A render error publishes no
partial candidates. The manifest explicitly says physical fit, final assembly,
electrical docking and commercial manufacturing remain unqualified. Source
dimensions are still **provisional** until real components are measured.
This is not a printable, integrated production robot.


Source [one_robot_adapter_kit.scad](one_robot_adapter_kit.scad) is original CC0 parametric geometry. It can produce **seven** separate provisional parts:

| Part | One robot qty | Use |
| --- | --- | --- |
| head_bridge | 1 | Centered slotted head/body spacer |
| tof_adjustable | 8 | One VL53L0X GY-530 candidate bracket per direction |
| oled_bezel | 1 | SSD1306 aperture |
| speaker_grille | 1 | 20mm speaker front |
| fsr_jaw_pocket | 1 | Force pad jaw holder |
| dock_tag_backplate | 1 | AprilTag marker frame |
| wire_clip | as needed | Cable routing |

Regenerate with `openscad -o head_bridge.stl -D 'part="head_bridge"' one_robot_adapter_kit.scad`, substitute each name. CAD was rendered locally as seven **watertight, single-body** STL meshes with provisional dimensions and packaged for this conversation. These parts are **not** a final fitted assembled robot.

**Fusion 360 workflow for complete robot**: follow [FUSION_ONE_ROBOT_ASSEMBLY.md](../FUSION_ONE_ROBOT_ASSEMBLY.md). Ground the original 28BYJ48 SMARS chassis, import existing wheel/track/lift/Bluino pinion and rack/Sparky head STL meshes individually in millimeters, assemble with real moving joints, and then insert these adapter meshes as candidate geometry. The head must face exactly forward; camera, mic, speaker and all 8 ToF lens sweeps need clear view. Measure real screw spacing, lens offsets, servo horn and pack before changing these parameters. Use **Mesh > Convert Mesh** only where an editable solid is needed. Native Fusion components for adapter plates are preferable to stretching the original gripper gear teeth.

**Grasp tuning**: Print the existing MG90S fit coupons first. The jaw FSR pocket is only a cable-safe pad; the controlled incremental closure is in `code/laptop/src/desk_robot/grasp_feedback.py`. It requires two distinct measured ADC conversions and actual calibration values. Neither a watertight STL nor a simulated code test proves lifting force.

**Docking**: The passive cradle `dock/dock_passive_fit.scad` and AprilTag plate are mechanical alignment prototypes, not wired charging electronics. **Do not energize dock contacts** without a protected, measured charging power path and safe interlock. Image tag detection is not contact confirmation.

Mechanical provenance remains separate: SMARS tracks/lift noncommercial/share-alike, Bluino gripper CC BY, and Sparky head CC BY-SA. These original files are not relicensed here.

## Fusion assembly scaffold

New [fusion_assembly_scaffold.py](fusion_assembly_scaffold.py) is a **Fusion GUI script**, not a generic system Python command. Place it within your cloned repository at `docs/cad/remixes/` and unzip the adapter STLs into `docs/cad/remixes/adapter_stls/`. Run in **Fusion > Utilities > Scripts and Add-Ins**. It creates a NEW direct design and stages **12 saved original STLs plus up to seven adapters** as individually named reference components, interpreting unitless STL coordinates as millimeters. It deliberately does **not** guess mesh transforms, join tracks, install a battery, make an electrical connector, or create joints. Ground/Align/Joint/Interference remains necessary after real measurements. Source and manifest are syntax checked, but Fusion GUI execution is not available in CI. See [Autodesk MeshBodies.add documentation](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_MeshBodies_add.htm).
