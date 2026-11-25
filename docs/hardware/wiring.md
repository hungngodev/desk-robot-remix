> **Canonical full five pet wiring allocation:** [complete feature and electrical plan](full-feature-wiring-and-shopping.md). The current full `esp32_full` build also sets `DESK_ROBOT_REQUIRE_DOCK_MONITOR=1`: a present, responsive, freshly sampled MCP23017 at expansion bus `0x71`, channel 5, is mandatory. A missing, unresponsive or failed module at boot refuses motor arming; this requirement cannot be waived. A missing module, invalid GPIOA transfer, zero sample sequence, or 500 ms stale reading locally refuses motor arming and stops moving tracks; any single seat switch or charger PGOOD indication also locks out motors. The base `esp32_stepper` profile is for staged tests only. Do not apply 5 V to MCP23017 inputs, and do not energize dock contacts from firmware. This is source code, not measured electrical qualification.

> **Full battery power and actual motor permission:** Both `esp32_full` and `esp32_dc_full` also require `DESK_ROBOT_REQUIRE_FUEL_MONITOR=1`. The MAX17048 at accessory mux `0x71`, channel 4, address `0x36` must provide an independently acquired valid, fresh cell voltage and fuel sequence. Missing, invalid, or 500 ms expired gauge evidence stops guarded movement and latches a fault until a newer valid conversion and deliberate local WROOM USB recovery. A voltage under 3,200 mV trips motion immediately; a new arm requires at least 3,300 mV. The Mac cannot clear either latch with a remote arm.

> **Unqualified stepper cutoff stays OFF:** The default `esp32_full` image sets `DESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED=0` because the existing 28BYJ48/ULN2003 rail lacks a measured independent fail-low power cutoff. WROOM status reports `motor_cutoff_unqualified`, `safety.ready=false`, and refuses `arm` even after local rearm. Do not confuse five clear VL53L0X samples with motor authorization. The alternative `esp32_dc_full` source requires an external CD74HC123 motor cutoff and DRV8833 nFAULT evidence, but neither electrical wiring nor loaded cutoff timing is physically qualified. No body drive is approved for desk-edge operation until those measurements exist.


The five-channel profile remains the earlier core WROOM safety foundation. The complete `esp32_full` profile now additionally polls left, right and rear VL53L0X channels 5 to 7, exports read-only freshness/validity, and lets the Mac react to their actual telemetry. This is implemented source but **not** qualified physical hardware. Most optional add-ons still require breakout-specific wiring, driver review, and measured bench acceptance. The 0x71 expansion mux is now quiesced before critical range reads if fitted.

> 2026-11-10 sensor correction: MPU6050 is the preferred six-axis module for the prototype, per the user's new hardware identification. Preserve the photographed BerryIMU as an optional alternative. Firmware probes MPU WHO_AM_I at register 0x75 expecting 0x68; never use BerryIMU register 0x0F for MPU. Both share WROOM GPIO21/22 I2C at 3.3V logic. Verify **this particular breakout**, its VCC regulator and pullups before power. No new GPIO is needed. A second installed IMU makes autodetection ambiguous and blocks motion. The original paragraphs below are historical build guidance and do not override this revision.

# Wiring and power — proposed stepper/sensor revision

Updated 2026-11-06. **Use only the matching profile.** Default `esp32_stepper` now compiles with
eight phase outputs and five sensor acquisition channels. It still refuses to arm without real mounted sensors, measured local calibration and manual USB rearm. Explicit `esp32dev` preserves four DC H-bridge inputs and
must never be connected to this stepper map. This is not physically qualified.

## Proposed WROOM allocation

Check actual ESP32-WROOM-32 development-board labels and exposed pins first.
Avoid flash GPIO6–11, strapping GPIO0/2/5/12/15 and programming UART0 GPIO1/3. GPIO4 is separately reserved by project policy, not an ESP32 strapping pin.

**Actuator reset safety (both exclusive drivetrain profiles):** ESP32 GPIO14 (left ULN2003 IN2) has a weak internal pullup after reset; GPIO13 has a weak pulldown. Other allocated actuator pins may float before setup. See the [Espressif GPIO reset table](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32/schematic-checklist.html). Provide verified external LOW bias at each connected driver input (all eight ULN2003 inputs or all four DRV8833 inputs), both servo signal inputs and the DC-only GPIO23 heartbeat when fitted. A 10 kΩ pulldown is a starting candidate, not an accepted value: check the exact carrier's input thresholds, existing bias, leakage and drive margin. Neither a passive bias nor the software LOW preload substitutes for independently inhibited actuator power before explicit authorization. With actuator power physically disconnected initially, scope every input and the independent cutoff across cold start, EN reset, USB upload/reset, watchdog reset, brownout and unequal rail sequencing. Require no unintended input assertion or driver enable, including the interval before setup; assess any powered servo startup motion separately. Only after the logic checks pass may isolated, restrained actuator trials establish absence of unintended motion. Keep physical qualification HOLD until these measurements exist.

