# Fusion 360 full one-pet assembly guide

## Source provenance gate

Before Fusion imports its twelve original STL references, the canonical
scaffold now verifies their exact Git blob revisions against a pinned list
from the original licensed source assets. Missing or substituted meshes
fail the import before a new Fusion document is created. This protects
license attribution and reproducible fit analysis, not actual physical
fit, shipping rights or final assembly acceptance. Update the revisions
only after inspecting the upstream license and rechecking affected joints.

## Cozmars packaging comparison before Sparky fallback

Evaluate Cozmars V2 before freezing the saved Sparky shell because its creator
published an editable full robot assembly specifically intended to be adapted to
different electronics. The upstream model repository is
`r-cute/rcute-cozmars-model-v2` at commit
`515f980d4ee91f6a279406085f591b882254aad8`. That revision contains
`cozmars-v2.f3z` Git blob `4ea3952fdc452081dfc711839e8b500e033a20ee`
and `cozmars-v2.step` Git blob
`aabc2da472af675a90ad51e425bd576ba1d31383`. The model repository itself
contains no LICENSE file. The creator's Cozmars V2 distribution page states
Creative Commons Attribution NonCommercial ShareAlike and the related server
repository says commercial use is prohibited.

Treat Cozmars V2 as an external noncommercial packaging reference only for
this personal prototype until its exact CAD redistribution grant is preserved
with the model. Do not copy its F3Z or STEP into this repository, do not
relicense it, and do not make a five robot commercial manufacturing claim from
this comparison. Its original Raspberry Pi Zero, three 9 g servos, N20 motors,
1.14 inch display, 10 by 35 by 65 mm battery and 20 by 35 by 3.5 mm speaker
are not our selected hardware and cannot be used as substitute dimensions.

For the comparison, open the upstream STEP or Fusion assembly separately and
record only measured interface envelopes that matter to this robot: track and
body packaging, front claw clearance, head electronics volume, service access,
wire bend space and center of gravity. Compare those values against the actual
parts entered in `FUSION_MEASUREMENT_SHEET.md`. Preserve the requested fixed
retro TV head, inset monochrome face, XIAO Sense camera and microphone, two
MG90S lift and jaw servos, eight VL53L0X placements and protected power stack.
If Cozmars geometry cannot accept those measured interfaces without violating
its license, appearance, safety clearances or drivetrain assumptions, record
the mismatch and use the already saved Sparky v0.1 head meshes as the fallback
reference. Sparky therefore remains executable fallback geometry, not the
unexamined first choice.

## What is real today

This is the exact mechanical integration plan for the requested **full featured**
one-robot build, not an electronics-free toy. The repository contains original STL
parts, not a dimensionally qualified printable all-in-one assembly. The last
rounded render is a layout drawing using partially illustrative track/arm mounts.

Use the existing printed sources as reference components. Never scale all parts
to fix one servo pocket. Preserve author/source/license information in
the original README files, including noncommercial and share alike restrictions.

| Fusion component | Existing repo file | Basis |
| --- | --- | --- |
| Main chassis | docs/cad/originals/smars-stepper/SMARS_2BJY8-Chassis.stl | ~58.0 by 86.2 by 41.6 mm source extents, verify units |
| Stepper output wheel | docs/cad/originals/smars-stepper/SMARS_28BYJ-48-RearWheel.stl | ~21.0 by 32.5 by 32.5 mm |
| Tracks, compatible slave wheels | docs/cad/originals/smars/mechanical_track.stl and slave_wheel_SL.stl | verify mating axle, do not mix original N20 motor wheel |
| Forklift mounting/lift | docs/cad/originals/forklift/fork_lift_e.stl, fork_lift_f.stl | alignment to stepper chassis not proven |
| Jaw servo case/rack/pinion | docs/cad/originals/gripper/servo_case_arm.stl, arm_rack.stl, pinion_gear.stl | Bluino rack and pinion preserved |
| Rounded shell | docs/cad/originals/sparky-head/sparky_shell.stl | ~56.0 by 52.0 by 54.0 mm |
| Head collar/lid, if used | docs/cad/originals/sparky-head/sparky_collar.stl, sparky_lid.stl | their separate mesh origins are not assembly transforms |
| Servo clearance gauge | docs/cad/remixes/mg90s_pocket_fit_gauges.scad | print once before altering jaw servo mount |

## Step-by-step in Fusion

