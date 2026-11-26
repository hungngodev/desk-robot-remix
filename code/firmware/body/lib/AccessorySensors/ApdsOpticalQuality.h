#pragma once
#include <cstdint>

namespace desk_robot {
// APDS9960 STATUS (0x93): AVALID bit 0, CPSAT bit 7. The ATIME
// register limits usable ADC counts even below the 16-bit register rail.
// Use the conservative 1024 counts/cycle + 1 from the datasheet table.
constexpr std::uint32_t apds_rgbc_ceiling(std::uint8_t atime) {
  const std::uint32_t counts = 1024U * (256U - atime) + 1U;
  return counts < 65535U ? counts : 65535U;
}
struct ApdsRgbcQuality {
  bool valid;
  bool saturated;
};
constexpr ApdsRgbcQuality apds_rgbc_quality(
    std::uint8_t status, std::uint8_t atime, std::uint16_t clear,
    std::uint16_t red, std::uint16_t green, std::uint16_t blue) {
  const auto limit = apds_rgbc_ceiling(atime);
  const bool saturated = (status & 0x80U) != 0U || clear >= limit ||
                         red >= limit || green >= limit || blue >= limit;
  return {(status & 0x01U) != 0U && !saturated, saturated};
}
constexpr bool apds_proximity_saturated(std::uint8_t raw) {
  return raw == 0xffU;
}
} // namespace desk_robot
