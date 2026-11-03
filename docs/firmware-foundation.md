# Firmware foundation — implemented 2026-11-03

The project now has a compiled XIAO ESP32S3 Sense head target, a compiled
28BYJ-48/ULN2003 body profile, and a portable local sensor-fault policy. These
are software milestones. No board has been flashed, sensor I/O is not connected
in firmware, and no physical edge, power, audio, camera or pickup test has passed.

## Body builds

```sh
PLATFORMIO_CORE_DIR="$PWD/.tools/platformio" .tools/body-pio-venv/bin/pio run -d firmware/body -e esp32_stepper
PLATFORMIO_CORE_DIR="$PWD/.tools/platformio" .tools/body-pio-venv/bin/pio run -d firmware/body -e esp32dev
```

`esp32_stepper` is now the default. It uses the eight phase pins in
[BodyPins.h](../firmware/body/include/BodyPins.h), two positional servo signals
and existing 115200 UART. `esp32dev` explicitly preserves the earlier DC/DRV8833
profile with its different four-wire motor allocation. Never connect a binary
to the other profile's motor wiring. No upload command was run.

`StepperDrive` uses half steps, signed requests clamped to40%, acceleration and
reversal through zero. Its unqualified scheduling ceiling is160 half-steps/s,
not measured speed or torque. A stopped/disabled output clears coils immediately
and preserves the phase index. Delayed calls never emit a catch-up burst. Coil-off
means coast, not qualified braking; loaded stopping and temperature still need tests.
Drive remains bounded to250ms and communication loss to500ms. Keepalives do not
extend a drive pulse. Step timing never uses blocking multi-step calls.

## Sensor policy and recovery

`CliffGuard` represents four downward floor sensors and one separate front
obstacle sensor. Each has validity and freshness; downward sensors have per-unit
floor intervals, the forward sensor a separate obstacle threshold/verified range.
Missing, invalid, stale, out-of-range or bus-failure data latches a fault. Fresh
readings cannot erase an already-expired gap or automatically clear a fault.
Replacing calibration and bus failure invalidate old observations.

`BodyControl` rechecks the guard before output/control paths. Fault stops drive,
freezes servo targets and disarms movement while retaining existing servo PWM
so it does not intentionally release a payload. Explicit `disarm` still releases
servos. Status includes protocol2, backend and a safety object; it does not report
measured travel, force, or successful edge protection.

Ordinary `arm` **cannot clear the latch**. This matters because the existing
coordinator automatically arms when consuming an operator permit: a permit
issued before a fault must not silently count as a new post-fault recovery.
The new `rearm` command is accepted only on the body-local USB receiver, with
healthy fresh readings and valid calibration. It clears the latch but leaves
movement disarmed. The head UART, HTTP/MCP parser and laptop transport reject it.
A future physical button or authenticated recovery design can be considered
separately; no model-controlled recovery was added.

**Current hardware adapter deliberately provides neither calibration nor sensor
samples. Both `arm` and local `rearm` therefore fail in the stepper build.**
There is no hidden bypass or claim of working physical cliff sensing. Next work:
checked, bounded ToF/mux I²C reads and per-robot measured calibration, followed by
tethered sensor/stop tests. A driver must propagate short reads, write failures,
range-quality errors and timeouts rather than treating absent data as clear floor.

The existing USB servo bench helper does not grant recovery. Servo-only tests
can use the explicit legacy profile with motors disconnected; its servo pins
are unchanged. That does not qualify the new drivetrain or sensors.

## Sense head

```sh
python3 firmware/head/install_overlay.py --board sense --upstream upstream/xiaozhi-esp32 --output firmware/head/build/xiaozhi-sense
bash scripts/build_head.sh --board sense
```

The isolated Sense build uses8MB flash/PSRAM, existing PDM input, camera,
SSD1306 and I²S output drivers, and the authenticated bridge. Actual camera
revision, mic/audio, display address/orientation, UART and fit need bench tests.
The generic verification binary has empty credentials and disabled wake word;
private per-robot settings remain separate and ignored.

See [exact Sense pins](../firmware/head/sense/README.md): OLED5/6, amplifier4/7/8,
UART TX2/RX1, PDM42/41 and stock camera pins. SD must remain empty/disabled;
GPIO21 holds chip select high because audio reuses SD signals. Native USB remains
reserved. Stock emotion/text UI is used; RoboEyes, pet behavior and spontaneous
roaming are not implemented by this milestone.

## Evidence and next gates

[Verification record](../test-results/firmware-foundation-2026-11-03.json) stores
commands, counts, build hashes/sizes and limits. Body tests cover fault injection,
both UART receivers, local recovery authority, gripper hold, drive expiry,
rollover, phase sequencing and no catch-up. Head tests cover installation/drift,
pin collisions, board separation, private identity and protocol/snapshot behavior.
Compilation is not evidence of physical peripheral or mechanical performance.

Keep the $50 delivered cap, actual inventory gaps and small-remix constraint.
Qualify real sensing/power/geometry before roaming, then add stationary original
face animation and the Mac pet scheduler. Repeat one validated core for five.
