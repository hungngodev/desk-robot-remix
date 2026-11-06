# Wiring and power — proposed stepper/sensor revision

Updated 2026-11-06. **Use only the matching profile.** Default `esp32_stepper` now compiles with
eight phase outputs and portable cliff policy, but no sensor I/O/calibration:
it refuses to arm. Explicit `esp32dev` preserves four DC H-bridge inputs and
must never be connected to this stepper map. This is not physically qualified.

## Proposed WROOM allocation

Check actual ESP32-WROOM-32 development-board labels and exposed pins first.
Avoid flash GPIO6–11, strapping GPIO0/2/5/12/15 and programming UART0 GPIO1/3.

| WROOM GPIO | Proposed use |
| --- | --- |
| 16 RX / 17 TX | Sense head UART TX / RX, 115200 8N1, 3.3 V; Sense TX2 / RX1, compiled allocation |
| 18 / 19 | Lift / grip MG90S signal |
| 13, 14, 25, 26 | Left ULN2003 IN1–IN4, phase order to verify |
| 27, 32, 33, 23 | Right ULN2003 IN1–IN4, phase order to verify |
| 21 / 22 | Body I²C SDA / SCL to mux upstream |
| 4 | Mux active-low RESET, only if board exposes and electrically supports it |
| GND | Head, body, sensors and actuator-supply common logic reference |
|34 | Proposed Adafruit #1374 AT42QT1010 OUT, powered at 3.3 V with common GND, momentary active-high. Bench test and firmware integration pending |
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
WROOM GPIO21/22 -> owned BerryIMU upstream (revision/addresses to verify), candidate
               -> TCA9548A upstream I²C
                  channel 0 -> front-left downward VL6180X
                  channel 1 -> front-right downward VL6180X
                  channel 2 -> rear-left downward VL6180X
                  channel 3 -> rear-right downward VL6180X
                  channel 4 -> separate forward-facing obstacle VL53L0X
Sense -> separate head-owned OLED bus
```

Each ToF keeps its default **7-bit 0x29** address; select only one corresponding
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
mix the two tables or add an SD44 wire to the current build. Software echo
cancellation and ordinary-speech interruption remain unimplemented in this target.

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
