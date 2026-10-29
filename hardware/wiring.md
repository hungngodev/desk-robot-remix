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

DRV8833 AOUT1/2 go to the left motor; BOUT1/2 to the right. Follow the selected
breakout's VM, GND, sleep and current-limit instructions; SLP must be high for
the Adafruit board to operate. Match the limit to the actual selected motors.
[Driver guide](https://learn.adafruit.com/adafruit-drv8833-dc-stepper-motor-driver-breakout-board).

UART is 115200 8N1, **3.3 V logic**, common ground. In the initial two-USB bench
test, join TX/RX/GND only; leave board 5 V rails separate. The previous CoreS3
reference used the same GPIO numbers on PORT.A; that connector and its cable
colors do not describe the new modular head.

## Power

On the bench, power the dev boards by USB, servos/motor driver from a separately
sized regulated supply, and join grounds. Never supply actuator current through
the ESP32's 3.3 V output or through the board from a laptop USB port. Confirm
servo voltage from its datasheet.

Proposed portable arrangement:

```text
assembled protected 2S pack -> switch/fuse -> buck adjusted to 5.0 V
                                         -> separate branches to servos,
                                            DRV8833 VM, approved 5 V board inputs
all grounds joined; UART remains 3.3 V
```

A charged 2S pack reaches 8.4 V. Measure the buck output before connecting loads.
MT3608 is boost-only; it cannot perform this step-down. Do not send 2S voltage
directly to a 5 V input or micro servo. Pack, wire, fuse and connector selection
remain dependent on actual currents. Avoid simultaneous external/USB 5 V unless
that board's documented power path permits it.

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
