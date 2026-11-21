#pragma once
#include <cstdint>

namespace desk_robot_room {
// Upstream BME680 fields are conversion scratch. Retain ONLY a completed,
// validated conversion with its original acquisition timestamp. Starting
// another heater conversion must never alter a published record.
struct BmeCompletedSample {
  float temperature_c = 0;
  float humidity_pct = 0;
  float pressure_pa = 0;
  unsigned gas_ohms = 0;
  std::uint32_t sample_ms = 0;
  bool valid = false;

  void publish(float temp, float humidity, float pressure,
               unsigned gas, std::uint32_t completed_at_ms) {
    temperature_c = temp;
    humidity_pct = humidity;
    pressure_pa = pressure;
    gas_ohms = gas;
    sample_ms = completed_at_ms;
    valid = true;
  }
  void invalidate() { valid = false; }

  bool fresh(std::uint32_t now_ms, std::uint32_t max_age_ms) const {
    return valid && now_ms - sample_ms <= max_age_ms;
  }
};
}  // namespace desk_robot_room
