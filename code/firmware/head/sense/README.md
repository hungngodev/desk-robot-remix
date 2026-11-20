# XIAO ESP32S3 Sense head target

Active board: **Seeed XIAO ESP32S3 Sense, SKU 113991115**, with its camera/mic
expansion attached. The user reports ordering at least one full Sense bundle;
receipt quantity, arrival and delivered revision remain unconfirmed. This target is
separate from the preserved CoreS3 and Freenove targets. No board is flashed.

Keep this purchased board. [RIO reuse research](../../../../docs/research/2026-11-03-sense-realtime-reuse.md)
identifies software playback-reference/AEC code for Sense. The current
SenseReferenceCodec is integrated, compiling, and supplies real microphone
plus playback-reference PCM to the selected AFE. Acoustic timing remains
unmeasured on the user's hardware. Ordinary-speech interruption must still pass the
[audio gate](../../../../docs/guides/audio-barge-in.md). Do not set `input_reference` true
without supplying actual synchronized mic/reference data. RIO's speaker pins
differ from the table below; do not mix the two wiring maps.

## Guarded RGB heart using upstream Xiaozhi state LED

The Sense board now exposes the **existing pinned Xiaozhi `SingleLed` / Espressif
`led_strip` WS2812 implementation** as its audio/conversation heart on GPIO9,
but only when `CONFIG_DESK_ROBOT_RGB_HEART_ENABLED=y` in the **Sense-only**
Kconfig. The default is `n`. The upstream application calls `GetLed()`
on device state changes; its existing implementation displays low-brightness
listening, speaking, WiFi and error/idle states. No additional LED driver,
camera worker, VAD process or motor output is created.

**DO NOT ENABLE OR WIRE THIS YET.** GPIO9 shares the shipped Sense expansion
microSD J3 routing; confirm Seeed's documented physical J3 isolation on the
actual board revision, verify the logic buffer that translates XIAO 3.3V data
for the chosen 5V WS2812, common-ground wiring, regulator loading and signal
integrity with an instrument. The opt-in flag is deliberately insufficient as
electrical authorization. This is a source implementation, not a passed
hardware trial. Sense audio, native JPEG and OLED still own their own pins.

## Native JPEG for natural live video

