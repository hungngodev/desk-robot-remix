#include "ServoCenterBenchGate.h"
#include <Arduino.h>

#include <cassert>
#include <cstdint>

using Gate = desk_robot::ServoCenterBenchGate;

namespace servo_bench_fake {
std::uint32_t clock_ms = 0, attached_at = 0, detached_at = 0;
int attached_pin = -1;
unsigned writes = 0;
}
FakeServoSerial Serial;
#include "../src/servo_center_bench.cpp"

static Gate::InputResult feed_line(Gate& bench, const char* command,
                                   std::uint32_t now, bool ready) {
  for (; *command; ++command) {
    assert(bench.feed(*command, now, ready) == Gate::InputResult::Incomplete);
  }
  return bench.feed('\n', now, ready);
}

static void test_out_of_order_steps() {
  using Channel = Gate::Channel;
  using Result = Gate::InputResult;
  Gate bench;
  assert(feed_line(bench, "close", 0, true) == Result::Rejected);
  assert(feed_line(bench, "CLOSE", 0, true) == Result::Rejected);
  assert(bench.active() == Channel::None);
  assert(!bench.already_used(Channel::Grip));
  // Failed PWM setup is not a recoverable USB command or a consumed pulse.
  assert(feed_line(bench, "CENTER GRIP", 1, false) == Result::Rejected);
  assert(feed_line(bench, "rearm", 2, false) == Result::Rejected);
  assert(feed_line(bench, "REARM", 3, false) == Result::Rejected);
  assert(feed_line(bench, "CENTER LIFT", 4, false) == Result::Rejected);
  assert(bench.active() == Channel::None);
  assert(!bench.already_used(Channel::Lift));
  assert(!bench.already_used(Channel::Grip));
  // A separate ready fixture can center; rejected commands never extend it.
  Gate ready;
  assert(feed_line(ready, "CENTER GRIP", 100, true) == Result::Started);
  assert(feed_line(ready, "CLOSE", 101, true) == Result::Rejected);
  assert(feed_line(ready, "REARM", 499, true) == Result::Rejected);
  assert(ready.active() == Channel::Grip);
  assert(!ready.should_detach(499));
  assert(ready.complete(500));
  assert(feed_line(ready, "REARM", 501, true) == Result::Rejected);
  assert(feed_line(ready, "CENTER GRIP", 502, true) == Result::Rejected);
  assert(ready.active() == Channel::None);
  assert(ready.already_used(Channel::Grip));
  assert(!ready.already_used(Channel::Lift));
}

static void test_live_loop() {
  using namespace servo_bench_fake;
  setup();
  Serial.feed("CLOSE\nREARM\n");
  loop();
  assert(attached_pin == -1 && writes == 0);
  Serial.feed("CENTER LIFT\r\n");
  loop();
  assert(attached_pin == body_pins::kLiftServo);
  assert(Serial.blocking_prints == 0 && clock_ms == 0);
  Serial.feed(std::string(5000, '\n'));
  // Even when the clock advances *within* a slice of RX bytes, detach
  // at the deadline rather than at the end of that slice.
  clock_ms = 390;
  Serial.rx_read_ms = 1;
  loop();
  assert(attached_pin == -1 && detached_at - attached_at == 400);
  assert(Serial.blocking_prints == 0);
  assert(Serial.rx.size() == 5000 - Gate::kMaxSerialBytesPerPoll);
  Serial.rx.clear();
  Serial.rx_read_ms = 0;
  Serial.feed("CEN\rTER GRIP\nCENTER GRIP\r\r\n");
  loop();
  assert(attached_pin == -1 && writes == 1);
  Serial.feed(std::string(80, 'X') + "CENTER GRIP\n");
  while (!Serial.rx.empty()) loop();
  assert(attached_pin == -1 && writes == 1);
  Serial.feed("CENTER GRIP\n");
  loop();
  assert(attached_pin == body_pins::kGripServo && writes == 2);
  clock_ms = attached_at + Gate::kCenterWindowMs;
  loop();
  assert(attached_pin == -1 && detached_at - attached_at == 400);
  Serial.feed("CENTER LIFT\nCENTER GRIP\n");
  loop();
  assert(attached_pin == -1 && writes == 2);
  // Restore TX after saturation: no partial or fabricated frames.
  for (unsigned i = 0; i < 16; ++i) {
    Serial.free = 7;
    loop();
  }
  assert(Serial.blocking_prints == 0);
}

