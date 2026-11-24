#include "AccessoryReadings.h"
#include "Bmp280Math.h"
#include "GestureDecoder.h"
#include <iostream>
#include <stdexcept>
#define CHECK(x) do { if (!(x)) throw std::runtime_error(#x); } while (false)
// Verify quantization against exact rational intervals, not a second copy
// of the production division. All intermediate arithmetic is signed 64-bit.
static void check_floor(std::int64_t actual, std::int64_t numerator,
                        std::int64_t denominator) {
  CHECK(actual * denominator <= numerator);
  CHECK(numerator < (actual + 1) * denominator);
}
static void check_register_precision() {
  for (std::uint32_t code = 0; code <= 0xffffU; ++code) {
    const auto raw = static_cast<std::uint16_t>(code);
    const std::int64_t n = code;
    check_floor(desk_robot::sht_temp_centi(raw),
                17500LL * n - 4500LL * 65535, 65535);
    const std::int64_t humidity = 12500LL * n - 600LL * 65535;
    const auto rh = desk_robot::sht_humidity_centi(raw);
    if (humidity <= 0) CHECK(rh == 0);
    else if (humidity >= 10000LL * 65535) CHECK(rh == 10000);
    else check_floor(rh, humidity, 65535);
    // MAX17048 VCELL: 78.125 uV/LSB; SOC: 1/256 percent/LSB.
    check_floor(desk_robot::max17048_cell_mv(raw), 78125LL * n, 1000000);
    check_floor(desk_robot::max17048_soc_centi(raw), 100LL * n, 256);
    // INA226 bus voltage has a 15-bit unsigned data field.
    if (code <= 0x7fffU)
      check_floor(desk_robot::ina226_bus_mv(raw), 1250LL * n, 1000);
    int uv = 123456;
    if (code == 0x7fffU || code == 0x8000U) {
      CHECK(!desk_robot::ina226_shunt_uv_from_raw(raw, uv));
      CHECK(uv == 123456);
      continue;
    }
    // Explicit two's-complement oracle; avoid an implementation-defined
    // narrowing cast in the expected value. Quantization is toward zero.
    const std::int64_t signed_code = code < 0x8000U ? n : n - 65536;
    CHECK(desk_robot::ina226_shunt_uv_from_raw(raw, uv));
    if (signed_code < 0)
      check_floor(-static_cast<std::int64_t>(uv), -5 * signed_code, 2);
    else check_floor(uv, 5 * signed_code, 2);
  }
}
int main() {
  try {
    check_register_precision();
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

    // A transient timeout, malformed ACK, or reinitialization must never
    // turn one uninterrupted NFC presentation into a second arrival.
    desk_robot::NfcRaw tag{};
    constexpr std::uint32_t kTagA = 0x12345678U;
    constexpr std::uint32_t kTagB = 0x87654321U;
    tag.completed_scan(true, kTagA, 4, 100);
    CHECK(tag.valid && tag.tag_visible && tag.tag_events == 1U);
    CHECK(tag.scan_seq == 1U && tag.tag_token == kTagA);
    tag.transport_failed();
    CHECK(!tag.present && !tag.valid);
    CHECK(tag.tag_visible && tag.tag_token == kTagA);
    tag.completed_scan(true, kTagA, 4, 200);
    CHECK(tag.tag_events == 1U && tag.scan_seq == 2U);
    // A DIFFERENT confirmed tag after recovery remains a real new event.
    tag.transport_failed();
    tag.completed_scan(true, kTagB, 7, 300);
    CHECK(tag.tag_events == 2U && tag.tag_token == kTagB);
    // Valid absence, unlike transport failure, ends a presentation.
    tag.completed_scan(false, 0U, 0, 400);
    CHECK(!tag.tag_visible && tag.tag_token == 0U);
    CHECK(tag.tag_events == 2U);
    tag.completed_scan(true, kTagB, 7, 500);
    CHECK(tag.tag_events == 3U && tag.scan_seq == 5U);
    // Preserve zero as the no-event sentinel after uint32 wrap.
    tag.tag_events = 0xffffffffU;
    tag.completed_scan(false, 0U, 0, 600);
    tag.completed_scan(true, kTagA, 4, 700);
    CHECK(tag.tag_events == 1U && tag.scan_seq == 7U);
    std::cout << "PASS manufacturer register conversions and no fake sensors\n";
  } catch(const std::exception& e) {
    std::cerr << "FAIL " << e.what() << "\n";
    return 1;
  }
}
