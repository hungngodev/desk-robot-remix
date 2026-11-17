#include "AccessoryReadings.h"
#include <cassert>
#include <cstdint>
#include <iostream>
#include <initializer_list>

using desk_robot::ina226_shunt_uv;
using desk_robot::ina226_pack_current_ma;
using desk_robot::next_nonzero_sensor_sequence;

int main() {
  int ma = 999;
  assert(ina226_shunt_uv(static_cast<std::int16_t>(0)) == 0);
  assert(ina226_shunt_uv(static_cast<std::int16_t>(16)) == 40);
  assert(ina226_shunt_uv(static_cast<std::int16_t>(-40)) == -100);
  assert(ina226_pack_current_ma(40, 5, ma) && ma == 8);
  assert(ina226_pack_current_ma(-100, 5, ma) && ma == -20);
  assert(ina226_pack_current_ma(0, 5, ma) && ma == 0);
  assert(ina226_pack_current_ma(81915, 5, ma) && ma == 16383);
  assert(ina226_pack_current_ma(-81915, 5, ma) && ma == -16383);
  // Saturating ADC values and all unknown shunts must never fabricate amps.
  for (int sample : {81920, -81920, 90000, -90000}) {
    assert(!ina226_pack_current_ma(sample, 5, ma));
  }
  for (unsigned unknown : {0U, 1U, 2U, 10U, 100U}) {
    assert(!ina226_pack_current_ma(40, unknown, ma));
  }
  assert(next_nonzero_sensor_sequence(0U) == 1U);
  assert(next_nonzero_sensor_sequence(0xffffffffU) == 1U);
  std::cout << "PASS INA226 signed 5mOhm pack current: polarity, saturation, identity\\n";
}
