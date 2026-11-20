# Printable one-robot adapter kit

## Reproducible prototype STL export

From the repository root, with OpenSCAD installed:

```sh
python3 code/scripts/export_fit_kit.py
```

This renders seven adapter candidates including the rectangular speaker front to
`docs/cad/remixes/adapter_stls/` for the Fusion scaffold and the
three existing power, docking and jaw fit gauges to
`docs/cad/remixes/fit_stls/`. Each STL is exported in deterministic binary
format, checked for nonzero triangles and exact file length, and listed in
`docs/cad/remixes/fit_kit_manifest.json`, including SHA256 digests of every
binary STL and its source SCAD file and explicit millimeter units. Run `python3 code/scripts/export_fit_kit.py --verify` before slicing. It
checks every expected part, current SCAD and STL digests, and watertight mesh
topology. Passing verifies source traceability, not actual part fit, license,
dock power, charging or physical qualification. A failed rebuild invalidates an earlier
manifest rather than presenting stale output as a fresh successful export.
A render error publishes no new candidates. The manifest explicitly says physical fit, final assembly,
electrical docking and commercial manufacturing remain unqualified. Source
dimensions are still **provisional** until real components are measured.
This is not a printable, integrated production robot.


Source [one_robot_adapter_kit.scad](one_robot_adapter_kit.scad) is original CC0 parametric geometry. It can produce **seven** separate provisional parts:

| Part | One robot qty | Use |
| --- | --- | --- |
| head_bridge | 1 | Centered slotted head/body spacer |
| tof_adjustable | 8 | One VL53L0X GY-530 candidate bracket per direction |
| oled_bezel | 1 | SSD1306 aperture |
| speaker_grille | 1 | Perforated front plate for current 20 x 16 mm Challenge 2 W rectangular speaker, not sealed soundbox |
| fsr_jaw_pocket | 1 | Force pad jaw holder |
| dock_tag_backplate | 1 | AprilTag marker frame |
| wire_clip | as needed | Cable routing |

Regenerate with `openscad -o head_bridge.stl -D 'part="head_bridge"' one_robot_adapter_kit.scad`, substitute each name. CAD was rendered locally as seven **watertight, single-body** STL meshes with provisional dimensions and packaged for this conversation. These parts are **not** a final fitted assembled robot.

The rectangular front grille and [separate speaker pocket gauge](speaker_rect_fit_gauge.scad) follow the fixed Challenge Electronics CS20-02P110-04-1X 8 ohm 2 W envelope, 20 x 16 x 4.7 mm. The earlier round 20 mm 1 W front geometry was retired. Neither print provides the qualified one cubic centimeter sealed speaker enclosure, pad clearance, thermal testing or microphone double talk. These remain mandatory physical steps before ordering five speakers.

**Fusion 360 workflow for complete robot**: follow [FUSION_ONE_ROBOT_ASSEMBLY.md](../FUSION_ONE_ROBOT_ASSEMBLY.md). Ground the original 28BYJ48 SMARS chassis, import existing wheel/track/lift/Bluino pinion and rack/Sparky head STL meshes individually in millimeters, assemble with real moving joints, and then insert these adapter meshes as candidate geometry. The head must face exactly forward; camera, mic, speaker and all 8 ToF lens sweeps need clear view. Measure real screw spacing, lens offsets, servo horn and pack before changing these parameters. Use **Mesh > Convert Mesh** only where an editable solid is needed. Native Fusion components for adapter plates are preferable to stretching the original gripper gear teeth.

**Grasp tuning**: Print the existing MG90S fit coupons first. The jaw FSR pocket is only a cable-safe pad; the controlled incremental closure is in `code/laptop/src/desk_robot/grasp_feedback.py`. It requires two distinct measured ADC conversions and actual calibration values. Neither a watertight STL nor a simulated code test proves lifting force.

**Docking**: The passive cradle `dock/dock_passive_fit.scad` now exports a short rail entry coupon from the same geometry. Test actual track clearance before printing the full cradle. The separate 80 mm AprilTag backplate is an alternative fixture, **not a drop-in insert** for the cradle's 71.2 mm paper pocket. Both are mechanical alignment prototypes, not wired charging electronics. **Do not energize dock contacts** without a protected, measured charging power path and safe interlock. Image tag detection is not contact confirmation.

Mechanical provenance remains separate: SMARS tracks/lift noncommercial/share-alike, Bluino gripper CC BY, and Sparky head CC BY-SA. These original files are not relicensed here.

## Fusion assembly scaffold

New [fusion_assembly_scaffold.py](fusion_assembly_scaffold.py) is a **Fusion GUI script**, not a generic system Python command. Place it within your cloned repository at `docs/cad/remixes/` and unzip the adapter STLs into `docs/cad/remixes/adapter_stls/`. Run in **Fusion > Utilities > Scripts and Add-Ins**. It creates a NEW direct design and stages **12 saved original STLs, up to seven adapters, and up to seven provisional dock, battery, contact, jaw, speaker, and sensor fit references** as individually named components, interpreting unitless STL coordinates as millimeters. Generate the optional references with `python3 code/scripts/export_fit_kit.py` first. Missing original licensed meshes fail the import; missing optional fit references are omitted, not invented. It deliberately does **not** guess mesh transforms, join tracks, install a battery, make an electrical connector, or create joints. Ground/Align/Joint/Interference remains necessary after real measurements. Source and manifest are syntax checked, but Fusion GUI execution is not available in CI. See [Autodesk MeshBodies.add documentation](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_MeshBodies_add.htm).
