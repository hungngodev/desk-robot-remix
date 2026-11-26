#include "AccessoryReadings.h"
#include "Bmp280Math.h"
#include "GestureDecoder.h"
#include <cfenv>
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
static void check_gesture_boundaries() {
  desk_robot::GestureDecoder g;
  const auto classify = [&g](std::uint8_t u, std::uint8_t d,
                              std::uint8_t l, std::uint8_t r) {
    g.push(100, 100, 100, 100);
    g.push(100, 100, 100, 100);
    g.push(u, d, l, r);
    return g.finish();
  };
  // Each pair sums to 200, so ratio differences are exact integers.
  CHECK(classify(71, 129, 100, 100) == 0); // 29: below threshold
  CHECK(classify(70, 130, 100, 100) == 1); // 30: inclusive
  CHECK(classify(130, 70, 100, 100) == 2);
  CHECK(classify(100, 100, 70, 130) == 3);
  CHECK(classify(100, 100, 130, 70) == 4);
  CHECK(classify(70, 130, 115, 85) == 0); // exact 2:1 rejected
  CHECK(classify(70, 130, 114, 86) == 1); // strictly dominant
  CHECK(classify(114, 86, 130, 70) == 4);
  CHECK(classify(60, 140, 60, 140) == 0); // equal axes: diagonal
  // A dark sample must not create a third qualified FIFO observation.
  g.push(100, 100, 100, 100);
  g.push(0, 39, 100, 100);
  g.push(70, 130, 100, 100);
  CHECK(g.finish() == 0);
  g.push(100, 100, 100, 100);
  g.push(100, 100, 39, 0);
  g.push(100, 100, 130, 70);
  CHECK(g.finish() == 0);
  // The exact optical threshold of 40 is accepted.
  g.push(20, 20, 20, 20);
  g.push(20, 20, 20, 20);
  g.push(14, 26, 20, 20);
  CHECK(g.finish() == 1);
  // Counter saturation must not wrap to zero and erase a long gesture.
  for (unsigned i = 0; i < 256; ++i) g.push(100, 100, 100, 100);
  g.push(70, 130, 100, 100);
  CHECK(g.finish() == 1);
  CHECK(g.finish() == 0);
}
static void check_gesture_optical_faults() {
  using desk_robot::GestureDecoder;
  using Action = GestureDecoder::PollAction;
  for (unsigned channel = 0; channel < 5; ++channel) {
    GestureDecoder g;
    std::uint8_t direction = 99;
    CHECK(g.poll_status(1, 100, direction) == Action::Read);
    g.begin_batch(100);
    g.push(180, 30, 85, 85);
    g.push(90, 90, 85, 85);
    std::uint8_t glare[] = {90, 90, 85, 85};
    for (unsigned i = 0; i < 4; ++i)
      if (channel == i || channel == 4) glare[i] = 255;
    g.push(glare[0], glare[1], glare[2], glare[3]);
    g.begin_batch(200);
    g.push(90, 90, 85, 85);
    g.push(30, 180, 85, 85);
    CHECK(g.poll_status(0, 201, direction) == Action::None && direction == 0);
    CHECK(g.poll_status(1, 202, direction) == Action::Read);
    g.begin_batch(202);
    g.push(180, 30, 85, 85);
    g.push(90, 90, 85, 85);
    g.push(30, 180, 85, 85);
    CHECK(g.poll_status(0, 203, direction) == Action::None && direction == 1);
  }
  // Overflow may be reported even after GVALID falls. It must win over
  // finalization and require clean idle before the next usable session.
  {
    GestureDecoder g;
    std::uint8_t direction = 99;
    CHECK(g.poll_status(1, 100, direction) == Action::Read);
    g.begin_batch(100);
    g.push(180, 30, 85, 85);
    g.push(90, 90, 85, 85);
    g.push(30, 180, 85, 85);
    CHECK(g.poll_status(2, 101, direction) == Action::Clear && direction == 0);
    CHECK(g.poll_status(1, 102, direction) == Action::Clear && direction == 0);
    CHECK(g.poll_status(0, 103, direction) == Action::None && direction == 0);
  }
  // Rail-only input must never be mistaken for a directional observation.
  GestureDecoder g;
  for (unsigned i = 0; i < 32; ++i) g.push(255, 255, 255, 255);
  CHECK(g.finish() == 0);
  // Each active-axis diode stuck while its partner changes enough to
  // cross the ratio threshold, in both directions and on both axes.
  for (unsigned axis = 0; axis < 2; ++axis) {
    for (unsigned stuck = 0; stuck < 2; ++stuck) {
      for (unsigned reverse = 0; reverse < 2; ++reverse) {
        for (unsigned i = 0; i < 3; ++i) {
          std::uint8_t q[] = {100, 100, 100, 100};
          q[2 * axis + (1 - stuck)] = reverse ? 180 - 75 * i : 30 + 75 * i;
          g.push(q[0], q[1], q[2], q[3]);
        }
        CHECK(g.finish() == 0);
      }
    }
  }
  // Asymmetric brightness change with both diodes moving the same way.
  g.push(20, 20, 85, 85);
  g.push(40, 80, 85, 85);
  g.push(60, 180, 85, 85);
  CHECK(g.finish() == 0);
}

