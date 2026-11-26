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

**Provisional downward VL53L0X range qualification:** The source-only
[GY-530 optical height trials](remixes/vl53l0x_gy530_fit_gauge.scad) render
three stationary, nonconductive open supports at board-rim heights 35, 45 and
55 mm, named `vl53l0x_gy530_height_trial_035`, `_045` and `_055`
in the fit kit. Use one actual carrier, unpowered while positioning, and
measure its **real lens-to-desk distance** and any cone obstruction before
collecting reflectance/range evidence through the normal isolated WROOM
sensor profile. The source heights are not lens heights; the PCB thickness,
lens position, window and cable bend remain unverified. These are removable
bench coupons, with zero approved installed quantity, not qualified floor
brackets or permission to move toward an edge. Their original authored
source is CC0; the selected GY-530 outline is only a nominal vendor drawing.

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

The STL fit kit manifest records a provisional FDM starting layer height of
0.2 mm, not a nozzle diameter or guaranteed XY fit tolerance. Select the actual
nozzle in the slicer, print a small coupon in the intended material, and measure
with calipers before adjusting the source-specific clearance. Do not add a
global 0.2 mm offset to every model. Regenerate older manifests with the exporter.

Each export must record source/license, dimensions, changes and hash. Derived
SMARS geometry retains its noncommercial/share-alike terms. Software MIT terms
do not relicense printed designs. Fusion tools are exposed; verify the live connection and active design before editing.
The EVA case has its own CC BY-SA 4.0 terms; preserve its attribution and mark
changes to it. A combined mechanical remix must respect every applicable source
license; do not assume the software MIT license covers the assembled robot CAD.

## Distribution boundary: separate components versus combined derivatives

Keep upstream meshes as individually attributed components in the Fusion
scaffold. A collection of independent components is not automatically a
single licensed adaptation; each component retains its terms, including
any noncommercial restrictions. A fused or otherwise inseparable derivative
of CC BY-SA 4.0 head geometry and CC BY-NC-SA 4.0 SMARS geometry cannot
be cleared for sharing by simply choosing the more restrictive license:
the two share-alike grants are not compatible for that adaptation.
Obtain separate permission or redesign the affected geometry independently
before distributing such a derivative. File separation alone does not
establish legal independence. See the [Creative Commons remix guidance](https://creativecommons.org/faq/#can-i-combine-material-under-different-creative-commons-licenses-in-my-work)
and [official compatible-license list](https://creativecommons.org/compatible-licenses/).

Original integration software remains MIT; independently authored adapter
geometry with an explicit CC0 declaration remains CC0. A source comment
or a matching mesh hash is provenance evidence, not proof of ownership
or permission for imported geometry. Preserve the original sources,
creator credits, change records and applicable terms in every release.

Tiny Engineer remains a CERN-OHL-S-2.0 reference, not an MIT head design.
Before adopting or conveying hardware based on it, review the
[definitive CERN OHL text](https://cern-ohl.web.cern.ch/) for Complete Source,
notices, source availability and the scope of the strongly reciprocal grant.

Cozmars is version-specific: the
[external V2 comparison](FUSION_ONE_ROBOT_ASSEMBLY.md#cozmars-packaging-comparison-before-sparky-fallback)
uses the pinned model repository without a LICENSE file and records the
creator's noncommercial share-alike distribution terms.
The [Cozmars V3 hardware README](https://github.com/hyansuper/cozmars_v3_hardware)
instead names the TAPR Open Hardware License. Do not apply the V3 declaration
retroactively to V2, infer a grant from the separate firmware, or import
V3 files until the exact revision, applicable license and ancestor rights
are recorded. TAPR OHL has its own documentation and distribution
obligations ([license text and guidance](https://tapr.org/the-tapr-open-hardware-license/)).
Neither version is a newly authorized CAD import or commercial release.

The saved N20 screwless chassis is historical and does not fit 28BYJ-48 motors.
The stepper remix is a different variant; verify matching track/slave-wheel
selection and forklift interface, not only motor mounting. STL source-coordinate
bounds and byte integrity do not establish millimeters, manifoldness, printability
or physical fit. No full assembly or cliff-coverage check has occurred.


## A4 paper overlays for unpowered fit screening

The source-derived [paper template exporter](remixes/print_2d_fit_templates.py)
produces five A4 SVG pages (`ranger`, `speaker`, `dock`, `dock_guide`, and `power`)
for the nominal GY-530 PCB outline, rectangular Challenge speaker body,
passive dock AprilTag paper/pocket dimensions, passive dock rail entry guide,
and candidate 1S pack/tray footprint. From the repository root, run:

```sh
python3 docs/cad/remixes/print_2d_fit_templates.py --output /tmp/robot-paper-fit
python3 docs/cad/remixes/print_2d_fit_templates.py --output /tmp/robot-paper-fit --verify
```

Print each SVG at **100% / actual size**, never "fit to page", and independently
measure the horizontal **100 mm** and **50 mm** and vertical **25 mm** reference
features on the resulting paper. The pages label front/top and back/bottom,
carry pinned source dimensions and a digest manifest, and deliberately
contain **zero approved drilling holes**. The dock outline is not a usable
AprilTag image. These are reversible, unpowered **nominal envelopes**, not
measured carrier fit, final mounting/cut patterns, camera calibration, a
safe charger or an approved final printable robot. Enter actual caliper,
mounting and optical measurements in
[Fusion measurement sheet](FUSION_MEASUREMENT_SHEET.md) before final parts.
