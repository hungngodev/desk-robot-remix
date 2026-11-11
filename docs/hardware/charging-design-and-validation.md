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
* With a protected qualified pack only, measure input current, pack terminal voltage, real pack charge/discharge current (bidirectional meter, not CHG/PGOOD GPIO), charger/boost thermals and 5V output ripple over a complete safe charge cycle. Check removal/power-loss, wrong seating, intermittent contact and brownout recovery. The existing WROOM local `dock_power_lockout_` disarms motors when both seat switches and input-good register; safety on sensor loss must be tested.
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

## Last centimeter of autonomous docking

Actual AprilTag camera geometry and body safety can approach a visible guide, but the current `Coordinator._dock_approach` intentionally holds before powered contacts. **No control loop may infer charging contact from an image.** To finish autonomous physical seating, measure actual camera intrinsics, marker location, wheel steering scale, 8 sensor geometry, switch travel and stop distances, and add a physically qualified low-speed contact approach using multiple independent contact checks. Keep local cliff guard, one-use operator permit, 500ms watchdog and dock power motion lockout intact. No uncontrolled charging or movement.

## Physical dimensions needed in Fusion

Protected battery enclosure and connector, BQ class PCB plus 10K NTC, boost board and heat clearance, two connectors/contacts with current rating and spring travel, contact separation, final track width/height, printed guide taper, two independent NC seat switches, cooling, wire strain relief and fused service access. Parametric unpowered fit gauges exist in `docs/cad/remixes/remaining_fit_gauges.scad` and the earlier adapter kit; do not treat the nominal printed tray as a qualified lithium enclosure.

**Decision:** retain this design review as an option, not a verified purchasable wiring harness. Physical measurements are necessary to settle the charger/controller and boost choice.
