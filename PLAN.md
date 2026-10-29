# Desk-robot remix — modular EVA head and Verdure integration

Accepted implementation plan, updated 2026-10-29 after choosing separate head
components and an existing printed case. This is an experimental physical robot;
software verification and physical acceptance must be reported separately.

## Cost and project folder

Current parts estimate: **$117.33 per robot before shipping and tax**, including
unquoted allowances. Keep the **$150 first-robot cap**, including order charges.
Do not place orders automatically. The head is now assembled from modules;
CoreS3 Lite is no longer on the active shopping list.

| Item | Estimated cost |
| --- | ---: |
| Freenove S3 camera board + OLED + microphone + amplifier + speaker | $38.98 midpoint; head range $37.98–39.98 |
| Existing ESP32-WROOM-32 | $0 |
| Motors, servos, driver, power system, wiring, fasteners, filament | $78.35 mix of observed prices and allowances |
| Total | $117.33 planning midpoint before shipping and tax |

Two identical robots: approximately $234.66 at these allowances before
shipping/tax, sharing the Mac. Buy the second only after the first passes. The
parts list is not a delivered shopping quote; fit and some SKUs are unresolved.

Project location: `/Users/hung/Documents/coding/desk-robot-remix`.

## Existing projects to combine

- Body: SMARS, https://www.thingiverse.com/thing:2662828.
- Lift and grip: Bluino, https://www.thingiverse.com/thing:4253681.
- Head: Freenove ESP32-S3 camera board, 1.3-inch SH1106 OLED, INMP441,
  MAX98357A and small speaker inside [EVA Robot's case](https://www.thingiverse.com/thing:7319190/files).
  [Saved case and component guide](docs/modular-head.md). The screen gives
  monochrome emotion symbols/text initially; smooth eye animation is a later
  adapter. Exact display/camera/speaker fit needs checking.
- Conversation: https://github.com/78/xiaozhi-esp32 and
  https://github.com/xinnan-tech/xiaozhi-esp32-server.
- Motor integration: adapt Verdure's UART/MCP bridge,
  https://github.com/maker-community/VerdureBuddyRover/blob/main/docs/xiaozhi-mcp-serial-integration.md,
  for the S3 head/WROOM-32 and extend it with lift and gripper controls.

Organize upstream sources, firmware, laptop software, CAD, assembly notes and test
results inside this folder. Pin upstream revisions and preserve attribution.

## Integration and small CAD changes

- Reuse existing camera, display and audio drivers; use existing mechanisms and
  cases. Create parts/code from scratch only where the remix needs a small adapter.
- Connect head and body through 3.3 V UART, with bounded drive/lift/grip commands,
  stop/status and a 500 ms loss-of-control stop.
- Run Ollama/Qwen3, SenseVoice, Kokoro and YOLO-World/OpenCV on the Mac.
- Permit brackets, spacers, clearances and replaceable fingertips. Preserve the
  original chassis, drivetrain, lift, rack-and-pinion mechanism and EVA shell.
  Check internal board fit and add a removable head mount; no new case or PCB.
- Use a battery-appropriate regulated supply; 2S-to-5 V requires a buck converter.

## Build order and acceptance

1. Save the plan, parts list and existing case. Resolve exact camera/speaker,
   display mount, delivered cost and clearances before a complete order.
2. Print/test the gripper with actual keys (including a flat key) and candy;
   make small measured CAD corrections if needed.
3. Use the compiled modular-head configuration with existing Xiaozhi drivers;
   assemble one rover and verify movement, stable power, stop behavior and head.
4. Add detection, camera-guided approach/alignment, gripping, lifting and visual
   verification of pickup in a clear, bounded, flat area.
5. Physical target: at least 8 successful pickups in 10 trials **per category**.
6. Build a second unit only after the first passes. Verify separate identities,
   correctly routed commands and one speaker at a time, capped at six exchanges.

## Assumptions and boundaries

Keys and candy are required targets, not replaced by blocks. Autonomous pickup
is not proven by existing sources. No fabricated physical test results, automatic
hardware purchases, flashing unverified hardware, major mechanical redesign or
new PCB design. Fusion MCP must be connected before model editing. Original SMARS
CAD has noncommercial restrictions; preserve each source's actual license.

## Progress

- [x] Project folder created and accepted plan saved.
- [x] Upstream revisions and licenses recorded.
- [x] Separate-component head chosen and parts list revised ($117.33 midpoint; exact camera/speaker, motor/battery quotes and fit remain unresolved).
- [x] Original EVA head 3MF saved, four meshes/dimensions/hash/license inspected.
- [x] Original gripper/lift and matching screwless SMARS print files saved with source hashes, licenses and assembly documents; no geometry edits or slicing.
- [x] Body firmware and stop behavior verified in software; hardware stop measurement pending.
- [x] Previous CoreS3 UART/MCP integration built as a reference; this does not validate the modular head.
- [x] Laptop control/vision/conversation logic verified in simulation; physical/model-provider tests pending.
- [x] Modular S3 head configuration and fresh-JPEG adapter compiled; camera I²C0/OLED I²C1 selected and guarded; 65 focused software checks pass.
- [ ] Modular S3 head camera, OLED, microphone, speaker and UART bench-tested on actual modules.
- [ ] Actual head module fit and removable head-to-SMARS bracket checked.
- [ ] Full local AI stack installed and tested with real devices.
- [ ] Physical gripper, power, camera and autonomous pickup acceptance performed.
- [ ] Second physical robot acceptance performed.
