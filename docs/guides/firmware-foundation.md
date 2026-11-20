# Firmware foundation — implemented 2026-11-03

Run commands from the repository’s `code/` folder.

The project now has a compiled XIAO ESP32S3 Sense head target with Xiaozhi
ESP-SR AFE device AEC and a playback-reference codec, and a compiled
28BYJ-48/ULN2003 body with eight VL53L0X I2C ranges (five safety-critical,
three side/rear read-only), local safety fault latch,
touch gestures, bounded stepper control and source-first OLED idle behavior.
These are **software milestones**. No board has been flashed or physically
qualified; no real edge, power, audio interruption, touch-through-case,
IMU tilt, camera, grip/place or fleet trial has passed.

The user has reported purchasing the Sense bundle; it remains the active head.
[Realtime reuse research](../research/2026-11-03-sense-realtime-reuse.md) maps
RIO reference timing to the pinned Xiaozhi ESP-SR AFE. The current Sense
`SenseReferenceCodec` and interrupt/decoder flush are compiled, but natural
double-talk still needs measured acoustic tests. The Mac `live_turns.py`
module holds transport-independent epoch/cancel semantics; the actual
Xiaozhi bridge remains the audio session and playback owner.
See [integration contract](live-conversation.md).
The optional Waveshare adapter is a separate fallback with host checks, not a
required purchase or a completed firmware-build claim.

## Body builds

```sh
PLATFORMIO_CORE_DIR="$PWD/../.tools/platformio" ../.tools/body-pio-venv/bin/pio run -d firmware/body -e esp32_stepper
PLATFORMIO_CORE_DIR="$PWD/../.tools/platformio" ../.tools/body-pio-venv/bin/pio run -d firmware/body -e esp32dev
```

`esp32_full` is the default eight-VL53L0X profile, with motor power
intentionally disabled until its independent cutoff is physically qualified.
The five-channel `esp32_stepper` bench profile uses the eight phase pins in
[BodyPins.h](../../code/firmware/body/include/BodyPins.h), two positional servo signals
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

**The default full firmware acquires eight VL53L0X channels**: four downward
cliff sensors and one front sensor are safety critical, while three side/rear
channels are read-only. It uses pinned Pololu VL53L0X initialization plus
checked, bounded I2C results and a TCA9548A bus.
Local USB calibration stores a checksummed NVS policy. Missing, stale, invalid
or bus-fault samples latch the body disarmed until a fresh local USB rearm.
No fabricated calibration is in firmware, so a fresh unassembled image cannot
arm on its own. The actual breakouts, optical heights, surface reflectance,
loaded stop margin, power rail and current cost remain unqualified.

The existing USB bench helper can now inspect five distance/age/validity
channels and the BerryIMU identity without moving any motor. An explicitly
qualified operator may request a **local USB-only** `--local-rearm` for a
supervised catch-tray command, after real measured calibration; it cannot
mint an AI permit or bypass a physical fault. The Mac performs read-only
five-channel, touch and identity preflight before operator permit and again
before requesting body arm. No host test certifies real stop distance.

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

See [exact Sense pins](../../code/firmware/head/sense/README.md): OLED5/6, amplifier4/7/8,
UART TX2/RX1, PDM42/41 and stock camera pins. SD must remain empty/disabled;
GPIO21 holds chip select high because audio reuses SD signals. Native USB remains
reserved. Stock Xiaozhi OLED emotion/text UI remains authoritative during listening
and speaking. A pinned MIT
[Stackchan behavior controller](https://github.com/botamochi6277/stackchan-agent)
now drives **idle OLED mood only** through the existing `SetEmotion` method
and Sense board overlay. All Stackchan motion actions are deliberately
discarded; they never become body or servo commands. Display glyph appearance
and idle behavior timing still need an actual screen test. The Mac pet
runtime independently handles opted-in fresh camera changes, memory,
quiet and shared speech. Continuing autonomous movement remains gated,
not silently substituted by fake idle motion.

## Evidence and next gates

[Verification record](../records/reports/firmware-foundation-2026-11-03.json) stores
commands, counts, build hashes/sizes and limits. Body tests cover fault injection,
both UART receivers, local recovery authority, gripper hold, drive expiry,
rollover, phase sequencing and no catch-up. Head tests cover installation/drift,
pin collisions, board separation, private identity and protocol/snapshot behavior.
Compilation is not evidence of physical peripheral or mechanical performance.

Keep the $50 delivered cap, actual inventory gaps and small-remix constraint.
Qualify real sensing/power/geometry before roaming, then add stationary original
face animation and the Mac pet scheduler. Repeat one validated core for five.

## Read-only BerryIMU identity and optional peer text sharing

The single WROOM I2C owner also probes WHO_AM_I once at boot to distinguish
likely BerryIMU V1 LSM9DS0, V2 LSM9DS1 or V3 LSM6DSL/LIS3MDL.
An unrecognized ID remains unknown. This is **not a gyro/accelerometer
driver or A11 attitude safety test**. Matching licensed Adafruit or SparkFun
drivers must be pinned only after actual board identification and checked
sample timing; no software guess declares the owned module usable.

The existing five robot Mac `PetController` can optionally share bounded
observed text between the **five independent per-robot SQLite memories**.
It retains true firsthand versus told-by provenance for each event and does
not share microphone PCM, camera JPEG, secret credentials or motion authority.
It is disabled by default; operators may enable it explicitly in private
`fleet_text_sharing_enabled` settings. This does not establish five physical
camera overlap or audio turn-taking on real devices.