int main() {
  // Production and hornless bench share the nominal 50 Hz duty mapping.
  // These are commanded values, never fitted horn travel evidence.
  static_assert(body_pins::servo_duty_for_degrees(
      60, body_pins::kServoMinUs, body_pins::kServoMaxUs) == 4367);
  static_assert(body_pins::servo_duty_for_degrees(
      90, body_pins::kServoMinUs, body_pins::kServoMaxUs) == 4915);
  static_assert(body_pins::servo_duty_for_degrees(
      120, body_pins::kServoMinUs, body_pins::kServoMaxUs) == 5459);
  assert(center_duty() == 4915U);
  // Even a continuously refilled USB RX queue leaves each loop iteration
  // bounded so deadline polling cannot be starved by parser throughput.
  assert(Gate::serial_budget(0) == 0U);
  assert(Gate::serial_budget(1) == 1U);
  assert(Gate::serial_budget(31) == 31U);
  assert(Gate::serial_budget(32) == 32U);
  assert(Gate::serial_budget(33) == 32U);
  assert(Gate::serial_budget(1000000) == 32U);

  Gate gate;
  assert(gate.active() == Gate::Channel::None);
  assert(!gate.request(nullptr, 0));
  assert(!gate.request("", 0));
  assert(!gate.request("CENTER", 0));
  assert(!gate.request("CENTER BOTH", 0));
  assert(!gate.request("CENTER LIFT 95", 0));
  assert(!gate.request("center lift", 0));
  assert(!gate.request("CENTER LIFT\n", 0));
  assert(!gate.already_used(Gate::Channel::Lift));
  assert(!gate.already_used(Gate::Channel::None));

  assert(gate.request("CENTER LIFT", 100));
  assert(gate.active() == Gate::Channel::Lift);
  assert(gate.already_used(Gate::Channel::Lift));
  assert(!gate.request("CENTER GRIP", 101)); // never simultaneous
  assert(!gate.should_detach(499));
  assert(!gate.complete(499));
  assert(gate.should_detach(500));
  assert(gate.complete(500));
  assert(gate.active() == Gate::Channel::None);
  assert(!gate.complete(501));
  assert(!gate.request("CENTER LIFT", 502)); // one lift pulse per boot
  assert(gate.request("CENTER GRIP", 502));
  assert(gate.active() == Gate::Channel::Grip);
  assert(gate.already_used(Gate::Channel::Grip));
  assert(!gate.request("CENTER GRIP", 503));
  assert(gate.complete(902));
  assert(!gate.request("CENTER GRIP", 903));

  // Millis rollover is safe; a delayed loop expires, never extends power.
  Gate wrapped;
  assert(wrapped.request("CENTER LIFT", 0xfffffff0U));
  assert(!wrapped.should_detach(0x0000017fU));
  assert(wrapped.should_detach(0x00000180U));
  assert(wrapped.complete(0x00000180U));
  assert(wrapped.request("CENTER GRIP", 0x00000181U));
  assert(!wrapped.should_detach(0x00000182U));
  assert(wrapped.should_detach(0x00000311U));
  assert(wrapped.complete(0x00000311U));

  // Nothing automatically starts after idle or expiry.
  assert(wrapped.active() == Gate::Channel::None);
  assert(!wrapped.should_detach(0x00000400U));
  test_out_of_order_steps();
  test_live_loop();
  return 0;
}
