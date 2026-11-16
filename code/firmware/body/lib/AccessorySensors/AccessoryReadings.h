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
  std::uint32_t sample_seq = 0; // increments only after complete CRC-valid SHT41 read
};
struct BarometerRaw {
  bool present = false, valid = false;
  std::uint8_t address = 0, chip_id = 0;
  int temp_centi = 0;
  unsigned pressure_pa = 0;
  std::uint32_t at_ms = 0;
  std::uint32_t sample_seq = 0; // successive independently spaced BMP280 conversions
};
// Zero denotes no completed conversion. Preserve that sentinel at uint32 wrap.
constexpr std::uint32_t next_nonzero_sensor_sequence(std::uint32_t previous) {
  return previous == 0xffffffffU ? 1U : previous + 1U;
}
// ADS1115 datasheet 8.1.3: OS=1 on read means conversion completed.
// Also require the configured single-shot mode and selected channel.
constexpr bool ads1115_completed_for_channel(std::uint16_t config,
                                             std::uint8_t channel) {
  return channel < 2U && (config & 0x8000U) != 0U &&
    (config & 0x7fffU) == (channel == 0U ? 0x4383U : 0x5383U);
}

struct ForceRaw {
  bool present = false, valid = false;
  std::uint8_t valid_mask = 0; // both ADC channels need independent fresh samples
  std::uint32_t jaw_sample_seq = 0; // only increments on fresh ADC channel 1 conversion
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
  std::uint8_t gesture_direction = 0; // decoded candidate; not physically qualified
  std::uint32_t gesture_events = 0;
  bool gesture_decoder_available = false;
};
struct DockPinRaw {
  bool present = false, valid = false;
  bool left_seated = false, right_seated = false;
  bool input_good = false, charge_indicated = false;
  std::uint32_t at_ms = 0;
  // Increment ONLY after a newly completed MCP23017 GPIOA read.
  // A repeated HTTP/UART cache response cannot fake independent samples.
  std::uint32_t sample_seq = 0;
};
// Slow optional accessory inputs do not need microsecond timing. The
// compulsory MCP23017 GPIOA dock interlock remains a separate fresh sample.
// GPIOB0: reed closed LOW, GPIOB1: PIR active HIGH. BANK=0 register map.
struct McpOptionalRaw {
  bool present = false, valid = false;
  bool reed_closed = false, pir_active = false;
  std::uint32_t at_ms = 0, sample_seq = 0;
};
struct NfcRaw {
  bool present = false; // only after genuine SAM + retry configuration
  bool valid = false;   // last full PN532 frame decoded with correct checksum
  bool tag_visible = false;
  std::uint8_t uid_length = 0; // only 4/7/10 ISO14443A UIDs
  std::uint32_t tag_token = 0; // FNV game token, never authentication
  std::uint32_t tag_events = 0; // increments on newly presented real tag
  std::uint32_t scan_seq = 0;   // completed independent PN532 scans
  std::uint32_t at_ms = 0;
};
struct AccessoryReadings {
  AngleRaw angle[3]{}; // index 0 nose, 1 left track, 2 right track
  ClimateRaw climate{};
  BarometerRaw barometer{}; // user's BMP280, independent of SHT41
  ForceRaw force{};
  GaugeRaw gauge{};
  DockPinRaw dock{};
  McpOptionalRaw optional_inputs{}; // read-only expander, not a dock safety input
  NfcRaw nfc{}; // optional toy tag reading, never arm/dock authority
  ProximityRaw proximity{};
};
} // namespace desk_robot
