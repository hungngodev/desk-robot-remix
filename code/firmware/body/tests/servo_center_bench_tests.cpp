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

static void test_live_loop() {
  using namespace servo_bench_fake;
  setup();
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
  test_live_loop();
  return 0;
}
