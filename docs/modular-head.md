# Separate-component head with an existing case

This is the active head direction. Assemble small modules in EVA Robot's existing
printed shell, then mount that head on the SMARS/Bluino rover. Keep the owned
ESP32-WROOM-32 as the motor/lift/gripper controller. No custom PCB is planned.

The display is a **1.3-inch monochrome OLED for face graphics and text**. Stock
Xiaozhi OLED software shows emotion symbols and chat text. Smooth EVA-style
moving eyes need an additional animation adapter; that UI is not implemented.
Camera, listening, speech and laptop AI remain in scope. This choice changes
the earlier color LCD head; it does not remove vision or conversation.

## Components for one head

The [active budget list](../hardware/parts.md) now targets **$15.13 for head
electronics**, using generic modules. This includes a $7.11 S3/OV2640 bundle,
$2.98 four-pin SH1106 OLED, $2.09 INMP441, $1.95 MAX98357 and a $1 speaker allowance.
Shipping, exact speaker and mechanical fit are unresolved.

**The compiled target below remains the Freenove N16R8 reference.** The cheap
PCBFUN board has not been matched to its pin allocation or programming method.
Confirm every camera signal, free GPIO, PSRAM/flash marking, board outline,
USB/programming connection and camera lens position before ordering/flashing.
If mapping differs, first determine whether a small pin-only adapter fits the
available GPIO. No hardware driver rewrite is planned. The earlier $21.99
Freenove reference is above the current whole-robot cap when combined with the
remaining components; it is not the active budget purchase recommendation.

The budget OLED is ElectroPeak LCD-01-103, SH1106, 128×64, 1.3-inch, four-pin I²C,
35.4×33.5 mm PCB. Match actual mounting holes and pin order. The amplifier's
actual footprint and speaker cavity also need measurement. No SD card, touch
sensor, expansion/programming dock, CoreS3 or Adafruit Feather is budgeted; if
the chosen camera board requires a dock, include its real cost before selection.

