# One complete desk robot: builder route and release gates

**Status: NOT A POWERED OR MOVING ASSEMBLY RELEASE.** This is the single navigation and execution entry point for the selected first pet, its dedicated dock and the one shared room station. Source code, tests, imported meshes and shopping candidates exist, but actual carrier revisions, full printed fit, battery, charger, dock contacts, motor cutoff and real acoustic trials remain unqualified. Do not substitute a plausible concept render for a measured build.

A first completed, physically qualified pet is required before buying parts for four more. The robot retains the Mac brain, Xiaozhi live Opus voice, XIAO ESP32S3 Sense streaming camera, microphone and display, WROOM independent safety, all eight mux isolated VL53L0X rangers, both positional MG90S, and the shared stationary room sensor. The room station never grants motion or charge permission.

## 1. Buy only against the canonical two lists

**Clean-checkout prerequisite (no existing Python venv required for read-only views):** Running these read-only procurement generators requires only standard-library Python 3 (`python3`) from `code/` and preserves all `HOLD` gates without modifying any file. For full repository tests, calibration scripts, or later firmware/integration work, set up the pinned Python 3.11 environment in [the firmware and Mac setup guide](build.md) (`uv sync --extra dev --python 3.11 --locked`) first before using `uv run --no-sync`.

For the first unit, use the **only two builder facing lists** printed by the `first-robot-markdown` command below: (1) reported owned or ordered and (2) first-unit remaining parts with conditional holds. Their source is [the canonical full feature plan](../hardware/full-feature-plan.json), [the reported inventory and photos](../hardware/photo-inventory-2026-11-04.md), and [the reviewed purchase register](../hardware/2026-11-16-five-pet-purchase-register.md). The separate [complete shopping checklist](../hardware/complete-shopping-checklist.md) is a **five-pet fleet projection**, NOT a one-unit checkout. Do not order fleet quantities from that static page or hand-edit a second first-unit cart.

From the repository root, enter `code/` and print the verified stdlib-only first complete pet, its dock, and one station projection without modifying the ledger or requiring a virtualenv:

```sh
cd code && python3 scripts/procurement_release.py --format first-robot-markdown
```

For **evaluation samples only**, print the separate, source-locked pilot worksheet:

```sh
cd code && python3 scripts/procurement_release.py --format pilot-cart-markdown
```

The November 18 pilot recorded thirteen candidate SKUs, seventeen individual sample items and USD 40.41 of historical merchandise quotes, **excluding shipping, tax, previous spending and unknown mandatory hardware**. It is not a safe to buy finished robot, charger or five pet kit. Check seller stock, exact PCB revision and actual delivered totals before any optional sample order. The first **complete** prototype has a USD 50 delivered cap **including previously paid items**. An unquoted mandatory part or unknown historical payment means no approved total.

Do not buy a lithium pack, powered docking contacts, five sets of VL53L0X, or either motor alternative until the specific electrical and physical gates below have receipts. Count owned MG90S, MAX30102, steppers, drivers, XIAO in transit and the Feather by actual revision before declaring a checkout balance.

## 2. Print only reversible fit pieces before releasing final numbered parts

The [Fusion assembly and measured source geometry](../cad/FUSION_ONE_ROBOT_ASSEMBLY.md), [CAD source and licensing register](../cad/README.md), and [measurement sheet](../cad/FUSION_MEASUREMENT_SHEET.md) own the mechanical plan. The [rounded appearance study](../cad/concepts/2026-11-03-rounded/README.md) is a concept, **not** a fitted production STL set.

