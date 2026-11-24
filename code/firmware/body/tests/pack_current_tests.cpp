#include "AccessoryReadings.h"
#include <cstdlib>
#include <cstdint>
#include <iostream>
#include <initializer_list>
#include <limits>

using desk_robot::ina226_shunt_uv;
using desk_robot::ina226_shunt_uv_from_raw;
using desk_robot::ina226_pack_current_ma;
using desk_robot::next_nonzero_sensor_sequence;

// Keep the safety-related regression active even with NDEBUG.
#define CHECK(condition) do { \
  if (!(condition)) { \
    std::cerr << "FAIL line " << __LINE__ << ": " << #condition << '\n'; \
    std::abort(); \
  } \
} while (false)

int main() {
  int ma = 999;
  CHECK(ina226_shunt_uv(static_cast<std::int16_t>(0)) == 0);
  CHECK(ina226_shunt_uv(static_cast<std::int16_t>(16)) == 40);
  CHECK(ina226_shunt_uv(static_cast<std::int16_t>(-40)) == -100);
  CHECK(ina226_pack_current_ma(40, 5, ma) && ma == 8);
  CHECK(ina226_pack_current_ma(-100, 5, ma) && ma == -20);
  CHECK(ina226_pack_current_ma(0, 5, ma) && ma == 0);
  CHECK(ina226_pack_current_ma(81915, 5, ma) && ma == 16383);
  CHECK(ina226_pack_current_ma(-81915, 5, ma) && ma == -16383);

  // Exercise the production raw-code gate before conversion. Positive
  // full-scale rounds below 81920uV, so testing only converted values misses it.
  // TI INA226: two's-complement shunt register, 2.5uV/LSB; 5mOhm gives
  // 0.5mA/LSB. Positive is charge, negative is discharge, not a trip policy.
  unsigned valid_codes = 0;
  for (std::uint32_t code = 0; code <= 0xffffU; ++code) {
    int uv = 123456;
    ma = 999;
    const bool valid = ina226_shunt_uv_from_raw(static_cast<std::uint16_t>(code), uv);
    if (code == 0x7fffU || code == 0x8000U) {
      CHECK(!valid);
      CHECK(uv == 123456);
      continue;
    }
    CHECK(valid);
    const int signed_code = code < 0x8000U ? static_cast<int>(code)
                                         : static_cast<int>(code) - 65536;
    CHECK(uv == signed_code * 5 / 2);
    CHECK(ina226_pack_current_ma(uv, 5U, ma));
    CHECK(ma == signed_code / 2);
    ++valid_codes;
  }
  CHECK(valid_codes == 65534U);

  // Invalid conversions preserve the caller's output. Validity, not an old
  // current value or a zero sentinel, is what a consumer must check.
  for (int sample : {81920, -81920, 90000, -90000,
                     std::numeric_limits<int>::min(), std::numeric_limits<int>::max()}) {
    ma = 999;
    CHECK(!ina226_pack_current_ma(sample, 5, ma));
    CHECK(ma == 999);
  }
  for (unsigned unknown : {0U, 1U, 2U, 4U, 6U, 10U, 100U,
                           std::numeric_limits<unsigned>::max()}) {
    ma = 999;
    CHECK(!ina226_pack_current_ma(40, unknown, ma));
    CHECK(ma == 999);
    CHECK(!ina226_pack_current_ma(-40, unknown, ma));
    CHECK(ma == 999);
  }
  CHECK(next_nonzero_sensor_sequence(0U) == 1U);
  CHECK(next_nonzero_sensor_sequence(1U) == 2U);
  CHECK(next_nonzero_sensor_sequence(0xfffffffeU) == 0xffffffffU);
  CHECK(next_nonzero_sensor_sequence(0xffffffffU) == 1U);
  std::cout << "PASS INA226 diagnostic conversion: 65536 raw codes, polarity, saturation, identity\n";
}
