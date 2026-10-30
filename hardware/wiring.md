# Wiring and power

Confirm printed GPIO labels on your **ESP32-WROOM-32 development board**; physical
pin positions vary. The Feather and USB-C breakout #4090 are not needed here.
The active modular head's proposed pins and electrical corrections are in
[the head guide](../docs/modular-head.md). Use the dedicated `--board modular`
firmware configuration; the earlier CoreS3 binary must not be flashed to Freenove.

| WROOM GPIO | Connection |
| --- | --- |
| 16 / UART RX | S3 head GPIO2 / TX, configured module-head allocation |
| 17 / UART TX | S3 head GPIO1 / RX, configured module-head allocation |
| GND | Head GND and actuator supply GND |
| 25, 26 | DRV8833 AIN1, AIN2 for left motor |
| 27, 32 | DRV8833 BIN1, BIN2 for right motor |
| 18 | Lift servo signal |
| 19 | Gripper servo signal |

DRV8833 AOUT1/2 (often OUT1/2) go to the left motor; BOUT1/2
(often OUT3/4) go to the right. IN1/2 correspond to AIN1/2; IN3/4 to BIN1/2.
Confirm actual silkscreen and the chip/board documentation before connecting.
On the inspected cheap listing, **EEP is nSLEEP (input)** and **ULT is nFAULT
(open-drain output)**; the seller prose reverses these roles. Once the actual
board is identified, nSLEEP must be high (3.3 V logic) to operate. Do not drive
nFAULT or assume an Adafruit-specific current-limit setting exists.

The [TI DRV8833 specifications](https://www.ti.com/product/DRV8833) distinguish
500 mA RMS PW and 1.5 A RMS PWP/RTY packages; a “2 A peak” listing is not a
continuous board rating. The generic board's package/cooling and N20 loaded or
stall current are unresolved. The seller's N20 50 mA is **no-load** current.
Bench-check current, voltage droop and temperature before a loaded rover test.

UART is 115200 8N1, **3.3 V logic**, common ground. In the initial two-USB bench
test, join TX/RX/GND only; leave board 5 V rails separate. The previous CoreS3
reference used the same GPIO numbers on PORT.A; that connector and its cable
colors do not describe the new modular head.

## Power

On the bench, power the dev boards by USB, servos/motor driver from a separately
sized regulated supply, and join grounds. Never supply actuator current through
the ESP32's 3.3 V output or through the board from a laptop USB port. Confirm
servo voltage from its datasheet.

Budget portable arrangement, conditional on the owned bank's rating/load/fit:

```text
regulated 5 V USB power bank -> suitably rated lead / switch / distribution
                              -> head and WROOM approved USB/5 V inputs
                              -> separate servo and DRV8833 power branches
all grounds joined; UART remains 3.3 V
```

The user confirmed having a bank, not its current rating, weight or dimensions.
Check the label, shared-port limits and loaded operation; a 5 V / 3 A label is a
useful candidate, not a guarantee against startup brownouts. Check auto-shutoff
at idle, mounting and stability too. Use short rated power conductors; ordinary
thin breadboard jumpers are not the actuator-current path. Do not power actuators
through the WROOM/S3 regulator or through a laptop USB port.

[Adafruit #4090](https://www.adafruit.com/product/4090) is listed up to 1.5 A;
do not treat it as a verified 3 A distributor for the complete robot. A suitable
USB power lead/distribution is included in the wiring allowance. Do not join
a bank/external 5 V source to a laptop USB 5 V source without a documented power
path. Disconnect portable power for the initial laptop-USB board tests.

The separate 2S pack/charger/buck has been removed from the active shopping plan.
If power-bank reuse fails, revise the delivered budget rather than silently
adding that $29.50 system. A future 2S supply still needs regulated step-down
from up to 8.4 V; MT3608 is boost-only and cannot do that conversion.

Measure voltage droop and temperature during motor startup, servo load, Wi-Fi and
speech together. No power/current/stall test has been performed yet.

## Bring-up order

1. Disconnect motors and remove servo horns. Flash only the WROOM first.
2. Confirm `READY ... disarmed`, `ping`, `status` at 115200. Boot servo PWM is off.
3. `arm` applies center PWM. Center unloaded servos before attaching horns, then
   `disarm`. Start powered linkage tests near 90°, with small angle changes.
4. Lift the rover so tracks cannot propel it. Test 15% PWM for 100 ms, direction
   and stop. Interrupt control and measure the 500 ms timeout on the stand.
5. Bring up head screen, audio and fresh camera capture before connecting UART.

Watchdog stop holds the last servo PWM. Support/remove the payload before
explicit `disarm` or power-off. Use the power switch if the mechanism stalls.
