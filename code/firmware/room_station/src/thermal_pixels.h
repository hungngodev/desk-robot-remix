#pragma once

#include <cstdint>

// Panasonic AMG8833 high-gain pixels: 0x80+2*n low/high, signed 12-bit
// two's-complement, 0.25 C/LSB, specified object range 0..80 C.
// Reference: https://industry.panasonic.eu/products/components/sensors/ir-thermophile-array-sensor-grid-eye
// The pinned Adafruit AMG88xx driver owns initialization; bounded 16-byte
// reads reject invalid data rather than interpreting it as a fresh frame.
namespace desk_robot_room {
inline bool decode_thermal_pixel(std::uint8_t low, std::uint8_t high,
                                 float& temperature_c) {
  const std::uint16_t raw = static_cast<std::uint16_t>(
      (static_cast<std::uint16_t>(high) << 8) | low) & 0x0fffU;
  std::int16_t quarters = static_cast<std::int16_t>(raw);
  if ((raw & 0x0800U) != 0U) quarters -= 4096;
  const float decoded_c = 0.25f * quarters;
  if (decoded_c < 0.0f || decoded_c > 80.0f) return false;
  temperature_c = decoded_c;
  return true;
}

template <typename WireLike>
bool read_thermal_chunk(WireLike& wire, std::uint8_t address,
                        std::uint8_t chunk, float* destination) {
  constexpr std::uint8_t kBytes = 16;
  if (!destination || chunk >= 8U) return false;
  const std::uint8_t reg = static_cast<std::uint8_t>(0x80U + kBytes * chunk);
  wire.beginTransmission(address);
  const bool wrote = wire.write(reg) == 1;
  const int acknowledged = wire.endTransmission(!wrote);
  if (!wrote || acknowledged != 0) return false;
  if (wire.requestFrom(address, kBytes, true) != kBytes ||
      wire.available() < kBytes) return false;
  std::uint8_t raw[kBytes]{};
  for (std::uint8_t i = 0; i < kBytes; ++i) {
    const int value = wire.read();
    if (value < 0) return false;
    raw[i] = static_cast<std::uint8_t>(value);
  }
  // Stage the whole chunk: a late invalid pixel must not expose partial data.
  float staged[kBytes / 2U]{};
  for (std::uint8_t pixel = 0; pixel < kBytes / 2U; ++pixel) {
    if (!decode_thermal_pixel(raw[2U * pixel], raw[2U * pixel + 1U],
                              staged[pixel])) return false;
  }
  for (std::uint8_t pixel = 0; pixel < kBytes / 2U; ++pixel)
    destination[pixel] = staged[pixel];
  return true;
}
}  // namespace desk_robot_room