static void check_gesture_session_recovery() {
  using desk_robot::GestureDecoder;
  using Action = GestureDecoder::PollAction;
  const auto batch = [](GestureDecoder& g, std::uint32_t now) {
    g.begin_batch(now);
    g.push(180, 30, 85, 85);
    g.push(90, 90, 85, 85);
    g.push(30, 180, 85, 85);
  };
  for (const auto start : {100U, 0xffffff80U}) {
    for (unsigned fault = 0; fault < 3; ++fault) {
      GestureDecoder g;
      std::uint8_t direction = 99;
      CHECK(g.poll_status(1, start, direction) == Action::Read && direction == 0);
      batch(g, start);
      if (fault == 0) g.invalidate(); // bus or FIFO read failure
      if (fault == 1)
        CHECK(g.poll_status(3, start + 100U, direction) == Action::Clear);
      if (fault == 2)
        CHECK(g.poll_status(1, start + 701U, direction) == Action::Clear);
      CHECK(g.poll_status(1, start + 702U, direction) == Action::Clear && direction == 0);
      CHECK(g.poll_status(0, start + 703U, direction) == Action::None && direction == 0);
      CHECK(g.poll_status(1, start + 704U, direction) == Action::Read && direction == 0);
      batch(g, start + 704U);
      CHECK(g.poll_status(0, start + 1404U, direction) == Action::None && direction == 1);
      CHECK(g.poll_status(0, start + 1405U, direction) == Action::None && direction == 0);
    }
    // GVALID clearing AFTER the deadline must not publish a stale swipe.
    GestureDecoder g;
    std::uint8_t direction = 99;
    CHECK(g.poll_status(1, start, direction) == Action::Read);
    batch(g, start);
    CHECK(g.poll_status(0, start + 701U, direction) == Action::None && direction == 0);
  }
}

static void check_bmp280_boundaries() {
  desk_robot::Bmp280Trim d{};
  d.t1 = 16384;
  d.t2 = 16384;
  d.p1 = 6250;
  int t = 0;
  unsigned p = 0;
  // With all other coefficients zero, T=(raw_t-262144)/5120,
  // and P=1048576-raw_p. These exact fixtures isolate each output gate.
  CHECK(desk_robot::bmp280_compensate(d, 57344, 1018576, t, p));
  CHECK(t == -4000 && p == 30000);
  CHECK(desk_robot::bmp280_compensate(d, 697344, 928576, t, p));
  CHECK(t == 8500 && p == 120000);
  const auto reject = [&t, &p](const desk_robot::Bmp280Trim& trim,
                              std::uint32_t rt, std::uint32_t rp) {
    t = 1234; p = 56789;
    CHECK(!desk_robot::bmp280_compensate(trim, rt, rp, t, p));
    CHECK(t == 1234 && p == 56789);
  };
  reject(d, 57343, 1018576);
  reject(d, 697345, 928576);
  reject(d, 262144, 1018577);
  reject(d, 262144, 928575);
  d.t2 = 0;
  d.p1 = 32768;
  // Each invalid raw code would otherwise yield an in-range result.
  reject(d, 0x80000U, 500000);
  reject(d, 0x100000U, 500000);
  reject(d, 0xffffffffU, 500000);
  reject(d, 262144, 0x80000U);
  d.p1 = 6250;
  d.p4 = -2500;
  reject(d, 262144, 0x100000U);
  // Extreme representable coefficients exercise all arithmetic before
  // conversion; either reject atomically or publish only bounded values.
  for (const auto signed_rail : {-32768, 32767}) {
    for (const auto unsigned_rail : {1U, 65535U}) {
      d.t1 = d.p1 = static_cast<std::uint16_t>(unsigned_rail);
      d.t2 = d.t3 = d.p2 = d.p3 = d.p4 = d.p5 = d.p6 =
          d.p7 = d.p8 = d.p9 = static_cast<std::int16_t>(signed_rail);
      for (const auto rt : {0U, 0x7ffffU, 0x80001U, 0xfffffU}) {
        for (const auto rp : {0U, 0x7ffffU, 0x80001U, 0xfffffU}) {
          t = 1234; p = 56789;
          if (desk_robot::bmp280_compensate(d, rt, rp, t, p)) {
            CHECK(t >= -4000 && t <= 8500 && p >= 30000 && p <= 120000);
          } else {
            CHECK(t == 1234 && p == 56789);
          }
        }
      }
    }
  }
}

