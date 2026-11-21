# Firmware builds

These commands build files. **Nothing in setup automatically flashes hardware.**

**Current hardware source, November 21, 2026:** This guide retains the
historical Freenove modular and CoreS3 sections below as references only.
The selected first robot uses **XIAO ESP32S3 Sense** for Xiaozhi audio,
streaming camera and OLED, and the **ESP32 WROOM** for independent local
motion safety. The default body build is now `esp32_full`, not the old
`esp32_stepper` bench profile. The eight cheap VL53L0X channels have
source drivers, but real optics, 3.3 V carriers, calibration, braking and
hardware motor cutoff are unqualified. Firmware compilation is **not**
permission to move, flash with motors connected, print the final chassis
or energize dock contacts.

For printable parts, initial physical measurements and the known protected
battery/chassis mismatch, begin at [Fusion one robot assembly](../cad/FUSION_ONE_ROBOT_ASSEMBLY.md).
For actual signal assignments use [generated one robot harness](../hardware/one-robot-signal-harness.generated.md),
and for full operating restrictions use [firmware progress](firmware-foundation.md).
Do not use historical Freenove/CoreS3 configurations for the selected Sense head.

## Current WROOM builds, with motion disabled until physical qualification

`code/firmware/body/platformio.ini` defaults to `esp32_full`, the full eight
VL53L0X sensor and 28BYJ48/ULN2003 guarded profile with independent
motor-power cutoff **unqualified and disabled**. `-e esp32_dc_full` is a separate
full sensor alternative for N20/DRV8833, requiring the independent
CD74HC123 cutoff and actual electrical, thermal and braking tests. Do not
substitute either motor/harness on the other profile. `-e esp32_stepper` is a
historical five critical sensor bench profile; `-e esp32dev` is an old DC
reference. Neither alternative is automatically the selected final drivetrain.

From the repository root, enter `code/` before running the build commands.

```sh
cd code
uv sync --extra dev
uv venv ../.tools/body-pio-venv --python 3.12
uv pip install --python ../.tools/body-pio-venv/bin/python platformio==6.1.18
export PLATFORMIO_CORE_DIR="$PWD/../.tools/platformio"
../.tools/body-pio-venv/bin/pio run -d firmware/body
```

The platform is pinned to espressif32 6.9.0 (Arduino 2.0.17). Its generic
`esp32dev` profile compiled for the WROOM development board, but the actual
board's flash/reset/USB interface still needs confirmation.

No upload is appropriate for the unfinished guarded build. After hardware and
sensor qualification, identify the exact board/port explicitly; port listing is read-only:

```sh
../.tools/body-pio-venv/bin/pio device list
```

After confirming the port belongs to the WROOM, upload explicitly with
`pio run -d firmware/body --target upload --upload-port PORT` using the local
`pio` path above. Replace `PORT` with that real device. Motors disconnected,
servo horns removed, separate actuator supply and common ground for the first
test. No port has been selected and nothing has been uploaded in this session.

For legacy servo-only bench work with motors disconnected, after wiring/centering:
The helper cannot clear the guarded profile’s sensor latch or grant recovery.

```sh
uv run python scripts/serial_bench.py --port PORT --command "grip 95"
uv run python scripts/serial_bench.py --port PORT --command "disarm"
```

The helper sends arm, one command, supervised keepalives for at most 1.5 seconds,
then stop. Remove/support any load before `disarm`, which detaches servo PWM.
It never retries an uncertain movement ACK. Start near 90°; first establish
mechanical clearance before testing wider travel.

Host tests:

```sh
cmake -S firmware/body -B ../.tools/body-host -DBODY_SANITIZERS=ON
cmake --build ../.tools/body-host
ctest --test-dir ../.tools/body-host --output-on-failure
```

On this Mac, the installed compiler needed its existing SDK C++ include path:
`export CPLUS_INCLUDE_PATH="$(xcrun --show-sdk-path)/usr/include/c++/v1"`. The head native test harness now probes this SDK include path automatically on macOS when no explicit `CPLUS_INCLUDE_PATH` was supplied; the manual setting remains useful for other direct compiler commands.
This is a per-terminal workaround, not a global configuration change.

## Shared head build environment

Existing firmware build outputs from the earlier folder layout are saved in
`.tools/pre-layout-builds/` at the repository root. Start a fresh build copy
at the paths below before rebuilding. The archived build caches contain the
original absolute paths.

The pinned Xiaozhi source requires ESP-IDF release/v6.1. This session installed
it under `../.tools/esp-idf` and tools under `../.tools/idf-tools`. On another machine,
restore the exact SDK commit recorded in `toolchain-lock.json`, initialize its
submodules, and run its `install.sh esp32s3` with `IDF_TOOLS_PATH` set as below.
Do not substitute IDF5.

The build helper seeds and verifies `firmware/head/dependencies.lock` in each
build copy. It rejects a changed dependency lock. Keep the two board copies
separate so that overlay changes and binaries retain their actual board identity.

## Selected XIAO ESP32S3 Sense head

These existing commands configure and compile only the selected XIAO Sense
overlay. From `code/`, after pinning and restoring its supported ESP-IDF 6.1
SDK and project local toolchain described above:

