# CAD source register

Saved upstream models remain unmodified in `originals/`: the EVA head 3MF,
Bluino gripper, forklift, SMARS chassis/wheels/tracks and stepper chassis/rear
wheel with their original assembly sources and licenses. The November 3 note
about no edited geometry applied only to those historical originals. **Locally
authored, provisional geometry now exists** in `remixes/`, but no complete robot
or powered dock has been assembled or physically fit qualified.

**Current builder path:** follow the [one robot Fusion assembly guide](FUSION_ONE_ROBOT_ASSEMBLY.md)
and [one robot adapter/export guide](remixes/one_robot_adapter_kit_README.md).
The [parametric adapter kit](remixes/one_robot_adapter_kit.scad),
[passive dock and rail entry coupon](remixes/dock/dock_passive_fit.scad),
[remaining nonconductive fit gauges](remixes/remaining_fit_gauges.scad), and
[Fusion one robot scaffold](remixes/fusion_one_robot_scaffold.py) are authored
source references. The adapter exporter can create provisional STLs and a
source-pinned mesh manifest, subject to its verification gate; these are **not**
approved permanent installation quantities or proof of physical fit. Confirm
actual part revisions, clearances, motion sweeps, licenses, pack enclosure,
ToF optical geometry, dock seating and protected contact charging before release.

**Appearance revision:** the selected look is rounder. Saved
[Sparky v0.1.0](originals/sparky-head/README.md) remains an unprinted upstream
head source considered by the Fusion fit guide, not a dimensionally qualified
or permanently selected assembled shell; EVA is historical.
[Four concept views](concepts/2026-11-03-rounded/README.md) use real shell/chassis
meshes but illustrative tracks/mechanism/mounts and no qualified battery envelope.

| Source | Author | Needed files | License |
| --- | --- | --- | --- |
| [Sparky v0.1.0](https://github.com/slahiri/sparky/releases/tag/v0.1.0) | Siddhartha Lahiri | [Saved shell, collar, rack, base/lid, archive and license](originals/sparky-head/README.md); unprinted upstream fit reference, not qualified final assembly | CC BY-SA 4.0 |
| [Tiny Engineer head](https://github.com/jamro/tiny-engineer/tree/aefc852a894174604a1e350bf9bc04c04f28ec80/3d_models) | Krzysztof Jamroz | [Saved Head/Hat/license/notice](originals/tiny-engineer-head/README.md); alternative reference only | CERN-OHL-S-2.0 |
| [EVA Robot head 7319190](https://www.thingiverse.com/thing:7319190/files) | Ksirailway-Base | [Saved EVA-Robot.3mf](originals/eva-head/EVA-Robot.3mf), [inspection/provenance](originals/eva-head/README.md); historical, four objects in assembly positions | CC BY-SA 4.0 |
| [SMARS 2662828](https://www.thingiverse.com/thing:2662828/files) | tristomietitoredeituit | [Saved screwless selection and documents](originals/smars/README.md): `chassis_-SL.stl`, `master_wheel.stl`, `slave_wheel_SL.stl`, `mechanical_track.stl`; `doc_lite.zip`, `Instructions.pdf` | CC BY-NC-SA 4.0 |
| [Stepper SMARS 2778904](https://www.thingiverse.com/thing:2778904/files) | unclejeff | [Two saved original STLs, source and hashes](originals/smars-stepper/README.md); WIP, slow drivetrain, original SMARS tracks, M4 motor/M3 slave mounts | Displayed CC BY 4.0; ancestor NC-SA difference recorded, retain both attributions and resolve before redistribution |
| [Gripper 4253681](https://www.thingiverse.com/thing:4253681/files) | bluino | [Saved originals and hashes](originals/gripper/README.md): `servo_case_arm.stl`, `arm_rack.stl`, `pinion_gear.stl` | CC BY 4.0 |
| [Original forklift 3027255](https://www.thingiverse.com/thing:3027255/files) | tristomietitoredeituit | [Saved E/F pieces, PDF and hashes](originals/forklift/README.md) | CC BY-NC-SA 4.0 |

Do not mix screwless/screwed axle and wheel variants. Follow original assembly
counts. Stepper chassis/lift/rounded head/WROOM/protected 1S pack/sensor mounting still needs measured fit checks.

Future permitted jobs: removable rounded-head bracket clearing camera/microphone/
speaker/button; small internal module spacers or camera-aperture corrections;
WROOM/protected 1S pack spacers, small sensor brackets, an SSD1306 bezel and thin replaceable
jaw tips. Keep the camera pose fixed relative to the jaws. **Current power envelope:** the old USB power-bank design is historical and
is not the selected first-robot supply. Use the [protected 1S power circuit
contract](../hardware/2026-11-17-one-pet-protected-power-circuit.md) as the
source for a protected cell with a real NTC, BQ24075 power-path charger,
regulated 5V actuator/audio and independent 3.3V sensor rails. The CAD must
fit the exact approved pack, protector, polarized connector, fuse, switch,
wire bend radii, buck/boost stages and physical service path. Check actual
tray dimensions, center of gravity, head/arm stability and ToF standoff
before final mounting. The battery, converter, charger, dock contacts and
power harness are NOT qualified for purchase, powered assembly or charging:
this schematic contract requires physical measurements and fault trials.
Do not substitute a power bank or infer battery fit from a source STL. Preserve the existing chassis and linkage.

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
