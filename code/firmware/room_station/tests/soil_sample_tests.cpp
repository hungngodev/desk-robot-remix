#include "soil_sample.h"
#include <cassert>
#include <cstddef>
#include <initializer_list>

namespace {
struct FakeAdc {
  int readings[3];
  std::size_t next = 0;
  FakeAdc(int a, int b, int c) : readings{a, b, c} {}
  int operator()() { return readings[next++]; }
};
}
int main() {
  {
    FakeAdc adc{2100, 2075, 2082};
    const auto sample = desk_robot_room::read_soil_sample([&]() { return adc(); });
    assert(sample.valid && sample.raw_adc == 2082 && adc.next == 3);
  }
  {
    FakeAdc adc{4000, 3900, 3950};
    const auto sample = desk_robot_room::read_soil_sample([&]() { return adc(); });
    assert(sample.valid && sample.raw_adc == 3950);
  }
  for (int bad : {-1, 0, 4095, 5000}) {
    for (std::size_t position = 0; position < 3; ++position) {
      FakeAdc adc{2048, 2048, 2048};
      adc.readings[position] = bad;
      const auto sample = desk_robot_room::read_soil_sample([&]() { return adc(); });
      assert(!sample.valid && sample.raw_adc == 0 && adc.next == 3);
    }
  }
  {
    FakeAdc adc{150, 800, 1000};
    assert(!desk_robot_room::read_soil_sample([&]() { return adc(); }).valid);
  }
  {
    FakeAdc adc{1, 1, 1};
    const auto sample = desk_robot_room::read_soil_sample([&]() { return adc(); });
    assert(sample.valid && sample.raw_adc == 1);
  }
  {
    FakeAdc adc{4094, 4094, 4094};
    const auto sample = desk_robot_room::read_soil_sample([&]() { return adc(); });
    assert(sample.valid && sample.raw_adc == 4094);
  }
  // Exercise every ordering at and immediately above the burst noise limit.
  const int orderings[][3] = {{0, 1, 2}, {0, 2, 1}, {1, 0, 2},
                              {1, 2, 0}, {2, 0, 1}, {2, 1, 0}};
  for (const auto& order : orderings) {
    for (int spread : {256, 257}) {
      const int values[] = {1000, 1128, 1000 + spread};
      FakeAdc adc{values[order[0]], values[order[1]], values[order[2]]};
      const auto sample = desk_robot_room::read_soil_sample([&]() { return adc(); });
      assert(adc.next == 3);
      assert(sample.valid == (spread == 256));
      assert(sample.raw_adc == (spread == 256 ? 1128 : 0));
    }
  }
  // A stable nonrail output could be dry soil, air, or a floating input.
  // These synthetic bursts prove acquisition semantics, not probe presence.
  for (int plausible : {1000, 2000, 3000}) {
    FakeAdc adc{plausible, plausible, plausible};
    const auto sample = desk_robot_room::read_soil_sample([&]() { return adc(); });
    assert(sample.valid && sample.raw_adc == plausible && adc.next == 3);
  }
  // A rejected burst must not carry a previous accepted ADC value; a later
  // electrically plausible burst is accepted without claiming reconnection.
  FakeAdc before{2000, 2001, 2002};
  FakeAdc fault{2000, 4095, 2002};
  FakeAdc after{3000, 3001, 3002};
  const auto first = desk_robot_room::read_soil_sample([&]() { return before(); });
  const auto invalid = desk_robot_room::read_soil_sample([&]() { return fault(); });
  const auto recovered = desk_robot_room::read_soil_sample([&]() { return after(); });
  assert(first.valid && first.raw_adc == 2001);
  assert(!invalid.valid && invalid.raw_adc == 0);
  assert(recovered.valid && recovered.raw_adc == 3001);
}