| WROOM GPIO | Proposed use |
| --- | --- |
| 16 RX / 17 TX | Sense head UART TX / RX, 115200 8N1, 3.3 V; Sense TX2 / RX1, compiled allocation |
| 18 / 19 | Lift / grip MG90S signal |
| 13, 14, 25, 26 | Left ULN2003 IN1–IN4, phase order to verify |
| 27, 32, 33, 23 | Right ULN2003 IN1–IN4, phase order to verify |
| 21 / 22 | Body I²C SDA / SCL to mux upstream |
| No GPIO | Mux active-low RESET passively pulled HIGH to 3.3V, not reserved ESP32 GPIO4 |
| GND | Head, body, sensors and actuator-supply common logic reference |
|34 | Owned Adafruit #1374 AT42QT1010 OUT, powered at 3.3 V with common GND, momentary active-high. Firmware has debounced tap, double tap, hold and local motion stop; actual connection, shell timing and noise testing remain open |
| 35 / 36 / 39 | GPIO35 is the direct normally closed bumper. GPIO36/39 are now reserved **only** for left/right 38 kHz terminal IR demodulated inputs, with bounded read-only RMT decoder source but no measured receiver timing or approved final docking. Slow reed/PIR move to MCP23017 GPIOB0/B1 on mux 0x71 lane 5. See [terminal IR verification](charging-design-and-validation.md#terminal-homing-pin-budget-real-blocker-not-a-fake-finished-dock) before wiring. |

The conservative output set has 15 pins. Steppers8 + servos2 + UART2 + I²C2
consume 14, so there are not five spare outputs for sensor XSHUT lines. The mux
isolates equal-address sensors rather than trying to assign them all new addresses.
Head display remains on the head bus: never simply join two independent MCU
masters. GPIO34–39 cannot drive outputs and lack internal pullups.

Connect each motor's existing five-pin plug to its correctly matched ULN2003
board; verify coil/common wiring, phase order and 3.3 V input behavior with the
actual parts. The ULN2003 sinks current from the four phases with the motor
common on +5 V. The Adafruit DRV8833 has two MOSFET H-bridges with current
limiting. Adafruit documents a separate unipolar hookup with the motor common
at ground. That option needs a different harness and a check of the phase and
stop behavior with the actual motor. One DRV8833 handles one stepper in this
setup. Keep the two owned ULN2003 boards for robot one's two 28BYJ-48 steppers.
[TI ULN2003A](https://www.ti.com/product/ULN2003A) ·
[Adafruit DRV8833 stepper guide](https://learn.adafruit.com/adafruit-drv8833-dc-stepper-motor-driver-breakout-board/stepper-motor-usage)
Do not modify the steppers to bipolar operation for this build. Pulse timing,
acceleration, loaded speed, stop/hold current and thermal limits need measurements.

## Sensor topology

```text
WROOM GPIO21/22 -> selected MPU6050 0x68/0x69 on the UPSTREAM body I2C bus
  -> TCA9548A RANGE mux 0x70
     CH0 front-left floor VL53L0X 0x29
     CH1 front-right floor VL53L0X 0x29
     CH2 rear-left floor VL53L0X 0x29
     CH3 rear-right floor VL53L0X 0x29
     CH4 front obstacle VL53L0X 0x29
     CH5 left-side VL53L0X 0x29, read-only
     CH6 right-side VL53L0X 0x29, read-only
     CH7 rear obstacle VL53L0X 0x29, read-only
  -> TCA9548A ACCESSORY mux 0x71
     CH0 CAP1188 0x29 default / 0x28 strapped + MAX30102 0x57
     CH1 APDS9960 0x39 + AS5600 nose 0x36
     CH2 ADS1115 force 0x48
     CH3 SHT41 0x44 + BMP280 0x76 (verify breakout)
     CH4 INA226 0x40 + MAX17048 0x36
     CH5 MCP23017 0x20 (GPIOA mandatory dock, GPIOB slow reed/PIR)
         + PN532 0x24 toy NFC only
     CH6 AS5600 left wheel 0x36
     CH7 AS5600 right wheel 0x36
XIAO -> independent HEAD-owned OLED GPIO5/6 bus; NOT connected to WROOM SDA/SCL
```

The earlier ST VL6180X proposal has been superseded by the selected
**VL53L0X**. The current `esp32_full` source scans **eight 0x29
VL53L0X channels** on TCA9548A 0x70: four floor, one forward and
three left/right/rear read-only directions. The first five channels
form the local movement guard; the other three add separate read-only
observations. The topology above lists the entire source allocation. Actual
optical short-range calibration and the mounting geometry are still pending.
Select only one multiplexer lane at a time for reads and configuration. Confirm channel numbering in firmware, module
supply, reset behavior, default mux address and **3.3 V signal pullups**. Generic
boards vary; an IC voltage range does not establish breakout level shifting.
No 5 V signal may enter a WROOM pin. Check total I²C pullup loading and use short
wires. A mux reset may recover a stuck downstream bus, but must leave motion
latched stopped. No automatic resume follows recovery.

Qualify four downward optical footprints beyond the relevant track contact
patch, including pivot sweep, at the final mounting height. One forward beam
covers only a limited obstacle region; it is not side/rear collision protection
or gripper-distance feedback. Use [sensor requirements](../research/2026-11-03-cliff-sensors.md).

The current WROOM source includes MPU6050 and revision-aware optional
BerryIMU raw six-axis drivers, immediate AT42QT1010 touch disarming,
CAP1188 petting and optional sensor telemetry. **None** has passed
physical breakout, mounting or timing tests. MPU6050 is the preferred first build; do not power a second IMU on the
shared bus until its exact revision and chip IDs are confirmed. BMP280 is wired
to accessory mux `0x71` lane 3 while any single selected IMU (MPU6050 default,
or optional historical BerryIMU alternate) sits upstream on GPIO21/22; never
infer `0x71` for BerryIMU, and verify the real chip ID and breakout address. [Photo identification and checks](photo-inventory-2026-11-04.md).
Keep body I2C reads bounded and serialized so floor sensing retains priority.
[Interaction wiring and acceptance](interaction-sensors.md) also covers optional
SenseGPIO9 RGB data with a level buffer; bodyGPIO4 is not spare.

## Head boundary

The [Sense head](../guides/modular-head.md) has a source-level pinned board map
whose latest GitHub Actions compile remains unverified:
OLED5/6, amplifier4/7/8, UARTTX2/RX1, PDM42/41 and stock camera. Old Freenove GPIO1/2 assignments or
video GPIO1/2 I²C instructions are not a Sense allocation. Preserve native USB,
internal camera/mic pins and flash/PSRAM; physically isolate the expansion board's
SD J3 connection as specified for the actual shipped revision before using
overlapping I2S pins. See [firmware source allocation](../../code/firmware/head/sense/README.md); physical
qualification is still pending, and its SD slot must stay empty/disabled.

[RIO's reference](../research/2026-11-03-sense-realtime-reuse.md) uses speaker
BCLK7/LRC8/DIN9 and amplifier SD44. Those are **not** the compiled allocation
above. Port software/reference handling to one checked map before wiring; do not
mix the two tables or add an SD44 wire to the current build. Sense AEC software reference and urgent PCM flush are in the stacked firmware implementation. No hardware acoustic interruption gate has passed.

**MAX98357A I2S GAIN and acoustic baseline (provisional, NOT physically qualified):**
For the selected digital MAX98357A, plan to leave its GAIN input electrically
floating for the nominal **+9 dB I2S gain**, rather than adopting an unknown
seller's strap. This is a *proposed configuration*, not evidence of what the
actual generic breakout supplies. Before wiring or powering it, inspect the
exact carrier revision, GAIN silkscreen, onboard bias resistors/solder bridges
and the manufacturer schematic; record the measured effective strap and do not
assume an exposed pin is truly floating. The chip also supports +3 dB
(100 kOhm to VDD), +6 dB (VDD), +12 dB (GND), and +15 dB (100 kOhm to GND)
in I2S mode. Do not connect GAIN to an XIAO GPIO or blindly copy another
breakout's solder jumper. Primary source: [Analog Devices MAX98357A](https://www.analog.com/en/products/max98357a.html)
and [MAX98357A/MAX98357B Rev. 16 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/MAX98357A-MAX98357B.pdf).

Record the board/strap, regulated input voltage, selected **8 ohm 2 W**
speaker, actual printed cavity/port and mic-to-speaker geometry. Under actual
speech and simultaneous camera/WiFi load, measure clipping, SPL, amplifier and
speaker temperature, reference delay, AEC echo return loss enhancement (ERLE)
and self-speech false VAD. **Changing the GAIN strap, speaker or enclosure
invalidates the previous acoustic tuning**: rerun the 20 audible interruption
trials (at least 19/20 stops within 500 ms and 18/20 recognized new requests)
plus the echo-only trial in [audio acceptance](../guides/audio-barge-in.md).
Neither the proposed +9 dB gain nor a compiled I2S path clears the physical
A1 acoustic gate or authorizes final assembly.



Initial two-USB head/body test joins **TX, RX and GND only**; keep 5 V rails
separate. Do not flash CoreS3/Freenove firmware onto Sense, or S3 firmware onto
the classic WROOM.

## Power

```text
matched1S cell/holder/pack -> charging + protection + regulated5V output
                           -> rated switch/fuse/distribution
                           -> approved head/WROOM inputs
                           -> separate stepper/servo/audio power branches
all grounds common; data signals remain3.3V
```

Exact cell/pack, protection/charger/output module and current rating remain
unselected. An integrated module may combine functions. Match charge current,
cell/protection/wiring input current and continuous5V output to actual loads;
a marketing peak or charge-current number is not the output rating. Keep the
battery low, retained independently of connectors, with a verified power path.
No new consumer bank is required. The owned unidentified bank is optional bench
stock only until its output/load behavior is verified.

No loaded current, thermal, stability or runtime test has passed. Measure supply
at logic and actuators during combined tracks, servos, Wi-Fi/audio. Capacitors
cannot establish sufficient supply capacity. The1S system needs regulated5V;
a2S system would require an appropriate buck and is outside this direction.

Use rated conductors for actuator power. Owned DuPont ribbons are signal leads,
not the main motor/servo supply. Never run motor/servo current through a board's
3.3 V regulator or from a laptop USB port through the board. Check the actual
MG90S voltage rating. MAX98357 speaker connects across SPK+ and SPK−, **neither
to ground**; use a documented initial MAX98357A GAIN pin left floating (nominal 9 dB) for bench AEC trials, then record the exact delivered carrier strap and measured gain before acceptance. A changed gain or speaker enclosure invalidates prior echo reduction measurements and requires a new calibration and ERLE/double talk test. Validate clipping, long speech temperature and enclosure acoustics for the fixed 8 Ω / 2 W Challenge CS20-02P110-04-1X speaker; 5 V amplifier supply is not yet physically accepted. Insulate brass/cosmetic metal.

The [Adafruit #4090](https://www.adafruit.com/product/4090) breakout is not a
qualified whole-robot high-current distributor. **Do not directly join the
robot's boosted 5 V rail to the XIAO VBUS/5V pin while a laptop USB VBUS is
connected.** Seeed's [XIAO ESP32S3 pin multiplexing guide](https://wiki.seeedstudio.com/xiao_esp32s3_pin_multiplexing/)
requires diode isolation when using the exposed 5V pin as external power input.
The final board revision must have an approved one-way, current-rated power
path or physically exclusive USB versus robot-power connection. A diode
voltage drop and reverse-current behavior must be measured under actual head
WiFi/camera/audio load; do not infer a charger or battery protection function.
Until approved, physically disconnect portable power for USB programming and
disconnect laptop USB before energizing robot power. The matched1S kit needs appropriate charging/protection; never treat Sense
charging or an arbitrary boost board as the complete actuator power system.

## XIAO external power and Sense SD J3 acceptance

Do this with **no Li-ion pack connected, no dock contact energized, tracks
lifted, and the MAX98357A/speaker output disconnected**. A qualified person
should select and verify the current-rated XIAO external 5V isolation path
against the actual shipped Sense revision, rather than soldering a guessed
diode or tying USB and the robot boost together.

1. With all supplies absent, inspect the expansion board for Seeed's SD
   J3 connection. If the selected I2S GPIO7/8 map is retained, follow
   [Seeed's documented SD disconnect procedure](https://wiki.seeedstudio.com/xiao_esp32s3_sense_filesystem/).
   Confirm the slot is unpopulated, the J3 SD link is open by continuity
   measurement, and the camera/microphone connectors are intact.
2. With only the isolated and current-limited **bench** supply connected to
   the approved robot 5V input, record XIAO input voltage and polarity under
   idle, camera, WiFi, OLED and speaker loads. Do not attach a laptop USB
   cable or a cell. If the output browns out or the chosen diode exceeds
   its continuous/thermal ratings, reject this path.
3. Remove that supply, attach **USB alone**, and confirm normal programming.
   Measure the disconnected robot-side input with a high-impedance meter:
   there must be no unintended backfeed capable of energizing actuators,
   unprotected charge contacts or the external boost converter.
4. Only if the selected power-path design specifically permits both inputs,
   repeat with both current-limited sources, verify reverse current, diode
   temperature and correct source switching under worst-case head load.
   Otherwise enforce a mechanically exclusive USB versus portable supply
   mode and label it on the enclosure. Never extrapolate this bench result
   to a protected battery, charger or dock acceptance.

The external supply diode does not isolate the signal harness. A powered
UART transmitter or I2S/RGB signal can feed an unpowered receiver through
its input protection network. With power absent, disconnect signal harnesses
before independently powering either board for USB programming unless the
actual installed interface has qualified partial-power-down isolation or
a hardware interlock. Do not rely on firmware pin modes, a common ground,
or an open J3 as proof of power-domain isolation.

For the installed harness receipt, a qualified reviewer must verify each
applicable UART direction (Sense GPIO2 to WROOM RX16 and WROOM TX17 to
Sense GPIO1), I2S GPIO4/7/8, OLED pullups, and any fitted RGB buffer.
Include separate head-only and body-only power trials, including reset
and power transitions, with actuators and charge contacts disabled. Do not
connect an unqualified driven signal to an unpowered board to perform a
trial. Establish a safe fixture and manufacturer-specific off-domain
voltage and injection-current limits before testing. Capture maximum
unpowered-rail voltage and injection current in both directions and reject
any unintended off-domain energization. Record the actual harness revision,
J3 continuity capture, empty SD slot, GPIO isolation capture, and reviewed
limit reference in the existing XIAO power gate receipt. The receipt's six
separate phase counts include head-only and body-only trials in addition
to USB attach/detach, cold start and loaded servo start.

Log instrument model, board revision, unloaded/loaded voltages,
reverse current or verified absence of conductive backfeed, photos
and source-to-connector continuity in the physical trial record.
Neither a successful ESP-IDF build nor an unmodified STL establishes
these physical facts. The machine receipt keeps
`sense_sd_j3_isolation_verified` and
`sense_vbus_power_path_verified` false until reviewed evidence exists.

## Bring-up and stopping

1. Keep tracks off the surface; remove servo horns/loads. Verify supplies,
   grounds and driver mapping before enabling any output.
2. Only after the new stepper build passes host/firmware checks, test one coil
   sequence slowly, both directions, ramping and bounded stop on the stand.
3. Center unloaded positional servos, then fit horns and test small movements
   near center. Preserve the communication watchdog; do not disable it to test.
4. Connect/calibrate sensors on a supported flat surface. Missing/invalid/stale
   readings, bus faults and cliffs must latch a local motor stop in every mode.
5. Measure stopping/latency and full sensor coverage with a tether/catch tray;
   recover explicitly after faults. Ordinary arm does not clear a latch; only
   local USB rearm with healthy fresh readings does, and it leaves motion disarmed. Never blindly reverse away from an edge.
6. Test Sense screen/camera/PDM/audio separately, then UART, then the integrated
   load. Only then try contained low-speed movement and pickups.

Existing 500 ms watchdog and 250 ms pulse bounds remain independent protections;
cliff checks must meet measured clearance deadlines locally. Stop should hold
servo targets without dropping payload; explicit disarm/power-off can release
servos, so support the object first. Stepper coil hold/coast policy must be
qualified for stopping distance, current and heat. No unprotected tabletop trial.

## 2026-11-09 HTML research reconciliation

The separate `ESP32 Deskpet Ideas.html` is not an as-built wiring diagram. It
incorrectly directs the optional GY-MAX30102 heartbeat pad to Sense GPIO41/42:
these are **the onboard PDM microphone data and clock**, not spare I2C pins.
The optional MAX30102 must instead be reviewed on the WROOM body I2C
GPIO21 SDA / GPIO22 SCL, potentially through mux channel 5. Do **not** wire
it until the actual purple breakout has been identified and its regulator,
level shifting, pullups and voltage limits are verified. The reported quantity
of about five remains an unconfirmed inventory claim, not an approved BOM line.
See [Seeed's Sense pin allocation](https://wiki.seeedstudio.com/xiao_esp32s3_pin_multiplexing/)
and [the MAX30102 datasheet](https://www.analog.com/en/products/max30102.html).

ST marks the earlier VL6180X obsolete and out of production. The currently
selected low-cost range component is a genuine **VL53L0X chip on an inexpensive
generic GY-530 compatible I2C carrier**. The critical body source and host
fake already use the pinned MIT Pololu VL53L0X 1.3.1 startup library; there
is no reason to buy expensive VL53L4CD boards. A real single-carrier trial
on matte, black, reflective and transparent desktop surfaces at the actual
mounting height is still needed before authorizing many units.
No optical timing, stopping margin or material support is physically
qualified. [Historical evidence](../research/2026-11-09-html-verification.md).

## Five-channel sensor integration and measured local USB calibration

The current esp32_stepper target selects the cheap **VL53L0X** driver for all five critical range sensors, using pinned MIT Pololu vl53l0x-arduino v1.3.1 for initialization and bounded nonblocking Wire register reads for the local guard. The full esp32_full target adds three read-only directions. The exact generic carrier and measured local stop/edge optical margin remain unqualified. Prior premium VL53L4CD and obsolete VL6180X recommendations are explicitly NOT current purchases.

WROOM GPIO21 SDA and GPIO22 SCL connect to TCA9548A range mux 0x70. Channels 0 through 3 are independent downward corners and channel 4 is forward obstacle; channels 5 through 7 are read-only side and rear measurements. Each inexpensive generic VL53L0X GY-530 compatible I2C module uses 0x29 behind its isolated mux lane. Power only from a verified 3.3V compatible module supply and a 3.3V I2C SDA/SCL bus; do NOT assume a generic board's VIN pin, on-board regulators, pullups or XSHUT logic have Pololu #3692 electrical behavior. Verify the ACTUAL purchased PCB schematic, pin labels, pullups, dimensions and 30 to 80 mm desk range before powering a full system. Keep TCA9548A RESET tied high appropriately at 3.3V, not to reserved GPIO4. Previous Pololu #3692 carrier voltage notes are historical, not instructions for generic GY-530 boards.

Local measured calibration commands are accepted only on the WROOM programming USB Serial. They are rejected over the head UART or Mac network service. **The values below must come from a real measured rig**, actual black/glossy/transparent surfaces and loaded stopping/scan latency with a catch tray:

    calfloor 0 MIN_MM MAX_MM
    calfloor 1 MIN_MM MAX_MM
    calfloor 2 MIN_MM MAX_MM
    calfloor 3 MIN_MM MAX_MM
    calfront NEAR_MM MAX_MM
    calfresh MAX_SAMPLE_AGE_MS
    calcommit
    rearm

Limits range 1..1300 mm; freshness is 30..200ms. All four floor, front and freshness settings must be staged before the atomic commit; calabort clears the stage. The body saves a versioned checksummed calibration in NVS, leaves motors disarmed, and requires five fresh measurements plus a NEW direct USB rearm before motion. Reboot and recovering I2C never resume old motion. Any stale/invalid/out-of-range sensor or bus fault latches stop, with no blind reversal. Measure real lead and stopping margin before putting tracks on a desk.

Pinned Pololu VL53L0X v1.3.1 handles sensor startup. Its readRangeContinuousMillimeters() waits for data-ready, so local critical sampling instead checks VL53L0X register 0x13 readiness once, reads result at 0x14, validates status and distance, then clears 0x0B. Real timeout, surface reflectance and loaded desk-edge stop measurements are still mandatory; this software code is NOT physical safety signoff.

## Five read-only range diagnostics

The WROOM `status` response exposes five raw measurements through the existing
Sense UART bridge and authenticated Mac `Head.status()`; no second server,
motor command, new I2C transaction or calibration privilege is needed.

The `ranges.mm` array is indexed 0 through 4 (four downward corners and
one forward channel). `ranges.age_ms` is each last sample's elapsed age in
WROOM monotonic milliseconds. `ranges.present_mask` and
`ranges.valid_mask` are five-bit integers, with bit 0 for channel 0 and
bit 4 for channel 4. A zero distance accompanied by a cleared presence bit
means **missing**, not a measurement of zero clearance. A raw distance with a
cleared valid bit is **invalid**, even if the number looks plausible.
The existing `safety.ready`, `safety.fault` and fault sensor remain
authoritative for movement. Raw ranges are for diagnosing wiring, actual
sensor geometry and calibration on the catch tray, never for bypassing a stop.

Missing readings and a bus reset clear all presence flags; calibration
replacement invalidates prior readings. Until the physical sensors and
floor samples are qualified, no valid mask or visually reasonable reading
authorizes motion. Native tests verify all five arrays, reset handling and
bounded JSON responses; neither the Mac nor model gains local USB rearm rights.

## Direct USB bringup for the owned boards

Reuse `code/scripts/serial_bench.py` rather than creating a second serial
console or independently controlling the actuators through a model. On a
**stationary, disconnected motor stand or catch tray** with the correct
3.3 V sensor wiring, run from the `code/` directory:

```sh
uv run --extra dev python scripts/serial_bench.py --port /dev/ttyUSB0 --inspect --samples 10
```

Substitute the real WROOM USB port. This command issues only ten `status`
reads, reports each raw five-channel distance, age and validity, the body
fault and the BerryIMU WHO_AM_I identity, and **never** arms, calibrates, rearms,
flashes or moves a robot. It does not call software output a measured physical
pass. Validate wiring, power rails and board ID against the actual breakout,
and measure the four corner optical heights and forward obstacle detection on
the intended surfaces. When I2C is absent, the board reports missing, not safe.

After the **real** local `calfloor` / `calfront` / `calfresh` / `calcommit`
sequence has been measured and saved through WROOM USB, a trained operator
may use a separate supervised, contained rig test such as:

```sh
uv run --extra dev python scripts/serial_bench.py --port /dev/ttyUSB0 --command "grip 95" --local-rearm
```

The explicit `--local-rearm` flag exists because opening a WROOM serial
port can reset it, and reboot deliberately leaves the local safety latch
disarmed. It asks the actual body over **local USB only** to clear a fault;
the body rejects this request if measured calibration or any fresh sensor is
unhealthy. This flag is not available via Sense, HTTP, Mac AI tools or a
background pet. The operator must already have qualified the physical
hardware on a catch tray. Remove servo horns/loads for initial tests.

In the normal Mac runtime, an operator permit and the actual bounded job
both perform a fresh read-only safety preflight through the existing Sense
HTTP status and WROOM UART. Five present/valid/still-recent ToF readings,
no touch, clear guard, correct robot identity, expected stepper backend and
disarmed state are required. This is additional software refusal, **never**
proof that the physical stop margin, IMU attitude safety or supply is qualified.


## Optional historical BerryIMU six-axis alternate bringup

MPU6050 / GY-521 on upstream GPIO21/GPIO22 is the selected default single IMU;
use this section only if explicitly evaluating an already owned BerryIMU as an
unpowered or bench-isolated **optional historical alternate** (never mount or
power both IMUs together). Connect its verified **3.3V compatible** supply,
SDA and SCL on body GPIO21 and GPIO22 upstream of the TCA9548A. Do not infer
VCC pin ordering from another revision, assume 5V tolerance or attach it to
a downstream mux port (`0x70`/`0x71`). The firmware reuses the existing boot-time
WHO_AM_I probe and only initializes the selected single IMU's matching registers.
The same status and USB inspection path reports raw acceleration, raw gyro and
age with an explicit validity bit, not interpreted tilt or an optical cliff
clearance. Keep actuators unloaded during board identification and measure the
real axis orientation before considering tilt or held interlock thresholds.
A valid raw IMU sample never substitutes for any missing VL53L0X corner.


The physical WROOM profile also refuses a motion `arm` without fresh supported
IMU six-axis samples (MPU6050 default, or the selected optional alternate). It
stops/disarms if those samples become stale or invalid during a drive, without
releasing a held payload intentionally.
The Mac's authenticated permit preflight checks the same data. Neither this
heartbeat nor the existing five optical channels replaces the pending,
measured tilt/held acceptance trials. The read-only USB inspection may show
valid raw counts while the robot is still unqualified for operation.


## November 10 reserved optional sensor bus and digital inputs

Source reviewed against the WROOM pin budget, Bosch BMP280 register map,
InvenSense MPU6050 RM-MPU-6000A and Adafruit AT42QT1010 breakout:

| Input or bus | Purpose and current ownership | Real electrical gate |
| --- | --- | --- |
| GPIO21 SDA / GPIO22 SCL, TCA9548A upstream | Preferred MPU6050 at 0x68 or 0x69; one selected IMU | Real MPU WHO_AM_I register 0x75 gives 0x68; 3.3 V logic, not a second Wire instance |
| RANGE mux 0x70 channels 0 through 4 | Four actual cliff footprints and front VL53L0X | Distinct mux lanes, device 0x29, floor calibration and stopping distance |
| RANGE mux 0x70 channels 5 through 7 | Three actual read-only left, right and rear VL53L0X | Existing firmware source acquires these in esp32_full; no local reverse/turn movement permission |
| ACCESSORY mux 0x71 channels 0 through 7 | CAP/paw, gesture/nose, force, SHT41/BMP280, power gauges, MCP dock/PN532, wheel angles | See complete channel list above and source checked generated harness; chip IDs, breakout VCC and I2C pullups remain unqualified |
| GPIO34 | Required active HIGH AT42QT1010 head pad | 3.3 V power and output, through-case physical false-touch trials |
| GPIO35, build flag DESK_ROBOT_ENABLE_BUMPER | Required in both full body profiles: two normally closed bumpers wired in series, direct raw local trip | External 3.3 V pullup is mandatory on this input-only pin; normally closed contacts hold GPIO35 LOW, opening either switch or unplugging a lead produces the active HIGH trip. A floating or unpowered input cannot prove continuity. Verify real switch release, disconnection and collision stopping with motors disconnected before physical release |
| MCP23017 GPIOB0, build flag DESK_ROBOT_ENABLE_REED | Slow read-only magnetic costume accessory reed closure | Source polls BANK=0 GPIOB 0x13, active LOW, 3.3 V pullup, actual dwell and magnet interference need measurement |
| MCP23017 GPIOB1, build flag DESK_ROBOT_ENABLE_PIR | Slow read-only PIR motion output | Source polls same expander byte, active HIGH; measured 3.3 V output, pulse dwell and external bias needed; not person recognition |
| WROOM GPIO36 and GPIO39 reserved | Two independent demodulated left/right terminal beacon inputs | **Source NEC/RMT decoder implemented, but NO physical receiver qualification or movement authority.** External bias, ESP32 RTC/ADC glitch erratum, actual interrupts/RMT version and optical baffles must be checked |

The optional reed/PIR event reports remain disabled by compile flags until
each actual MCP23017 input is wired and qualified. The bumper remains direct,
with an independently latched local motor stop. GPIO34 through GPIO39 have
no internal pull resistors and are not interchangeable with the expander. Do not plug an anonymous PIR 5 V logic output into the ESP32;
use a qualified level converter when required. A reed contact near the motors
may trigger from their magnetic fields. The BMP280 can add atmospheric pressure
and temperature *only* if its existing vendor driver is selected and tested on
the actual hardware. Its address may conflict with an optional Berry pressure
chip if someone wires both upstream: keep BMP280 on ACCESSORY mux 0x71 channel 3. No extra I2C
sampling may starve five-channel floor polling. None of this bypasses WROOM
local guard, MPU heartbeat, one-use operator permit, or the robot's $50 cap.


### Inspect extra sensor and MPU wiring without arming motors

With a qualified and physically disconnected motor supply, run the existing
`code/scripts/serial_bench.py --port <actual-WROOM-USB-port> --inspect` on
the WROOM USB serial interface. The inspection now exposes MPU6050 (family4)
raw six-axis data and the `optional_inputs` enabled bit mask, bumper/reed/PIR
levels and rising counters. It reports false physical qualification even when
values are fresh. GPIO35 is enabled in both full guarded body profiles, but GPIO36/39 remain dock IR receiver inputs until each
has measured voltage levels, hardware pull resistors and a real enclosure mount.
An active bumper also blocks the tool's *eligibility diagnostic* for a local
rearm; only actual physical calibration and the separate direct USB command can
clear the WROOM safety latch. No web or model endpoint gets that authority.


## Source-verified bounded WROOM status size

The original body reply array 752B and Sense bridge UART read cap 768B were dangerously tight after adding eight touch zones, optional event counters and future telemetry. A valid long-lived robot with several 32-bit event counters approaching 10 digits could return an `ERR status response_too_long`, hiding health diagnostics. The current integrated source uses a WROOM reply buffer of **1536 bytes**, a Sense UART line cap of **1664 bytes**, and the local USB inspector's matching **1664-byte** read bound. Those caps retain strict malformed-frame rejection and a buffer for the CRLF terminator. The earlier 1100/1152 byte documentation and test assumptions became stale after IMU and dock diagnostics grew. The body still uses a fixed allocation and never emits a truncated JSON status as healthy. This change **does not** increase model motor permissions or alter local cliff fault handling. It is verified by the existing compiler and native tests, not yet a physical UART trace.
