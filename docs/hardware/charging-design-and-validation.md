# One complete desk pet: protected 1S power and autonomous dock acceptance

Status November 10, 2026: **source-verified electrical design references, NOT an assembled or physically verified charger**. This retains all selected sensors, both 28BYJ48 motors, both MG90S, XIAO Sense, I2S speaker and the 5-pet expansion design. No powered contact or battery connection has been tested.

## What the actual source documents say

1. TI BQ24074 is a genuine single-cell Li-ion/LiPo **linear** charger with dynamic power path, configurable input/charge current up to 1.5A, PGOOD/CHG open-drain status and NTC temperature input. Datasheet https://www.ti.com/lit/ds/symlink/bq24074.pdf . Never confuse the battery charger's **OUT** with a fixed 5V, 3A motor rail.
2. Adafruit published an open-source [BQ24074 reference PCB](https://github.com/adafruit/Adafruit-BQ24074-PCB) and [pinout/load-sharing guidance](https://learn.adafruit.com/adafruit-bq24074-universal-usb-dc-solar-charger-breakout?view=all). It is a useful *source/reference*, not a generic module certification. Its LOAD output is no more than about 4.4V and the board's load sharing budget is up to 1.5A. The vendor says its 2-pin battery connector is for its own compatible cells; do not assume generic JST polarity or safe substitution. Licenses and vendor notices are retained.
3. [Pololu U3V70F5](https://www.pololu.com/product/2891/specs) is a 5V step-up regulator that can accept 2.9V input and has a 10A instantaneous input-current limit. This is **not** a guaranteed 5V output-current rating: thermal and input-voltage-dependent curves govern continuous load. Its published 0.6 by 1.6 inch footprint is a mechanical candidate only.

## Critical BQ24074 versus BQ24075 output distinction

The selected *source alternatives* are NOT interchangeable 5V supplies. TI
BQ2407x Rev N table 6 and electrical characteristics explicitly specify
BQ24074 OUT nominal **4.4V** (4.3..4.5V) and BQ24075 OUT nominal **5.5V**
(5.4..5.6V) when the input is sufficient. With input absent, OUT can follow
the battery near 3V through the power-path FET. Therefore **neither variant
is a regulated fixed 5V rail**. A BQ24075 VOUT pad MUST NOT be wired
directly into a 5V-only WROOM, Sense, servo or amplifier supply. A
source-verified *step-up/step-down* regulator with input acceptance covering
the actual entire power-path range, and real protected contact/thermal
tests, is required. With an ordinary 5V dock supply, the BQ24075 may not
reach 5.5V because headroom is limited; do not use that circumstance as
proof that a later adapter or fault cannot expose the higher rail rating.
Primary manufacturer: https://www.ti.com/lit/ds/symlink/bq24074.pdf .

The SparkFun PRT-13777 Battery Babysitter specifically uses **BQ24075**
plus **BQ27441-G1A** (not BQ24074); SparkFun documents a 3.0..5.5V
power-path output: https://learn.sparkfun.com/tutorials/battery-babysitter-hookup-guide/all .
That board's I2C fuel gauge must not be duplicated by a separate MAX17048.
Its published TS 10k bypass is not proof of actual external protected pack
NTC monitoring. No board, pack or energized dock is selected by this
comparison. A fail-closed software regulator-input screen is implemented
at `code/scripts/power_preflight.py::screen_bq2407x_output_path`; a
passing screen is only part of source qualification and cannot certify
an assembled battery or regulator.

## Single-robot block architecture requiring review

```text
5V bench supply (CURRENT LIMITED) or protected dock input
    -> correctly polarized, recessed, keyed contact pair
    -> input fuse, reverse/backfeed protection, transient protection
    -> measured charger IN (TI BQ24074 class power-path)
             | -> protected matched 1S battery via BAT and NTC
             | -> system/load node OUT (~battery voltage, not 5V)
                    -> selected peak-qualified 5V buck-boost converter
                           -> separately fused 5V motors/servos/speaker/head
                    -> measured quiet 3.3V regulator for accessory sensors
    -> PGOOD + CHG open-drain status via 3.3V MCP23017 inputs
    -> independent left/right normally closed seat-switch inputs
```

**Electrical limit resolved on paper, actual pack and dock still unqualified:** TI's programmable charger *input current* and *battery charge current* are limited to 1.5 A; the separate up-to-4.5 A OUT figure applies only under the datasheet's specified electrical conditions, including possible **battery supplement**. It is not an additional 4.5 A dock input or a guaranteed continuous output from the 5 V adapter. These are different limits: 4.5 A at OUT is **not** a guarantee of 4.5 A of sustained dock-adapter power or successful net battery charging. Dynamic power-path management can reduce charging current, and the battery can supplement the system load. Board copper, temperature, cell discharge rating and charger thermal regulation must also be qualified. A CHG-active indication does **not** prove net battery charging. Qualified dock behavior must keep motors disarmed and measure *all remaining WiFi, camera, display and audio peaks*, boost input current and signed battery current. If the real load cannot remain within the source, device, board, battery and thermal limits simultaneously, choose a qualified higher-capacity power-path design or a validated dock power mode; do not parallel unqualified modules or trust the BQ status pin. Reference: TI BQ24074 electrical specifications, https://www.ti.com/lit/ds/symlink/bq24074.pdf .

## Frozen source architecture for the first robot

The current `cap_power` entry in the canonical purchase register explicitly
targets a **protected 1S pack with real NTC, BQ24075 power-path candidate,
and a separately qualified 5 V buck-boost converter**. This is ONE
source architecture for selection, not a selected purchasable charger PCB,
battery or motor rail. The BQ24074 circuit above is a datasheet comparison
and must not silently replace the BQ24075 variant in the register.
Do not add more charger chip candidates until an actual carrier revision,
protection circuit, NTC connection, battery discharge/PCM trip,
connector/wire current ratings, output peaks and printed fit can be screened
together. BQ24075's possible 5.6 V OUT makes a step-up-only 5 V board
unsuitable. Dock contacts remain physically disconnected/unenergized;
neither `PGOOD` nor `CHG` is a pack-current sensor.

## Five volt converter topology is a hard purchasing gate

TI BQ24075 SYS/OUT can rise to approximately 5.6 V when docked while a
protected 1S cell can approach 3.0 V at the low-voltage design limit.
A plain step-up-only converter cannot regulate downward to 5.0 V from a
possible 5.6 V dock output. The existing source-first candidate
[Pololu S13V30F5 #4082](https://www.pololu.com/product/4082)
explicitly uses a buck-boost topology (2.8 to 22 V input), but its
continuous output current at a depleted cell and enclosure thermal curve
still require manufacturer-derated screening plus real loaded trials.
A generic board with the same chip name is not automatically equivalent.
The selected charger source and converter topology must match before
any actual regulator PCB or battery order. The existing
`screen_bq2407x_output_path` and `screen_one_cell_power_stack`
reject a boost-only path for BQ24075. An on-paper pass does not close
the protected-cell, NTC, connector, charge-current or heat gates.

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

The user's original 23-section `ESP32 Deskpet Ideas` research (active project sections 1–16, section titled **Docking — the OOMWOO pattern**) includes a **two receiver 38 kHz NEC-burst beacon** for final alignment, a normally unpowered dock contact, a short verification window and at most three attempts. The **read-only sensor acquisition and full NEC frame decoding** portion is now implemented in PR #17. Real signed bearing measurement, final approach motion, the beacon transmitter and independently qualified isolated contact/charger circuits remain absent. AprilTag/OpenCV predock still cannot authorize the final centimeter.

**Verified source reuse candidates:**

* [makerspet/oomwoo, dock-cycle RFC](https://github.com/makerspet/oomwoo/blob/main/contributions/dock-cycle/README.md) separates navigation to predock from final IR alignment, unpowered contact sensing, verification and recovery. Its ROS2/Nav2 and Gazebo stack is a research/reference, **not** software to install on this WROOM/XIAO/Mac robot. Adapt its isolation and transition criteria to the existing WROOM local safety owner, rather than porting a second motion coordinator.
* [wennycooper/Auto-Docking-Design](https://github.com/wennycooper/Auto-Docking-Design) is cited by OOMWOO as the modulated emitter and baffled receiver reference. The published docking RFC calls for two forward facing differential receivers for final homing, with wider-field receivers an optional independent search tier.
* [Vishay TSOP38238 datasheet](https://www.vishay.com/docs/82491/tsop382.pdf): this receiver rejects continuous 38 kHz light under automatic gain control. It must see compatible **bursts** (such as NEC), not an always-on LED. That is an electrical and decoder contract, not proof that the user's current boards have two spare timer-capable pins.

**Pin and driver source now reconcile:** GPIO36 and GPIO39 on the WROOM have independent read-only legacy ESP-IDF 4.4 RMT receiver channels. The slow reed/PIR inputs moved to MCP23017 GPIOB and no 12ms mux poll is used for ~560 microsecond NEC edges. The portable decoder requires a real 34-symbol full frame, correct active-low mark polarity, inverse address/command bytes and independently fresh same-code sightings. A local mirrored C++11 sanitizer smoke test passed 100 valid codes and 400 corrupted frames; the actual repository CI has NOT executed any of its four jobs. Real WROOM board pin accessibility, simultaneous RMT under actual WiFi/ADC behavior, transmitter, optical baffles, input bias and rate still need bench measurements. The driver cannot grant motion or charge.

**Proposed remaining software acceptance contract, not completed implementation:**

1. Predock state comes only from measured calibrated AprilTag camera intrinsics and observed WROOM cliff/obstacle safety. No AI decides physical contact.
2. Final alignment needs real timestamped left/right IR NEC burst observations from qualified hardware. Missing, conflicting, repeated or saturated receiver evidence yields **HOLD** and no forward motion. The final centimeter cannot rely only on camera pose.
3. At first contact or charger PGOOD the WROOM already immediately disarms locally. The dock-side contacts must remain **deenergized** until an **independent, physically verified** safe seating/current-limit/interlock circuit approves them. Source code cannot substitute for hardware isolation.
4. Verify bidirectional pack current and NTC/charger state under the complete load. A mere voltage rise within the originally suggested 10 seconds is not sufficient to prove net charging; BQ24074 PGOOD/CHG status alone also cannot prove it. A false or changed status cannot authorize power.
5. Limit attempts, never reverse blindly near an edge, and only retry following a fresh complete floor, front, rear, bumper and power check. The original three-retry concept is a maximum **after** physical clearance measurement, not permission to back out automatically today.

The source IR pin budget and read-only decoder are now implemented, but the complete robot remains **NOT DOCKING OR CHARGING VERIFIED** until the actual 38kHz beacon/transmitter, dual receiver physical measurements, terminal steering calibration, independently isolated contact/charger circuit, printed fit and repeated hardware approach/charge bench record all exist. This note is intentionally a gap and source reconciliation, not a completed software feature or an unapproved new purchase.

### Dual-receiver NEC beacon compatibility

The current `DualIrEvidence` implementation requires the **same complete
classic NEC address/command frame** to be received freshly by both physically
separate 38 kHz receivers. The two optical emitters therefore transmit the
same encoded frame on independently current-limited and optically baffled
channels. The emitter protocol and both receivers must be evaluated together.
OOMWOO reference variants with distinct left/right codes are NOT source
compatible with this matcher without a deliberate firmware redesign and
requalification. Equal codes establish correlated beacon identity only, not
measured signed steering bearing, safe final motion or charging permission.
This duplicates the exact rule in
`docs/hardware/complete-shopping-checklist.md` to prevent incompatible
beacon purchases or flashing.

## Last centimeter of autonomous docking

Actual AprilTag camera geometry and body safety can approach a visible guide, but the current `Coordinator._dock_approach` intentionally holds before powered contacts. **No control loop may infer charging contact from an image.** To finish autonomous physical seating, measure actual camera intrinsics, marker location, wheel steering scale, 8 sensor geometry, switch travel and stop distances, and add a physically qualified low-speed contact approach using multiple independent contact checks. Keep local cliff guard, one-use operator permit, 500ms watchdog and dock power motion lockout intact. No uncontrolled charging or movement.

## Physical dimensions needed in Fusion

Protected battery enclosure and connector, BQ class PCB plus 10K NTC, boost board and heat clearance, two connectors/contacts with current rating and spring travel, contact separation, final track width/height, printed guide taper, two independent NC seat switches, cooling, wire strain relief and fused service access. Parametric unpowered fit gauges exist in `docs/cad/remixes/remaining_fit_gauges.scad` and the earlier adapter kit; do not treat the nominal printed tray as a qualified lithium enclosure.

**Decision:** retain this design review as an option, not a verified purchasable wiring harness. Physical measurements are necessary to settle the charger/controller and boost choice.


## Terminal homing pin budget: real blocker, not a fake finished dock

Review of the original [OOMWOO dock-cycle reference](https://github.com/makerspet/oomwoo/blob/main/contributions/dock-cycle/README.md) and its [PCB specification](https://github.com/makerspet/oomwoo-pcb/blob/main/docs/SPEC.md) confirms a valuable reusable scheme: an *encoded* 38 kHz beacon and two separate, optically baffled front receivers allow differential final alignment. OOMWOO is Apache-2.0 and not a ready-to-flash docking solution for this WROOM/SMARS robot. Its software and actual PCB still require hardware bringup. Never assume constant IR illumination works with burst-rejecting demodulator AGC.

**Pinned ESP32 documentation check:** The official ESP32 [GPIO matrix and input-only description](https://docs.espressif.com/projects/esp-idf/en/v4.4.2/esp32/api-reference/peripherals/gpio.html) supports routing peripheral input signals from input-only GPIO36/39, with **no internal pullups**. It separately warns of GPIO36/39 interrupts under ADC or WiFi/Bluetooth sleep use; ESP-IDF describes an `adc_power_acquire()` workaround for GPIO interrupt glitches, with an added approximately 1mA draw. This is a *candidate* for dual RMT RX capture, not proof that both receivers decode valid NEC bursts in the pinned Arduino firmware or assembled device. Pin the selected receiver output bias and account for that sleep-mode silicon warning before approving the wiring.

**The software pin allocation collision is now resolved in source, not hardware:** Body GPIO13,14,25,26,27,32,33,23 still drive the two 28BYJ48 motors; 18/19 MG90S; 16/17 Sense UART; 21/22 I2C; 34 direct touch; 35 direct NC bumper. Slow reed and PIR now use the **existing MCP23017 GPIOB0 and GPIOB1**, with separate fresh optional status read and source tests. WROOM GPIO36/39 are reserved as independent **direct** IR input candidates. No actual NEC burst receiver, RMT capture, decoder or final terminal approach has been enabled. The existing 0x71 mux read occurs roughly every 84 ms, so it cannot detect 560 microsecond IR edges. IRremoteESP8266's FAQ does not promise two simultaneous independent receivers: https://github.com/crankyoldgit/IRremoteESP8266/wiki/Frequently-Asked-Questions .

**Selected source allocation, still physically unapproved:** `AccessorySensors` initializes MCP23017 BANK=0 GPIOB as 3.3 V inputs and reads it only after successfully sampling mandatory GPIOA. GPIOB0 is slow reed active LOW and GPIOB1 is slow PIR active HIGH; loss of GPIOB validity does not forge a new dock status. The existing `BodyControl.sample_optional_inputs` receives only fresh GPIOB events when optional build flags are enabled. WROOM GPIO36/39 are reserved for separate 3.3 V demodulated left/right IR receivers with external bias, pending actual ESP32 board pin exposure, boot, sleep/ADC erratum and two independent RMT RX channels on the **pinned** PlatformIO espressif32 6.9.0 / Arduino-ESP32 2.0.17 / ESP-IDF 4.4.7 stack. Never copy a newer Arduino 3.x RMT API without reviewing this pinned build. See [ESP32 GPIO restrictions](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/gpio.html) and [Espressif's GPIO36/39 erratum](https://docs.espressif.com/projects/esp-chip-errata/en/latest/esp32/03-errata-description/esp32/gpio-inputs-pulled-down.html).

Before approving physical wiring or shopping: verify (1) selected IR demodulator 3.3 V logic and decoded NEC frame format; (2) the new legacy 2-channel RMT adapter captures two genuine simultaneous independent sources under WiFi/audio load, with measured 34-symbol NEC polarity and filtering; (3) relocating reed/PIR to MCP GPIOB retains qualifying signal dwell and freshness; (4) physical receiver baffle geometry has a signed, repeatable left/right bearing; (5) local WROOM guard remains unaffected by missing/invalid IR. If the two GPIO capture constraints cannot be satisfied, the hardware allocation must be explicitly revised rather than quietly dropping existing user features.

**Permitted terminal state progression once hardware exists:** calibrated AprilTag predock; fresh independent dual IR observations with bounded attempts and alignment threshold; stop on lost/asymmetric/stale evidence; guarded short drive pulses with fresh WROOM safety before each pulse; stop on first physical seat contact; charging contact power stays disabled by the motion algorithm; qualified current-limited charger separately measures and approves contact/pack input; require real bidirectional pack current and thermal acceptance before declaring `charging_verified`. Never interpret MCP23017 PGOOD/CHG alone as accepted charge.

Two independent legacy ESP-IDF 4.4 RMT receivers and a strict 34-symbol classic NEC parser are now implemented in WROOM firmware, with read-only UART, XIAO HTTP and Mac API evidence. Physical receiver board, beacon transmitter, optical geometry, measured bearing, actual completed dock, charging controller and qualified last-centimeter movement are NOT verified. The new source never arms motors or charges batteries. This prevents an unsafe unsupported implementation shortcut while preserving the complete required product.


## Read-only terminal NEC calibration, after the actual receiver hardware exists

The WROOM now includes two independent legacy RMT receiver channels only in the `esp32_full` profile. The simple five-range `esp32_stepper` staging build does not initialize these channels. Its `ir` UART command, the XIAO `/api/ir` route and the authenticated Mac `/v1/robots/{robot_id}/dock/ir` endpoint all remain **read-only**. The strict 34-symbol classic NEC checksum decoder accepts only complete non-repeat frames, and the Mac rejects claimed charger or motor permission. Source protocol tests and a separate C++ mirror smoke exist; actual WROOM flash and real 38kHz optical receiver tests are not recorded.

Once the receiver **signal lines only** are powered from a bench-qualified 3.3V rail and the dock's charge contacts are physically isolated from any source, a human can hold the assembled but **motor-disconnected** robot left, centered and right of a test beacon and record optical evidence with existing authorized Mac API. Run these commands from the `code` directory with your private `DESK_ROBOT_OPERATOR_TOKEN` environment variable set on the local machine:

```sh
uv run python scripts/calibrate_terminal_ir.py --robot robot-01 --label left --samples 30 --out /tmp/robot-01-ir.jsonl
uv run python scripts/calibrate_terminal_ir.py --robot robot-01 --label center --samples 30 --out /tmp/robot-01-ir.jsonl
uv run python scripts/calibrate_terminal_ir.py --robot robot-01 --label right --samples 30 --out /tmp/robot-01-ir.jsonl
uv run python scripts/calibrate_terminal_ir.py --robot robot-01 --input /tmp/robot-01-ir.jsonl
```

The tool requires an actual advancing left/right RMT acquisition sequence, increasing local receive timestamps, at least 20 real observations per position and authentic per-robot token. It estimates optical left/right fresh-hit fractions and center same-beacon fraction. Three identical reception patterns cannot pass the differential signal candidate. **It cannot assign bearing angles, calibrate wheel turn sign, prove final clearance, allow powered contact, or claim electrical acceptance.** Never interpret its `candidate_differential_signal` as a motion permit. `code/tests/test_calibrate_terminal_ir.py` verifies good synthetic sample structure, stale/replayed/forged signals and no authority, without pretending the robot is assembled.

## November 11: final marker age check after health polling

An additional time-of-check versus time-of-use race remained after moving PnP off the event loop: a valid new AprilTag pose could become stale **during** the subsequent authenticated WROOM sensor status HTTP request. The existing local guard protects cliff and touch state, but that does not make the previously captured marker position current. `Coordinator._dock_approach` now invokes `assess_dock` again immediately before the command, using the actual monotonic clock. Any changed phase, in practice an expired marker, results in a `hold` response with no drive and no charging permission. `test_dock_motion.py` now includes a second WROOM status request delayed beyond the existing 200 ms marker validity window to enforce this rule. This is a source-level race fix with unverified CI and not a physical terminal docking acceptance.

## November 11: AprilTag inference age and audio event loop isolation

A concrete cross-robot priority bug was identified in the existing docking path. `Coordinator._dock_approach` called CPU heavy OpenCV AprilTag and PnP synchronously on the Mac asyncio event loop, potentially blocking the authenticated human speech and urgent cancellation tasks. Worse, it passed the **JPEG receipt time** as both the pose timestamp and the time to `assess_dock`. A detector taking longer than the existing 200 ms validity window could still produce an allegedly fresh marker and allow a drive based on old geometry.

The current canonical PR now delegates AprilTag inference to the existing `asyncio.to_thread` pattern with a two second deadline, and passes actual post inference `time.monotonic()` into the existing `assess_dock` stale pose policy. `dock_runtime.observe_actual_dock` uses the same correction for the read only diagnostic API. `test_dock_motion.py` exercises a delayed fake AprilTag detector and asserts that the event loop stays responsive while the resulting stale pose issues no motor command; `test_dock_runtime.py` checks a stale diagnostic never grants motion or charging authority. These tests were committed but are **not recorded passing** while GitHub Actions fails without worker steps. Actual capture exposure timing, motion latency and charged hardware remain physically unverified.


### Required measured power budget before charger selection

Record these *real measured values* at the lowest intended protected-cell voltage and separately while docked, rather than projecting a charger from the advertised motor or amplifier rating. Do not mark unmeasured fields as zero.

| Mode | 5 V continuous A | 5 V transient peak A | charger IN A | boost input A | signed battery A (+ discharge) | minimum 5 V rail V | charger/boost temperature C | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Idle with WiFi and all sensors | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | |
| Camera capture, reasoning and OLED | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | |
| Full speaker peak and simultaneous radio | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | |
| Both wheels and servo motion on safe fixture | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | |
| Seated, motors disarmed, speech/camera active | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | |
| Seated, motors disarmed, intended quiet charge mode | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | |

**Candidate, not selection:** TI BQ24190 has a switch-mode NVDC power-path topology and selectable nominal input current limit steps up to 3 A, subject to the actual ILIM, adapter, board thermals, and datasheet. Its charger registers and watchdog require different integration from the current BQ24074 read-only status plan; it is not a pin-compatible swap. Compare only after measurement. Primary datasheet: https://www.ti.com/lit/ds/symlink/bq24190.pdf . If reusing status semantics, Zephyr's Apache 2.0 charger driver is the candidate reference: https://github.com/zephyrproject-rtos/zephyr/blob/main/drivers/charger/charger_bq24190.c . No charger IC, electrical schematic, board, battery or power path is hereby approved or verified.

## November 12 research: switch-mode charger does not prove net charging

TI [BQ24195](https://www.ti.com/product/BQ24195) is a switch-mode 1S power-path alternative to the existing linear [BQ24074](https://www.ti.com/product/BQ24074) candidate. The BQ24195 has programmable input current limits (up to 3 A), NTC and fault reporting, and battery supplement mode. Importantly, its own documentation states that after charge current falls to zero under excessive system load, the battery may **discharge to supplement the dock source**. Consequently neither PGOOD, a charger-present indication, nor the existence of a nominal charging state is evidence of positive signed battery current. This is an additional acceptance hazard, not a reason to switch the PCB without a measured power budget.

**Reuse decision:** keep the present WROOM read-only GPIOA dock interlock and Mac power-preflight ownership. Do not add an unreviewed I2C charger driver, substitute a BQ24195 module, or treat an upstream software driver as a certified charging design. The BQ24195 requires a different PCB, input-limit configuration, battery temperature circuit, board-level protection and power sequencing; an I2C status integration would also require an explicit existing bus owner and a reviewed driver license/version. TI datasheets are component specifications, not redistributable software licenses. Adafruit's [BQ24074 PCB design](https://github.com/adafruit/Adafruit-BQ24074-PCB) remains the existing open hardware reference, subject to its own repository license and exact board revision.

**Next independent electrical acceptance:** with a qualified protected 1S pack and a current-limited bench setup, measure signed pack current, dock input current, 5 V boost output, thermals and ripple simultaneously during camera/WiFi/audio peaks and a safe motor-disabled docked state. Repeat at low battery voltage, hot/cold NTC boundaries, unplug and brownout. A battery discharge reading while docked fails the claim of net charging even if PGOOD/CHG or I2C status appears favorable. Until measurements and a reviewed schematic exist, leave charging unqualified and the terminal contacts unpowered. This is source research only; no powered experiment or driver test was performed.


## November 12 reusable charger alternative assessment: BQ24190, not an approved substitution

This comparison is a research gate, **not a wiring instruction or selection**. The existing BQ24074 design remains provisional and the contact supply must stay unpowered until independently qualified. A previous review conflated its 1.5 A programmable adapter input/charge limit with its separately specified OUT current. They are different ratings; neither proves sufficient delivered 5 V boost power or net battery charging under concurrent robot load.

| Candidate | Reusable upstream | Electrical and software implications | Decision |
| --- | --- | --- | --- |
| BQ24074 | TI datasheet and Adafruit open hardware PCB/reference; the board maker publishes its own battery connector and load limit guidance | Linear power path, 1.5 A programmed adapter input ceiling, OUT not a regulated 5 V rail; board thermal and battery supplement require measurement | Retain only as a provisional measured-load candidate |
| BQ24190 | TI switch-mode NVDC charger, Zephyr Apache-2.0 driver `drivers/charger/charger_bq24190.c` | Programmable input current up to 3 A with separate ILIM hardware ceiling; SYS follows an NVDC battery-related voltage, not a fixed 5 V motor rail. Adds I2C register ownership, input source detection, watchdog, faults and thermal constraints. Not pin-compatible with the existing board | Candidate only after measured peaks and validated breakout/PCB, no driver port yet |
| Linux BQ24190 charger driver | Linux `drivers/power/supply/bq24190_charger.c`, GPL-2.0 | Useful register-behavior reference, but copying implementation into the robot would impose license obligations and introduce an unqualified new charger owner | Read for behavior only; do not copy into firmware |

TI explains that BQ24190 dynamic power management first reduces charging current; if the input still cannot supply the system, its battery can supplement SYS. Therefore PGOOD, CHG and even an apparently healthy SYS voltage cannot independently prove **positive signed pack charging current**. For any candidate, keep the existing WROOM contact lockout, independently isolated unpowered contacts, matched protected 1S pack, NTC and hardware current limiting. Never let an I2C driver or status bit authorize charging or movement. Record actual dock-input droop, boost input/output currents, signed pack current, temperatures, camera/WiFi/audio bursts and servo/motor startup before selecting a charger. Check the candidate's PCB layout, connector polarity, component revision and distribution license independently; a chip datasheet is not a qualified breakout or reusable PCB license.

**Primary sources:** [TI BQ24074](https://www.ti.com/product/BQ24074), [TI BQ24190](https://www.ti.com/product/BQ24190), [Adafruit BQ24074 board guidance](https://learn.adafruit.com/adafruit-bq24074-universal-usb-dc-solar-charger-breakout), [Zephyr BQ24190 Apache-2.0 driver](https://github.com/zephyrproject-rtos/zephyr/blob/main/drivers/charger/charger_bq24190.c), [Linux GPL-2.0 reference driver](https://github.com/torvalds/linux/blob/master/drivers/power/supply/bq24190_charger.c). This assessment adds **no executable test**, electrical assembly or physical pass. Next source-level action: check the existing `power_preflight.py` inputs against the full measured current table before any candidate replacement.

## November 12 instrumentation research: prove net pack current, not just dock status

The existing charging design already requires signed pack current. This review narrows the measurement implementation without choosing or wiring a charger. The [TI INA226](https://www.ti.com/product/INA226) is a bidirectional, single-channel 16-bit shunt monitor with 0 to 36 V common-mode range, configurable conversion/averaging and I2C telemetry. It can be evaluated for **measurement**, not charge authorization. Its register conversion cadence and shunt calibration must be logged alongside battery current polarity; a 5 V rail monitor cannot substitute for a pack-path measurement. A high-side shunt in a protected pack circuit changes impedance, heating and protection interactions, so location, resistor power, copper and safety must be reviewed by a qualified electrical reviewer before any wiring.

| Reference | Reuse and license | Fit and limitation |
| --- | --- | --- |
| [TI INA226 product/datasheet](https://www.ti.com/product/INA226) | Primary device specification; not a firmware license | One channel per measured path; signed shunt current possible with calibrated polarity. Its I2C readings are not an independent safety interlock |
| [Adafruit INA228 PCB](https://github.com/adafruit/Adafruit-INA228-PCB) | Published PCB under Creative Commons Attribution ShareAlike, with its own notice | Higher-resolution alternative for a bench measurement fixture, **not** an interchangeable INA226 module or an approved battery wiring design |
| [Adafruit INA228 Arduino library](https://github.com/adafruit/Adafruit_INA228) | BSD licensed software, subject to its notices | Reusable driver candidate only if that specific INA228 device is selected; do not import into the WROOM motion-critical loop merely to gather charging data |

**Minimum evidence record per operating mode:** timestamp, charger input voltage/current, boosted 5 V voltage/current, battery terminal voltage and **signed battery current** (positive direction explicitly defined), ambient/charger/boost temperature, dock contact state, CHG/PGOOD state, and sensor acquisition freshness. Capture idle, camera/WiFi burst, full-duplex audio, stepper startup, servo loaded hold, low-pack-voltage and unplug/brownout. Report current measurement bandwidth and peak capture method: slow averaged I2C samples can miss servo inrush, so independently capture transient peaks with suitable instrumentation. Treat negative signed pack current while docked as battery supplement, not a charging success. Do not infer cell charge acceptance from voltage or GPIO alone.

**Decision:** no new driver, charging enable, battery connection, or board selection is justified by this research. The existing power preflight and WROOM dock lockout remain the owners. Next integration step after real measurements is to record the calibrated shunt/polarity and worst-case transient data, then evaluate whether BQ24074 or a different protected power path can satisfy the complete robot's simultaneous loads. No tests or hardware trials were performed for this note.
