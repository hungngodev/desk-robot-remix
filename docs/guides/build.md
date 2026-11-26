# One robot build and firmware guide

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

## Complete first robot route

On a clean Mac, first install the Xcode Command Line Tools (`xcode-select --install` if needed), `uv`, CMake and OpenSCAD. OpenSCAD must be callable as `openscad` for the fit-kit exporter; if installed as an application, pass its verified executable path with `--openscad`. Check the tools before proceeding, and use the exact intended repository checkout. From the repository root, prepare the locked Python environment **before** the shopping step's `uv run --no-sync` command:

```sh
(cd code && uv sync --extra dev --python 3.11 --locked)
```

Python 3.11 is the coordinator's minimum supported version and the host CI reference minor, recorded in `code/toolchain-lock.json` under `python`. The selector intentionally follows available 3.11 patch releases rather than pinning an exact interpreter patch. The Python 3.12 firmware toolchain bootstrap environments described below are separate from the coordinator's locked application environment.

If dependency installation fails, stop this setup stage rather than proceeding with stale generated artifacts. The CAD export and paper template commands below run from the repository root; coordinator and firmware commands run from `code/` unless otherwise stated.

For the Mac coordinator, private configuration, pinned Xiaozhi overlay,
provider dependencies and server startup, follow [Local AI setup](local-ai.md).
The read-only CLI doctor is not physical qualification or a movement permit.

Use this file as the single entry point for the first complete pet. The linked
records remain canonical for measurements and generated wiring, so do not copy
them into a second shopping list or hand-edit generated pin tables.

1. **Buy and inventory.** Start with
   [the first complete robot procurement entry point](../hardware/one-robot-inventory-and-shopping.md).
   Keep reported or ordered stock separate from still-to-buy items. A HOLD item
   stays out of checkout until its listed release evidence exists.
   For a separately bounded evaluation sample, use the same canonical generator
   from `code/`: `uv run --no-sync python scripts/procurement_release.py --format pilot-samples-markdown`.
   Check the listed sample quantity, delivered price, electrical restrictions and
   unresolved roles before checkout. A pilot sample is not final cart release
   or authority to order the remaining fleet quantities. Keep private order
   receipts outside this repository.
2. **Measure before final CAD.** Fill
   [the Fusion measurement sheet](../cad/FUSION_MEASUREMENT_SHEET.md) from the
   actual delivered parts. Protected pack body, leads and connector, charger,
   boost, fuse, switch, service path, track width, two dock seat switches,
   MG90S geometry, GY-530 optics and head interfaces remain separate inputs.
3. **Print reversible fit pieces first.** Generate and verify the provisional
   kit with `python3 code/scripts/export_fit_kit.py` and then
   `python3 code/scripts/export_fit_kit.py --verify`. Follow
   [the adapter kit instructions](../cad/remixes/one_robot_adapter_kit_README.md).
   These parts are fit references, not the final installed print set.
   For source-derived A4 **paper** fit overlays, separately run from the repository root:

   ```bash
   python3 docs/cad/remixes/print_2d_fit_templates.py --output /tmp/robot-paper-fit
   python3 docs/cad/remixes/print_2d_fit_templates.py --output /tmp/robot-paper-fit --verify
   ```

   Print **all five** source-derived A4 SVGs at **100% / actual size**:
   `ranger_reference_A4.svg` (GY-530 carrier),
   `speaker_reference_A4.svg` (speaker),
   `dock_reference_A4.svg` (AprilTag paper pocket),
   `dock_guide_reference_A4.svg` (front entry and back stop rails), and
   `power_reference_A4.svg` (provisional protected 1S pack and tray footprint).
   Never fit-to-page. Measure their independent 100 mm, 50 mm and 25 mm scales with a
   ruler, then compare carrier size and holes against the delivered parts. A
   clipped, scaled or mismatched paper reference is a **STOP** before drilling,
   purchasing final mounts or printing permanent solids. These are unpowered
   provisional outlines, not approved mounting holes or a qualified dock.
4. **Assemble and inspect mechanically.** Follow
   [the one robot Fusion assembly](../cad/FUSION_ONE_ROBOT_ASSEMBLY.md).
   Check track and servo swept spaces, camera and ToF visibility, battery
   removal, wire bends, USB access, speaker cavity, center of gravity and dock
   seating before exporting final installed parts.
5. **Wire connector to connector.** Use the
   [generated signal harness](../hardware/one-robot-signal-harness.generated.md)
   together with [the wiring and power guide](../hardware/wiring.md). Do not
   infer a pin from a concept render and do not energize dock contacts.