1. Create new design **DeskPet01** in millimeters and Save. Under Modify > Change
   Parameters, record measured actual board width, board length, shaft locations,
   screw diameter, servo case length/width and horn center, battery enclosure
   envelope, track outside width, the active Challenge CS20-02P110-04-1X 8-ohm 2 W, 20 × 16 × 4.7 mm rectangular speaker body, solder pads, gasket and cavity, camera assembly
   width/depth and each selected cheap generic VL53L0X GY-530 carrier PCB/lens offset. Set values from
   calipers/vendor STEP models of the **actual purchased breakout**, not guessed
   values from the rendered concept.
2. In the Browser create eight Components: Chassis, Drivetrain, Lift, Gripper,
   Head, Electronics, Range Sensors, Dock. Ground Chassis. For each existing
   STL use **Design > Mesh > Create > Insert Mesh** with Unit Type millimeter.
   STL has no unit metadata. Verify the chassis bounding width is roughly
   58 mm before proceeding. Never treat the original coordinate offsets
   as assembled positions. Use Modify > Move/Copy and align using actual
   axle, shaft and mating geometry. Autodesk help:
   https://help.autodesk.com/cloudhelp/ENU/Fusion-Mesh/files/MESH-INSERT-MESH.htm
3. In the stepper reference design, install two **28BYJ48** motor envelope
   components and ULN2003 electronics placeholders in the chassis. These are
   reference envelopes, not a released drivetrain purchase or a qualified
   motor cutoff. Do not reuse the fit result for the guarded DC alternative. Align real shaft centers, verify two wheels,
   rear/slave and repeated track links rotate without intersecting chassis.
   Use the SMARS original instructions for exact track piece count; do not
   infer track count from one STL file. Verify the slow stepper output torque,
   wheel axle length and fastener retention.
4. Insert the two original forklift pieces and three original gripper meshes.
   Assemble the two **positional MG90S** envelopes as Lift and Jaw only.
   Install a sliding rack and servo-driven pinion; use joints for actual
   degrees of freedom. Print the four-pocket MG90S gauge first and correct
   only the mounting pocket and horn interface. Do not scale either gear.
   Follow the [first gripper test](../guides/first-gripper-test.md) to center
   each hornless servo in the isolated fixture, detach PWM and remove servo
   power before fitting the horn. In Fusion, align the pinion shaft to the
   measured rack pitch line and couple a revolute joint to the slider using
   measured travel per degree, not a guessed gear ratio. Use **Inspect >
   Interference** throughout the collision-free measured range for each
   servo and in combined lift/jaw poses. The old nominal 60 to 120 degree
   sweep is not a qualified endpoint pair; do not power the installed
   mechanism at either extreme before measurement.
   With power disconnected, reverse the pinion at multiple rack positions
   and measure lost rack travel, axial/radial play, tooth engagement, rack
   retention and remaining tooth travel at both ends. Check actual printed
   interference and tooth root/tip clearance, horn screw/fastener clearance,
   and repeat with installed FSR, silicone, tail and representative object.
   Record opening and closing backlash separately. Choose safe endpoints
   inside the measured collision-free interval with reserve for backlash,
   print tolerance, cable sweep and loaded deflection. The WROOM measured
   lift and jaw travel/force limits and no-motion commissioning gate stay
   authoritative; a command ACK is not a measured horn position.
5. If the Cozmars comparison requires the fallback, insert the **Sparky v0.1**
   shell as a head reference, with center
   facing the vehicle's forward axis. Preserve its visible outside surface.
   Design a new small solid *adapter plate* between chassis and shell, with
   measured M2/M3 clearance holes and trapped heat-set inserts. Design a
   removable XIAO Sense bracket and SSD1306 bezel inside the head. Do not
   reinterpret the tiny front LED aperture as a verified camera aperture.
   Leave accessible camera view, PDM microphone sound port, speaker rear
   cavity, BOOT button and connectors. Ensure physical access to the Sense
   board's J3 microSD isolation operation.
6. Add an electronics envelope for WROOM, 2 ULN boards, 2 TCA9548A muxes,
   MAX98357A amp, 3.3 V sensor rail, the actual protected charge and boost
   assembly, strain relief and fused main switch. Design cable passages
   and avoid routing motor current through Dupont signal ribbons. Do not
   put a guessed bare 18650 beside unprotected charging contacts.
