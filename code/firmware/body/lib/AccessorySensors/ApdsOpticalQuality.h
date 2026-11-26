#pragma once
#include <cstdint>

namespace desk_robot {
// APDS9960 STATUS (0x93): AVALID bit 0, CPSAT bit 7. The ATIME
// register limits usable ADC counts even below the 16-bit register rail.
// Use the conservative 1024 counts/cycle + 1 from the datasheet table.
namespace apds_detail {
// C++11 constexpr bodies permit a single return statement (WROOM toolchain).
constexpr std::uint32_t clamp_rgbc_counts(std::uint32_t counts) {
  return counts < 65535U ? counts : 65535U;
}
} // namespace apds_detail
constexpr std::uint32_t apds_rgbc_ceiling(std::uint8_t atime) {
  return apds_detail::clamp_rgbc_counts(1024U * (256U - atime) + 1U);
}
struct ApdsRgbcQuality {
  bool valid = false;
  bool saturated = false;
  constexpr ApdsRgbcQuality() = default;
  constexpr ApdsRgbcQuality(bool is_valid, bool is_saturated = false)
      : valid(is_valid), saturated(is_saturated) {}
};
namespace apds_detail {
constexpr ApdsRgbcQuality quality_with_limit(
    std::uint8_t status, std::uint32_t limit, std::uint16_t clear,
    std::uint16_t red, std::uint16_t green, std::uint16_t blue) {
  return ((status & 0x80U) != 0U || clear >= limit || red >= limit ||
          green >= limit || blue >= limit)
      ? ApdsRgbcQuality(false, true)
      : ApdsRgbcQuality((status & 0x01U) != 0U, false);
}
} // namespace apds_detail
constexpr ApdsRgbcQuality apds_rgbc_quality(
    std::uint8_t status, std::uint8_t atime, std::uint16_t clear,
    std::uint16_t red, std::uint16_t green, std::uint16_t blue) {
  return apds_detail::quality_with_limit(status, apds_rgbc_ceiling(atime),
                                        clear, red, green, blue);
}
// STATUS bit 1 signals an unread completed proximity conversion.
constexpr bool apds_proximity_ready(std::uint8_t status) {
  return (status & 0x02U) != 0U;
}
constexpr bool apds_proximity_saturated(std::uint8_t raw) {
  return raw == 0xffU;
}
} // namespace desk_robot
