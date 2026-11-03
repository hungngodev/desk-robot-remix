# Edge detection and local stopping — research, 2026-11-03

**Recommendation:** qualify four downward-facing sensors near the chassis
corners, plus a separate front-facing obstacle sensor. The WROOM body controller
owns their readings and motor interlock. This is a proposed design: the body firmware at the research checkpoint used DC PWM only. A later
[firmware milestone](../firmware-foundation.md) adds stepper and guard policy,
but actual sensor I/O/calibration and physical protection remain unfinished. No physical sensor, power or stopping test has passed yet.

## Candidate parts and alternatives

ST now marks [VL6180X](https://www.st.com/en/imaging-and-photonics-solutions/vl6180x.html)
obsolete and out of production. The video's TOF050C/VL6180 example is useful
inspiration but is not the preferred new procurement choice.

The candidate is the [GY-530 VL53L0X double-hole module, SEN-19-018](https://electropeak.com/gy-530-vl53l0x-laser-ranging-sensor-module-double-hole),
**$1.75 each**, with a [TCA9548A eight-channel mux breakout](https://electropeak.com/tca9548a-1-to-8-i2c-8-way-multi-channel-expansion-board),
**$0.47**. Both USD prices were rechecked in the seller's live HTML price metadata.
They exclude delivery, tax and wiring. Sensor height, optical footprint, board
dimensions, pullups, supply arrangement and usable range remain qualification
items. The [ST VL53L0X product documentation](https://www.st.com/en/imaging-and-photonics-solutions/vl53l0x.html)
describes the sensor IC; it does not certify this generic breakout or our mounting.

| Arrangement | One robot | Five robots |
| --- | ---: | ---: |
| Four downward sensors + one mux | $7.47 | $37.35 |
| Four downward + separate forward sensor + mux | **$9.22** | **$46.10** |

The second arrangement requires 25 sensors and five muxes for the fleet. It is
the proposed roaming baseline. One downward sensor cannot cover reversing and
pivots; four sensors still require geometric and stopping tests. A downward
floor reading cannot also provide object distance inside the gripper.

A cheaper option is four [TCRT5000 reflector modules, SEN-05-018](https://electropeak.com/tcrt5000-infrared-sensor),
$0.38 each: $1.52 per robot or $7.60 for twenty. The seller specifies roughly
1–8 mm detection distance. Their actual output voltage/polarity and adjustment
must be checked at 3.3 V. This is a different low-mounted design, strongly
dependent on surface reflectance. [Vishay's bare-sensor datasheet](https://www.vishay.com/docs/83760/tcrt5000.pdf)
places peak response at 2.5 mm. Alternatively, the documented
[Pololu QTR-HD-01A](https://www.pololu.com/product/4201) costs $3.25 singly and has
an optimal 5 mm sensing distance. Neither is automatically equivalent to ToF.

## WROOM pin budget and ownership

On an ESP32-WROOM-32, reserve flash pins, boot strapping pins and UART0. A
conservative usable output set is GPIO4,13,14,16,17,18,19,21,22,23,25,26,27,32,33:
15 pins. Two ULN2003 stepper interfaces need eight; two servos need two; head
UART needs two; body I²C needs two. That consumes 14, leaving insufficient
outputs for four or five individual XSHUT lines. GPIO34–39 are input-only and
lack internal pullups. Confirm the actual development board exposes the chosen
pins. These restrictions follow [Espressif's ESP32 datasheet](https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_en.pdf).

Proposed allocation, **not a wiring instruction for the current firmware**:

| Function | WROOM GPIO |
| --- | --- |
| Head UART RX / TX | 16 / 17 |
| Lift / grip signal | 18 / 19 |
| Left ULN2003 IN1–IN4 | 13, 14, 25, 26 |
| Right ULN2003 IN1–IN4 | 27, 32, 33, 23 |
| Body I²C SDA / SCL | 21 / 22 |
| Mux RESET, if exposed and electrically verified | 4 |

The mux gives each VL53L0X its own channel, retaining the default **7-bit 0x29**
address; do not confuse this with an 8-bit transfer address. Select only one
same-address channel for transactions. The head's OLED remains on its separate
head-owned bus. Do not tie two MCU masters onto the sensor bus.

[TI documents TCA9548A](https://www.ti.com/product/TCA9548A) channel isolation and
active-low reset for recovering a stuck downstream bus. Verify the purchased
board's reset connection and 3.3 V pullups. Recovery must leave motion stopped;
reset is not permission to resume. Optional bumper inputs on exposed
GPIO34/35/36/39 require external pullups and their own verification.

## Required local behavior

Boot disarmed. Arming requires valid calibration and healthy, fresh readings
from every required sensor, with floor intervals only for the downward sensors.
The forward sensor has its own obstacle threshold and verified range. Treat an
invalid/out-of-range forward view as unknown and deny movement; explicitly test
an empty forward scene rather than assuming no return means no obstacle. A detected drop, invalid/no-return measurement,
stale sample, unplugged sensor or bus timeout latches a motor stop. Reject
manual, UART, HTTP, MCP, pickup and autonomous drive requests through the same
body-side interlock. Healthy readings returning do not clear the latch;
explicit human rearming is required. Never automatically reverse away from an
edge: the rear might already be unsafe.

The existing 500 ms communications watchdog remains a separate last resort.
Cliff handling must run locally during each control cycle, without waiting for
Wi-Fi, camera processing or an LLM. Use continuous ranging and bounded bus reads;
do not sequentially block step generation on five full measurement delays.
Choose freshness and decision deadlines from measurements rather than an
invented universal threshold. On a cliff stop, stop wheel stepping while
retaining the existing servo hold policy so a payload is not deliberately
dropped. Stepper hold versus coast needs thermal/current and stopping tests.

## Mounting, power and acceptance

Mount each downward beam ahead of the track contact patch in its relevant
direction, including the swept footprint during pivots. The engineering gate is:

`required sensor lead >= speed × (worst sensor age + decision latency) + measured braking distance + error margin`

Measure every term with the final bank, head, arm and payload. Test matte, black,
glossy and transparent surfaces, lighting changes, thin table edges, sensor
occlusion, disconnection and bus faults. Use a tether/catch tray; record stopping
distance for forward, reverse and pivot separately. Exclude surfaces/motions
that cannot pass. A single forward ToF does not cover side/rear collisions.

Use rated actuator power wiring and common ground, with logic kept at 3.3 V.
Owned DuPont ribbons are suitable signal leads, not an assumed motor-current
distribution system. Verify bank output and startup droop under simultaneous
stepper, servo, Wi-Fi and speaker load. Decoupling capacitors cannot repair an
undersized supply. These tests reduce risk; they do not establish that the robot
cannot fall from any table.
