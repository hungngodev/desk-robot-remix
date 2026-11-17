# Motor cutoff after a stalled ESP32 application: source first design

**Status: source implemented in a nonproduction lab target; electronics NOT
qualified.** A normal DRV8833 breakout with nSLEEP held high does not provide
an independent application watchdog. The existing WROOM `control.tick()`
and local CliffGuard guard software commands, but a frozen CPU could leave
peripheral LEDC waveforms running. This is a distinct failure class: another
software timeout or Mac-side heartbeat does not prove that motor drive ceases.

## Manufacturer and proven design reuse

* Texas Instruments DRV8833 datasheet §7.3.4: **nSLEEP LOW disables BOTH
  H bridges**, with up to about 1 ms wake time afterward. TI states the
  nSLEEP pin has an internal approximately 500 kΩ pulldown. On many assembled
  carriers including Pololu 2130, nSLEEP is **already tied HIGH through a
  resistor**, so **no direct signal-level or unpowered fail-low guarantee**
  follows from the bare-chip data sheet.
  [TI datasheet](https://www.ti.com/lit/ds/symlink/drv8833.pdf),
  [Pololu built carrier guide](https://www.pololu.com/product/2130).
* TI CD74HC123 datasheet: a **dual** retriggerable hardware monostable,
  with a second separate timing circuit and independent output.
  The existing haptic kit already proposes its first channel, so the
  second channel is a reuse candidate instead of buying another processor.
  [TI 74HC123](https://www.ti.com/lit/ds/symlink/cd74hc123.pdf).
* ESP32 software watchdogs do not prove an independent power gate:
  if LEDC has already been configured as an autonomous peripheral, a
  stopped application cannot be assumed to have zeroed its output.
  See [Espressif board reset and pull states](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32/schematic-checklist.html).
* **Do not implement the heartbeat using motor PWM edges or an MCP23017
  latch.** Motor PWM can remain active without CPU progress; I2C output
  can remain latched during bus stall.

## Exact existing pin and code integration

| Net | Source selected behavior | Electrical acceptance |
| --- | --- | --- |
| CPU heartbeat | ESP32 WROOM GPIO23, DC only | 3.3 V, startup output LOW, 10 kΩ external pulldown |
| Heartbeat generation | `MotorHeartbeat` called *after* local cliff/IMU/dock checks and `BodyControl::tick` | First rising edge starts after a genuine authorized drive |
| Toggle intervals | CPU toggles every 15 ms during an authorized drive, rising edges ~30 ms | Continuous logic trace needed over CPU stall, I2C NACK and unsigned timer rollover |
| Heartbeat OFF | Immediate logical LOW on disarm, stop, expired drive, stale sensors or dock contact | Motor PWM must be stopped independently; hardware Q will expire after its own RC timeout |
| One-shot input | CD74HC123 pin 10 (2B) from GPIO23; pin 9 (2A) LOW; reset pin 11 (2R) HIGH | Verify exact SOIC/PDIP chip footprint and reset behavior on 3.3 V and brownout |
| One-shot RC | Pin 7 (2RxCx) timing resistor to 3.3 V and capacitor between pins 7 and 6 (2Cx); pin 6 to GND | Do NOT assume 0.45RC at 3.3 V without datasheet + oscilloscope; select margin from measured stop distance |
| Time-limited output | Channel two Q pin 5 | A qualified **fail LOW at power loss** interface must drive DRV8833 nSLEEP |
| DRV8833 | nSLEEP must become LOW on heartbeat timeout or brownout | Inspect and, if needed, modify the exact carrier onboard nSLEEP pullup; never connect a 3.3 V CMOS output to an unknown VM-referenced pullup |

The logic timing above makes 30 ms nominal positive-edge intervals while
the application is running. The actual timer must be tuned so the **shortest**
qualified hardware pulse exceeds the maximum rising edge interval plus loop
jitter, and the **longest** pulse and stopping distance both stay inside the
measured distance to the desk edge. A 200 ms default watchdog from an unrelated
IC might be too slow for a small table robot. The TI `0.45 * R * C` formula
for CD74HC123 is specified at **5 V**, and is not a 3.3 V min/max bound.

**DO NOT** assume the direct pin 5 to nSLEEP connection is approved. An
assembled carrier that already pulls sleep HIGH to its motor voltage, plus a
3.3 V logic output or unpowered microcontroller, can violate logic ratings
or unexpectedly enable the H bridge. A fixed schematic must prove the
startup, disabled, active, stall, supply-loss, and nSLEEP pullup states using
the exact generic driver PCB revision. This gate is not solved just by
compiling `esp32_dc_watchdog_lab`.

## Production and prototype split

`code/firmware/body/platformio.ini` contains
`esp32_dc_watchdog_lab`, extending the full sensor guarded DC backend,
with `DESK_ROBOT_ENABLE_DC_WATCHDOG=1`. It is **not the default**.
The chosen standalone GPIO23 is also used as a stepper phase in
`esp32_full`; therefore the **two motor architectures are electrically
exclusive**, not one interchangeable harness. No mixed assembly is allowed.

`MotorHeartbeat.h` is reusable pure C++11 and has an executable regression
for disarmed startup, authorized toggling, stale/disarm forced LOW and millis
rollover. The GPIO is toggled in the ESP32 main loop after the local sensor
checks; the LEDC peripheral does not own it. The code does **not** pretend
to verify the CD74HC123, its external RC, DRV8833 carrier, or disabled
power rail.

## Before any fivefold purchase

Confirm one exact DRV8833 carrier with a known nSLEEP pullup and current limit
behavior, then engineer the fail-low logic interface, verify powered and
unpowered voltage levels with oscilloscope, remove/run I2C sensor/USB/WiFi
faults while motors run on a safe workstand, and show that hardware Q times
out while LEDC output is still HIGH or PWM is still toggling. Measure the
worst-case Q timeout across cold/hot and low/high supply, and the actual
deceleration distance after nSLEEP goes LOW. The bound must fit the
source-calculated cliff geometry budget. Hold motor/charger shopping until
that evidence exists.
