> **Canonical full five pet wiring allocation:** [complete feature and electrical plan](full-feature-wiring-and-shopping.md). The five-channel implementation below remains the actual installed firmware foundation; the extra three ranging lanes and most optional modules require drivers and physical qualification. The 0x71 expansion mux is now quiesced before critical range reads if fitted.

> 2026-11-10 sensor correction: MPU6050 is the preferred six-axis module for the prototype, per the user's new hardware identification. Preserve the photographed BerryIMU as an optional alternative. Firmware probes MPU WHO_AM_I at register 0x75 expecting 0x68; never use BerryIMU register 0x0F for MPU. Both share WROOM GPIO21/22 I2C at 3.3V logic. Verify **this particular breakout**, its VCC regulator and pullups before power. No new GPIO is needed. A second installed IMU makes autodetection ambiguous and blocks motion. The original paragraphs below are historical build guidance and do not override this revision.

# Wiring and power — proposed stepper/sensor revision

Updated 2026-11-06. **Use only the matching profile.** Default `esp32_stepper` now compiles with
eight phase outputs and five sensor acquisition channels. It still refuses to arm without real mounted sensors, measured local calibration and manual USB rearm. Explicit `esp32dev` preserves four DC H-bridge inputs and
must never be connected to this stepper map. This is not physically qualified.

## Proposed WROOM allocation

Check actual ESP32-WROOM-32 development-board labels and exposed pins first.
Avoid flash GPIO6–11, strapping GPIO0/2/4/5/12/15 and programming UART0 GPIO1/3.

| WROOM GPIO | Proposed use |
| --- | --- |
| 16 RX / 17 TX | Sense head UART TX / RX, 115200 8N1, 3.3 V; Sense TX2 / RX1, compiled allocation |
| 18 / 19 | Lift / grip MG90S signal |
| 13, 14, 25, 26 | Left ULN2003 IN1–IN4, phase order to verify |
| 27, 32, 33, 23 | Right ULN2003 IN1–IN4, phase order to verify |
| 21 / 22 | Body I²C SDA / SCL to mux upstream |
| No GPIO | Mux active-low RESET passively pulled HIGH to 3.3V, not ESP32 strapping GPIO4 |
| GND | Head, body, sensors and actuator-supply common logic reference |
|34 | Owned Adafruit #1374 AT42QT1010 OUT, powered at 3.3 V with common GND, momentary active-high. Firmware has debounced tap, double tap, hold and local motion stop; actual connection, shell timing and noise testing remain open |
| Optional35/36/39 | Input-only bumper/interrupt signals with **external** pullups as needed; not implemented |

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
WROOM GPIO21/22 -> user's reported MPU6050 0x68 (AD0 low) or 0x69 (AD0 high), upstream; BerryIMU optional alternative
               -> TCA9548A upstream I²C
                  channel 0 -> front-left downward VL53L4CD candidate, 0x29
                  channel 1 -> front-right downward VL53L4CD candidate, 0x29
                  channel 2 -> rear-left downward VL53L4CD candidate, 0x29
                  channel 3 -> rear-right downward VL53L4CD candidate, 0x29
                  channel 4 -> separate forward VL53L4CD candidate, 0x29