```sh
python3 scripts/restore_upstreams.py
python3 firmware/head/install_overlay.py --board sense --upstream upstream/xiaozhi-esp32 --output firmware/head/build/xiaozhi-sense
bash scripts/build_head.sh --board sense
```

This default verification build has no private head credential and is not
a functional consented speech or camera deployment. The operator must first
qualify actual USB board identity, 3.3 V pin levels, camera, PDM mic,
MAX98357A speaker wiring, OLED and local WiFi. Keep motor and charger
power physically disconnected during that head bench test. No robot was
flashed or qualified by writing these commands. See
[Sense board connections](../../code/firmware/head/sense/README.md).

## Modular S3 head — historical Freenove reference

Prepare its own build copy, leaving `upstream/` and the CoreS3 reference untouched:

```sh
python3 scripts/restore_upstreams.py
python3 firmware/head/install_overlay.py --board modular --upstream upstream/xiaozhi-esp32 --output firmware/head/build/xiaozhi-modular
bash scripts/build_head.sh --board modular
```

On an existing modular copy, check it with
`python3 firmware/head/install_overlay.py --board modular --target firmware/head/build/xiaozhi-modular`.
The installer refuses changed overlay files. Remove only unchanged overlay files
with `--remove`; preserve local edits first.

This target uses **16 MB flash and 8 MB octal PSRAM**. Camera SCCB explicitly uses
I²C0 and the new I²C driver; the OLED uses I²C1. The board has a compile guard
against changing the camera to I²C1 or mixing in the legacy I²C driver. Setting
only `camera_config_t.sccb_i2c_port` is insufficient when SCCB pins are assigned:
the pinned camera driver chooses that bus through Kconfig.

The verification configuration uses an empty bridge token and disabled wake word.
For private local-server settings, after generating `config/local.env`:

```sh
uv run desk-robot --config config/fleet.example.toml secrets --add-missing
python3 firmware/head/private_config.py --board modular --robot robot-01 --server-ip MAC_LAN_IP
bash scripts/build_head.sh --board modular --private
```

Replace `MAC_LAN_IP` with the Mac's reachable IPv4 address. Select robot-01
through robot-05 from the same fleet configuration used by the Mac; pass
`--config config/local.toml` once real identities are configured. Keep private settings/binaries in the ignored build
directory. Real wake-word, audio, camera, OLED address/orientation and UART must
still be tested. The default SH1106 UI shows emotion symbols/text; smooth moving
eyes are a later animation adapter.

After selecting the actual Freenove device and confirming its module/camera,
flash only from `firmware/head/build/xiaozhi-modular` using the same exported IDF
environment and upstream `idf.py -p PORT flash monitor`. No device has been
selected or flashed. Bring up the head alone on USB before connecting the WROOM
UART or actuator supply.

## Previous CoreS3 head reference

These commands are retained for the earlier board and do not build modular-head
firmware:

```sh
python3 scripts/restore_upstreams.py
python3 firmware/head/install_overlay.py --board cores3 --upstream upstream/xiaozhi-esp32 --output firmware/head/build/xiaozhi
bash scripts/build_head.sh --board cores3
```

If the build copy already exists, check the overlay with
`python3 firmware/head/install_overlay.py --target firmware/head/build/xiaozhi`.
It refuses changed overlay files. `--remove` restores only unchanged overlay
files; preserve any local edits first. Upstream clones remain separate.

The verification build has an empty bridge token, so movement/HTTP controls are
disabled. It is a compile check, not ready-to-use personalized firmware.
For a real head, prepare private settings after generating `config/local.env`:

```sh
uv run desk-robot --config config/fleet.example.toml secrets --add-missing
python3 firmware/head/private_config.py --board cores3 --robot robot-01 --server-ip MAC_LAN_IP
bash scripts/build_head.sh --board cores3 --private
```

The helper selects the existing local Python 3.12 bootstrap before exporting
IDF. On another Mac, create `../.tools/sdk-bootstrap` with
`uv venv ../.tools/sdk-bootstrap --python 3.12` before the SDK install.

Replace `MAC_LAN_IP` with the Mac's reachable IPv4 address. Select the actual
robot ID from the same fleet configuration used by the Mac. The private variant embeds a head credential and local OTA
address; keep the entire build directory and binary private. Empty credentials
disable the bridge. Wake-word support is prepared, but the verified build used
`disabled`; hardware wake-word behavior has not been tested.

After selecting the correct CoreS3 port, use upstream `idf.py -p PORT flash
monitor` from its build project with the same exported IDF environment. Provision
Wi-Fi using the upstream flow and confirm the local server/OTA address. Check
the actual display revision, screen, camera, microphone and speaker before UART.
Do not flash the generic verification binary expecting local credentials.

The head exports authenticated LAN status/control/camera endpoints on 8081.
Snapshots use a separate task so stop/keepalive requests are not blocked by the
camera. Stock camera, audio and screen pins are preserved in the unique
`desk-robot-core-s3` board. Raw drive/lift/grip MCP tools are off by default to
avoid competing with laptop jobs; status remains available. Voice stop goes
through the laptop's job-cancelling tool. Low-level tools
can be enabled only for bench debugging; the laptop pickup tool is the normal path.