6. **First power.** Complete the staged connector-level preflight in
   [the protected single cell power gate](../hardware/one-robot-power-gate.md#staged-connector-level-first-power-preflight-checklist)
   before energizing anything: verify WROOM and XIAO USB/5 V supply isolation,
   connector pin/polarity order, unpowered continuity and adjacent-pin short
   checks, and explicit STOP on any failed branch/fuse HOLD. Bring up logic with
   motors and charger power disconnected first. The power gate, actual regulator
   behavior, pack temperature path and protected dock circuit must pass before
   actuator or charging qualification.
7. **Build and flash.** Use the exact WROOM and XIAO Sense commands later in
   this guide. Confirm the physical USB device before any upload. The selected
   body profile is `esp32_full`; the selected head is `sense`.
8. **Calibrate physical behavior.** Use
   [IMU handling](imu-handling.md),
   [the jaw calibration helper](jaw-calibration-helper.md), and
   [the first gripper test](first-gripper-test.md), plus the camera, ToF,
   dock and acoustic procedures referenced by the live verification record.
   The accepted first-unit object-return path additionally requires [Guide 50
   calibrated map and per-robot spatial memory](../plans/spatial-first-unit/50-map-and-spatial-memory.md)
   and [Guide 60 object recall and navigation](../plans/spatial-first-unit/60-object-recall-and-navigation.md).
   Record the measured camera/body transform, stationary tag and map anchor,
   AS5600 wheel coupling and odometry origin for the same physical unit.
   Keep route proposals **read-only** until the actual body pose, safe desk
   support, fresh visual target and local WROOM stop/cutoff are qualified.
   Unavailable pose, moved/hidden target, pickup, new boot/origin, human STOP,
   stale camera or wrong pet/session means no motion and no claimed arrival.
9. **Operate, STOP and recover.** Start disarmed. Use the STOP and rearm rules
   in [the wiring guide](../hardware/wiring.md) and never treat reconnect,
   putdown or a recovered Mac session as permission to resume motion.
10. **Diagnose faults.** Keep the robot disarmed when a required sensor,
    dock monitor, charger state, current sample or safety receipt is missing,
    stale or contradictory. Trace the relevant source and physical measurement
    before replacing a guard with a bypass.
11. **Run acceptance.** Record exact build and calibration identity, then run
    the applicable A1 through A12 cases in
    [the verification record](../records/verification.md), and the separate
    [first-unit object return trials](../plans/spatial-first-unit/60-object-recall-and-navigation.md):
    at least 9/10 map re-anchors within 20 mm and 8/10 stationary object
    returns from changed starting poses, with zero false arrivals or unsafe
    commands in negative trials. Log each actual assembly and calibration ID,
    pose/target receipt and operator observation. Software checks, printed fit
    and physical qualification are distinct evidence.

    **Dedicated dock:** follow the existing [charging design and validation](../hardware/charging-design-and-validation.md)
    for unpowered alignment, independent seat confirmation and qualified
    electrical enable. Stop before powered contact if seating, protection,
    pack temperature, voltage/current or measured net-charge evidence is missing.

    **One shared read-only room station:** follow the [Feather station build and
    measurement procedure](../../code/firmware/room_station/README.md). Start
    with the reported owned Feather alone on USB and the
    `feather_nrf52840_room_bench` target; qualify exact carrier supplies,
    3.3 V logic and pull-ups before attaching modules. Use
    `feather_nrf52840_room_full` only after the installed soil probe's analog
    output is verified. Run the documented `bench_room_station.py` capture
    with a new private report outside the checkout; record board/carrier IDs,
    supply minima, current, regulator temperature, and USB/sensor freshness.
    Missing, stale or invalid readings and unqualified rails are STOP/HOLD
    points. Enable shared context only by explicit opt-in; the station never
    grants motion or charging permission.
12. **Release the final print set only after qualification.** The current
    repository intentionally does not call the source meshes and fit coupons a
    production robot. Final installed quantities and dock charging remain
    blocked until the required measurements and physical trials pass.

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
../.tools/body-pio-venv/bin/pio run -d firmware/body -e esp32_full
```

The platform is pinned to espressif32 6.9.0 (Arduino 2.0.17). All body
profiles inherit the exact PlatformIO framework package
`3.20017.241212+sha.dcc1105b` and Xtensa compiler `8.4.0+2021r2-patch5`.
Dock and room station likewise pin their framework and compiler packages in
shared `[env]` sections. `code/toolchain-lock.json` records those resolved
versions from [CI run 45768389395](https://github.com/hungngodev/desk-robot-remix/actions/runs/45768389395).
The host lock test checks all declared profiles, including lab variants. This
locks the listed packages, not every transitive build input.

The generic `esp32dev` profile compiled for the WROOM development board, but
the actual board's flash/reset/USB interface still needs confirmation.

A guarded logic-only upload is a prerequisite for sensor calibration, not a
movement release. First verify board identity, logic supply, common ground,
USB backfeed isolation and unpowered harness continuity. Physically disconnect
motor, servo, battery and dock/charger power. If any prerequisite is unknown,
stop before upload. Identify the exact board/port; port listing is read-only:

```sh
../.tools/body-pio-venv/bin/pio device list
```

After confirming the port belongs to the WROOM, set `WROOM_PORT` to its exact USB
device and upload the same explicit full profile (from `code/`):

```sh
(
  : "${WROOM_PORT:?Set WROOM_PORT to the verified WROOM USB device}"
  ../.tools/body-pio-venv/bin/pio run -d firmware/body -e esp32_full --target upload --upload-port "$WROOM_PORT" || exit 1
  ../.tools/body-pio-venv/bin/pio device monitor --port "$WROOM_PORT" --baud 115200
)
```

Expect a disarmed body and local rearm required. Missing calibration or sensor
faults must not enable outputs. Stop on the wrong profile, unstable supply,
missing status or unexpectedly armed outputs. Disconnect the serial monitor
before using the USB bench helper. No hardware upload is claimed.

### Center the two hornless MG90S before measuring installed lift travel

The old `esp32dev` DC reference is **actuator inert**, so its `arm` command
cannot center either physical servo. The guarded `esp32_full` and
`esp32_dc_full` builds intentionally refuse ARM until per-unit jaw and lift
limits are measured. Do **not** bypass the guard to center a servo.

An explicitly selected centering fixture reuses the production WROOM GPIO18
(lift), GPIO19 (jaw), 50 Hz LEDC timer and 1500 us commanded center pulse.
With **both servo horns and linkages removed**, unplug both drive motors,
disconnect the charger/dock/battery path, and power one MG90S at a time from
a separately current-limited regulated supply sharing ground with WROOM.
Do not feed servo motor current from the WROOM 3.3 V pin or its USB port.
Verify polarity and actual idle/current-limit behavior before energizing.

```sh
../.tools/body-pio-venv/bin/pio run -d firmware/body -e esp32_servo_center_bench
../.tools/body-pio-venv/bin/pio run -d firmware/body -e esp32_servo_center_bench --target upload --upload-port PORT
../.tools/body-pio-venv/bin/pio device monitor --port PORT --baud 115200
```

Only on the confirmed **local USB0 serial monitor**, send `CENTER LIFT`
followed by a newline, then `CENTER GRIP` after the first completion. Each
command can run **once per boot**, operates **one servo at a time** at a fixed
nominal 90 degrees for at most **400 ms**, and automatically detaches its
PWM channel. There is no drive, arbitrary angle, remote control, battery
charge or safety rearm command in the fixture. If an ACK or visible center
position is missing, remove power and inspect wiring; do not assume an angle
was physically reached.

Once the outputs are detached, disconnect actuator power, mark each horn's
center mechanically, and fit the two horns without moving the shafts.
Measure the installed lift's safe **minimum and maximum commanded angles**
around its 90 degree boot position on a collision-free fit fixture. The
measured `DESK_ROBOT_LIFT_MIN_DEG` and `DESK_ROBOT_LIFT_MAX_DEG` must
be inside the generic 60 to 120 degree parser envelope and contain 90.
Record the installed MG90S, horn index, source SHA, load, current,
linkage clearance and motion direction. Only after a supervised physical
test may a dedicated build set `DESK_ROBOT_LIFT_LIMITS_QUALIFIED=1`
and the two measured values. Do not set that flag for a stock image or
reuse another robot's readings.

After those measurements, switch back to the guarded full firmware and
follow the jaw calibration, ToF/IMU, electrical cutoff and explicit USB
rearm procedures. With actuator power disconnected, inspect the guarded body
from `code/` using the read-only USB bench mode:

```sh
uv run --no-sync python scripts/serial_bench.py --port "${WROOM_PORT:?Set WROOM_PORT to the verified WROOM USB device}" --inspect --samples 10
```

Stop if status is missing, stale or invalid; inspection does not rearm or
qualify hardware. The helper's motion mode is only for an **already qualified
guarded body**, not initial servo centering. It requires explicit local rearm,
sends one bounded command and issues HALT in cleanup, disarming while retaining
servo PWM. A command ACK remains different from physical motion or successful
grasp evidence.

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

For a fresh installation only, from `code/`, create the SDK bootstrap and
clone the SDK at the exact commit in the checked-out toolchain lock. The
following subshell stops on the first failure and refuses an existing SDK
checkout or bootstrap environment. For an existing installation, inspect its
origin, revision, submodules and Python environment instead of deleting it.

```sh
(
  set -eu
  mkdir -p ../.tools
  for existing in ../.tools/sdk-bootstrap ../.tools/esp-idf; do
    if [ -e "$existing" ] || [ -L "$existing" ]; then
      printf 'Preserve and inspect existing path: %s\n' "$existing" >&2
      exit 1
    fi
  done
  uv venv ../.tools/sdk-bootstrap --python 3.12
  idf_commit="$(python3 -c 'import json; print(json.load(open("toolchain-lock.json"))["esp_idf"]["commit"])')"
  git clone --no-checkout https://github.com/espressif/esp-idf.git ../.tools/esp-idf
  git -C ../.tools/esp-idf fetch origin "$idf_commit"
  git -C ../.tools/esp-idf checkout --detach "$idf_commit"
  git -C ../.tools/esp-idf submodule update --init --recursive
  test "$(git -C ../.tools/esp-idf rev-parse HEAD)" = "$idf_commit"
  tools_root="$(cd ../.tools && pwd)"
  export IDF_TOOLS_PATH="$tools_root/idf-tools"
  export PATH="$tools_root/sdk-bootstrap/bin:$PATH"
  "$tools_root/esp-idf/install.sh" esp32s3
)
```

A successful install is not a flash or physical qualification. If an existing
SDK or bootstrap is present, do not rerun the fresh-install block until its
identity and preservation have been reviewed.

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
[Sense board connections](../../code/firmware/head/sense/README.md), including
J3 microSD isolation inspection before attaching the GPIO7/8 amplifier (and
optional GPIO9 RGB). Leave the SD slot empty.

### Private Sense build and isolated USB commissioning

Complete [Local AI setup](local-ai.md) for private `config/local.toml` and
`config/local.env`. Use the actual robot ID and the reachable Mac LAN IPv4
of the running server. From `code/`:

```sh
python3 firmware/head/private_config.py --board sense --config config/local.toml --robot robot-01 --server-ip "${MAC_LAN_IP:?Set MAC_LAN_IP to the Mac LAN IPv4}"
bash scripts/build_head.sh --board sense --private
```

Add `--continuous-audio` only with explicit operator consent; camera streaming
requires separate Mac operator consent. Keep private settings, firmware and
serial logs private. Do not reuse a generic image or another robot's token.

After a successful private Sense build, identify the actual Sense USB device.
Keep the WROOM UART and all actuator and charging power disconnected. From
`code/`, use the same project-local SDK as the build helper:

```sh
(
  : "${SENSE_PORT:?Set SENSE_PORT to the verified Sense USB device}"
  tools_root="$(cd ../.tools && pwd)" || exit 1
  export IDF_TOOLS_PATH="$tools_root/idf-tools"
  export PATH="$tools_root/sdk-bootstrap/bin:$PATH"
  source "$tools_root/esp-idf/export.sh" || exit 1
  cd firmware/head/build/xiaozhi-sense || exit 1
  idf.py -p "$SENSE_PORT" flash monitor
)
```

If the SDK was installed under `code/.tools`, use that verified root instead.
Recheck the port when switching boards; never assume the WROOM port is Sense.
Stop on failed flash, unstable supply, unexpected reset, wrong board or failed
local server registration. Verify OLED, camera, microphone privacy control
and speaker wiring independently before reconnecting UART. Physical AEC,
motion, charging and final assembly remain separate gates.

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
The Mac CLI, Xiaozhi `laptop/server/run_server.py` launcher and head
`firmware/head/private_config.py` all default to `local.env` beside the selected
TOML configuration, regardless of the current working directory. Use an explicit
`--secrets` path for a shared credential file in another directory. For the Mac
CLI, pass it before the subcommand for both credential creation and subsequent
commands. Relative paths supplied explicitly are relative to the invoking shell;
repository-owned build assets remain anchored to the source tree.

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
