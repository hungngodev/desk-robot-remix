# Printable one-robot adapter kit

## Reproducible prototype STL export

From the repository root, with OpenSCAD installed:

```sh
python3 code/scripts/export_fit_kit.py
```

This renders seven adapter candidates including the rectangular speaker front to
`docs/cad/remixes/adapter_stls/` for the Fusion scaffold and the
current **16** provisional fit references across
`docs/cad/remixes/fit_stls/` and `docs/cad/remixes/dock_stls/`. Each STL is exported in deterministic binary
format, checked for nonzero triangles and exact file length, and listed in
`docs/cad/remixes/fit_kit_manifest.json`, including SHA256 digests of every
binary STL and its source SCAD file, declared millimeter units, and
actual triangle-derived `bbox_mm` minimum, maximum and dimensions for every
provisional STL. Those bounds help identify wrong print scale and oversize
envelopes, but cannot prove an assembled part fits. Run
`python3 code/scripts/export_fit_kit.py --verify` before slicing. It
checks every expected part, current SCAD and STL digests, and watertight mesh
topology. Passing verifies source traceability, not actual part fit, license,
dock power, charging or physical qualification. A failed rebuild invalidates an earlier
manifest rather than presenting stale output as a fresh successful export.
A render error publishes no new candidates. The manifest explicitly says physical fit, final assembly,
electrical docking and commercial manufacturing remain unqualified. Source
dimensions are still **provisional** until real components are measured.
This is not a printable, integrated production robot.


**Manifest quantities are not installation approval.** The generated
`fit_kit_manifest.json` records provisional `quantity_per_robot` for layout
only, plus `installed_quantity_per_robot: 0` for every unqualified part.
`temporary_fit_coupon` identifies trial prints that are never permanently
installed. The mesh verifier rejects altered installed quantities or coupon
labels, forged provisional quantities, non-millimeter units, mismatched part
identities, duplicate JSON keys and nonfinite manifest numbers. When the original stepper chassis STL is present, the manifest also
compares the exported battery tray against that source chassis outer footprint.
An oversized tray is a visible axis-aligned packaging conflict, not a reason
to remove the protected battery. Even a successful bounding-box screen could
never prove interior or diagonal clearance, motor sweep, service access, or
real physical fit. Final assembly print quantities come only after real parts are fitted,
licensed, and qualified; this provisional export does not create another
purchase or production parts list.

Source [one_robot_adapter_kit.scad](one_robot_adapter_kit.scad) is original CC0 parametric geometry. It can produce **seven** separate provisional parts:

| Part | One robot qty | Use |
| --- | --- | --- |
| head_bridge | 1 | Centered slotted head/body spacer |
| tof_adjustable | 8 provisional | GY-530 optical aperture and angle reference, NOT a retained PCB mount. The pilot still needs measured clips, fastening and lens offset |
| oled_bezel | 1 | Provisional 37 x 35 mm SSD1306 display window, M2 bores retaining >=2 mm printable web both outside and beside aperture; PCB mount positions unmeasured |
| speaker_grille | 1 | Provisional 36 x 32 mm perforated front plate for current 20 x 16 mm Challenge 2 W rectangular speaker. M2 holes require at least 2 mm plastic web to the nominal speaker pocket and outer edge; not a sealed soundbox |
| fsr_jaw_pocket | 1 | Provisional 34.3 x 34.3 mm FSR402 envelope coupon, 18.65 mm recess, 7.97 mm continuous supported tail channel and relieved rigid rim; jaw attachment, silicone compression and force unqualified |
| dock_tag_backplate | 1 | AprilTag marker frame |
| wire_clip | as needed | Provisional 22 x 13 x 4 mm M2 routing and cable tie plate; at least 2 mm plastic between bores and slot, not tested load-rated strain relief |

Regenerate with `openscad -o head_bridge.stl -D 'part="head_bridge"' one_robot_adapter_kit.scad`, substitute each name. CAD was rendered locally as seven **watertight, single-body** STL meshes with provisional dimensions and packaged for this conversation. These parts are **not** a final fitted assembled robot.

The rectangular front grille and [separate speaker pocket gauge](speaker_rect_fit_gauge.scad) follow the fixed Challenge Electronics CS20-02P110-04-1X 8 ohm 2 W envelope, 20 x 16 x 4.7 mm. The earlier round 20 mm 1 W front geometry was retired. The separate OpenSCAD `speaker_rear_chamber_reference` adds a nominal 36 x 32 x 11.4 mm open-front, closed-back cup aligned to the enlarged grille M2 pattern. It checks at least 1 cc of conservative geometric air after subtracting the complete speaker body envelope, and does not cut an unsealed wire notch. It is a **source-only reference**, not a qualified acoustically sealed enclosure: speaker gasket compression, lead feedthrough potting, head clearance, actual displaced volume, leak/thermal measurements and microphone double talk remain mandatory before ordering five speakers.

