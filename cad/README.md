# CAD source register

Originals go in `originals/`, small changes in `remixes/`. EVA's original head
3MF, three Bluino gripper STLs, two original forklift STLs and the four requested
SMARS chassis/wheel/track STLs are saved and inspected, with original assembly
documents. No geometry has been edited or sliced. Updated 2026-11-03: the stepper chassis
and rear wheel originals are also saved; combined mechanical fit is unverified.

| Source | Author | Needed files | License |
| --- | --- | --- | --- |
| [EVA Robot head 7319190](https://www.thingiverse.com/thing:7319190/files) | Ksirailway-Base | [Saved EVA-Robot.3mf](originals/eva-head/EVA-Robot.3mf), [inspection/provenance](originals/eva-head/README.md); four objects in assembly positions | CC BY-SA 4.0 |
| [SMARS 2662828](https://www.thingiverse.com/thing:2662828/files) | tristomietitoredeituit | [Saved screwless selection and documents](originals/smars/README.md): `chassis_-SL.stl`, `master_wheel.stl`, `slave_wheel_SL.stl`, `mechanical_track.stl`; `doc_lite.zip`, `Instructions.pdf` | CC BY-NC-SA 4.0 |
| [Stepper SMARS 2778904](https://www.thingiverse.com/thing:2778904/files) | unclejeff | [Two saved original STLs, source and hashes](originals/smars-stepper/README.md); WIP, slow drivetrain, original SMARS tracks, M4 motor/M3 slave mounts | Displayed CC BY 4.0; ancestor NC-SA difference recorded, retain both attributions and resolve before redistribution |
| [Gripper 4253681](https://www.thingiverse.com/thing:4253681/files) | bluino | [Saved originals and hashes](originals/gripper/README.md): `servo_case_arm.stl`, `arm_rack.stl`, `pinion_gear.stl` | CC BY 4.0 |
| [Original forklift 3027255](https://www.thingiverse.com/thing:3027255/files) | tristomietitoredeituit | [Saved E/F pieces, PDF and hashes](originals/forklift/README.md) | CC BY-NC-SA 4.0 |

Do not mix screwless/screwed axle and wheel variants. Follow original assembly
counts. Stepper chassis/lift/EVA head/WROOM/bank/sensor mounting still needs measured fit checks.

Future permitted jobs: removable EVA head bracket clearing camera/microphone/
speaker/button; small internal module spacers or camera-aperture corrections;
WROOM/bank spacers, small sensor brackets, an SSD1306 bezel and thin replaceable
jaw tips. Keep the camera pose fixed relative to the jaws. The old separate
battery/buck system is not in the bank-based plan. Confirm physical bank size,
head/arm stability and ToF standoff before final mounting. Preserve the existing chassis and linkage.

Each export must record source/license, dimensions, changes and hash. Derived
SMARS geometry retains its noncommercial/share-alike terms. Software MIT terms
do not relicense printed designs. Fusion tools are exposed; verify the live connection and active design before editing.
The EVA case has its own CC BY-SA 4.0 terms; preserve its attribution and mark
changes to it. A combined mechanical remix must respect every applicable source
license; do not assume the software MIT license covers the assembled robot CAD.

The saved N20 screwless chassis is historical and does not fit 28BYJ-48 motors.
The stepper remix is a different variant; verify matching track/slave-wheel
selection and forklift interface, not only motor mounting. STL source-coordinate
bounds and byte integrity do not establish millimeters, manifoldness, printability
or physical fit. No full assembly or cliff-coverage check has occurred.