The selected Sense firmware now asks the pinned `Esp32Camera` for
`PIXFORMAT_JPEG` at VGA, with two PSRAM frame buffers and
`CAMERA_GRAB_LATEST`. The upstream pinned
[`Esp32Camera::Capture`](https://github.com/78/xiaozhi-esp32/blob/c435f99a88066029ec2dbd2d758c8cc9d051565b/main/boards/common/esp32_camera.cc)
handles sensor JPEG without copying VGA RGB565 and reencoding it in software.
The existing `modular_snapshot.inc` passes through the already compressed JPEG
under the camera mutex and now checks both JPEG boundary markers and a 512 KiB
size cap. The OLED is used for emotional expressions, not the upstream LVGL
camera preview, which the pinned upstream explicitly skips for JPEG.
A separate read-only body-polling task now protects the 100 ms local
Stackchan face renderer from a 350 ms WROOM UART timeout. Bounded atomic
touch cues and a 1.2 second body health freshness gate prevent a missing
controller from appearing healthy or replaying queued touch events.
The actual five-minute unplugged face responsiveness test remains open.

A physical non-motion camera/status stress probe is in
`code/scripts/bench_head_camera.py`. With a real camera-connected XIAO,
a real Xiaozhi device identity, and private hardware TOML configured:

```sh
cd code
uv run --no-sync python scripts/bench_head_camera.py \
  --config config/local.toml --robot robot-01 --seconds 60 \
  --stream --status-period 0.2 \
  --report ../docs/records/reports/sense-camera-bench-local.json
```

It makes authenticated GET requests only, records JPEG and body status
timing without writing any pictures or voice, and rejects stale/replayed
source metadata through the existing `HttpHead` transport. Its report
always leaves actual acoustic interruption, sensor exposure synchronization,
charging and assembly acceptance FALSE. Run an independent sound recording
and real interrupt trials for those separate release gates.

The head now exposes one authenticated, long-lived
`GET /api/camera.mjpg` multipart JPEG stream, adapting Espressif's
`esp32-camera` CameraWebServer pattern using the **existing pinned Xiaozhi
`SnapshotJpeg` camera owner**. The selected camera can emit up to four native
VGA JPEG frames per second; the Mac consumes them on one persistent connection,
checks boot/sequence/completion identity and frame integrity, and samples at
most two frames per second for lightweight change detection. The existing
proactive pet, VAD, direct look, image selection and local VLM reuse the same
three-frame RAM ring. No additional camera/model/motor service is created.

In hardware mode, `voice_vision_tools_enabled=true` starts the real stream.
For automatic visible-scene reactions also set `pet_autostart_enabled=true`
and configure an installed local `vision_model`. These settings are existing
operator camera consent gates, not defaults. If the stream is disconnected,
visual mode reports the outage and refuses a silent fallback to
`/api/camera.jpg`; the Mac reconnects with bounded delay. Standalone
non-stream camera bench tools may still use the original snapshot endpoint
when no stream is active. Mic AEC, Opus and emergency speech interruption
remain with pinned Xiaozhi. Four FPS is a software ceiling, NOT physically
measured performance. Two PSRAM frame buffers with latest-frame acquisition are the current
source configuration, pending real simultaneous camera, microphone, heat,
JPEG age and WiFi measurements. The stream bench rejects gaps longer than
1.2 seconds, including a delayed first frame or stale final frame; this is
transport continuity evidence, not a measured exposure rate.

## Continuous microphone is a separate explicit permit

The native audiovisual thinker cannot hear ambient sounds until the existing
Xiaozhi audio channel enters its `realtime` listening mode. On the selected
Sense board the upstream `Application::ToggleChatState()` already opens that
channel using full-duplex ESP-SR device AEC. A new Sense-only
`CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED` switch reuses this existing
code after boot, without another PDM driver or competing Opus connection.

It defaults to **off**. For a private production build the operator must
explicitly supply `--continuous-audio` to
`firmware/head/private_config.py --board sense` along with the existing
private credentials, selected robot and Mac server address. The on-device
BOOT button can close the streaming channel even while the robot speaks;
operator intervention disables automatic reactivation for that boot.
A power cycle starts another explicitly configured continuous audio session.
This is a software privacy control, **not an electrically qualified microphone
mute switch**. Confirm the OLED listening state, AEC, silence-stream continuity
and actual headset interruption with instruments before production.

For actual continuous camera transport (not single-photo polling), run the
existing read-only bench with `--stream`. This consumes exactly one
authenticated `/api/camera.mjpg` connection while polling status separately,
reports actual receiving FPS, JPEG identity continuity, frame interval and
connection stalls, and never stores any photo or microphone recording. The
`--camera-period` option applies only to legacy snapshot mode. A successful
stream bench does not certify sound, inference, docking or electrical safety.

## Pin source and allocation

[Seeed's official pin table](https://wiki.seeedstudio.com/xiao_esp32s3_pin_multiplexing/)
and [board guide](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/)
were checked 2026-11-03. Sense has 8MB flash/PSRAM, PDM microphone42clock/41data,
and the camera signals below. Current camera bundles may contain OV3660 or
OV5640 AF; the actual delivered revision must be tested. This adapter does not
add autofocus controls or establish optical/pickup performance.

| Function | ESP32-S3 GPIO | Header / connection |
| --- | --- | --- |
| SSD1306 SDA / SCL | 5 / 6 | D4 / D5, head-owned I²C1, 128×64, address0x3C |
| MAX98357 BCLK / LRC / DIN | 4 / 7 / 8 | D3 / D8 / D9 |
| Body UART TX / RX | 2 / 1 | D1 / D0 → WROOM RX16 / TX17, 3.3V1152008N1 |
| Onboard microphone clock / data | 42 / 41 | PDM, internal expansion connection |
| Camera D0–D7 | 15,17,18,16,14,12,11,48 | Stock Sense camera |
| Camera XCLK / PCLK / VSYNC / HREF | 10 / 13 / 38 / 47 | Stock Sense camera |
| Camera SDA / SCL | 40 / 39 | SCCB on I²C0 using new driver |
| BOOT button | 0 | Built-in chat/Wi-Fi provisioning action |
| Unused SD chip-select | 21 | Held high; **leave SD slot empty** |

Native USB19/20, debug UART43/44, strapping GPIO3 and flash/PSRAM pins are not
assigned to external peripherals. Amplifier7/8 reuse SD signals, so never insert
an SD card or initialize SD. No touch pad is allocated. Floor/obstacle sensors**Required real-board mod for the chosen audio+RGB pins:** The microSD slot shares S3 GPIO7, GPIO8 and GPIO9 via the Sense expansion's **J3 solder bridge, shipped enabled by default**. Merely disabling SD software does **not** electrically remove the slot. Before connecting speaker amp on GPIO7/8 or optional RGB on GPIO9, use Seeed's [official J3 instructions](https://wiki.seeedstudio.com/xiao_esp32s3_sense_filesystem/) on the actual shipped expansion revision: remove camera to protect the lens, open J3 for SPI header use, then electrically inspect and confirm no microSD routing is active. **No SD card**, no SD.begin(). The current firmware compile does not verify physical J3.

No touch pad is allocated. Floor/obstacle sensors
belong to the WROOM bus, not this head's display bus.

SSD1306 pin order/voltage, address, orientation and the rounded Sparky bezel fit still need
checking. MAX98357 speaker connects across SPK+ and SPK−, neither to ground;
use the selected Challenge Electronics CS20-02P110-04-1X 8 ohm 2 W rectangular speaker, not the retired 1 W candidate; actual MAX98357A 5V output and enclosure acoustic/thermal margins must still be qualified. Use qualified supplies/grounds and
rated actuator wiring. Do not join independent USB5V sources blindly.

## Bounded I2S write under urgent speech interruption

The exact pinned Xiaozhi `NoAudioCodec::Write` normally calls the ESP-IDF
`i2s_channel_write` with `portMAX_DELAY` while holding its codec mutex.
An urgent decoder reset and `EnableOutput(false)` cannot reliably interrupt
a stalled write until that lock is released. The **Sense-only disposable
overlay** in `install_overlay.py` now reuses the same native I2S writer with
a 500 ms TX wait ceiling, preserves its actual accepted sample count so the
playback AEC reference is not fabricated, and returns a transient write fault
instead of rebooting the head with `ESP_ERROR_CHECK`. Other Xiaozhi boards
retain the original upstream writer. The overlay test checks the pinned
upstream anchor and reversibility, but this software bound alone does not
certify audible interruption: WiFi, AFE/VAD, output DMA, codec locking and
speaker-to-PDM acoustic coupling must still be timed with real equipment.
See [voice acceptance](../../../../docs/guides/audio-barge-in.md).

## Driver reuse and isolation

This adapter uses the pinned Xiaozhi `Esp32Camera`, `OledDisplay`, IDF SSD1306
panel driver, `NoAudioCodecSimplexPdm` input and I²S speaker output. It retains
our authenticated bridge, fresh-camera snapshot lock and disabled-by-default
raw motion tools. No new camera/audio driver, RoboEyes/GPL face code or custom
animation is incorporated. Stock OLED emotion/text UI is used initially.

Camera SCCB must be I²C0 and OLED I²C1; compile guards reject the known conflicting
camera setting. The8MB partition table is `partitions/v2/8m.csv`: two0x2f0000
OTA slots and2MB assets at0x600000. Actual app/assets size and a successful build
are required; never truncate the old16MB merged image.

## Build only

From the project root:

```sh
python3 firmware/head/install_overlay.py --board sense --upstream upstream/xiaozhi-esp32 --output firmware/head/build/xiaozhi-sense
bash scripts/build_head.sh --board sense
```

An existing installed copy is checked with:

```sh
python3 firmware/head/install_overlay.py --board sense --target firmware/head/build/xiaozhi-sense
```

The installer rejects drift and different-board overlays. It never edits the
source clone. `--remove` restores only unchanged generated files. Private
settings remain under the ignored build copy, with mode0600 and the selected
robot's existing credential:

```sh
python3 firmware/head/private_config.py --board sense --config config/local.toml --robot robot-01 --server-ip MAC_LAN_IP
bash scripts/build_head.sh --board sense --private
```

These commands require valid existing private configuration; no credentials are
embedded in the generic verification build. That build uses an empty bridge
token and disabled wake word. Actual screen, camera, PDM, speaker, UART,
Wi-Fi/wake-word, case fit, power and physical stopping remain bench tests.