1. Inspect the actual assembled battery, PCB, servo, wheel, antenna, camera lens and connector dimensions. Identify the exact revision and take dimensions from hardware rather than nominal chip data.
2. Import the pinned licensed SMARS, Sparky head, forklift and gripper references through the existing Fusion scaffold and check the separate servo lift and jaw swept volumes.
3. Print small battery, breakout, speaker baffle, sensor angle, servo horn and dock fit coupons where the Fusion guide calls for measurements. Preserve every upstream noncommercial and share alike restriction.
4. Check lens height against the actual VL53L0X minimum measurement, camera view of floor objects and raised jaw, battery removal and wire bending, microphone/speaker paths, center of gravity, track clearance and dock seating.
5. **Do not print a numbered final robot or dock assembly as a qualified kit** until the measured, editable fitted assembly, part numbers, quantities, orientation and fasteners exist. The former 68 mm battery gauge was undersized for the 86 mm candidate pack. The current 86 mm body-only coupon is corrected, but it does not establish connector, charger, boost, restraint or service clearance. Its provisional tray with tabs exceeds the original chassis XY diagonal; resolve that conflict through the measured assembly, not by scaling all STLs.

## 3. Wiring starts unpowered and with independent safety

Use [the generated exact signal harness](../hardware/one-robot-signal-harness.generated.md) and [full pin and electrical wiring plan](../hardware/full-feature-wiring-and-shopping.md), then [detailed wiring and stop behavior](../hardware/wiring.md). These remain the source for connector orientation. Do not connect an unknown breakout from a chip name alone.

```text
Mac, private memory and Xiaozhi tool ownership
  ⇅ consented streaming/audio and robot communications
XIAO ESP32S3 Sense head → live camera, PDM microphone, OLED, I2S speaker
  ⇅ guarded head to body link
ESP32 WROOM → local STOP/latch, ToF, IMU, touch, tracks and gripper
  ├ 0x70 mux: four floor rangers, front and three read-only side/rear
  └ 0x71 mux: isolated accessories, fuel monitor and dock status

One separate stationary Feather nRF52840 → USB room observations to Mac
Dedicated unpowered dock → mechanical seat, then qualified charger only
```

The WROOM owns movement safety even during a Mac fault. On its sensor bus, SDA is GPIO21 and SCL is GPIO22; the 0x70 and 0x71 mux lanes must be isolated and verified at 3.3 V. A read-only side or rear observation cannot authorize reversing. The selected head owns its existing PDM pins and Xiaozhi audio path, not a second microphone stack.

Review [the BQ24075 candidate power architecture and actual tests](../hardware/charging-design-and-validation.md) and [read-only dock seat and charge status wiring](../hardware/read-only-dock-charge-pins.md). The BQ24075 SYS/OUT can exceed 5 V; never feed its possible 5.6 V directly to a nominal 5 V load. Its separate buck boost must be rated across depleted cell and dock output, including peak current and temperature. A charger PGOOD, CHG or dock switch alone does **not** prove net cell charging. Until exact protected 1S pack, real NTC to TS, fuse, regulator, reverse polarity, properly recessed contacts and signed cell current pass physical review, keep battery and dock electrical contacts disconnected.

## 4. Build and inspect code without energizing a robot

Use the [current firmware build guide](build.md) for selected WROOM `esp32_full`, experimental guarded DC `esp32_dc_full` and XIAO Sense overlay, not the historical Freenove or CoreS3 sections. Record the board revision, source SHA, pinned upstream versions, exact command, result and binary hash in [the verification ledger](../records/verification.md).

The room station has [its own pin map, safe bench and full soil PlatformIO profiles](../../code/firmware/room_station/README.md). The safe default leaves the analog soil probe off. Before enabling the full profile, verify actual 3.3 V probe output and analog A0, SCD40 and BME688 I2C carriers, optional AMG8833, and a separate qualified 5 V supply for the LD2410C with **3.3 V UART**. The station uses the existing owned Feather if its actual board qualifies. Confirm a new USB reader session and real sampling freshness; a mock frame cannot qualify a rail.

The already committed source and host tests cover room SCD40 readiness bus errors, BME688 range contracts, staged thermal frames, radar sample time, soil ADC and the Mac decoder. Run the existing repository CI and the room station physical evidence procedure. Do not call a canceled CI run a pass or substitute passing synthetic frames for measured sensor output.

## 5. Calibrate physical interaction, then permit only approved operations

