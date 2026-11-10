#pragma once
#include <cstdint>
namespace desk_robot {
// Fixed-point manufacturer register math. No sensor fusion, no medical data.
inline std::uint8_t sensirion_crc(const std::uint8_t* bytes, unsigned count) {
  std::uint8_t crc = 0xff;
  for (unsigned i = 0; i < count; ++i) {
    crc ^= bytes[i];
    for (int n = 0; n < 8; ++n)
      crc = (crc & 0x80U) ? static_cast<std::uint8_t>((crc << 1) ^ 0x31U)
                          : static_cast<std::uint8_t>(crc << 1);
  }
  return crc;
}
inline int sht_temp_centi(std::uint16_t raw) {
  return -4500 + static_cast<int>((17500L * raw) / 65535L);
}
inline int sht_humidity_centi(std::uint16_t raw) {
  int value = -600 + static_cast<int>((12500L * raw) / 65535L);
  return value < 0 ? 0 : value > 10000 ? 10000 : value;
}
inline unsigned max17048_cell_mv(std::uint16_t raw) {
  return static_cast<unsigned>((static_cast<std::uint32_t>(raw) * 5U) / 64U);
}
inline unsigned max17048_soc_centi(std::uint16_t raw) {
  return static_cast<unsigned>((static_cast<std::uint32_t>(raw) * 100U) / 256U);
}
inline unsigned ina226_bus_mv(std::uint16_t raw) {
  return static_cast<unsigned>((static_cast<std::uint32_t>(raw) * 5U) / 4U);
}
inline int ina226_shunt_uv(std::int16_t raw) {
  return static_cast<int>(raw) * 5 / 2;
}
struct AngleRaw {
  bool present = false, valid = false;
  std::uint16_t angle = 0;
  std::uint8_t magnet_status = 0;
  std::uint32_t at_ms = 0;
};
struct ClimateRaw {
  bool present = false, valid = false;
  int temp_centi = 0, humidity_centi = 0;
  std::uint32_t at_ms = 0;
};
struct ForceRaw {
  bool present = false, valid = false;
  std::uint8_t valid_mask = 0; // both ADC channels need independent fresh samples
  std::int16_t adc[2]{};
  std::uint32_t at_ms = 0;
};
struct GaugeRaw {
  bool fuel_present = false, fuel_valid = false;
  unsigned cell_mv = 0, soc_centi = 0;
  bool monitor_present = false, monitor_valid = false;
  unsigned bus_mv = 0;
  int shunt_uv = 0;
  std::uint32_t at_ms = 0;
};
struct ProximityRaw {
  bool present = false, valid = false;
  std::uint8_t raw = 0;
  std::uint32_t at_ms = 0;
};
struct AccessoryReadings {
  AngleRaw angle[3]{}; // index 0 nose, 1 left track, 2 right track
  ClimateRaw climate{};
  ForceRaw force{};
  GaugeRaw gauge{};
  ProximityRaw proximity{};
};
} // namespace desk_robot
