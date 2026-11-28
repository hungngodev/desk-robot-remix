#pragma once
#include "Bmp280Math.h"
#include <cfenv>
#include <stdexcept>

static void check_bmp280_register_rails() {
  // Bosch DS001 rev 1.26, table 17: signed words are two's complement.
  for (std::uint32_t word = 0; word <= 0xffffU; ++word) {
    const std::uint8_t bytes[] = {static_cast<std::uint8_t>(word),
                                  static_cast<std::uint8_t>(word >> 8)};
    const auto expected = static_cast<std::int32_t>(word) -
                          (word >= 32768U ? 65536 : 0);
    CHECK(desk_robot::bmp_u16(bytes) == word);
    CHECK(desk_robot::bmp_s16(bytes) == expected);
  }
  // Exercise every ADC value with the unused low nibble set.
  for (std::uint32_t raw = 0; raw <= 0xfffffU; ++raw) {
    const std::uint8_t bytes[] = {static_cast<std::uint8_t>(raw >> 12),
                                  static_cast<std::uint8_t>(raw >> 4),
                                  static_cast<std::uint8_t>((raw << 4) | 15U)};
    CHECK(desk_robot::bmp280_raw20(bytes) == raw);
  }
}

static void check_bmp280_mixed_coefficient_rails() {
  using desk_robot::Bmp280Trim;
  // These are storage-type bounds, not guaranteed physical factory trims.
  // Test the math directly, separately from NVM block validation.
  constexpr std::uint32_t adc[] = {0, 0x7ffffU, 0x80000U, 0x80001U,
                                   0xfffffU, 0x100000U, 0xffffffffU};
  unsigned accepted = 0;
  for (unsigned mask = 0; mask < 4096U; ++mask) {
    Bmp280Trim d{};
    d.t1 = (mask & 1U) ? 65535U : 1U;
    d.p1 = (mask & 2U) ? 65535U : 1U;
    std::int16_t* fields[] = {&d.t2, &d.t3, &d.p2, &d.p3, &d.p4,
                              &d.p5, &d.p6, &d.p7, &d.p8, &d.p9};
    for (unsigned i = 0; i < 10; ++i)
      *fields[i] = (mask & (4U << i)) ? 32767 : -32768;
    for (auto rt : adc) {
      for (auto rp : adc) {
        int t = 12345;
        unsigned p = 6789;
        std::feclearexcept(FE_ALL_EXCEPT);
        const bool ok = desk_robot::bmp280_compensate(d, rt, rp, t, p);
        CHECK(std::fetestexcept(FE_DIVBYZERO | FE_INVALID | FE_OVERFLOW) == 0);
        if (rt == 0x80000U || rp == 0x80000U || rt > 0xfffffU || rp > 0xfffffU)
          CHECK(!ok);
        if (ok) {
          ++accepted;
          CHECK(t >= -4000 && t <= 8500 && p >= 30000 && p <= 120000);
        } else {
          CHECK(t == 12345 && p == 6789);
        }
      }
    }
  }
  CHECK(accepted > 0); // reject-all must not satisfy the matrix
}

static void check_bmp280_signed_trim_words() {
  using desk_robot::Bmp280Trim;
  constexpr unsigned offsets[] = {2, 4, 8, 10, 12, 14, 16, 18, 20, 22};
  constexpr std::int16_t Bmp280Trim::* fields[] = {
      &Bmp280Trim::t2, &Bmp280Trim::t3, &Bmp280Trim::p2, &Bmp280Trim::p3,
      &Bmp280Trim::p4, &Bmp280Trim::p5, &Bmp280Trim::p6, &Bmp280Trim::p7,
      &Bmp280Trim::p8, &Bmp280Trim::p9};
  // Every combination of signed zero and -1 must decode, not just one
  // isolated word; the nonzero unsigned anchors distinguish erased NVM.
  for (unsigned mask = 0; mask < 1024U; ++mask) {
    std::uint8_t words[24]{};
    words[0] = 0x70; words[1] = 0x6b;
    words[6] = 0x7d; words[7] = 0x8e;
    for (unsigned i = 0; i < 10; ++i)
      words[offsets[i]] = words[offsets[i] + 1] = (mask & (1U << i)) ? 255U : 0U;
    Bmp280Trim decoded{};
    CHECK(desk_robot::bmp280_trim(words, decoded));
    CHECK(decoded.t1 == 27504 && decoded.p1 == 36477);
    for (unsigned i = 0; i < 10; ++i)
      CHECK(decoded.*fields[i] == ((mask & (1U << i)) ? -1 : 0));
  }
}

static void check_bmp280_invalid_blocks() {
  using desk_robot::Bmp280Trim;
  std::uint8_t words[24]{};
  words[1] = 64; words[6] = 106; words[7] = 24;
  Bmp280Trim decoded{};
  CHECK(desk_robot::bmp280_trim(words, decoded));
  int t = 1234; unsigned p = 56789;
  CHECK(desk_robot::bmp280_compensate(decoded, 262144, 948576, t, p));
  CHECK(t == 0 && p == 100000);
  const auto preserved = [&]() {
    CHECK(decoded.t1 == 16384 && decoded.p1 == 6250);
    CHECK(decoded.t2 == 0 && decoded.t3 == 0 && decoded.p2 == 0 && decoded.p3 == 0);
    CHECK(decoded.p4 == 0 && decoded.p5 == 0 && decoded.p6 == 0 && decoded.p7 == 0);
    CHECK(decoded.p8 == 0 && decoded.p9 == 0);
  };
  CHECK(!desk_robot::bmp280_trim(nullptr, decoded)); preserved();
  words[1] = 0;
  CHECK(!desk_robot::bmp280_trim(words, decoded)); preserved();
  words[1] = 64; words[6] = words[7] = 0;
  CHECK(!desk_robot::bmp280_trim(words, decoded)); preserved();
  for (auto& byte : words) byte = 0;
  CHECK(!desk_robot::bmp280_trim(words, decoded)); preserved();
  for (auto& byte : words) byte = 255;
  CHECK(!desk_robot::bmp280_trim(words, decoded)); preserved();
  words[2] = 0;
  CHECK(desk_robot::bmp280_trim(words, decoded));
  CHECK(decoded.t1 == 65535U && decoded.p1 == 65535U && decoded.t2 == -256);
}
