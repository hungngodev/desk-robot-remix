// Bench-only infrared docking beacon. This is NOT a charger controller.
// Reuse Arduino-IRremote v4.7.1 MIT NEC sender. A classic NEC frame is
// required by the WROOM's existing NecBurst.h decoder.
//
// Reference host: Arduino Nano ATmega328P, not the selected production dock.
// Digital pin D3 is a LOGIC signal for separate transistor / current-limited
// 940nm IR emitter channels. NEVER connect IR LEDs directly to the output.
// Both physically aimed channels must send the SAME frame simultaneously:
// the current WROOM DualIrEvidence pairs only identical complete codes.
// This firmware does not control charging contacts, battery, or motor permits.
#include <Arduino.h>
#include <stdint.h>
#define IR_SEND_PIN 3
#define NO_LED_SEND_FEEDBACK_CODE
#define IR_SEND_DUTY_CYCLE_PERCENT 30
#include <IRremote.hpp>

#ifndef DESK_ROBOT_DOCK_ID
#error Define DESK_ROBOT_DOCK_ID as the numbered physical dock (1..5)
#endif
static_assert(DESK_ROBOT_DOCK_ID >= 1 && DESK_ROBOT_DOCK_ID <= 5,
              "The five designated docks have IDs 1 through 5 only");

namespace {
constexpr uint8_t kAddress = 0x12;
// Match the classic 8-bit NEC address + complement and command + complement
// enforced by code/firmware/body/lib/TerminalIr/NecBurst.h.
// Distinct dock IDs are not, by themselves, authentication or docking permits.
constexpr uint8_t kCommand = static_cast<uint8_t>(0x30 + DESK_ROBOT_DOCK_ID);
constexpr uint32_t kQuietMs = 80;
uint32_t last_end_ms = 0;
bool sent = false;
}  // namespace

void setup() {
  // The external MOSFET gates REQUIRE separate passive pulldowns so the LEDs
  // remain off while the MCU boots, is resetting, or is unpowered.
  digitalWrite(IR_SEND_PIN, LOW);
  pinMode(IR_SEND_PIN, OUTPUT);
}

void loop() {
  // Unsigned elapsed time survives millis() rollover. Measure the quiet gap
  // from completion, not the scheduled start; never catch up missed bursts.
  if (sent && static_cast<uint32_t>(millis() - last_end_ms) < kQuietMs) return;
  // The upstream sender is synchronous for one full frame. Only the idle
  // interval is nonblocking. Never substitute unmodulated TinyIRSender mode.
  IrSender.sendNEC(kAddress, kCommand, 0);
  digitalWrite(IR_SEND_PIN, LOW);
  last_end_ms = millis();
  sent = true;
}
