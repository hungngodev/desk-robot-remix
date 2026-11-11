# One complete desk pet: protected 1S power and autonomous dock acceptance

Status November 10, 2026: **source-verified electrical design references, NOT an assembled or physically verified charger**. This retains all selected sensors, both 28BYJ48 motors, both MG90S, XIAO Sense, I2S speaker and the 5-pet expansion design. No powered contact or battery connection has been tested.

## What the actual source documents say

1. TI BQ24074 is a genuine single-cell Li-ion/LiPo **linear** charger with dynamic power path, configurable input/charge current up to 1.5A, PGOOD/CHG open-drain status and NTC temperature input. Datasheet https://www.ti.com/lit/ds/symlink/bq24074.pdf . Never confuse the battery charger's **OUT** with a fixed 5V, 3A motor rail.
2. Adafruit published an open-source [BQ24074 reference PCB](https://github.com/adafruit/Adafruit-BQ24074-PCB) and [pinout/load-sharing guidance](https://learn.adafruit.com/adafruit-bq24074-universal-usb-dc-solar-charger-breakout?view=all). It is a useful *source/reference*, not a generic module certification. Its LOAD output is no more than about 4.4V and the board's load sharing budget is up to 1.5A. The vendor says its 2-pin battery connector is for its own compatible cells; do not assume generic JST polarity or safe substitution. Licenses and vendor notices are retained.
3. [Pololu U3V70F5](https://www.pololu.com/product/2891/specs) is a 5V step-up regulator that can accept 2.9V input and has a 10A instantaneous input-current limit. This is **not** a guaranteed 5V output-current rating: thermal and input-voltage-dependent curves govern continuous load. Its published 0.6 by 1.6 inch footprint is a mechanical candidate only.

## Single-robot block architecture requiring review

```text
5V bench supply (CURRENT LIMITED) or protected dock input
    -> correctly polarized, recessed, keyed contact pair
    -> input fuse, reverse/backfeed protection, transient protection
    -> measured charger IN (TI BQ24074 class power-path)
             | -> protected matched 1S battery via BAT and NTC
             | -> system/load node OUT (~battery voltage, not 5V)
                    -> selected peak-qualified 5V boost
                           -> separately fused 5V motors/servos/speaker/head
                    -> measured quiet 3.3V regulator for accessory sensors
    -> PGOOD + CHG open-drain status via 3.3V MCP23017 inputs
    -> independent left/right normally closed seat-switch inputs
```

**Engineering conflict to resolve:** The maximum 1.5A charger/input-path budget might not supply the boost input current drawn by the full rover. The battery may supplement load during docking, so a CHG-active indication does **not** prove net battery charging. Qualified dock behavior must keep motors disarmed and measure *all remaining WiFi, camera, display and audio peaks*. If those exceed the actual source/charger output rating, choose a higher-rated power-path controller or separate safe power modes; do not parallel unqualified modules or trust the BQ status pin.

## Required physical acceptance before purchasing five sets or energizing contacts

* Confirm the actual cell/pack chemistry, connector polarity, PCM/protection board, allowable charge/discharge C-rates, NTC wiring, low-cell cutout, dimensions and verified manufacturer datasheet. No bare lithium cell or floating dock terminal.
* On a current-limited bench supply, record simultaneous 5V loads with two motors, two servos, Sense camera/WiFi, OLED, amplifier and all selected accessories. Record idle, average, startup surge, servo stall and audio peak. Keep motors on a raised test fixture and do not stall them intentionally long enough to overheat.
* Input those measured currents and candidate ratings into `code/scripts/power_preflight.py`. Demand protected pack continuous/discharge rating, thermal margin and low-pack-voltage boost output. A pass on paper is not a thermal test.
* Verify docking guide, spring stroke, hidden contact insulation, correct polarity, contact bounce and independent mechanical seat switch behavior with **zero power**.
* With a protected qualified pack only, measure input current, pack terminal voltage, real pack charge/discharge current (bidirectional meter, not CHG/PGOOD GPIO), charger/boost thermals and 5V output ripple over a complete safe charge cycle. Check removal/power-loss, wrong seating, intermittent contact and brownout recovery. The WROOM now latches a local power/contact lockout at **either** seat input or charger PGOOD, instead of waiting for both seat switches. When a dock MCP23017 is installed, missing, invalid, unsequenced or 500 ms stale GPIO samples stop the local drive and prevent any new arm. A sensor fault preserves the MG90S holding PWM rather than deliberately releasing a key. An observed full removal clears only the contact latch, never automatically rearms. This logic is committed with deterministic C++ regression, **not** physically tested; live contact circuits and charger power remain unqualified.
* A lab reviewer should confirm NTC fail behavior, fused charger input, overcurrent protection, undervoltage and accidental short behavior before regular use. The MCP23017 is read-only and **does not activate charging**.
* Do not turn `charging_verified` true in firmware or UX based on simulated pin evidence. New authenticated `GET /v1/robots/{id}/dock/evidence` reports stable repeated status classifications while leaving both charge and motion authorization false.

## Fresh safety after each camera image

The existing calibrated AprilTag guarded approach previously called WROOM
`_assert_armed_health` **before** snapshot and PnP. A large camera delay
could make that Mac safety response obsolete by the time the pulse command
was generated. The controller now checks local body safety again
**after** the real camera and marker inference, immediately before every
100 ms turn/forward pulse. The camera fetch is bounded to two seconds.
Changed cliff, touch, IMU or side/rear clearance status refuses the pulse.
The physical WROOM watchdog and local guard remain the ultimate authority,
and the final contact approach stays disabled.

`code/tests/test_dock_motion.py` includes synthetic status races where the
body becomes disarmed or side/rear clearance fails during the image. Both
must yield **no motor command**. Tests were committed but no passing host
or physical trial has been recorded.

### Full build boot and hot removal behavior

The `esp32_full` PlatformIO environment now compiles `DESK_ROBOT_REQUIRE_DOCK_MONITOR=1` and the WROOM setup calls `control.require_dock_monitor(true)` locally before any network or head commands. This refuses arming when the MCP23017 is missing from startup, when a required I2C GPIOA read has never succeeded, or when samples are invalid or over 500 ms old. A single seated switch, not just both switches, or PGOOD immediately latches contact stop; after full removal and restored fresh sensing, rearming still requires the operator. An unpowered sensor loss stops wheels but retains servo holding PWM rather than dropping a carried object. Source-level C++ tests cover absence, hot removal, old samples, single contact and recovery. No charger output or battery connection is enabled by these changes.

## Reuse original OOMWOO dock design rather than inventing a final approach

The user's original 23-section `ESP32 Deskpet Ideas` research (active project sections 1–16, section titled **Docking — the OOMWOO pattern**) includes a **two receiver 38 kHz NEC-burst beacon** for final alignment, a normally unpowered dock contact, a short verification window and at most three attempts. This idea **has not been implemented** in PR #17. The present AprilTag/OpenCV observation and guarded predock approach are **not** a substitute for the close-range homing evidence or an electrically qualified contact state machine.

**Verified source reuse candidates:**

* [makerspet/oomwoo, dock-cycle RFC](https://github.com/makerspet/oomwoo/blob/main/contributions/dock-cycle/README.md) separates navigation to predock from final IR alignment, unpowered contact sensing, verification and recovery. Its ROS2/Nav2 and Gazebo stack is a research/reference, **not** software to install on this WROOM/XIAO/Mac robot. Adapt its isolation and transition criteria to the existing WROOM local safety owner, rather than porting a second motion coordinator.
* [wennycooper/Auto-Docking-Design](https://github.com/wennycooper/Auto-Docking-Design) is cited by OOMWOO as the modulated emitter and baffled receiver reference. The published docking RFC calls for two forward facing differential receivers for final homing, with wider-field receivers an optional independent search tier.
* [Vishay TSOP38238 datasheet](https://www.vishay.com/docs/82491/tsop382.pdf): this receiver rejects continuous 38 kHz light under automatic gain control. It must see compatible **bursts** (such as NEC), not an always-on LED. That is an electrical and decoder contract, not proof that the user's current boards have two spare timer-capable pins.

**Do not fabricate hardware pin assignments.** The chosen WROOM already has both steppers, two MG90S, physical touch/bumper/reed/PIR, UART, and I2C allocated. Decoding ~560-microsecond IR edges by occasional MCP23017 polling at 12 ms intervals is not technically sound. Before adding two TSOP receivers to the mandatory shopping list, identify and verify two physically usable interrupt/RMT inputs on the *actual board* or an existing physically capable head interface, and retain the local cliff and rear sensor fail-closed priority. No new head servo, chassis replacement, separate ROS2 computer or from-scratch driver is justified by this reference.

**Proposed remaining software acceptance contract, not completed implementation:**

1. Predock state comes only from measured calibrated AprilTag camera intrinsics and observed WROOM cliff/obstacle safety. No AI decides physical contact.
2. Final alignment needs real timestamped left/right IR NEC burst observations from qualified hardware. Missing, conflicting, repeated or saturated receiver evidence yields **HOLD** and no forward motion. The final centimeter cannot rely only on camera pose.
3. At first contact or charger PGOOD the WROOM already immediately disarms locally. The dock-side contacts must remain **deenergized** until an **independent, physically verified** safe seating/current-limit/interlock circuit approves them. Source code cannot substitute for hardware isolation.
4. Verify bidirectional pack current and NTC/charger state under the complete load. A mere voltage rise within the originally suggested 10 seconds is not sufficient to prove net charging; BQ24074 PGOOD/CHG status alone also cannot prove it. A false or changed status cannot authorize power.
5. Limit attempts, never reverse blindly near an edge, and only retry following a fresh complete floor, front, rear, bumper and power check. The original three-retry concept is a maximum **after** physical clearance measurement, not permission to back out automatically today.

The complete robot remains **NOT DOCKING OR CHARGING VERIFIED** until the IR receiver pin budget, beacon, dock-side isolated charger/contact circuit, actual printed fit and a repeated hardware approach/charge bench record all exist. This note is intentionally a gap and source reconciliation, not a completed software feature or an unapproved new purchase.

## Last centimeter of autonomous docking

Actual AprilTag camera geometry and body safety can approach a visible guide, but the current `Coordinator._dock_approach` intentionally holds before powered contacts. **No control loop may infer charging contact from an image.** To finish autonomous physical seating, measure actual camera intrinsics, marker location, wheel steering scale, 8 sensor geometry, switch travel and stop distances, and add a physically qualified low-speed contact approach using multiple independent contact checks. Keep local cliff guard, one-use operator permit, 500ms watchdog and dock power motion lockout intact. No uncontrolled charging or movement.

## Physical dimensions needed in Fusion

Protected battery enclosure and connector, BQ class PCB plus 10K NTC, boost board and heat clearance, two connectors/contacts with current rating and spring travel, contact separation, final track width/height, printed guide taper, two independent NC seat switches, cooling, wire strain relief and fused service access. Parametric unpowered fit gauges exist in `docs/cad/remixes/remaining_fit_gauges.scad` and the earlier adapter kit; do not treat the nominal printed tray as a qualified lithium enclosure.

**Decision:** retain this design review as an option, not a verified purchasable wiring harness. Physical measurements are necessary to settle the charger/controller and boost choice.
