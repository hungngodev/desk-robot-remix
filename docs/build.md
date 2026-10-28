# Firmware builds

These commands build files. **Nothing in setup automatically flashes hardware.**
The body target is classic ESP32-WROOM-32; the head target requires CoreS3 Lite's
ESP32-S3. Do not flash a head image onto WROOM.

## Body

From the project root:

```sh
uv sync --extra dev
uv venv .tools/body-pio-venv --python 3.12
uv pip install --python .tools/body-pio-venv/bin/python platformio==6.1.18
export PLATFORMIO_CORE_DIR="$PWD/.tools/platformio"
.tools/body-pio-venv/bin/pio run -d firmware/body
```

The platform is pinned to espressif32 6.9.0 (Arduino 2.0.17). Its generic
`esp32dev` profile compiled for the WROOM development board, but the actual
board's flash/reset/USB interface still needs confirmation.

When your board is connected, identify its exact port using:

```sh
.tools/body-pio-venv/bin/pio device list
```

After confirming the port belongs to the WROOM, upload explicitly with
`pio run -d firmware/body --target upload --upload-port PORT` using the local
`pio` path above. Replace `PORT` with that real device. Motors disconnected,
servo horns removed, separate actuator supply and common ground for the first
test. No port has been selected and nothing has been uploaded in this session.

One bounded USB bench test, after wiring/centering:

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
cmake -S firmware/body -B .tools/body-host -DBODY_SANITIZERS=ON
cmake --build .tools/body-host
ctest --test-dir .tools/body-host --output-on-failure
```

On this Mac, the installed compiler needed its existing SDK C++ include path:
`export CPLUS_INCLUDE_PATH="$(xcrun --show-sdk-path)/usr/include/c++/v1"`.
This is a per-terminal workaround, not a global configuration change.

## CoreS3 head

The pinned Xiaozhi source requires ESP-IDF release/v6.1. This session installed
it under `.tools/esp-idf` and tools under `.tools/idf-tools`. On another machine,
restore the exact SDK commit recorded in `toolchain-lock.json`, initialize its
submodules, and run its `install.sh esp32s3` with `IDF_TOOLS_PATH` set as below.
Do not substitute IDF5.

```sh
python3 scripts/restore_upstreams.py
python3 firmware/head/install_overlay.py --upstream upstream/xiaozhi-esp32 --output firmware/head/build/xiaozhi
bash scripts/build_head.sh
```

If the build copy already exists, check the overlay with
`python3 firmware/head/install_overlay.py --target firmware/head/build/xiaozhi`.
It refuses changed overlay files. `--remove` restores only unchanged overlay
files; preserve any local edits first. Upstream clones remain separate.

The verification build has an empty bridge token, so movement/HTTP controls are
disabled. It is a compile check, not ready-to-use personalized firmware.
For a real head, prepare private settings after generating `config/local.env`:

```sh
uv run desk-robot secrets
python3 firmware/head/private_config.py --robot robot-01 --server-ip MAC_LAN_IP
bash scripts/build_head.sh --private
```

The helper selects the existing local Python 3.12 bootstrap before exporting
IDF. On another Mac, create `.tools/sdk-bootstrap` with
`uv venv .tools/sdk-bootstrap --python 3.12` before the SDK install.

Replace `MAC_LAN_IP` with the Mac's reachable IPv4 address. Use robot-02 only
for the second head. The private variant embeds a head credential and local OTA
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
