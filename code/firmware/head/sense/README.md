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
limit volume for the selected8Ω1W speaker. Use qualified supplies/grounds and
rated actuator wiring. Do not join independent USB5V sources blindly.

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
