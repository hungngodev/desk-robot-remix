# Desk robot remix — five identical budget cores

Updated 2026-10-30 from the user's cheaper, five-unit direction. Each unit retains
camera, screen, microphone, speaker, movement, lift and grip. Only removable hats
or costumes differ. Shared Mac provides speech, vision and conversation.

## Cost and selection

Inventory correction, 2026-10-31: the user owns ESP32-WROOM-32 boards and **no
ESP32-S3**. The earlier pasted N8R8 statement was incorrect. Keep an S3/camera
head as a provisional purchase, not an owned part. The WROOM remains usable as
the body controller; do not flash S3 head firmware onto it. Uno/Pico boards do
not supply the missing S3 camera-head hardware or expand the WROOM's RAM.

First prototype delivered cap **$50**, using one owned WROOM and a usable owned
USB power bank. [Parts target](hardware/parts.md): **$36.88 before shipping/tax**,
with three allowances. The $7.11 S3/camera listing is a procurement candidate,
**not qualified for the compiled Freenove firmware**. Check its schematic/GPIO,
programming and case fit before purchase. No delivered cart is complete.

Five times that target is $184.40 before order charges and any missing WROOMs or
power banks. Exact owned counts and five-unit quotes are unknown; do not assume
five free controllers/batteries. Build and validate one before buying multiples.
The old $117.33 retail BOM is archived, not the active plan.

## Existing sources and minimal changes

- [SMARS chassis/tracks](https://www.thingiverse.com/thing:2662828): keep two N20
  geared motors and original drivetrain; no TT/servo drivetrain redesign.
- [Bluino gripper](https://www.thingiverse.com/thing:4253681), linked SMARS lift:
  two ordinary positional SG90 servos, one lift and one grip. Actual loaded
  performance on flat keys and wrapped candy remains unproven.
- [EVA Robot case](https://www.thingiverse.com/thing:7319190/files): original 3MF
  saved; SH1106 1.3-inch monochrome OLED, S3 camera board, INMP441, MAX98357 and
  speaker. Existing mounts need measured checks; emotion symbols/text initially.
- [Xiaozhi firmware](https://github.com/78/xiaozhi-esp32) and
  [server](https://github.com/xinnan-tech/xiaozhi-esp32-server): reuse camera,
  display, audio and protocol drivers. [Verdure UART/MCP approach](https://github.com/maker-community/VerdureBuddyRover/blob/main/docs/xiaozhi-mcp-serial-integration.md)
  links head to WROOM; bounded drive/lift/grip/stop/status commands already added.
- Mac: Ollama/Qwen3, SenseVoice, Kokoro and YOLO-World/OpenCV. Full model-provider
  and real-hardware bring-up still pending; mock demonstrations are labeled.

Small brackets, spacers, jaw tips, camera-aperture corrections and removable
cosmetics are permitted. Preserve chassis/mechanism/shell and source licenses.
Fusion MCP must be connected and the live design inspected before CAD editing.
No geometry edits, new PCB, whole chassis or new arm are part of this phase.

## Build order and acceptance

1. Complete exact head-board qualification, actual power-bank rating/load/fit,
   speaker mount, component clearances and delivered prototype cost under $50.
2. Print one SG90 fit part and the original gripper/lift; test real flat keys and
   candy. Adjust only small clearances/tips if necessary.
3. Bring up one head's OLED, camera, microphone and speaker; assemble the rover,
   test power/current/temperature and loss-of-control stop on stands.
4. Calibrate the fixed camera, enable bounded supervised approach/alignment and
   visible lift verification in a flat contained area, away from desk edges.
5. Require at least 8/10 physical pickups per category (flat key, candy), with
   measured lift, hold and controlled placement; log failures and assistance.
6. Duplicate the validated core four times. Give every head a unique identity,
   token, address and device ID; measure calibration per robot. Fit costumes
   without covering camera/audio/screen/USB or restricting gripper travel.
7. Verify routing and stops per robot, then conversations/games across five:
   one speaker at a time, digital peer transcripts, **ten utterances total** by
   default for five (two rounds). Pairs retain a six-utterance default/cap.
   Conversation time limit is five minutes; test stop/disconnect cleanup.

## Progress

- [x] Project organized at `/Users/hung/Documents/coding/desk-robot-remix`.
- [x] Pinned upstream sources and original body/lift/gripper/head print files saved.
- [x] Body firmware and Freenove-based modular-head overlay compiled previously.
- [x] Cheaper SG90/N20/driver quotes recorded; [ten-check audit](docs/budget-audit.md)
  distinguishes software/source evidence from unresolved hardware checks.
- [x] Five-robot configuration, bounded conversation, per-head private settings
  and append-only missing credential setup implemented; existing tokens preserved.
- [ ] Cheap head board qualified for the compiled target or a small verified pin adapter.
- [ ] Delivered basket and owned bank/controller quantities confirmed.
- [ ] One physical robot assembled, calibrated and accepted.
- [ ] Four duplicates built and all-five physical interaction tested.

Simulation is not a successful physical pickup or playback test. Preserve the
500 ms watchdog, 250 ms drive bound, operator permits and disarmed hardware
configuration. No automatic purchases, flashing or publishing.
