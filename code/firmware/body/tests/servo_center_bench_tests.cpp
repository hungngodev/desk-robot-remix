#include "ServoCenterBenchGate.h"
#include <Arduino.h>

#include <cstdlib>
#include <cstdint>
#include <limits>

#define CHECK(expr) do { if (!(expr)) std::abort(); } while (0)

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
    CHECK(bench.feed(*command, now, ready) == Gate::InputResult::Incomplete);
  }
  return bench.feed('\n', now, ready);
}

static void test_out_of_order_steps() {
  using Channel = Gate::Channel;
  using Result = Gate::InputResult;
  Gate bench;
  CHECK(feed_line(bench, "close", 0, true) == Result::Rejected);
  CHECK(feed_line(bench, "CLOSE", 0, true) == Result::Rejected);
  CHECK(bench.active() == Channel::None);
  CHECK(!bench.already_used(Channel::Grip));
  // Failed PWM setup is not a recoverable USB command or a consumed pulse.
  CHECK(feed_line(bench, "CENTER GRIP", 1, false) == Result::Rejected);
  CHECK(feed_line(bench, "rearm", 2, false) == Result::Rejected);
  CHECK(feed_line(bench, "REARM", 3, false) == Result::Rejected);
  CHECK(feed_line(bench, "CENTER LIFT", 4, false) == Result::Rejected);
  CHECK(bench.active() == Channel::None);
  CHECK(!bench.already_used(Channel::Lift));
  CHECK(!bench.already_used(Channel::Grip));
  // A separate ready fixture can center; rejected commands never extend it.
  Gate ready;
  CHECK(feed_line(ready, "CENTER GRIP", 100, true) == Result::Started);
  CHECK(feed_line(ready, "CLOSE", 101, true) == Result::Rejected);
  CHECK(feed_line(ready, "REARM", 499, true) == Result::Rejected);
  CHECK(ready.active() == Channel::Grip);
  CHECK(!ready.should_detach(499));
  CHECK(ready.complete(500));
  CHECK(feed_line(ready, "REARM", 501, true) == Result::Rejected);
  CHECK(feed_line(ready, "CENTER GRIP", 502, true) == Result::Rejected);
  CHECK(ready.active() == Channel::None);
  CHECK(ready.already_used(Channel::Grip));
  CHECK(!ready.already_used(Channel::Lift));
}

static void test_live_loop() {
  using namespace servo_bench_fake;
  setup();
  Serial.feed("CLOSE\nREARM\n");
  loop();
  CHECK(attached_pin == -1 && writes == 0);
  Serial.feed("CENTER LIFT\r\n");
  loop();
  CHECK(attached_pin == body_pins::kLiftServo);
  CHECK(Serial.blocking_prints == 0 && clock_ms == 0);
  Serial.feed(std::string(5000, '\n'));
  // Even when the clock advances *within* a slice of RX bytes, detach
  // at the deadline rather than at the end of that slice.
  clock_ms = 390;
  Serial.rx_read_ms = 1;
  loop();
  CHECK(attached_pin == -1 && detached_at - attached_at == 400);
  CHECK(Serial.blocking_prints == 0);
  CHECK(Serial.rx.size() == 5000 - Gate::kMaxSerialBytesPerPoll);
  Serial.rx.clear();
  Serial.rx_read_ms = 0;
  Serial.feed("CEN\rTER GRIP\nCENTER GRIP\r\r\n");
  loop();
  CHECK(attached_pin == -1 && writes == 1);
  Serial.feed(std::string(80, 'X') + "CENTER GRIP\n");
  while (!Serial.rx.empty()) loop();
  CHECK(attached_pin == -1 && writes == 1);
  Serial.feed("CENTER GRIP\n");
  loop();
  CHECK(attached_pin == body_pins::kGripServo && writes == 2);
  clock_ms = attached_at + Gate::kCenterWindowMs;
  loop();
  CHECK(attached_pin == -1 && detached_at - attached_at == 400);
  Serial.feed("CENTER LIFT\nCENTER GRIP\n");
  loop();
  CHECK(attached_pin == -1 && writes == 2);
  // Restore TX after saturation: no partial or fabricated frames.
  for (unsigned i = 0; i < 16; ++i) {
    Serial.free = 7;
    loop();
  }
  CHECK(Serial.blocking_prints == 0);
}

static void test_extreme_pulse_requests() {
  using namespace body_pins;
  const int low = std::numeric_limits<int>::min();
  const int high = std::numeric_limits<int>::max();
  const int requests[] = {low, -1, 0, 999, 1000, 1500, 2000, 2001, 5000, high};
  const unsigned expected[] = {3276, 3276, 3276, 3276, 3276,
                               4915, 6553, 6553, 6553, 6553};
  for (unsigned i = 0; i < sizeof(requests) / sizeof(requests[0]); ++i) {
    CHECK(servo_duty_for_microseconds(requests[i], kServoMinUs, kServoMaxUs) ==
           expected[i]);
  }
  CHECK(servo_duty_for_degrees(low, kServoMinUs, kServoMaxUs) == 3276U);
  CHECK(servo_duty_for_degrees(-1, kServoMinUs, kServoMaxUs) == 3276U);
  CHECK(servo_duty_for_degrees(0, kServoMinUs, kServoMaxUs) == 3276U);
  CHECK(servo_duty_for_degrees(180, kServoMinUs, kServoMaxUs) == 6553U);
  CHECK(servo_duty_for_degrees(5000, kServoMinUs, kServoMaxUs) == 6553U);
  CHECK(servo_duty_for_degrees(high, kServoMinUs, kServoMaxUs) == 6553U);
  CHECK(servo_duty_for_degrees(high, low, high) == 0U);
  CHECK(servo_duty_for_microseconds(1500, 2000, 1000) == 0U);
  CHECK(servo_duty_for_microseconds(1500, 1000, 1000) == 0U);
  CHECK(servo_duty_for_microseconds(1500, 0, 2000) == 0U);
  CHECK(servo_duty_for_microseconds(1500, 1000, 20000) == 0U);
  CHECK(servo_duty_for_microseconds(1500, 1000, high) == 0U);
  unsigned previous = 3276U;
  for (int degrees = 0; degrees <= 180; ++degrees) {
    const unsigned duty = servo_duty_for_degrees(degrees, kServoMinUs, kServoMaxUs);
    CHECK(duty >= previous && duty <= 6553U);
    CHECK(duty - previous <= 20U);
    previous = duty;
  }
}

