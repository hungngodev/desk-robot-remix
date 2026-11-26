#pragma once
#include <cstdint>
#include "ApdsOpticalQuality.h"
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
inline bool sht41_frame_crc_valid(const std::uint8_t (&bytes)[6]) {
  return sensirion_crc(bytes, 2) == bytes[2] &&
         sensirion_crc(bytes + 3, 2) == bytes[5];
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
enum class Ina226Fault : std::uint8_t { None, MathOverflow, ShuntSaturated };
// TI INA226 Mask/Enable (0x06), bit 2: current/power arithmetic overflow.
constexpr bool ina226_math_overflow(std::uint16_t status) {
  return (status & 0x0004U) != 0U;
}
inline const char* ina226_fault_name(Ina226Fault fault) {
  switch (fault) {
    case Ina226Fault::MathOverflow: return "math_overflow";
    case Ina226Fault::ShuntSaturated: return "shunt_saturated";
    default: return "none";
  }
}
inline unsigned ina226_bus_mv(std::uint16_t raw) {
  return static_cast<unsigned>((static_cast<std::uint32_t>(raw) * 5U) / 4U);
}
inline bool ina226_bus_mv_from_raw(std::uint16_t raw, unsigned& out_mv) {
  // TI INA226 register 0x02: D15 is always zero; do not refresh on corruption.
  if ((raw & 0x8000U) != 0U) return false;
  out_mv = ina226_bus_mv(raw);
  return true;
}
inline int ina226_shunt_uv(std::int16_t raw) {
  return static_cast<int>(raw) * 5 / 2;
}
// A converted-only +/-81920uV limit misses the positive ADC rail:
// 0x7fff rounds down to 81917uV. Reject BOTH signed saturation codes
// before division; do not assign an old shunt reading a fresh identity.
inline bool ina226_shunt_uv_from_raw(std::uint16_t raw, int& out_uv) {
  if (raw == 0x7fffU || raw == 0x8000U) return false;
  out_uv = ina226_shunt_uv(static_cast<std::int16_t>(raw));
  return true;
}
inline bool ina226_pack_current_ma(int signed_shunt_uv,
                                   unsigned shunt_milliohm, int& out_ma) {
  // TI INA226: +/-81.92mV, 2.5uV LSB. Choose exactly one physically
  // inspected 5mOhm / 2W Kelvin-sensed shunt for pack-line measurements.
  // uV / mOhm = mA. Never guess current from a breakout board's
  // uninspected built-in shunt, nor from CHG/PGOOD indicator pins.
  // Nonrail raw codes span -32767..32766, or -81917..81915uV.
  // Keep this standalone conversion consistent with the raw-code gate.
  if (shunt_milliohm != 5U ||
      signed_shunt_uv < -81917 || signed_shunt_uv > 81915) return false;
  out_ma = signed_shunt_uv / static_cast<int>(shunt_milliohm);
  return true;
}
struct AngleRaw {
  bool present = false, valid = false;
  std::uint16_t angle = 0;
  std::uint8_t magnet_status = 0;
  std::uint32_t at_ms = 0;
  // One identity per successful full AS5600 status AND angle acquisition.
  // This is measured magnet rotation only, not calibrated wheel travel.
  std::uint32_t sample_seq = 0;
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
// Transport or CRC failure invalidates the live sample without advancing
// its acquisition identity or changing previously measured values.
inline void sht41_accept_frame(ClimateRaw& sample, const std::uint8_t (&b)[6],
                               std::uint32_t now_ms, bool transport_valid) {
  sample.valid = transport_valid && sht41_frame_crc_valid(b);
  if (!sample.valid) return;
  const auto t = static_cast<std::uint16_t>((b[0] << 8) | b[1]);
  const auto h = static_cast<std::uint16_t>((b[3] << 8) | b[4]);
  sample.temp_centi = sht_temp_centi(t);
  sample.humidity_centi = sht_humidity_centi(h);
  sample.at_ms = now_ms;
  sample.sample_seq = next_nonzero_sensor_sequence(sample.sample_seq);
}
// ADS1115 datasheet 8.1.3: OS=1 on read means conversion completed.
// Also require the configured single-shot mode and selected channel.
constexpr bool ads1115_completed_for_channel(std::uint16_t config,
                                             std::uint8_t channel) {
  return channel < 2U && (config & 0x8000U) != 0U &&
    (config & 0x7fffU) == (channel == 0U ? 0x4383U : 0x5383U);
}

constexpr bool ads1115_force_raw_valid(std::uint16_t raw) {
  return raw != 0x7fffU && raw != 0x8000U;
}

struct ForceRaw {
  bool present = false, valid = false;
  std::uint8_t valid_mask = 0; // bit 0: belly (ADC channel 0), bit 1: jaw (ADC channel 1)
  std::uint32_t belly_sample_seq = 0; // only increments on fresh ADC channel 0 conversion
  std::uint32_t belly_at_ms = 0; // independent of jaw conversion timestamp
  std::uint32_t jaw_sample_seq = 0; // only increments on fresh ADC channel 1 conversion
  std::uint32_t jaw_at_ms = 0; // independent of belly conversion timestamp
  std::int16_t adc[2]{};
  std::uint32_t at_ms = 0;
};
struct GaugeRaw {
  bool fuel_present = false, fuel_valid = false;
  unsigned cell_mv = 0, soc_centi = 0;
  // Advance only after two valid MAX17048 register reads, not HTTP replay.
  std::uint32_t fuel_sample_seq = 0;
  bool monitor_present = false, monitor_valid = false;
  // Last observed conversion fault; only a clean acquisition clears it.
  Ina226Fault monitor_fault = Ina226Fault::None;
  unsigned bus_mv = 0;
  int shunt_uv = 0;
  // Sign convention only if real pack wiring has charger BAT upstream
  // of the 5mOhm shunt and protected PACK+ downstream: positive = charge.
  // This is calculated raw current, not physical shunt calibration or proof
  // of charging, and is OFF unless a dedicated lab build selects shunt=5.
  int pack_current_ma = 0;
  bool pack_current_valid = false;
  std::uint32_t monitor_sample_seq = 0;
  // Fuel and shunt are independent chip conversions. Their individual last
  // successful read times must not refresh each other across partial faults.
  std::uint32_t fuel_at_ms = 0;
  std::uint32_t monitor_at_ms = 0;
  std::uint32_t at_ms = 0;  // aggregate diagnostic only, never freshness authority
};
struct ProximityRaw {
  bool present = false, valid = false;
  std::uint8_t raw = 0;
  bool saturated() const { return apds_proximity_saturated(raw); }
  std::uint32_t at_ms = 0;
  std::uint8_t gesture_direction = 0; // decoded candidate; not physically qualified
  std::uint32_t gesture_events = 0;
  bool gesture_decoder_available = false;
};
// MCP23017 GPIOA fixed source mapping. PGOOD and CHG are independent,
// active-low charger outputs. Preserve contradictory raw pin evidence so
// local safety and Mac fault diagnostics can reject it.
constexpr bool dock_pgood_asserted(std::uint8_t gpioa) {
  return (gpioa & 0x04U) == 0;
}
constexpr bool dock_chg_asserted(std::uint8_t gpioa) {
  return (gpioa & 0x08U) == 0;
}
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
  // DRV8833 nFAULT, active LOW, wired to MCP23017 GPB3 on the DC profile.
  // Physical wire health requires an external far-end pullup and near-end
  // pulldown; a GPIO read alone cannot certify a connected fault wire.
  bool driver_fault_active = false;
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

  // Discard live UID provenance on a failed transaction or dock boundary.
  // A private historical baseline only suppresses duplicate arrivals; it
  // cannot be exposed as a current tag without a complete validated scan.
  void transport_failed() {
    present = valid = false;
    tag_visible = false;
    tag_token = 0;
    uid_length = 0;
  }
  void completed_scan(bool visible, std::uint32_t token,
                      std::uint8_t uid_len, std::uint32_t now_ms) {
    present = valid = true;
    at_ms = now_ms;
    scan_seq = next_nonzero_sensor_sequence(scan_seq);
    if (visible) {
      if (!last_confirmed_visible_ || last_confirmed_token_ != token)
        tag_events = next_nonzero_sensor_sequence(tag_events);
      tag_visible = true;
      tag_token = token;
      uid_length = uid_len;
    } else {
      tag_visible = false;
      tag_token = 0;
      uid_length = 0;
    }
    last_confirmed_visible_ = visible;
    last_confirmed_token_ = visible ? token : 0U;
  }

 private:
  bool last_confirmed_visible_ = false;
  std::uint32_t last_confirmed_token_ = 0;
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