7. Add **four downward VL53L0X GY-530 modules** facing the table, **front, left, right,
   rear VL53L0X GY-530 modules** facing outward. Model the actual carrier PCB, connector
   stack height and lens field of view. Make eight individually removable
   brackets so their elevations and optical sweeps can be calibrated.
   Keep the four downward sensors away from track shadow and lifted jaw.
   Check the actual tabletop reflection from each bracket position.
   The current `tof_adjustable` mesh is only an optical angle/aperture
   reference. Assumed PCB screw holes were removed because they crossed the
   lens opening with the 10.5 mm pilot board. Design and verify a separate
   real PCB retainer after measuring the purchased carrier; do not treat
   eight imported aperture references as mounted cliff sensors.
   Before screening any motion, use the same builder CLI to record each
   downward mux lane separately (0 through 3):

   ```sh
   (set -C; python3 code/scripts/cliff_mount_preflight.py --floor-mount-template > robot01_floor_mounts.json)
   python3 code/scripts/cliff_mount_preflight.py --floor-mount-measurements robot01_floor_mounts.json
   ```

   Fill the blank record with the measured lens height, angle from downward
   vertical and calibrated minimum/maximum floor interval for each lane before
   running the second command. Require `all_floor_mounts_possible_on_paper`
   to be true. Stop on missing lanes, failures or malformed evidence. This is
   not a live sensor qualification. For each intended straight, reverse or
   pivot command, separately use the planar cliff preflight:

   ```sh
   (set -C; python3 code/scripts/cliff_mount_preflight.py --planar-template > robot01_cliff_motion.json)
   python3 code/scripts/cliff_mount_preflight.py --planar-measurements robot01_cliff_motion.json
   ```

   Save the blank template as a new local JSON record, fill the measured body
   X-forward/Y-left optical centers and every load-bearing support contact,
   track width, signed wheel velocities, mount datum, downward tilt, worst
   loaded stop distance and detection latency. Keep lateral coverage at zero
   until measured; the 10 mm paper margin is a design input, not a calibration.
   Repeat for distinct motion commands using new records. Both screens print
   JSON even when a paper screen fails: require
   `necessary_planar_coverage_on_paper` to be true, not just exit status zero.
   A positive paper result neither verifies
   the real lens-to-desk height and optical orientation nor releases motion.
8. Create small, independent mounting/vent openings for eight capacitive
   touch electrodes, the MAX30102 finger contact pad, APDS9960 gesture sensor,
   two FSR pads (belly and jaw), SHT41 vent, RGB heart, PN532 toy reader,
   tactile bumper switches, encoder magnets and magnetic hat reed sensor.
   Keep the finger/optical sensors accessible to fingers, protect
   microphones from fan and motor vibration, and avoid all exposed mains.
9. Assemble the dock as a **separate component**: guide ramp geometry from
   actual measured overall track width, rigid tag board clearly visible from
   the XIAO camera, and a stopped position that leaves the dock charge
   contacts mechanically recessed. Model electrical contacts only when an
   actual protected, current rated charging path is selected. Before
   cutting the backstop for IR electronics, print the separate unpowered
   `dock_ir_pair_position_coupon` and measure both real emitter carriers,
   independent WROOM receiver views, left/right field overlap and aim.
   Place two electrically independent fail-closed seat switches with measured
   travel and service access; the AprilTag and decoded IR are not seat
   evidence. Before final mounting, create a new source-pinned record for
   the actual dock number (example for dock 01, from the repository root):

   ```sh
   python3 code/scripts/screen_dock_seat_mechanics.py --template-for-dock 1 --output dock01_seat.json
   python3 code/scripts/screen_dock_seat_mechanics.py --measurements dock01_seat.json
   ```

   Fill measured fields before the second command. Require
   `source_only_layout_possible` to be true; stop on a failed layout or
   stale CAD hash. Keep contacts unpowered for physical seat, polarity,
   bounce, fault and clearance verification. The screen always reports
   `physical_dock_seating_qualified` and `charging_authorized` false.
   Never connect bare cell contacts to a live 5 V pad. The CAD does not
   certify charging.
10. Use **Inspect > Section Analysis** to examine assembly and removable
    service access. Move tracks through full travel, servos through their
    complete mechanical range, and look at camera/cliff lens field obstructions.
    Record top/heavy battery center of mass relative to the track footprint.
    Also screen ALL load-bearing wheel/track contacts and the weighted
    assembled center of mass with the source-only `screen_assembly_stability.py`
    before any loaded grip or moving dock trial. A heavy external protected
    pack must not be assumed stable merely because it physically mounts.
    Use Mesh > Prepare > Generate Face Groups and Mesh > Modify > Convert Mesh
    only on simplified local shapes you need as Fusion solids. For dense
    curved meshes, keep source STL as mesh reference and model your
    new bracket as a native parametric Fusion solid. Autodesk reference:
    https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/How-to-Convert-a-Mesh-to-a-BRep-in-Fusion-360.html
