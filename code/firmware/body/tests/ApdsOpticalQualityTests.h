#pragma once
#include "ApdsOpticalQuality.h"

// Deliberately default-initialize, not value-initialize with braces.
constexpr desk_robot::ApdsRgbcQuality cold_rgbc;
static_assert(!cold_rgbc.valid && !cold_rgbc.saturated, "RGB evidence must start invalid");

// These compile-time regressions are included by accessory_math_tests.cpp.
static_assert(desk_robot::apds_rgbc_quality(1, 0, 65534, 0, 0, 0).valid, "Below rail is valid");
static_assert(desk_robot::apds_rgbc_quality(1, 0, 65535, 0, 0, 0).saturated, "Clear rail saturates");
static_assert(!desk_robot::apds_rgbc_quality(1, 0, 65535, 0, 0, 0).valid, "Saturation invalidates RGB");
static_assert(desk_robot::apds_rgbc_quality(1, 0, 0, 65535, 0, 0).saturated, "Red rail saturates");
static_assert(desk_robot::apds_rgbc_quality(1, 0, 0, 0, 65535, 0).saturated, "Green rail saturates");
static_assert(desk_robot::apds_rgbc_quality(1, 0, 0, 0, 0, 65535).saturated, "Blue rail saturates");
static_assert(desk_robot::apds_rgbc_quality(0x81, 0, 10, 10, 10, 10).saturated, "CPSAT wins");
static_assert(!desk_robot::apds_rgbc_quality(0, 0, 10, 10, 10, 10).valid, "Missing AVALID invalidates RGB");
static_assert(desk_robot::apds_rgbc_quality(1, 255, 1024, 0, 0, 0).valid, "Below short exposure ceiling is valid");
static_assert(desk_robot::apds_rgbc_quality(1, 255, 1025, 0, 0, 0).saturated, "Short exposure ceiling saturates");
static_assert(desk_robot::apds_rgbc_quality(1, 0, 0, 0, 0, 0).valid, "Zero counts are valid with AVALID");
static_assert(!desk_robot::apds_proximity_saturated(254), "Below proximity rail is valid");
static_assert(desk_robot::apds_proximity_saturated(255), "Proximity rail saturates");
static_assert(desk_robot::apds_rgbc_ceiling(192) == 65535U, "64 cycles clamp to rail");
static_assert(desk_robot::apds_rgbc_ceiling(193) == 64513U, "63 cycles limit counts");
static_assert(desk_robot::apds_rgbc_quality(0x80, 255, 0, 0, 0, 0).saturated,
              "CPSAT is independent of AVALID");

namespace apds_test {
constexpr bool expect_quality(std::uint8_t status, std::uint8_t atime,
                              std::uint16_t c, std::uint16_t r,
                              std::uint16_t g, std::uint16_t b,
                              bool valid, bool saturated) {
  return desk_robot::apds_rgbc_quality(status, atime, c, r, g, b).valid == valid &&
         desk_robot::apds_rgbc_quality(status, atime, c, r, g, b).saturated == saturated;
}

// Exercise every status byte with clear=0 and clear=1: quality is not a
// color/ambient ratio, and unrelated proximity/interrupt bits must not gate ALS.
constexpr bool status_matrix(unsigned status) {
  return status == 256U ||
      (expect_quality(static_cast<std::uint8_t>(status), 255, 0, 1024, 1, 2,
                      (status & 0x81U) == 1U, (status & 0x80U) != 0U) &&
       expect_quality(static_cast<std::uint8_t>(status), 255, 1, 2, 1024, 0,
                      (status & 0x81U) == 1U, (status & 0x80U) != 0U) &&
       expect_quality(static_cast<std::uint8_t>(status), 255, 0, 0, 0, 1025,
                      false, true) && status_matrix(status + 1U));
}

// Independent exposure oracle: start at the 64-cycle boundary and subtract
// 1024 for each shorter integration interval, rather than reusing the helper.
constexpr std::uint16_t ceiling(unsigned atime) {
  return static_cast<std::uint16_t>(atime <= 192U ? 65535U :
      65537U - 1024U * (atime - 192U));
}
constexpr std::uint16_t channel(unsigned mask, unsigned bit, std::uint16_t limit) {
  return static_cast<std::uint16_t>((mask & bit) ? limit : limit - 1U);
}
constexpr bool channel_matrix(std::uint8_t atime, std::uint16_t limit, unsigned mask) {
  return mask == 16U ||
      (expect_quality(1, atime, channel(mask, 1, limit), channel(mask, 2, limit),
                      channel(mask, 4, limit), channel(mask, 8, limit),
                      mask == 0U, mask != 0U) &&
       expect_quality(0, atime, channel(mask, 1, limit), channel(mask, 2, limit),
                      channel(mask, 4, limit), channel(mask, 8, limit),
                      false, mask != 0U) && channel_matrix(atime, limit, mask + 1U));
}
constexpr bool exposure_matrix(unsigned atime) {
  return atime == 256U ||
      (desk_robot::apds_rgbc_ceiling(static_cast<std::uint8_t>(atime)) == ceiling(atime) &&
       channel_matrix(static_cast<std::uint8_t>(atime), ceiling(atime), 0) &&
       expect_quality(1, static_cast<std::uint8_t>(atime), 0, 0, 0, 65535, false, true) &&
       exposure_matrix(atime + 1U));
}
constexpr bool proximity_matrix(unsigned raw) {
  return raw == 256U ||
      (desk_robot::apds_proximity_saturated(static_cast<std::uint8_t>(raw)) == (raw == 255U) &&
       proximity_matrix(raw + 1U));
}
} // namespace apds_test

static_assert(apds_test::status_matrix(0), "ALS flags must remain independent of other status bits");
static_assert(apds_test::exposure_matrix(0), "All exposure/channel saturation boundaries must hold");
static_assert(apds_test::proximity_matrix(0), "Only the proximity byte rail is digitally saturated");