1. With independent motor power disconnected, inspect all electrical polarity, pin strapping, fuses, 3.3 V pullups, USB ground paths and power backfeed. Record actual idle and worst case current on a current limited fixture before a battery connection.
2. Execute the [real MPU6050 tilt, handling and vibration trials](imu-handling.md). A pickup, putdown or restored connection must never silently rearm motor power.
3. Execute [the gripper and servo fit steps](first-gripper-test.md) and [force feedback calibration](force-feedback-gripper.md) using the actual flat key and wrapped candy. A commanded servo angle is not proof of a grasp.
4. On a raised/tethered fixture, test stale or absent range readings, all four floor sensors, mixed motor/gripper/audio loads, loaded stopping distance and the independent external motor cutoff on a halted CPU. No source build can certify real desk edge operation.
5. Validate passive unpowered docking alignment, left/right independent seat inputs, insulated recessed contacts, contact bounce and correct polarity **before** any external electrical enable. Then use a properly protected qualified pack and a current limited measured charge setup; verify signed net battery current under real WiFi/audio load and fault behavior.
6. Use [the private acoustic capture and timing procedure](sense-aec-port.md) to measure real audible speaker interruption and double talk. Digital I2S acceptance does not establish acoustic playback completion.

## 6. Mac setup, consent, STOP and private evidence

Follow [Mac and firmware interfaces](interfaces.md), [live conversation](live-conversation.md), and [multimodal world evidence ownership](multimodal-voice-video-orchestration.md). Keep Xiaozhi as the single realtime microphone, speaker and MCP route. Only consented persistent camera and microphone streams may contribute. Old frames, stale tools and another pet's memory cannot authorize movement. New human speech preempts speech playback while the independent WROOM keeps local safety authority.

Quiet mode uses the existing operator-only `POST /v1/pet/{robot_id}/quiet` route. Send `{"quiet": true}` to suppress spontaneous pet speech and activity while keeping user-requested interaction available, and send `{"quiet": false}` through the same operator route to leave quiet mode. The tool token is intentionally not authorized to change quiet mode. Entering quiet cancels current pet speech through the same bounded stop path; it does not arm movement, clear a local WROOM fault or qualify an acoustic stop.

Do not put personal audio, camera recordings, room occupancy histories, raw conversations or private keys in GitHub. Keep per pet memory isolated. Record software and physical trials separately, with robot identity, board revision, source hash, test fixture, capture clock, expected and actual behavior, failures and safe recovery. STOP, fault, contact loss, reboot and putdown require deliberate explicit safe resume, never automatic rearm.

## 7. Final release decision

The permanent gates are recorded in [product definition](../product-definition.md), [the full engineering plan](../PLAN.md) and [the verification ledger](../records/verification.md). Before claiming the first robot ready, prove complete pinned firmware builds and integrations on the exact release SHA, natural speech and grounded visual behavior, physical device audio cutoff, reliable floor stops, at least 8/10 successful unassisted physical grasp-and-place trials in each of the key and candy categories on the same qualified assembly ([A5 procedure](first-gripper-test.md)), qualified battery charging and full docking, assembled printable fit, true delivered cost, and the privacy and recovery trials. The [Guide 60 spatial acceptance](../plans/spatial-first-unit/60-object-recall-and-navigation.md#acceptance) is also mandatory. Require at least 9/10 valid re-anchors with translation error at most 20 mm, 8/10 remembered-object returns from changed robot starting positions with stationary targets, and zero false arrivals and zero unsafe commands in the moved/occluded and other negative trials. Record the assembly, calibration, source SHA and fresh target evidence. Missing or failed spatial trials prohibit duplication. Only after that first pet passes should the four sibling robots and four more docks proceed to full purchasing. Retain the same one shared room station; do not purchase a second station as part of fleet expansion.

**Current outcome: source and staged bench engineering can proceed. Final parts printing, full buying release, loaded desk movement, battery charging and autonomous docking remain HOLD until the named receipts exist.**
