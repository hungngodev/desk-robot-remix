#include "AccessoryReadings.h"
#include "Bmp280Math.h"
#include "GestureDecoder.h"
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
    // INA226 16-bit register rails must be rejected BEFORE scaling.
    // Positive 0x7fff truncates below the converted 81920uV ceiling.
    int shunt_uv = 123;
    CHECK(!desk_robot::ina226_shunt_uv_from_raw(0x7fffU, shunt_uv));
    CHECK(shunt_uv == 123); // failed sample must not overwrite prior value
    CHECK(!desk_robot::ina226_shunt_uv_from_raw(0x8000U, shunt_uv));
    CHECK(shunt_uv == 123);
    CHECK(desk_robot::ina226_shunt_uv_from_raw(0x7ffeU, shunt_uv));
    CHECK(shunt_uv == 81915);
    CHECK(desk_robot::ina226_shunt_uv_from_raw(0x8001U, shunt_uv));
    CHECK(shunt_uv == -81917);
    CHECK(desk_robot::ina226_shunt_uv_from_raw(0U, shunt_uv));
    CHECK(shunt_uv == 0);
    // Four physically distinct BQ2407x PGOOD/CHG combinations.
    // PGOOD high while CHG low is a diagnostic contradiction, not
    // permission to erase CHG before the WROOM receives it.
    CHECK(desk_robot::dock_pgood_asserted(0x08U));
    CHECK(!desk_robot::dock_chg_asserted(0x08U));
    CHECK(!desk_robot::dock_pgood_asserted(0x04U));
    CHECK(desk_robot::dock_chg_asserted(0x04U));
    CHECK(desk_robot::dock_pgood_asserted(0x00U));
    CHECK(desk_robot::dock_chg_asserted(0x00U));
    CHECK(!desk_robot::dock_pgood_asserted(0x0CU));
    CHECK(!desk_robot::dock_chg_asserted(0x0CU));
    // Bosch BMP280 datasheet example: T=25.08C, P=100653Pa.
    desk_robot::Bmp280Trim trim{};
    trim.t1 = 27504; trim.t2 = 26435; trim.t3 = -1000;
    trim.p1 = 36477; trim.p2 = -10685; trim.p3 = 3024;
    trim.p4 = 2855; trim.p5 = 140; trim.p6 = -7;
    trim.p7 = 15500; trim.p8 = -14600; trim.p9 = 6000;
    int bmp_t = 0;
    unsigned bmp_p = 0;
    CHECK(desk_robot::bmp280_compensate(trim, 519888, 415148, bmp_t, bmp_p));
    CHECK(bmp_t == 2508);
    CHECK(bmp_p >= 100652 && bmp_p <= 100654);
    CHECK(!desk_robot::bmp280_compensate(trim, 0x80000, 415148, bmp_t, bmp_p));
    CHECK(!desk_robot::bmp280_compensate(trim, 519888, 0x80000, bmp_t, bmp_p));
    desk_robot::Bmp280Trim invalid{};
    CHECK(!desk_robot::bmp280_compensate(invalid, 519888, 415148, bmp_t, bmp_p));
    desk_robot::GestureDecoder gesture;
    // Strong vertical swipe: first UP, finally DOWN, output UP.
    gesture.push(180, 30, 85, 85);
    gesture.push(90, 90, 85, 85);
    gesture.push(30, 180, 85, 85);
    CHECK(gesture.finish() == 1);
    CHECK(gesture.finish() == 0); // no replay without fresh FIFO
    gesture.push(30, 180, 85, 85);
    gesture.push(90, 90, 85, 85);
    gesture.push(180, 30, 85, 85);
    CHECK(gesture.finish() == 2);
    gesture.push(85, 85, 180, 30);
    gesture.push(85, 85, 90, 90);
    gesture.push(85, 85, 30, 180);
    CHECK(gesture.finish() == 3);
    gesture.push(85, 85, 30, 180);
    gesture.push(85, 85, 90, 90);
    gesture.push(85, 85, 180, 30);
    CHECK(gesture.finish() == 4);
    gesture.push(85, 85, 90, 85);
    gesture.push(86, 84, 90, 84);
    gesture.push(85, 85, 86, 90);
    CHECK(gesture.finish() == 0);
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