**Fusion 360 workflow for complete robot**: follow [FUSION_ONE_ROBOT_ASSEMBLY.md](../FUSION_ONE_ROBOT_ASSEMBLY.md). Ground the original 28BYJ48 SMARS chassis, import existing wheel/track/lift/Bluino pinion and rack/Sparky head STL meshes individually in millimeters, assemble with real moving joints, and then insert these adapter meshes as candidate geometry. The head must face exactly forward; camera, mic, speaker and all 8 ToF lens sweeps need clear view. Measure real screw spacing, lens offsets, servo horn and pack before changing these parameters. Use **Mesh > Convert Mesh** only where an editable solid is needed. Native Fusion components for adapter plates are preferable to stretching the original gripper gear teeth.

**Sensor mounting hold:** The nominal 10.5 mm GY-530 carrier is too
narrow for the former assumed paired screw slots, which overlapped the lens
aperture. Those unmeasured holes were removed from `tof_adjustable`.
The base mounting slots remain, but the reference does not retain a PCB. The separate GY530 source-size
pocket coupon now enforces at least a 2 mm perimeter and 1.5 mm
floor even when a builder overrides dimensional parameters. It still
cannot establish the real lens center, 3.3 V I2C pullup compatibility,
controller mount, optical FoV, connector routing or cliff stopping.
Print the fit coupon and measure real carrier width, thickness, connector,
lens position and any mounting features before designing a captive clamp.
Do not install eight of these as qualified cliff sensing mounts.

**Downward optical standoff trial:** Three separate removable,
nonconductive GY-530 open supports in the exporter, named
`vl53l0x_gy530_height_trial_035`, `_045`, and `_055`, bracket
nominal PCB rim heights of 35, 45, and 55 mm. These are staged in
Fusion as unaligned **trial references only**. Start with the motor
rail disconnected, position one actual PCB on a support without
obscuring its lens, record the actual lens-to-target distance with
calipers, and check the WROOM's own fresh ToF results over
representative dark, light, matte and reflective surfaces. A nominal
rim height is not lens-to-target height. Any result below the
firmware's 30 mm minimum, uncertain beam clipping, invalid sensor
age or no stable surface return keeps that location unqualified.
Never use the temporary support to drive or approach a desk edge;
the final eight mounts require measured lens centers and cable
clearance, real coast-distance testing, and independent stop gates.

**Grasp tuning**: Print the existing MG90S fit coupons first. The jaw FSR pocket is a removable reference coupon, not an installed jaw. Its nominal flat floor is 1.8 mm above the underside, with a 3.5 mm rigid rim below the 4 mm unloaded grip reference plane. The 2.2 mm sensor/adhesive/silicone stack and 0.5 mm rim relief are unmeasured allowances; verify the actual FSR body, tail length, connector, flat adhesive, vent and compressed silicone contact before final geometry. Never bridge the active area with a rigid rim or use the coupon as proof of force. Regenerate and verify the STL after measurements. The controlled incremental closure is in `code/laptop/src/desk_robot/grasp_feedback.py`. It requires two distinct measured ADC conversions and actual calibration values. Neither a watertight STL nor a simulated code test proves lifting force.

**Docking**: The passive cradle `dock/dock_passive_fit.scad` now exports a short rail entry coupon from the same geometry. Test actual track clearance before printing the full cradle. The separate AprilTag backplate is an alternative fixture, **not a drop-in insert** for the cradle's 71.2 mm paper pocket. Its provisional 76 mm square M3 pitch now makes the plate 85.35 mm square so the 3.35 mm bores retain at least 3 mm of edge web; the two bores crossing the rear stiffening rib are drilled through its full 12 mm height. Both mounting geometry and printed strength still need actual fit trials. The full `dock_passive_fit` cradle is also emitted as `temporary_fit_coupon: true`; it is a mechanical alignment prototype that must not become the permanently installed charging dock. Both are mechanical alignment prototypes, not wired charging electronics. **Do not energize dock contacts** without a protected, measured charging power path and safe interlock. Image tag detection is not contact confirmation.

Mechanical provenance remains separate: SMARS tracks/lift noncommercial/share-alike, Bluino gripper CC BY, and Sparky head CC BY-SA. These original files are not relicensed here.

