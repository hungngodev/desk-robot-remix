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
  desk_robot_room::RadarSampleClock clock;
  desk_robot_room::RadarDataFrameGate gate;
  assert(!clock.has_sample());

  clock.observe(false, true, 1000);
  assert(!clock.has_sample());
  assert(feed(gate, kBasicFrame));
  clock.observe(true, true, 1010);
  assert(clock.has_sample() && clock.sample_ms() == 1010);

  // The pinned driver can still say connected for 100 ms after a good frame.
  // Noise and partial frames must never refresh cached target fields.
  assert(!gate.consume(0x17));
  clock.observe(false, true, 1060);
  assert(clock.sample_ms() == 1010);
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
  assert(feed(gate, kBasicFrame));
  clock.observe(true, true, 3);
  assert(clock.sample_ms() == 3);
  return 0;
}