11. Export **each physical component separately**, with model origin and
    units recorded, to 3MF or binary STL. Slice the small fit gauge and
    bracket first. Mount against real hardware, remeasure and adjust
    parameter values. Export a final print plate only after you verify
    no missing gear, track, insert, connector or electrical clearance.

## Removable cosmetic qualification (G018 / G024)

These are reserved cosmetic interfaces, not fitted hat/ear/antenna geometry
or a qualified personality input. Follow the [product definition](../product-definition.md)
and [measurement sheet](FUSION_MEASUREMENT_SHEET.md). Do not release a
costume solely because the bare head or a watertight accessory mesh fits.

For each distinct accessory and allowed combination, model its installed
geometry, installation/removal path, worst measured mounting offset,
retention play, print tolerance and flexible antenna deflection. Compare
the complete swept envelope against the actual assembly, including the
full lift/jaw travel and dock seating path. Check the following against
the undecorated baseline:

| Interface | Required comparison with cosmetic installed |
| --- | --- |
| OV2640 camera | Measured lens center and horizontal/vertical field of view remain clear across the full image; verify edge/corner targets and absence of new reflections or shadows. Do not assume the supplied camera revision has a particular field angle. |
| Eight VL53L0X lanes (0x70) | All four down, front, left, right and rear optical envelopes remain clear, including reflected IR from costume surfaces; repeat each lane's installed range/validity and controlled edge/obstacle trials under the existing safety procedure. The three read-only lanes gain no motion authority. |
| PDM microphone | Keep the physical sound inlet open and isolated from vibration; GPIO42 clock and GPIO41 data are electrical connections, not extra acoustic ports. Compare capture level, noise, echo and double talk with the existing [Sense AEC procedure](../guides/sense-aec-port.md). |
| Speaker | Preserve the full grille open area, rear cavity, gasket and lead seal; compare audible output, clipping, rattling and barge-in with the same speaker/gain configuration. |
| BOOT (GPIO0), USB and switch | Retain deliberate finger/tool and connector insertion/removal access; the attachment must not press BOOT or obstruct emergency power-off. Check with power disconnected first. |
| Cooling and RF | Keep Sense, WROOM and amplifier cooling paths and their actual Wi-Fi antenna keepouts clear. Compare temperatures and connectivity under the same sustained workload and ambient conditions; a vent visible in CAD is not thermal acceptance. |
| Retention and sensors | Capture magnets mechanically, insulate conductive decorations, and check accidental reed activation, touch, encoder magnets, mechanical snag and loose-part risk. A flexible cosmetic antenna is passive, not a mains probe or a second radio. |

Use the [OpenSCAD costume keepout guard](remixes/costume_keepouts.scad) as a
conservative preflight before exporting any modeled costume. In a common
assembly coordinate frame, supply nonempty swept accessory bounding boxes
expanded for tolerance, play and deflection, and nonempty measured protected
boxes for camera, ToF lanes 0 through 7, PDM inlet, speaker, and the Sense,
WROOM and amplifier cooling paths, in the order returned by `costume_interfaces()`.
Wrap the accessory geometry in `costume_keepout_guard(swept, keepouts) { ... }`.
Each box is `[minimum_xyz, maximum_xyz]` in millimeters; protected volumes
must include the required clearance. Missing inputs, overlap and even contact
fail the screen. A passing screen only checks the supplied boxes, not whether
they actually enclose the full geometry, optics or airflow; all physical and
other mechanical/RF comparisons above remain mandatory. No default measured
coordinates or release authorization are provided.

Record accessory ID/revision, robot/assembly ID, exact CAD and firmware
revisions, measured offsets and minimum clearances by interface and pose,
baseline and installed measurements, trial conditions, results and evidence.
Keep missing or failed comparisons unqualified; remove the attachment
before powered use rather than relaxing a safety threshold or reusing
bare-head optical/acoustic acceptance. Do not add motion permission or
automatic personality changes from a reed closure. G018 identity and G024
optional input remain independently unqualified until the existing sensor
and interaction evidence supports them.

## Read the automatic battery packaging warning

