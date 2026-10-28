# Desk-robot remix — updated with Verdure

Accepted implementation plan, 2026-10-28. This is an experimental physical robot;
software verification and physical acceptance must be reported separately.

## Cost and project folder

Estimate: **$100–140 per robot before shipping and tax**. Keep a **$150 spending
cap for the first robot**. Do not place orders automatically.

| Item | Estimated cost |
| --- | ---: |
| CoreS3 Lite (https://shop.m5stack.com/products/m5stack-cores3-lite-esp32s3-iot-dev-kit) | $44.90 at planning verification |
| Existing ESP32-WROOM-32 | $0 |
| Motors, servos, driver, power system, wiring, fasteners, filament | $55–95 allowance |
| Total | About $100–140 before shipping and tax |

Two robots: approximately $200–280 before shipping/tax, sharing the existing Mac.
Prices beyond the head are allowances until the actual basket is checked.

Project location: `/Users/hung/Documents/coding/desk-robot-remix`.

## Existing projects to combine

- Body: SMARS, https://www.thingiverse.com/thing:2662828.
- Lift and grip: Bluino, https://www.thingiverse.com/thing:4253681.
- Head: CoreS3 Lite, with display, camera, microphones and speaker.
- Conversation: https://github.com/78/xiaozhi-esp32 and
  https://github.com/xinnan-tech/xiaozhi-esp32-server.
- Motor integration: adapt Verdure's UART/MCP bridge,
  https://github.com/maker-community/VerdureBuddyRover/blob/main/docs/xiaozhi-mcp-serial-integration.md,
  for CoreS3/WROOM-32 and extend it with lift and gripper controls.

Organize upstream sources, firmware, laptop software, CAD, assembly notes and test
results inside this folder. Pin upstream revisions and preserve attribution.

## Integration and small CAD changes

- Reuse camera, display and audio drivers.
- Connect head and body through 3.3 V UART, with bounded drive/lift/grip commands,
  stop/status and a 500 ms loss-of-control stop.
- Run Ollama/Qwen3, SenseVoice, Kokoro and YOLO-World/OpenCV on the Mac.
- Permit brackets, spacers, clearances and replaceable fingertips. Preserve the
  original chassis, drivetrain, lift and rack-and-pinion mechanism.
- Use a battery-appropriate regulated supply; 2S-to-5 V requires a buck converter.

## Build order and acceptance

1. Create this folder, save the plan and prepare a priced parts list within the cap.
2. Print/test the gripper with actual keys (including a flat key) and candy;
   make small measured CAD corrections if needed.
3. Assemble one rover; verify movement, stable power, stop behavior and head.
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
- [x] Parts allowance list and first-build guide prepared ($123.25 target; final motor/battery quotes and fit remain unresolved).
- [x] Body firmware and stop behavior verified in software; hardware stop measurement pending.
- [x] CoreS3 UART/MCP integration built; physical peripherals untested.
- [x] Laptop control/vision/conversation logic verified in simulation; physical/model-provider tests pending.
- [ ] Full local AI stack installed and tested with real devices.
- [ ] Physical gripper, power, camera and autonomous pickup acceptance performed.
- [ ] Second physical robot acceptance performed.
