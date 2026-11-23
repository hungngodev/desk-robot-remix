#include "WheelAngleCapture.h"

#include <cstdint>
#include <stdexcept>

using desk_robot::AngleRaw;
using desk_robot::WheelAngleCapture;
using Result = WheelAngleCapture::Result;

static void check(bool ok) {
  if (!ok) throw std::runtime_error("wheel angle capture contract failed");
}

static AngleRaw angle(std::uint16_t value, std::uint32_t sequence,
                      std::uint32_t acquisition_ms) {
  AngleRaw a{};
  a.present = a.valid = true;
  a.magnet_status = 0x20;
  a.angle = value;
  a.sample_seq = sequence;
  a.at_ms = acquisition_ms;
  return a;
}

static void replay_and_reverse() {
  WheelAngleCapture left, right;
  auto first = angle(4000, 1, 100);
  check(left.observe(first, 100) == Result::Unqualified);
  check(!left.continuous());
  // An unmeasured high-speed wheel is NOT made credible by a guess.
  check(!left.configure(15000, 150, 50));
  check(left.configure(4000, 150, 50));
  check(right.configure(4000, 150, 50));
  check(left.observe(first, 101) == Result::Baseline);
  check(right.observe(angle(20, 1, 100), 101) == Result::Baseline);
  check(left.observe(angle(12, 2, 150), 150) == Result::Delta);
  check(left.last_delta() == 108 && left.angular_counts() == 108);
  check(right.observe(angle(4080, 2, 150), 150) == Result::Delta);
  check(right.last_delta() == -36 && right.angular_counts() == -36);
  check(left.observe(angle(12, 2, 150), 151) == Result::Duplicate);
  check(left.angular_counts() == 108);
  check(left.observe(angle(9, 3, 200), 201) == Result::Delta);
  check(left.last_delta() == -3 && left.angular_counts() == 105);
  // A changed register without a new acquisition identity is a fault.
  check(left.observe(angle(500, 3, 200), 201) == Result::Invalid);
  check(!left.continuous() && left.angular_counts() == 0);
  check(left.observe(angle(9, 3, 200), 202) == Result::Invalid);
  check(left.observe(angle(30, 4, 250), 251) == Result::Baseline);
  check(left.angular_counts() == 0 && left.segment() == 2);
}

static void gaps_and_magnets() {
  WheelAngleCapture wheel;
  check(wheel.configure(2000, 200, 80));
  check(wheel.observe(angle(0, 41, 100), 100) == Result::Baseline);
  check(wheel.observe(angle(2048, 42, 200), 200) == Result::Invalid);
  check(wheel.observe(angle(2000, 43, 210), 210) == Result::Baseline);
  // New measured acquisition with an implausible speed cannot be unwrapped.
  check(wheel.observe(angle(0, 44, 220), 220) == Result::Invalid);
  check(wheel.observe(angle(1, 45, 230), 230) == Result::Baseline);
  auto absent = angle(2, 46, 240);
  absent.magnet_status = 0x00;
  check(wheel.observe(absent, 240) == Result::Invalid);
  check(wheel.observe(angle(2, 46, 240), 240) == Result::Baseline);
  // Failure invalidates continuity; the following sample cannot recover
  // prior distance, even though its acquisition is newer.
  check(wheel.angular_counts() == 0);
  check(wheel.observe(angle(100, 47, 600), 600) == Result::Invalid);
  check(wheel.observe(angle(101, 48, 620), 620) == Result::Baseline);
  check(wheel.observe(angle(105, 49, 630), 800) == Result::Invalid);
  check(wheel.observe(angle(106, 50, 700), 700) == Result::Baseline);
  check(wheel.segment() >= 3);
}

static void source_rollover_and_reset() {
  WheelAngleCapture wheel;
  check(wheel.configure(3000, 100, 60));
  check(wheel.observe(angle(4090, 0xfffffffeU, 0xfffffff0U), 0xfffffff1U) == Result::Baseline);
  check(wheel.observe(angle(10, 0xffffffffU, 0x20), 0x21) == Result::Delta);
  check(wheel.angular_counts() == 16);
  check(wheel.observe(angle(13, 1, 0x40), 0x41) == Result::Delta);
  check(wheel.angular_counts() == 19);
  // Exactly zero is a real millis() timestamp at rollover. It must not
  // invalidate a completed AS5600 conversion with a fresh sequence.
  WheelAngleCapture exact_wrap;
  check(exact_wrap.configure(3000, 100, 60));
  check(exact_wrap.observe(angle(4090, 99, 0xfffffff0U), 0xfffffff0U) ==
        Result::Baseline);
  check(exact_wrap.observe(angle(2, 100, 0U), 0U) == Result::Delta);
  check(exact_wrap.angular_counts() == 8);
  check(exact_wrap.observe(angle(8, 101, 0x20U), 0x20U) == Result::Delta);
  check(exact_wrap.angular_counts() == 14);
  // The default uninitialized reading must still be rejected.
  check(exact_wrap.observe(AngleRaw{}, 0x21U) == Result::Invalid);
  // A replay from before wrap cannot be a new wheel sample.
  check(wheel.observe(angle(1, 0xffffffffU, 0x20), 0x42) == Result::Invalid);
  wheel.reset_for_boot();
  check(!wheel.continuous());
  check(wheel.observe(angle(1, 1, 1), 1) == Result::Unqualified);
}

int main() {
  replay_and_reverse();
  gaps_and_magnets();
  source_rollover_and_reset();
}
