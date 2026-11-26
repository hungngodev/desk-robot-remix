#include "WheelAngleCapture.h"
#include "WheelPairCapture.h"

#include <cstdint>
#include <initializer_list>
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
  // Fresh sequence and later timestamp at identical angle is valid zero motion.
  check(left.observe(angle(9, 4, 225), 226) == Result::Delta);
  check(left.continuous() && left.last_delta() == 0 && left.angular_counts() == 105);
  // A changed register without a new acquisition identity is a fault.
  check(left.observe(angle(500, 4, 225), 226) == Result::Invalid);
  check(!left.continuous() && left.angular_counts() == 0);
  check(left.observe(angle(9, 4, 225), 227) == Result::Invalid);
  check(left.observe(angle(30, 5, 250), 251) == Result::Baseline);
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
  check(wheel.observe(angle(2, 46, 240), 240) == Result::Invalid);
  check(wheel.observe(angle(2, 47, 250), 250) == Result::Baseline);
  // Failure invalidates continuity; the following sample cannot recover
  // prior distance, even though its acquisition is newer.
  check(wheel.angular_counts() == 0);
  check(wheel.observe(angle(100, 48, 600), 600) == Result::Invalid);
  check(wheel.observe(angle(101, 49, 620), 620) == Result::Baseline);
  check(wheel.observe(angle(105, 50, 630), 800) == Result::Invalid);
  check(wheel.observe(angle(106, 51, 700), 700) == Result::Baseline);
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

static void rejected_conversion_replay_and_register_width() {
  WheelAngleCapture wheel;
  check(wheel.configure(4000, 150, 100));
  check(wheel.observe(angle(4095, 0xfffffffeU, 0xfffffff0U), 0xfffffff0U) ==
        Result::Baseline);
  auto bad = angle(65535, 0xffffffffU, 0U);
  check(wheel.observe(bad, 0U) == Result::Invalid);
  check(wheel.observe(angle(0, 0xffffffffU, 0U), 1U) == Result::Invalid);
  check(wheel.observe(angle(4095, 1, 10), 10) == Result::Baseline);
  check(wheel.observe(angle(0, 2, 20), 20) == Result::Delta);
  check(wheel.last_delta() == 1);
  check(wheel.observe(angle(4095, 3, 30), 30) == Result::Delta);
  check(wheel.last_delta() == -1 && wheel.angular_counts() == 0);
  // A future-dated invalid record cannot poison the real sequence fence.
  check(wheel.observe(angle(65535, 100, 1000), 31) == Result::Invalid);
  check(wheel.observe(angle(0, 4, 40), 40) == Result::Baseline);
  // Every out-of-range 16-bit register word is invalid, not masked or wrapped.
  for (std::uint32_t raw = 4096; raw <= 65535; ++raw) {
    WheelAngleCapture capture;
    check(capture.configure(4000, 150, 100));
    check(capture.observe(angle(static_cast<std::uint16_t>(raw), 1, 100), 100) ==
          Result::Invalid);
    check(capture.observe(angle(0, 1, 100), 100) == Result::Invalid);
    check(capture.observe(angle(0, 2, 101), 101) == Result::Baseline);
  }
}

// Combine the 49.7-day millis wrap, sequence wrap, reverse rotation,
// fresh stationary readings and cached observations in one trajectory.
static void stress_rollover_reverse_and_stall() {
  WheelAngleCapture wheel;
  check(wheel.configure(4000, 100, 60));
  std::uint32_t at = 0xfffffff0U, seq = 0xfffffffeU;
  int raw = 2;
  std::int64_t expected = 0;
  check(wheel.observe(angle(raw, seq, at), at) == Result::Baseline);
  for (unsigned i = 0; i < 100000; ++i) {
    at += 16U;
    seq = seq == 0xffffffffU ? 1U : seq + 1U;
    const int step = i % 3 == 0 ? -17 : i % 3 == 1 ? 0 : 11;
    raw = (raw + step + 4096) % 4096;
    expected += step;
    const auto sample = angle(raw, seq, at);
    check(wheel.observe(sample, at) == Result::Delta);
    check(wheel.last_delta() == step && wheel.angular_counts() == expected);
    check(wheel.segment() == 1);
    check(wheel.observe(sample, at + 1) == Result::Duplicate);
    check(wheel.last_delta() == 0 && wheel.angular_counts() == expected);
  }
  const auto cached = angle(raw, seq, at);
  check(wheel.observe(cached, at + 60) == Result::Duplicate);
  check(wheel.observe(cached, at + 61) == Result::Invalid);
  check(!wheel.continuous() && wheel.angular_counts() == 0);
  check(wheel.observe(cached, at + 61) == Result::Invalid);
  check(wheel.observe(angle(raw, seq + 1, at + 62), at + 62) == Result::Baseline);
  check(wheel.segment() == 2 && wheel.angular_counts() == 0);
}

