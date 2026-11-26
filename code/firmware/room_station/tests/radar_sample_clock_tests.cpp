#include <cassert>
#include <cstddef>
#include <cstdint>

#include "radar_data_frame_gate.h"
#include "radar_sample_clock.h"

namespace {
constexpr uint8_t kBasicFrame[] = {
    0xF4, 0xF3, 0xF2, 0xF1, 13, 0,
    0x02, 0xAA, 0x03, 42, 0, 50, 35, 0, 60, 80, 0, 0x55, 0x00,
    0xF8, 0xF7, 0xF6, 0xF5,
};

template <std::size_t N>
bool feed(desk_robot_room::RadarDataFrameGate& gate,
          const uint8_t (&data)[N], std::size_t begin = 0,
          std::size_t end = N) {
  bool valid = false;
  for (std::size_t i = begin; i < end; ++i) {
    valid |= gate.consume(data[i]);
  }
  return valid;
}
}  // namespace

int main() {
  // A dropped suffix (e.g. UART overflow during an I2C transaction)
  // must not consume the next complete basic packet.
  for (std::size_t cut = 1; cut < sizeof(kBasicFrame); ++cut) {
    desk_robot_room::RadarDataFrameGate recovery;
    assert(!feed(recovery, kBasicFrame, 0, cut));
    assert(feed(recovery, kBasicFrame));
    assert(recovery.completed_sample().moving_cm == 42);
    assert(recovery.completed_sample().stationary_cm == 35);
  }

  // Simulate a full millis cycle with periodic reports but no new packet.
  // Once stale, the old sample must never become fresh at the same raw clock.
  desk_robot_room::RadarSampleClock expired;
  expired.observe(true, true, 1000U);
  assert(expired.fresh(4000U, 3000U));
  assert(!expired.fresh(4001U, 3000U));
  for (uint64_t elapsed = 5000; elapsed < (1ULL << 32); elapsed += 1000) {
    assert(!expired.fresh(static_cast<uint32_t>(1000U + elapsed), 3000U));
  }
  expired.observe(false, true, 1001U);
  assert(!expired.fresh(1001U, 3000U));
  expired.observe(true, true, 1002U);
  assert(expired.fresh(1002U, 3000U));

  desk_robot_room::RadarSampleClock clock;
  desk_robot_room::RadarDataFrameGate gate;
  assert(!clock.has_sample());
  assert(!clock.fresh(1000, 3000));

  clock.observe(false, true, 1000);
  assert(!clock.has_sample());
  assert(feed(gate, kBasicFrame));
  clock.observe(true, true, 1010);
  assert(clock.has_sample() && clock.sample_ms() == 1010);
  const auto first = gate.completed_sample();
  assert(first.presence && first.moving && first.stationary);
  assert(first.moving_cm == 42 && first.stationary_cm == 35);
  assert(clock.fresh(1010, 3000));
  assert(clock.fresh(4010, 3000));  // inclusive age limit
  assert(!clock.fresh(4011, 3000));

  // The pinned driver can still say connected for 100 ms after a good frame.
  // Noise and partial frames must never refresh cached target fields.
  assert(!gate.consume(0x17));
  clock.observe(false, true, 1060);
  assert(clock.sample_ms() == 1010);
  assert(!clock.fresh(4011, 3000));  // noise cannot refresh age
  assert(!feed(gate, kBasicFrame, 0, 10));
  clock.observe(false, true, 1080);
  assert(clock.sample_ms() == 1010);
  assert(feed(gate, kBasicFrame, 10));
  clock.observe(true, true, 1090);
  assert(clock.sample_ms() == 1090);

  // Command acknowledgments and corrupt data must not impersonate a reading.
  const uint8_t command[] = {0xFD, 0xFC, 0xFB, 0xFA, 4, 0, 0x60, 0,
                             0, 0, 0x04, 0x03, 0x02, 0x01};
  assert(!feed(gate, command));
  const uint8_t wrong_footer[] = {
      0xF4, 0xF3, 0xF2, 0xF1, 13, 0,
      0x02, 0xAA, 0x03, 42, 0, 50, 35, 0, 60, 80, 0, 0x55, 0x00,
      0xF8, 0xF7, 0xF6, 0xF4,
  };
  assert(!feed(gate, wrong_footer));
  // Reject forged lengths without uint16 overflow or out-of-bounds reads.
  const uint8_t oversized[] = {0xF4, 0xF3, 0xF2, 0xF1, 0xFF, 0xFF};
  assert(!feed(gate, oversized));
  clock.observe(false, true, 1120);
  assert(clock.sample_ms() == 1090);

  // Identical legitimate frames still advance acquisition, even without a
  // semantic change; connection alone or a disconnected frame never does.
  assert(feed(gate, kBasicFrame));
  clock.observe(true, false, 1140);
  assert(clock.sample_ms() == 1090);
  assert(feed(gate, kBasicFrame));
  clock.observe(true, true, 1200);
  assert(clock.sample_ms() == 1200);

  assert(feed(gate, kBasicFrame));
  clock.observe(true, true, UINT32_MAX);
  assert(clock.sample_ms() == UINT32_MAX);
  assert(clock.fresh(2999, 3000));   // 32-bit rollover
  assert(!clock.fresh(3000, 3000));
  assert(feed(gate, kBasicFrame));
  clock.observe(true, true, 3);
  assert(clock.sample_ms() == 3);
  assert(clock.fresh(3003, 3000));
  assert(!clock.fresh(3004, 3000));
  // Multiple complete frames in one UART drain must publish the latest
  // packet, not the upstream decoder's potentially older live getters.
  const uint8_t next[] = {
      0xF4, 0xF3, 0xF2, 0xF1, 13, 0,
      0x02, 0xAA, 0x02, 0, 0, 0, 0x2C, 0x01, 60, 80, 0, 0x55, 0x00,
      0xF8, 0xF7, 0xF6, 0xF5,
  };
  assert(feed(gate, kBasicFrame));
  assert(feed(gate, next));
  const auto latest = gate.completed_sample();
  clock.observe(true, true, 4);
  assert(latest.presence && !latest.moving && latest.stationary);
  assert(latest.moving_cm == 0 && latest.stationary_cm == 300);
  assert(clock.sample_ms() == 4);
  assert(first.moving_cm == 42 && first.stationary_cm == 35);
  assert(!feed(gate, wrong_footer));
  assert(!feed(gate, kBasicFrame, 0, 14));
  assert(gate.completed_sample().stationary_cm == 300);
  assert(!gate.completed_sample().moving);
  assert(clock.sample_ms() == 4);
  assert(feed(gate, kBasicFrame, 14));
  assert(gate.completed_sample().moving_cm == 42);
  // Table 13 reserves every target state above 3. An otherwise valid
  // frame must not change the last observation or renew its acquisition.
  uint8_t reserved[] = {
      0xF4, 0xF3, 0xF2, 0xF1, 13, 0,
      0x02, 0xAA, 0xFF, 99, 0, 50, 35, 0, 60, 80, 0, 0x55, 0x00,
      0xF8, 0xF7, 0xF6, 0xF5,
  };
  for (unsigned state = 4; state <= 255; ++state) {
    reserved[8] = static_cast<uint8_t>(state);
    const bool accepted = feed(gate, reserved);
    clock.observe(accepted, true, 1000);
    assert(!accepted);
    assert(clock.sample_ms() == 4);
    assert(gate.completed_sample().moving_cm == 42);
  }
  for (uint8_t state = 0; state <= 3; ++state) {
    reserved[8] = state;
    assert(feed(gate, reserved));
    assert(gate.completed_sample().presence == (state != 0));
    assert(gate.completed_sample().moving == ((state & 1) != 0));
    assert(gate.completed_sample().stationary == ((state & 2) != 0));
  }
  // A complete footer is not enough: basic reports have 13 payload
  // bytes; engineering reports need the full fixed gate-energy section.
  const uint8_t short_engineering[] = {
      0xF4, 0xF3, 0xF2, 0xF1, 13, 0,
      0x01, 0xAA, 0x03, 42, 0, 50, 35, 0, 60, 80, 0, 0x55, 0x00,
      0xF8, 0xF7, 0xF6, 0xF5,
  };
  const uint8_t long_basic[] = {
      0xF4, 0xF3, 0xF2, 0xF1, 14, 0,
      0x02, 0xAA, 0x03, 42, 0, 50, 35, 0, 60, 80, 0, 0, 0x55, 0x00,
      0xF8, 0xF7, 0xF6, 0xF5,
  };
  assert(!feed(gate, short_engineering));
  assert(!feed(gate, long_basic));
  assert(gate.completed_sample().moving_cm == 99);
  // Pinned LD2410C protocol Table 14: engineering example with both
  // targets, nine moving and nine stationary gates and retained bytes.
  const uint8_t engineering[] = {
      0xF4, 0xF3, 0xF2, 0xF1, 0x23, 0,
      0x01, 0xAA, 0x03, 0x1E, 0, 0x3C, 0, 0, 0x39, 0, 0,
      8, 8, 0x3C, 0x22, 5, 3, 3, 4, 3, 6, 5,
      0, 0, 0x39, 0x10, 0x13, 6, 6, 8, 4,
      3, 5, 0x55, 0,
      0xF8, 0xF7, 0xF6, 0xF5,
  };
  assert(feed(gate, engineering));
  assert(gate.completed_sample().presence);
  assert(gate.completed_sample().moving_cm == 30);
  // Both distance fields retain the full unsigned little-endian range.
  const uint8_t full_width[] = {
      0xF4, 0xF3, 0xF2, 0xF1, 13, 0,
      0x02, 0xAA, 0x03, 0xFF, 0xFF, 50, 0, 0x80, 60, 80, 0, 0x55, 0x00,
      0xF8, 0xF7, 0xF6, 0xF5,
  };
  assert(feed(gate, full_width));
  assert(gate.completed_sample().moving_cm == UINT16_MAX);
  assert(gate.completed_sample().stationary_cm == 0x8000U);
  return 0;
}