static void check_bmp280_zero_divisor() {
  desk_robot::Bmp280Trim d{};
  d.t1 = 1;
  d.p1 = 65535;
  int t = 0;
  unsigned p = 0;
  // ADC endpoints are not the disabled-conversion sentinel (0x80000).
  CHECK(desk_robot::bmp280_compensate(d, 0, 0, t, p));
  CHECK(t == 0 && p == 100002);
  d.p1 = 6250;
  d.p4 = -6250;
  CHECK(desk_robot::bmp280_compensate(d, 0xfffffU, 0xfffffU, t, p));
  CHECK(t == 0 && p == 100001);
  const auto reject = [&t, &p](const desk_robot::Bmp280Trim& trim,
                              std::uint32_t rt, std::uint32_t rp) {
    t = 1234; p = 56789;
    std::feclearexcept(FE_ALL_EXCEPT);
    CHECK(!desk_robot::bmp280_compensate(trim, rt, rp, t, p));
    CHECK(std::fetestexcept(FE_DIVBYZERO | FE_INVALID | FE_OVERFLOW) == 0);
    CHECK(t == 1234 && p == 56789);
  };
  d.t1 = 0; // otherwise produces a plausible temperature and pressure
  reject(d, 0xfffffU, 0xfffffU);
  d.t1 = 1; d.p1 = 0;
  reject(d, 0xfffffU, 0xfffffU);
  std::uint8_t words[24]{};
  desk_robot::Bmp280Trim decoded{};
  words[6] = 1;
  CHECK(!desk_robot::bmp280_trim(words, decoded));
  words[0] = 1; words[6] = 0;
  CHECK(!desk_robot::bmp280_trim(words, decoded));
  words[6] = 1;
  CHECK(!desk_robot::bmp280_trim(words, decoded));
  // Nonzero P1 is insufficient: these coefficients produce fine=-920576,
  // a=-524288, then a pressure divisor of exactly zero.
  d = {};
  d.t1 = 32768; d.t2 = 28768; d.p1 = 1;
  d.p2 = 32767; d.p3 = -1;
  reject(d, 0, 415148);
}

static void check_bmp280_trim_registers() {
  // Bosch example: negative coefficients and individual zero bytes are legal.
  const std::uint16_t values[] = {27504, 26435, 64536, 36477, 54851, 3024,
                                  2855, 140, 65529, 15500, 50936, 6000};
  std::uint8_t words[24]{};
  for (unsigned i = 0; i < 12; ++i) {
    words[2 * i] = static_cast<std::uint8_t>(values[i]);
    words[2 * i + 1] = static_cast<std::uint8_t>(values[i] >> 8);
  }
  desk_robot::Bmp280Trim decoded{};
  CHECK(desk_robot::bmp280_trim(words, decoded));
  const auto check_preserved = [&decoded]() {
    CHECK(decoded.t1 == 27504 && decoded.t2 == 26435 && decoded.t3 == -1000);
    CHECK(decoded.p1 == 36477 && decoded.p2 == -10685 && decoded.p3 == 3024);
    CHECK(decoded.p4 == 2855 && decoded.p5 == 140 && decoded.p6 == -7);
    CHECK(decoded.p7 == 15500 && decoded.p8 == -14600 && decoded.p9 == 6000);
    int t = 0;
    unsigned p = 0;
    CHECK(desk_robot::bmp280_compensate(decoded, 519888, 415148, t, p));
    CHECK(t == 2508 && p >= 100652 && p <= 100654);
  };
  check_preserved();
  CHECK(!desk_robot::bmp280_trim(nullptr, decoded));
  check_preserved();
  for (unsigned i = 0; i < 12; ++i) {
    for (const auto rail : {0U, 255U}) {
      words[2 * i] = words[2 * i + 1] = static_cast<std::uint8_t>(rail);
      CHECK(!desk_robot::bmp280_trim(words, decoded));
      check_preserved();
    }
    words[2 * i] = static_cast<std::uint8_t>(values[i]);
    words[2 * i + 1] = static_cast<std::uint8_t>(values[i] >> 8);
  }
  CHECK(desk_robot::bmp280_trim(words, decoded));
  check_preserved();
}

int main() {
  try {
    check_register_precision();
    check_bmp280_boundaries();
    check_bmp280_zero_divisor();
    check_bmp280_trim_registers();
    check_gesture_boundaries();
    check_gesture_session_recovery();
    check_gesture_optical_faults();
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
    CHECK(!tag.tag_visible && tag.tag_token == 0U && tag.uid_length == 0U);
    CHECK(tag.tag_events == 1U && tag.scan_seq == 1U);
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