static void exact_wrap_and_half_turn_boundaries() {
  for (int direction : {-1, 1}) {
    WheelAngleCapture wheel;
    // A 500ms interval can admit 2047 counts, never an ambiguous half turn.
    check(!wheel.configure(4096, 500, 500));
    check(wheel.configure(4094, 500, 500));
    const int start = direction > 0 ? 4090 : 5;
    const int end = direction > 0 ? 5 : 4090;
    check(wheel.observe(angle(start, 1, 100), 100) == Result::Baseline);
    check(wheel.observe(angle(end, 2, 110), 110) == Result::Delta);
    check(wheel.last_delta() == direction * 11);
    check(wheel.angular_counts() == direction * 11);
    const int near_half = (end + direction * 2047 + 4096) % 4096;
    check(wheel.observe(angle(near_half, 3, 610), 610) == Result::Delta);
    check(wheel.last_delta() == direction * 2047);
    check(wheel.angular_counts() == direction * 2058);
    const int ambiguous = (near_half + 2048) % 4096;
    const auto rejected = angle(ambiguous, 4, 1110);
    check(wheel.observe(rejected, 1110) == Result::Invalid);
    check(!wheel.continuous() && wheel.last_delta() == 0);
    check(wheel.angular_counts() == 0);
    check(wheel.observe(rejected, 1111) == Result::Invalid);
    check(wheel.observe(angle(ambiguous, 5, 1120), 1120) == Result::Baseline);
    check(wheel.segment() == 2 && wheel.angular_counts() == 0);
  }
}

static void paired_wrap_and_invalid_half_turn() {
  using desk_robot::WheelPairCapture;
  using PairResult = WheelPairCapture::Result;
  for (bool fault_left : {false, true}) {
    WheelAngleCapture left, right;
    WheelPairCapture pair;
    check(left.configure(4094, 500, 500));
    check(right.configure(4094, 500, 500));
    check(pair.configure(10));
    const auto observe = [&](AngleRaw l, AngleRaw r) {
      const auto lr = left.observe(l, l.at_ms);
      const auto rr = right.observe(r, r.at_ms);
      return pair.observe(lr, rr, l, r, left.last_delta(), right.last_delta(),
                          l.at_ms);
    };
    check(observe(angle(4090, 1, 100), angle(5, 1, 100)) == PairResult::Waiting);
    check(observe(angle(5, 2, 110), angle(4090, 2, 110)) == PairResult::Paired);
    check(pair.receipt().valid && pair.ready_for_origin());
    check(pair.receipt().left_delta == 11 && pair.receipt().right_delta == -11);
    check(observe(angle(fault_left ? 2053 : 5, 3, 610),
                  angle(fault_left ? 4090 : 2042, 3, 610)) == PairResult::Invalid);
    check(!pair.receipt().valid && !pair.ready_for_origin());
    // Match BodyControl's invalidation of both captures after a pair fault.
    left.discard_continuity();
    right.discard_continuity();
    check(observe(angle(10, 4, 620), angle(10, 4, 620)) == PairResult::Waiting);
    check(!pair.ready_for_origin());
    check(observe(angle(11, 5, 630), angle(9, 5, 630)) == PairResult::Paired);
    check(pair.receipt().segment == 2 && pair.receipt().pair_seq == 2);
    check(pair.receipt().left_delta == 1 && pair.receipt().right_delta == -1);
  }
}

static void reject_zero_elapsed_new_sequence() {
  for (std::uint32_t start : {100U, 0xfffffff0U}) {
    for (bool changed_angle : {false, true}) {
      WheelAngleCapture wheel;
      check(wheel.configure(4000, 100, 60));
      const auto at = start + 16U;
      check(wheel.observe(angle(100, 1, start), start) == Result::Baseline);
      check(wheel.observe(angle(110, 2, at), at) == Result::Delta);
      check(wheel.angular_counts() == 10);
      // A fresh sequence without a newer acquisition time is not even
      // stationary evidence. A later request cannot repair that timestamp.
      const auto invalid = angle(changed_angle ? 111 : 110, 3, at);
      check(wheel.observe(invalid, at + 1U) == Result::Invalid);
      check(!wheel.continuous() && wheel.angular_counts() == 0);
      check(wheel.last_delta() == 0 && wheel.segment() == 1);
      check(wheel.observe(invalid, at + 2U) == Result::Invalid);
      check(wheel.observe(angle(120, 4, at + 3U), at + 3U) == Result::Baseline);
      check(wheel.segment() == 2 && wheel.angular_counts() == 0);
      check(wheel.observe(angle(120, 5, at + 4U), at + 4U) == Result::Delta);
      check(wheel.continuous() && wheel.last_delta() == 0);
    }
  }
}

int main() {
  reject_zero_elapsed_new_sequence();
  exact_wrap_and_half_turn_boundaries();
  paired_wrap_and_invalid_half_turn();
  stress_rollover_reverse_and_stall();
  rejected_conversion_replay_and_register_width();
  replay_and_reverse();
  gaps_and_magnets();
  source_rollover_and_reset();
}
