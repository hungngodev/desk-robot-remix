#include "AccessoryReadings.h"
#include <iostream>
#include <stdexcept>
#define CHECK(x) do { if (!(x)) throw std::runtime_error(#x); } while (false)
int main() {
  try {
    const std::uint8_t known[2] = {0xBE, 0xEF};
    CHECK(desk_robot::sensirion_crc(known, 2) == 0x92);
    CHECK(desk_robot::sht_temp_centi(0) == -4500);
    CHECK(desk_robot::sht_temp_centi(65535) == 13000);
    CHECK(desk_robot::sht_humidity_centi(0) == 0);
    CHECK(desk_robot::sht_humidity_centi(65535) == 10000);
    CHECK(desk_robot::max17048_cell_mv(46080) == 3600);
    CHECK(desk_robot::max17048_soc_centi(12800) == 5000);
    CHECK(desk_robot::ina226_bus_mv(9584) == 11980);
    CHECK(desk_robot::ina226_shunt_uv(8000) == 20000);
    CHECK(desk_robot::ina226_shunt_uv(-8000) == -20000);
    desk_robot::AccessoryReadings uninitialized{};
    for (const auto& a : uninitialized.angle) CHECK(!a.present && !a.valid);
    CHECK(!uninitialized.gauge.fuel_valid);
    CHECK(!uninitialized.climate.valid);
    std::cout << "PASS manufacturer register conversions and no fake sensors\n";
  } catch(const std::exception& e) {
    std::cerr << "FAIL " << e.what() << "\n";
    return 1;
  }
}