After exporting provisional OpenSCAD fit coupons, the Fusion scaffold
verifies their mesh hashes and source bounds. The original chassis source
XY envelope is approximately 58.002 by 86.194 mm, with a 103.892 mm
diagonal. The provisional battery tray with mounting tabs spans about
107.6 mm along its long axis. Because this physical span exceeds the
chassis's entire outer planar diagonal, **no flat yaw rotation** can place
the whole tray inside the original chassis outer XY footprint. Tilting
out of plane or external mounting changes the system and still needs
full modeled track, power, cable and stability clearance. Its startup message now flags
a concrete packaging conflict if the provisional battery tray is larger
than the original stepper chassis XY source envelope. This warning comes
from the actual binary STL triangles, not a guessed component fit.
**Do not silently resize the protected pack, omit charging, cut through
a motor mount, or declare an external battery placement safe.** Use the
full assembly to redesign the battery location with measured connector
bend radius, battery removal, crash protection, track/servo swept space
and real protected charger/boost dimensions. A passing outer bounding
box is never proof of interior fit or charging acceptance.

## Measurements that remain necessary

These are the last actual physical design inputs, not missing theoretical
features: MG90S case and horn, dimensions of delivered XIAO Sense expansion
and camera, current rated battery/boost/charge hardware, full track outer
width and axle geometry, exact 0.96 inch OLED module, 8 ranging PCB carriers
and their mounting standoff, speaker/mic openings, two FSR sizes, and printed
parts tolerances on your chosen filament/printer. Do not replace these with
invented numbers just to output an impressive but unprintable final STL.

## Passive dock test geometry included

The original editable passive alignment gauge is now in
[remixes/dock/dock_passive_fit.scad](remixes/dock/dock_passive_fit.scad).
It intentionally has no electrical contacts and is only a dimensioned
mechanical test piece. Regenerate it with the real track width and
clearance after the track assembly is printed. The example 96 mm model
was checked locally as one watertight mesh, but that example width is
not a measurement of the user's robot.

## Explicit print readiness

* **Raw source print meshes:** present and downloadable, as listed above.
* **Servo fit gauge:** parametric source is present. Nominal local mesh checked.
* **One integrated printer-ready full robot set:** NOT present.
* **One assembled working robot:** NOT present.
* **Charging dock with a safe qualified charger:** NOT present.
* **Fusion native combined assembly (.f3d):** NOT present.

Sources/licensing: docs/cad/README.md and the individual original-source
README files. This guide is a reproducible mechanical work order and does not
claim the user's physical fit has passed.


## Loaded whole-robot static stability screen

The original SMARS chassis cannot contain the provisional protected power
tray flat within its XY footprint. Any outboard battery relocation or lifted
jaw changes the robot's stability and desk-edge clearance. Do not solve
battery packaging with an unsupported overhanging cell.

The pure source-level screen requires independent measured load-bearing
support contacts for EACH of four poses: stowed empty, key grasp extended,
candy grasp lifted, and stopped at the dock. The contact polygon may change
when a track unloads or a dock guide carries weight, so a union of all
contact points must never be reused as one optimistic footprint. Every pose
also needs its own complete assembly mass groups. Generate a blank record with:

```sh
python3 code/scripts/screen_assembly_stability.py --template --output robot01_stability.json
```

After measuring which wheel, track, caster or dock guide contacts actually
carry load in EACH pose, along with its heavy component masses/centers,
maximum body roll and pitch and required static reserve, fill the
`poses[].support_contacts_mm` and component blanks and run:

```sh
python3 code/scripts/screen_assembly_stability.py --measurements robot01_stability.json
```

Require `necessary_stability_on_paper` to be true, not merely exit status
zero. A negative result is a stop before loaded or moving trials.

The input body frame is X forward, Y left, Z upward, with millimeters
and grams. Z=0 is the support plane; every positive-mass component center
must be above it. Zero X/Y coordinates and zero-mass empty payloads remain
valid. The tool computes a DISTINCT convex support footprint per pose,
weighted source center of mass and worst signed distance to its own boundary
under the supplied maximum positive and negative tilts. Simultaneous
roll and pitch use a conservative coupled gravity-line envelope that bounds
both rigid-body rotation orders, not independent tangent offsets. It rejects
missing key or candy payload masses, stale or partial component roles,
degenerate support contacts, malformed numbers and unsupported tilt.
It deliberately does not infer a mass or support position from raw STLs.
Even a passing paper screen keeps physical mass locations, **dynamic**
acceleration, stopping, tip, desk-edge and actual printed assembly gates
unverified. It never approves motion, charging, printing or procurement.
