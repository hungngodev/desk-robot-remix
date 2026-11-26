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
  // Test the math directly, separately from the conservative NVM policy.
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
