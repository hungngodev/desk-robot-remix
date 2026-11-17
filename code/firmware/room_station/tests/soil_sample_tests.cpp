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
    FakeAdc adc{2048, bad, 2049};
    assert(!desk_robot_room::read_soil_sample([&]() { return adc(); }).valid);
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
}