int main() {
  test_extreme_pulse_requests();
  // Production and hornless bench share the nominal 50 Hz duty mapping.
  // These are commanded values, never fitted horn travel evidence.
  static_assert(body_pins::servo_duty_for_degrees(
      60, body_pins::kServoMinUs, body_pins::kServoMaxUs) == 4367, "60-degree nominal duty changed");
  static_assert(body_pins::servo_duty_for_degrees(
      90, body_pins::kServoMinUs, body_pins::kServoMaxUs) == 4915, "90-degree nominal duty changed");
  static_assert(body_pins::servo_duty_for_degrees(
      120, body_pins::kServoMinUs, body_pins::kServoMaxUs) == 5459, "120-degree nominal duty changed");
  CHECK(center_duty() == 4915U);
  // Even a continuously refilled USB RX queue leaves each loop iteration
  // bounded so deadline polling cannot be starved by parser throughput.
  CHECK(Gate::serial_budget(0) == 0U);
  CHECK(Gate::serial_budget(1) == 1U);
  CHECK(Gate::serial_budget(31) == 31U);
  CHECK(Gate::serial_budget(32) == 32U);
  CHECK(Gate::serial_budget(33) == 32U);
  CHECK(Gate::serial_budget(1000000) == 32U);

  Gate gate;
  CHECK(gate.active() == Gate::Channel::None);
  CHECK(!gate.request(nullptr, 0));
  CHECK(!gate.request("", 0));
  CHECK(!gate.request("CENTER", 0));
  CHECK(!gate.request("CENTER BOTH", 0));
  // Boundary ownership for raw microsecond rejection vs clamping:
  // - USB bench parser (ServoCenterBenchGate::feed / request) owns command
  //   rejection and accepts only exact "CENTER LIFT" / "CENTER GRIP" lines.
  // - Full-body UART path (BodyControl::execute) accepts integer degrees and
  //   enforces measured mechanical endstops; no raw-us interface exists.
  // - ServoPulse.h owns span validation (valid_servo_pulse_span) and clamps
  //   internal pulse_us values (499 -> min_us, 2501 -> max_us); endpoint
  //   clamping is neither external command rejection nor fitted travel safety.
  for (const char* rejected_raw_pulse : {
           "CENTER LIFT 499", "CENTER LIFT 2501",
           "CENTER GRIP 499", "CENTER GRIP 2501",
           "PULSE 499", "PULSE 2501", "499", "2501",
       }) {
    Gate fed;
    CHECK(!gate.request(rejected_raw_pulse, 0));
    CHECK(feed_line(fed, rejected_raw_pulse, 0, true) ==
          Gate::InputResult::Rejected);
    CHECK(fed.active() == Gate::Channel::None);
    CHECK(!fed.already_used(Gate::Channel::Lift));
    CHECK(!fed.already_used(Gate::Channel::Grip));
  }
  CHECK(!gate.request("CENTER LIFT 95", 0));
  CHECK(!gate.request("center lift", 0));
  CHECK(!gate.request("CENTER LIFT\n", 0));
  CHECK(!gate.already_used(Gate::Channel::Lift));
  CHECK(!gate.already_used(Gate::Channel::None));

  CHECK(gate.request("CENTER LIFT", 100));
  CHECK(gate.active() == Gate::Channel::Lift);
  CHECK(gate.already_used(Gate::Channel::Lift));
  CHECK(!gate.request("CENTER GRIP", 101)); // never simultaneous
  CHECK(!gate.should_detach(499));
  CHECK(!gate.complete(499));
  CHECK(gate.should_detach(500));
  CHECK(gate.complete(500));
  CHECK(gate.active() == Gate::Channel::None);
  CHECK(!gate.complete(501));
  CHECK(!gate.request("CENTER LIFT", 502)); // one lift pulse per boot
  CHECK(gate.request("CENTER GRIP", 502));
  CHECK(gate.active() == Gate::Channel::Grip);
  CHECK(gate.already_used(Gate::Channel::Grip));
  CHECK(!gate.request("CENTER GRIP", 503));
  CHECK(gate.complete(902));
  CHECK(!gate.request("CENTER GRIP", 903));

  // Millis rollover is safe; a delayed loop expires, never extends power.
  Gate wrapped;
  CHECK(wrapped.request("CENTER LIFT", 0xfffffff0U));
  CHECK(!wrapped.should_detach(0x0000017fU));
  CHECK(wrapped.should_detach(0x00000180U));
  CHECK(wrapped.complete(0x00000180U));
  CHECK(wrapped.request("CENTER GRIP", 0x00000181U));
  CHECK(!wrapped.should_detach(0x00000182U));
  CHECK(wrapped.should_detach(0x00000311U));
  CHECK(wrapped.complete(0x00000311U));

  // Nothing automatically starts after idle or expiry.
  CHECK(wrapped.active() == Gate::Channel::None);
  CHECK(!wrapped.should_detach(0x00000400U));
  test_out_of_order_steps();
  test_live_loop();
  return 0;
}
