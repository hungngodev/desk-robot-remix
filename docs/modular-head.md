# Small-component head — Sense candidate

Updated 2026-11-03. Reuse the owned **0.96-inch SSD1306 OLED** and saved EVA shell.
Candidate new board: [Seeed XIAO ESP32S3 Sense, SKU 113991115](https://www.seeedstudio.com/XIAO-ESP32S3-Sense-p-5639.html),
**$13.99**, including camera and digital microphone. Add the $1.95 MAX98357
amplifier and $0.29 speaker: **$16.23 of new head electronics**, excluding
shipping/tax/mount parts. [Quote and specification evidence](research/2026-11-03-head-budget.md).
No S3 is owned. This is not the bare XIAO or an expansion-board-only offer.

## Reuse drivers, change the board configuration

The [official Sense guide](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/)
specifies 8 MB flash / 8 MB PSRAM and a PDM microphone. Current stock may contain
OV3660 or OV5640 AF; verify actual delivered sensor, cable and lens housing. The
camera/microphone stack is about 21 × 17.8 × 15 mm. No new INMP441 is required.

The proposed head reuses pinned Xiaozhi camera, SSD1306, PDM input and I²S output
components. It needs a **new Sense board target**, pin map and 8 MB partition/
asset configuration. The existing modular build is Freenove 16 MB + SH1106 +
INMP441 I²S; it cannot be flashed to Sense. CoreS3 and WROOM binaries are also
incompatible. No Sense configuration/build/physical test has happened yet.

Preliminary header budget: OLED2 + amplifier3 + UART2 = seven signals, with
camera/PDM internally connected. This is not a validated allocation. Inspect the
actual schematic, reserve camera/mic, USB, flash/PSRAM and boot functions, then
select safe pins. Disable SD where pins are reused. Do not copy video GPIO1/2
sensor wiring or the old Freenove UART pin numbers blindly. The body owns all
cliff sensors; the head owns OLED, so no shared two-master bus is required.

The earlier 2,500,528-byte app suggests an 8 MB OTA-slot build may be feasible,
but its full merged image is not an 8 MB Sense image. Select correct partitions,
reduce/measure assets as required and build/check actual sizes; never truncate a
binary. Firmware installation/build scripts do **not** yet accept `--board sense`.
[Implementation milestone](plans/2026-11-03-active-desk-pet.md#milestone-4--sense-head-and-original-face).

## Face and interaction

The OLED is monochrome, not a color LCD. Begin with original blink/gaze/listening/
speaking/rest/blocked expressions. [RoboEyes](https://github.com/FluxGarage/RoboEyes)
is a strong **GPL-3.0** candidate, with an Arduino/GFX graphics layer; a small
ESP-IDF drawing/timing adapter is needed. Tech Talkies' custom-face fork is also
GPL-3.0. Neither is integrated; resolve dependency/notices/source obligations
before copying. Do not mark a combined GPL firmware MIT-only.

One task should own OLED updates; animation must yield and never delay audio,
UART stop or camera handling. Blink/idle behavior can continue locally while the
Mac provides higher-level character state. Use an existing button first; an
optional touch pad/TTP223 is unquoted until pins, mounting and wiring are known.
Head patting does not locate the user or navigate back to them.

## Existing case and small changes

The [EVA original](../cad/originals/eva-head/README.md) is saved unchanged under
CC BY-SA 4.0. Four meshes are in assembly coordinates, overall approximately
74 × 48 × 48.8 mm; screen opening about 35 × 19.6 mm and camera opening about
4.4 mm. Arrange parts separately before slicing.

The opening was not designed for the owned SSD1306/Sense combination. Measure
actual OLED PCB/glass and lens position. Expected small remixes: a replaceable
bezel insert, camera/board spacer, speaker retention and removable rover bracket.
Keep lens, mic, speaker, USB and antenna clear; check full arm sweep and bank
weight/stability. If the combination needs a new shell/chassis, revisit the
choice rather than silently enlarging scope. Do not cut display glass or PCB.

Keep camera pose fixed relative to jaws for calibration. Check actual MG90S
pockets/horns and the stepper chassis lift interface before final head mounting.
No geometry edit or physical fit has passed. Fusion tools are exposed for future precision work; verify the live connection
and active design before touching geometry.

## Power/audio and staged bring-up

- Logic stays 3.3 V. Verify amplifier variant/pins and supply per its documentation.
  Speaker connects **SPK+ to SPK−**, neither output to GND. Limit output for the
  8 Ω / 1 W speaker; check acoustic port and cavity fit.
- Use a qualified power bank and separate rated actuator branches. Do not route
  motor current through head/body regulators or laptop USB.
- On USB with motors absent, verify screen, fresh camera capture, PDM recording,
  speaker/listening transition and head identity before joining UART TX/RX/GND.
- Only after hardware and local body interlock tests should the head command
  bounded motion. Mac handles speech/LLM/vision; no Uno/Pico/Pi needed.

## Preserved historical reference

`firmware/head/modular/` and [build.md](build.md) retain the previously compiled
Freenove N16R8 map: OLED38/39, INMP44142/41/40, amplifier14/21/47, UART2/1;
camera uses Freenove's stock signals, SCCB I²C0 and OLED I²C1. These are **not
Sense wiring instructions**. Native USB, octal PSRAM reservations and exact
module wiring remain board-specific. Preserve the historical build rather than
renaming it Sense or treating its successful compilation as new hardware proof.
