#pragma once

#include <cstdint>

// Panasonic AMG8833 and pinned Adafruit AMG88xx: 0x80+2*n low/high
// pixel registers are signed 12-bit two's-complement, 0.25 C/LSB.
// Pure converter, reusable by host tests and the one shared room station.
namespace desk_robot_room {
inline bool decode_thermal_pixel(std::uint8_t low, std::uint8_t high,
                                 float& temperature_c) {
  const std::uint16_t raw = static_cast<std::uint16_t>(
      (static_cast<std::uint16_t>(high) << 8) | low) & 0x0fffU;
  std::int16_t quarters = static_cast<std::int16_t>(raw);
  if ((raw & 0x0800U) != 0U) quarters -= 4096;
  temperature_c = 0.25f * quarters;
  // Do not turn an out-of-range device value into a credible room sample.
  return temperature_c >= -40.0f && temperature_c <= 125.0f;
}
}  // namespace desk_robot_room