## A4 source-scale paper fit overlays

Before printing the full tray or buying a pack, generate the five **unpowered**
A4 SVG reference pages from the existing OpenSCAD dimensions:

```sh
python3 docs/cad/remixes/print_2d_fit_templates.py --output /tmp/desk-robot-paper
python3 docs/cad/remixes/print_2d_fit_templates.py --output /tmp/desk-robot-paper --verify
```

Print at **100% actual size**, with any fit-to-page scaling turned off, and
check both the horizontal 100 mm and vertical 25 mm printed rulers. Measure
between the **centers of the two opposing strokes** on each rectangle, not
the outside ink edges. The nominal 0.3 mm stroke makes the outside spans
100.3 mm and 25.3 mm even at exact scale; the inside spans are 99.7 mm and
24.7 mm. If the stroke centers are hard to locate, measure both the inside
and outside spans and average them.

For each printed sheet, record its manifest page SHA256, printer and actual
size settings, both measured lengths in mm, measuring instrument and
estimated measurement uncertainty. Calculate the scale ratios as measured
horizontal / 100 and measured vertical / 25. For the intended fit screen,
allocate an allowable dimensional error from the smallest relevant fit
clearance before relying on the sheet. Check each axis independently:
multiply the absolute scale error by the maximum relevant dimension on that
axis, and include measurement uncertainty (scaled by that dimension divided
by the corresponding reference length). Reject the sheet if either error
budget is exceeded or if the required clearance or uncertainty is unknown.
Do not average the horizontal and vertical scale ratios or substitute this
screen for caliper measurements and printed coupon trials.

The
`power_reference_A4.svg` page outlines the candidate protected 1S pack BODY
(86 x 35 mm) inside the provisional 91.6 x 40.6 mm tray outer walls. It is a
paper collision check, **not** an approved pack housing. It excludes the actual
connector and NTC exits, PCM overhang, wiring bends, charger, boost, switch,
fuse, and mounting/service clearances. If the real assembly exceeds either
outline, measure the whole stack and redesign before printing. These paper
pages contain no approved drilling coordinates and confer no authority to
power or charge the robot. The separate `dock_guide_reference_A4.svg`
draws the actual **source-polygon** left and right rail shapes, 37 mm entry
flare, nominal 100 mm straight channel and 126 x 138 mm passive cradle
footprint. The arrow marks the approaching robot's entry end; the backstop
is at the opposite end. The 96 mm chassis track width and 2 mm side
clearances are still **nominal**, not a measured fit, and the paper drawing
does not supply a usable charging-contact fixture. Compare a real unpowered
track assembly with this sheet and the rail entry coupon before committing
the full dock print. The independent full-power, current and temperature
gates remain mandatory.

## Fusion assembly scaffold

New [fusion_assembly_scaffold.py](fusion_assembly_scaffold.py) is a **Fusion GUI script**, not a generic system Python command. Place it within your cloned repository at `docs/cad/remixes/` and unzip the adapter STLs into `docs/cad/remixes/adapter_stls/`. Run in **Fusion > Utilities > Scripts and Add-Ins**. It creates a NEW direct design and stages **12 saved original STLs, up to seven adapters, and up to 16 provisional dock, battery, contact, jaw, speaker, and sensor fit references** as individually named components, interpreting unitless STL coordinates as millimeters. Generate the optional references with `python3 code/scripts/export_fit_kit.py` first. Missing original licensed meshes fail the import; missing optional fit references are omitted, not invented. It deliberately does **not** guess mesh transforms, join tracks, install a battery, make an electrical connector, or create joints. Ground/Align/Joint/Interference remains necessary after real measurements. Source and manifest are syntax checked, but Fusion GUI execution is not available in CI. See [Autodesk MeshBodies.add documentation](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_MeshBodies_add.htm).


## Measured printer build volume screen

After exporting and verifying the source STL candidates, check the **actual**
printer usable build dimensions in millimeters rather than assuming the
selected printer or forcing a scale change:

```sh
python3 code/scripts/export_fit_kit.py --verify --build-volume-mm 180 180 180
```

The JSON result adds `print_bed_screen` for every candidate STL. It checks
the existing source triangle bounding boxes in the flat print orientation
at zero or ninety degrees, identifies parts whose Z height exceeds the
specified volume, and explicitly rules out every flat yaw only if the
candidate has an actual horizontal span longer than the bed diagonal.
An inconclusive screen is **not** permission to claim a different rotation
fits. Real supports, resin/FDM process, tolerances, part strength, curing
and an assembled robot still require printed and measured trials.
