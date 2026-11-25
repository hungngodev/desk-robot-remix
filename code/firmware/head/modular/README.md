> Updated 2026-11-03: this is the historical Freenove 16 MB/SH1106/I²S target.
> The Sense/PDM/SSD1306/8 MB head is a separate compiled target, not physically tested.
> Do not flash this build onto Sense. See `docs/guides/modular-head.md`.

# Modular S3 head — hardware unverified

Unique `desk-robot-modular-s3` board for Freenove FNK0085B / N16R8 (16 MB flash,
8 MB octal PSRAM), a 1.3-inch SH1106 I2C OLED, INMP441, MAX98357A and speaker.
It reuses Xiaozhi's Esp32Camera, OledDisplay and NoAudioCodecSimplex drivers.
This historical source profile still requests 24 kHz speaker output; the
selected MAX98357A does not support 24 kHz LRCLK. Do not power that combination
or infer amplifier compatibility from compilation. The active Sense profile
uses 32 kHz output and 16 kHz PDM/AEC reference instead.
The seller's exact camera sensor/lens and case fit still need confirmation.
An N8R8 board is not covered by this 16 MB partition configuration.

The existing OLED UI shows monochrome emotion glyphs and chat/status text.
Smooth EVA-style animated eyes have not been adapted or tested. The camera
uses VGA RGB565 in PSRAM; live color, orientation and capture speed are untested.

Proposed connections (confirm each module's labeling before powering it):

| Module | Head GPIO |
| --- | --- |
| SH1106 SDA / SCL, address 0x3C | 38 / 39, I2C controller 1 |
| INMP441 WS / SCK / SD | 41 / 42 / 40; L/R to GND |
| MAX98357A BCLK / LRC / DIN | 14 / 21 / 47 |
| Body UART TX / RX | 2 / 1 to WROOM RX16 / TX17 |
| Boot interaction button | Built-in GPIO0 button |

Camera pins retain Freenove's stock mapping and use SCCB controller 0. The board
variant explicitly selects camera I2C0 in Kconfig and rejects a different
resolved selection at compile time; the camera port field alone does not select
that bus when SCCB pins are assigned. No SD
card is used: GPIO38–40 are reused. Leave octal PSRAM GPIO35–37, native USB19/20,
debug UART43/44 and the onboard RGB LED48 alone. Head and body use 3.3 V logic
and common ground. Use the properly regulated supply described in hardware docs.
The speaker connects between MAX98357A **SPK+ and SPK−**; neither terminal is GND.
Do not copy EVA's GPIO36/37 OLED wiring onto an N16R8 board.

The authenticated LAN API, UART protocol, boot-disarm and body watchdog behavior
are the same as the CoreS3 reference. Configure a unique private ID/token; the
default empty token disables the robot bridge and all movement tools. Snapshots
capture a fresh frame and share a recursive lock with upstream capture/explain.
They run outside the HTTP control task. No background movement keepalive exists.

Prepare an independent build copy from the repository root; nothing is flashed:

```sh
cd code
python3 firmware/head/install_overlay.py --board modular --upstream upstream/xiaozhi-esp32 --output firmware/head/build/xiaozhi-modular
bash scripts/build_head.sh --board modular
```

For private local-server firmware, after generating local credentials:

```sh
python3 firmware/head/private_config.py --board modular \
  --config config/local.toml --robot robot-01 \
  --server-ip "${MAC_LAN_IP:?Set MAC_LAN_IP to the Mac LAN IPv4}"
bash scripts/build_head.sh --board modular --private
```

Keep private configurations and binaries in the ignored build folder. Do not
flash a CoreS3 image onto this head, or either S3 image onto the classic WROOM.