The reference [EVA Robot hardware](https://github.com/Ksirailway-base/EVA-Robot/tree/c7ff17718a40d071b352e9894506c264578120c0)
uses a Freenove S3, OV3660 camera, SH1106, INMP441 and MAX98357A. Its source is a
case/module reference. Our existing Xiaozhi/Mac stack stays the conversation and
robot-control base; EVA's Windows server is not required.

## Case already saved

- [Original EVA-Robot.3mf](../cad/originals/eva-head/EVA-Robot.3mf).
- [Preview and print preparation](../cad/originals/eva-head/README.md).
- [Author's files](https://www.thingiverse.com/thing:7319190/files),
  Ksirailway-Base, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

The actual four meshes were inspected: assembled shell **74×48×48.8 mm**. The
screen opening is about **35×19.6 mm**, with an approximately **4.4 mm camera
opening** below it. Original geometry is unchanged. The file places parts in
assembly positions: separate/arrange them on the bed before slicing.

EVA does not specify exact display-PCB or speaker SKUs. The generic LCD-01-103
is a candidate, not a measured fit. Verify its holes/PCB against the shell. Do not substitute a
0.96-inch display or a larger eight-pin OLED assuming equal fit. Confirm selected
camera dimensions and alignment before ordering; the budget OV2640 is not the
OV3660 named in EVA's reference. Even the same sensor name does not guarantee the
same lens housing.

Expected small remixes are internal spacers, a camera-opening correction if
needed, and a removable EVA-to-SMARS mounting bracket. Check rover stability and
full gripper travel with the head in place. No compatible existing mounting
bracket was found. A major head/chassis redesign is outside this plan. Fusion MCP
must be connected and the active design checked before geometry editing.

## Configured pin allocation — hardware unverified

This allocation preserves the Freenove camera wiring, avoids octal-PSRAM pins,
and retains the same UART pair as the earlier head. A dedicated
`desk-robot-modular-s3` board configuration now implements it; real peripheral
tests are required before the wiring can be considered physically validated.

| Connection | S3 GPIO / setup |
| --- | --- |
| Camera | Freenove stock mapping: SIOD 4, SIOC 5, VSYNC 6, HREF 7, XCLK 15, PCLK 13; Y2–Y9 = 11, 9, 8, 10, 12, 18, 17, 16 |
| Camera SCCB | I²C controller 0, explicitly selected in Kconfig with the new I²C driver |
| OLED SDA / SCL | 38 / 39, **I²C controller 1**; 3.3 V power |
| INMP441 SCK / WS / SD | 42 / 41 / 40; L/R to GND, 3.3 V power |
| MAX98357A BCLK / LRC / DIN | 14 / 21 / 47; regulated 5 V power, common logic ground |
| Head UART TX / RX | 2 / 1 → WROOM RX16 / TX17; 115200 8N1, 3.3 V logic |
| Interaction button | Existing BOOT button, GPIO0 |
| Unused | SD-card slot; GPIO38–40 are assigned above, so leave the slot empty |

Reserve GPIO35–37 for octal PSRAM, GPIO19/20 for native USB and GPIO43/44 for
debug UART. Check the actual module marking and board pin labels. Freenove's
[GPIO notes](https://docs.freenove.com/projects/fnk0085/en/latest/fnk0085/codes/C/Preface.html)
and [camera example](https://github.com/Freenove/Freenove_ESP32_S3_WROOM_Board/blob/main/C/Sketches/Sketch_07.1_CameraWebServer/camera_pins.h)
are the hardware references.

Do not copy EVA's wiring table verbatim: it assigns OLED pins 36/37, which
conflict with the selected R8 board's PSRAM. Its speaker-ground instruction is
also incorrect for MAX98357A. Connect the speaker **between SPK+ and SPK−**;
neither speaker output goes to GND. See the
[amplifier guide](https://learn.adafruit.com/adafruit-max98357-i2s-class-d-mono-amp/pinouts).
Use short audio wires, insulated joints and volume suitable for the speaker.

## Firmware reuse and remaining work

Reuse the pinned Xiaozhi `Esp32Camera`, SH1106/SSD1306 display support and
`NoAudioCodecSimplex` I²S audio. The existing `bread-compact-wifi-s3cam` and
`bread-compact-wifi` targets supply those pieces. No camera/audio driver or
speech engine needs to be written from scratch.

The overlay now has a unique `desk-robot-modular-s3` configuration, alongside the
earlier CoreS3 reference. Select it explicitly with `--board modular`; its ignored
build copy is `firmware/head/build/xiaozhi-modular`. The authenticated fresh-JPEG
adapter uses `Esp32Camera` and shares the capture/explain lock. The body protocol,
watchdog, authentication and laptop API remain unchanged. See
[build commands](build.md) and [verification evidence](../test-results/verification.md).

Camera SCCB is forced to I²C0 through Kconfig, with a compile guard; the camera
port field alone does not select its bus when SCCB pins are assigned. OLED uses
I²C1. The selected 16 MB flash supports the configured partition/assets layout.
Compilation does not establish actual sensor, display, audio or case fit. Do not
flash a CoreS3 binary onto Freenove, or either S3 binary onto the WROOM.

## Build sequence

1. Open the saved case; compare the display, camera, speaker and amplifier
   drawings against its mounts. Resolve exact camera/speaker choices and quote
   delivery from as few suppliers as practical.
2. Print/test the gripper with real keys/candy and print a head fit sample before
   the full rover. No physical fit or pickup trial has happened yet.
3. Build the dedicated modular-head configuration, then bring up screen, camera,
   microphone and speaker on USB with no actuators attached.
4. Connect the verified 3.3 V UART to the WROOM. Power motors/servos separately
   during bench tests; follow [body wiring and power](../hardware/wiring.md).
5. Fit a small removable head bracket, measure stability/camera pose, and run the
   existing pickup and multi-robot acceptance steps.
