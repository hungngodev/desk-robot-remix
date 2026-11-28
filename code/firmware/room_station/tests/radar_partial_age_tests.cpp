#include <cassert>
#include <cstddef>
#include <cstdint>
#include <initializer_list>

#include "radar_data_frame_gate.h"
#include "radar_sample_clock.h"

namespace {
constexpr uint32_t kMaxAgeMs = 3000;
constexpr uint8_t kFrame[] = {
    0xF4, 0xF3, 0xF2, 0xF1, 13, 0,
    0x02, 0xAA, 0x03, 42, 0, 50, 35, 0, 60, 80, 0, 0x55, 0x00,
    0xF8, 0xF7, 0xF6, 0xF5,
};

void check_split(uint32_t start, uint32_t age, bool periodic_expiry) {
  for (std::size_t split = 1; split < sizeof(kFrame); ++split) {
    desk_robot_room::RadarDataFrameGate gate;
    desk_robot_room::RadarSampleClock clock;
    const uint32_t end = start + age;
    for (std::size_t i = 0; i < split; ++i)
      assert(!gate.consume_at(kFrame[i], start, kMaxAgeMs));
    if (periodic_expiry) gate.expire_partial(end, kMaxAgeMs);
    for (std::size_t i = split; i < sizeof(kFrame); ++i) {
      const bool accepted = gate.consume_at(kFrame[i], end, kMaxAgeMs);
      assert(accepted == (age <= kMaxAgeMs && i + 1 == sizeof(kFrame)));
      clock.observe(accepted, true, end);
    }
    assert(clock.fresh(end, kMaxAgeMs) == (age <= kMaxAgeMs));
    // A complete new packet must recover without a station reboot.
    for (std::size_t i = 0; i < sizeof(kFrame); ++i) {
      const bool accepted = gate.consume_at(kFrame[i], end + 1U, kMaxAgeMs);
      assert(accepted == (i + 1 == sizeof(kFrame)));
      clock.observe(accepted, true, end + 1U);
    }
    assert(clock.fresh(end + 1U, kMaxAgeMs));
    assert(clock.sample_ms() == end + 1U);
    assert(gate.completed_sample().moving_cm == 42);
  }
}
}  // namespace

int main() {
  for (bool periodic_expiry : {false, true}) {
    check_split(0U, 3000U, periodic_expiry);
    check_split(0U, 3001U, periodic_expiry);
    check_split(UINT32_MAX - 100U, 3000U, periodic_expiry);
    check_split(UINT32_MAX - 100U, 3001U, periodic_expiry);
  }
  // Trickle bytes cannot continually reset the first-byte deadline.
  desk_robot_room::RadarDataFrameGate gate;
  desk_robot_room::RadarSampleClock clock;
  for (std::size_t i = 0; i < sizeof(kFrame); ++i) {
    const uint32_t now = static_cast<uint32_t>(i) * 200U;
    const bool accepted = gate.consume_at(kFrame[i], now, kMaxAgeMs);
    assert(!accepted);
    clock.observe(accepted, true, now);
  }
  assert(!clock.has_sample());
  // Expiration of an incomplete packet must not alter a completed tuple.
  for (uint8_t byte : kFrame) clock.observe(gate.consume_at(byte, 5000U, kMaxAgeMs), true, 5000U);
  assert(clock.fresh(5000U, kMaxAgeMs));
  assert(!gate.consume_at(kFrame[0], 5001U, kMaxAgeMs));
  gate.expire_partial(8002U, kMaxAgeMs);
  assert(gate.completed_sample().moving_cm == 42);
  assert(clock.sample_ms() == 5000U);
  assert(!clock.fresh(8002U, kMaxAgeMs));
}
