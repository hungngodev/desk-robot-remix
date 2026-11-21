#include <cassert>
#include <cstdint>

#include "radar_sample_clock.h"

int main() {
  desk_robot_room::RadarSampleClock clock;
  assert(!clock.has_sample());

  // A cached connection state without fresh UART activity cannot invent a
  // newer sample timestamp.
  clock.observe(false, true, 1000);
  assert(!clock.has_sample());

  clock.observe(true, true, 1010);
  assert(clock.has_sample());
  assert(clock.sample_ms() == 1010);

  clock.observe(false, true, 1090);
  assert(clock.sample_ms() == 1010);

  // Bytes that do not coexist with the library's valid-packet window cannot
  // refresh the evidence timestamp.
  clock.observe(true, false, 1110);
  assert(clock.sample_ms() == 1010);

  // Repeated identical radar frames still carry UART activity and therefore
  // can advance freshness without comparing semantic target values.
  clock.observe(true, true, 1200);
  assert(clock.sample_ms() == 1200);

  // uint32 millis wrap remains a valid local timestamp.
  clock.observe(true, true, UINT32_MAX);
  assert(clock.sample_ms() == UINT32_MAX);
  clock.observe(true, true, 3);
  assert(clock.sample_ms() == 3);
  return 0;
}