Sense -> separate head-owned OLED bus
```

The proposed ST VL6180X downrange part is obsolete. A compatible short-range part must be selected after a one-sample physical desk-height test and the corresponding driver/mount must be reviewed; the four corner roles do not change. The 7-bit **0x29** address applies to the currently named ST ToF family and must be checked for the finally selected sensor. Select only one corresponding
channel for reads/configuration. Confirm channel numbering in firmware, module
supply, reset behavior, default mux address and **3.3 V signal pullups**. Generic
boards vary; an IC voltage range does not establish breakout level shifting.
No 5 V signal may enter a WROOM pin. Check total I²C pullup loading and use short
wires. A mux reset may recover a stuck downstream bus, but must leave motion
latched stopped. No automatic resume follows recovery.

Qualify four downward optical footprints beyond the relevant track contact
patch, including pivot sweep, at the final mounting height. One forward beam
covers only a limited obstacle region; it is not side/rear collision protection
or gripper-distance feedback. Use [sensor requirements](../research/2026-11-03-cliff-sensors.md).

IMU and touch are new planned additions, not compiled/qualified interfaces.
The photographed BerryIMU is likely an older V1; verify its actual power/header
and chip identity before wiring. Do not apply a V3 or LSM6 pin/register map.
The maker's V1 example suggests0x1E accel/mag and0x6A gyro, not measured addresses.
An optional extra BMP280 may conflict with its pressure sensor at0x77; omit it
unless the collision is resolved. [Photo identification and checks](photo-inventory-2026-11-04.md).
Keep body I2C reads bounded and serialized so floor sensing retains priority.
[Interaction wiring and acceptance](interaction-sensors.md) also covers optional
SenseGPIO9 RGB data with a level buffer; bodyGPIO4 is not spare.

## Head boundary

The [Sense head](../guides/modular-head.md) now has a separate compiled board map:
OLED5/6, amplifier4/7/8, UARTTX2/RX1, PDM42/41 and stock camera. Old Freenove GPIO1/2 assignments or
video GPIO1/2 I²C instructions are not a Sense allocation. Preserve native USB,
internal camera/mic pins and flash/PSRAM; disable SD use where necessary. See [exact compiled Sense allocation](../../code/firmware/head/sense/README.md); physical
qualification is still pending, and its SD slot must stay empty/disabled.

[RIO's reference](../research/2026-11-03-sense-realtime-reuse.md) uses speaker
BCLK7/LRC8/DIN9 and amplifier SD44. Those are **not** the compiled allocation
above. Port software/reference handling to one checked map before wiring; do not
mix the two tables or add an SD44 wire to the current build. Sense AEC software reference and urgent PCM flush are in the stacked firmware implementation. No hardware acoustic interruption gate has passed.

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
to ground**; set volume for the 8 Ω / 1 W speaker. Insulate brass/cosmetic metal.

The [Adafruit #4090](https://www.adafruit.com/product/4090) breakout is not a
qualified whole-robot high-current distributor. Avoid joining external/bank 5 V
to laptop USB 5 V without a documented power path. Portable power should be
disconnected during initial USB programming. The matched1S kit needs appropriate charging/protection; never treat Sense
charging or an arbitrary boost board as the complete actuator power system.

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

ST now labels the proposed VL6180X **obsolete and out of production**. The
existing sensor channel plan is still a proposed baseline, not a fleet
procurement authorization. Bench evaluate one supported short range
[VL53L4CD](https://www.st.com/en/imaging-and-photonics-solutions/vl53l4cd.html)
against the intended surfaces and height before substituting: it requires a
different driver and may exceed the existing budget at current breakout prices.
No optical scan time, stopping margin or surface support is physically
qualified. [Full evidence and blockers](../research/2026-11-09-html-verification.md).

## Five-channel sensor integration and measured local USB calibration

The current esp32_stepper target selects the same **VL53L4CD driver for all five sensors**, reusing pinned Pololu ST-derived code for device setup and start, plus bounded checked Wire measurement reads. Neither actual breakout part, case optic fit, five-unit purchase or loaded stop margin is qualified. Historic VL6180X and VL53L0X suggestions are **not** the current firmware purchase list.

WROOM GPIO21 SDA and GPIO22 SCL go to TCA9548A at 0x70, with channels 0,1,2,3 allocated to individual downward corners and channel 4 to forward obstacle. Each VL53L4CD uses isolated 0x29 I2C. Shared 3.3V logic and ground, verified pullups. Connect mux active-low RESET to 3.3V pullup, never strapping GPIO4.

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

The pinned Pololu generic read helper can divide by zero for zero SPAD returns; the runtime uses only its initialization and start functions, and a checked raw I2C results path. All of this is software integration, **not** a verified physical stop test or a solution to the current $50 delivered budget contradiction.

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


## Bounded BerryIMU six-axis bringup

Use the already owned BerryIMU with its verified **3.3V compatible** supply,
SDA and SCL on body GPIO21 and GPIO22 upstream of the TCA9548A. Do not infer
VCC pin ordering from another revision, assume 5V tolerance or attach it to
a downstream mux port. The firmware reuses the existing boot-time WHO_AM_I
probe and only initializes the matching V1/V2/V3 gyro and accelerometer.
The same status and USB inspection path reports raw acceleration, raw gyro and
age with an explicit validity bit, not interpreted tilt or an optical cliff
clearance. Keep actuators unloaded during board identification and measure the
real axis orientation before considering tilt or held interlock thresholds.
A valid raw IMU sample never substitutes for any missing VL53L4CD corner.


The physical WROOM profile also refuses a motion `arm` without fresh
BerryIMU six-axis samples. It stops/disarms if those samples become stale
or invalid during a drive, without releasing a held payload intentionally.
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
| TCA9548A channels 0,1,2,3,4 | Four actual cliff footprints and one front VL53L4CD | Distinct mux lanes, sensor 0x29, floor calibration and stopping distance |
| TCA9548A channel 5 reserved | Optional owned Bosch BMP280 at 0x76/0x77 | Confirm chip ID 0x58 and carrier power; pressure/temperature only, NOT humidity; channel is not currently sampled |
| TCA9548A channels 6,7 reserved | Optional light sensor, touch-zone expander, opted-in accessory | One address/channel owner, timeout, external pullups and per-module actual VCC |
| GPIO34 | Required active HIGH AT42QT1010 head pad | 3.3 V power and output, through-case physical false-touch trials |
| GPIO35, build flag DESK_ROBOT_ENABLE_BUMPER | Optional normally-closed mechanical bumper, raw local trip | External 3.3 V pullup, active LOW; must be physically fitted and tested before enable |
| GPIO36, build flag DESK_ROBOT_ENABLE_REED | Optional magnetic costume accessory reed closure | External 3.3 V pullup, active LOW; magnet interference and contact bounce |
| GPIO39, build flag DESK_ROBOT_ENABLE_PIR | Optional photographed PIR motion output | Measure HIGH <=3.3 V and actual timing; external pulldown; PIR is not a person recognizer |

Those three digital extras are disabled in normal builds, even if their firmware
can decode host simulated test vectors. GPIO34 through GPIO39 have no internal
pull resistors. Do not plug an anonymous PIR 5 V logic output into the ESP32;
use a qualified level converter when required. A reed contact near the motors
may trigger from their magnetic fields. The BMP280 can add atmospheric pressure
and temperature *only* if its existing vendor driver is selected and tested on
the actual hardware. Its address may conflict with an optional Berry pressure
chip if someone wires both upstream: isolate it on mux lane 5. No extra I2C
sampling may starve five-channel floor polling. None of this bypasses WROOM
local guard, MPU heartbeat, one-use operator permit, or the robot's $50 cap.


### Inspect extra sensor and MPU wiring without arming motors

With a qualified and physically disconnected motor supply, run the existing
`code/scripts/serial_bench.py --port <actual-WROOM-USB-port> --inspect` on
the WROOM USB serial interface. The inspection now exposes MPU6050 (family4)
raw six-axis data and the `optional_inputs` enabled bit mask, bumper/reed/PIR
levels and rising counters. It reports false physical qualification even when
values are fresh. GPIO35/36/39 remain disabled in default firmware until each
has measured voltage levels, hardware pull resistors and a real enclosure mount.
An active bumper also blocks the tool's *eligibility diagnostic* for a local
rearm; only actual physical calibration and the separate direct USB command can
clear the WROOM safety latch. No web or model endpoint gets that authority.


## Source-verified bounded WROOM status size

The original body reply array 752B and Sense bridge UART read cap 768B were dangerously tight after adding eight touch zones, optional event counters and future telemetry. A valid long-lived robot with several 32-bit event counters approaching 10 digits could return an `ERR status response_too_long`, hiding health diagnostics. This patch raises WROOM reply buffer to **1100 bytes**, Sense bridge maximum UART line to **1152 bytes** and local USB inspector read bound to **1152 bytes**, retaining the same strict line limits and malformed-frame rejection. The body still uses a fixed allocation and never emits a truncated JSON status as healthy. This change **does not** increase model motor permissions or alter local cliff fault handling. It is verified by the existing compiler and native tests, not yet a physical UART trace.
