#pragma once

#include <stdint.h>

namespace desk_robot_room {

// Sensirion SCD4x: stop_periodic_measurement (0x3F86) needs 500 ms to
// settle before start_periodic_measurement; don't delay inside the loop.
inline bool scd_stop_settled(uint32_t now, uint32_t stop_ms) {
  return now - stop_ms >= 500U;
}

// Require both command bytes and the bus acknowledgement. A buffered write
// can fail even if endTransmission() acknowledges the partial transaction.
template <typename WireLike>
bool scd_request_stop(WireLike& wire, uint8_t address) {
  wire.beginTransmission(address);
  const bool high_ok = wire.write(0x3f) == 1;
  const bool low_ok = wire.write(0x86) == 1;
  const int result = wire.endTransmission();
  return high_ok && low_ok && result == 0;
}

// All three I2C peripherals recover independently. A failed probe must not
// keep the 256 kbaud radar and USB readers out of their normal loop cadence.
class SensorRecoverySchedule {
 public:
  static constexpr uint32_t kRetryMs = 5000U;
  static constexpr uint32_t kMaxRetryMs = 60000U;
  enum Sensor : uint8_t { kScd = 0, kBme = 1, kAmg = 2, kCount = 3 };

  void record_attempt(Sensor sensor, uint32_t now) {
    const unsigned index = static_cast<unsigned>(sensor);
    const uint32_t previous = retry_ms_[index];
    retry_ms_[index] = previous == 0 ? kRetryMs :
        (previous >= kMaxRetryMs / 2U ? kMaxRetryMs : previous * 2U);
    last_attempt_ms_[index] = now;
    last_sensor_ = index;
  }

  // A probe ACK alone is not recovery. Reset only after a complete sample.
  void record_success(Sensor sensor) {
    retry_ms_[static_cast<unsigned>(sensor)] = 0;
  }

  // At most one due I2C re-probe per loop. Unsigned subtraction tolerates
  // the millis() rollover while preserving a minimum retry interval.
  int next(uint32_t now, const bool active[kCount]) {
    for (unsigned offset = 1; offset <= kCount; ++offset) {
      const unsigned index = (last_sensor_ + offset) % kCount;
      if (active[index] ||
          (retry_ms_[index] && now - last_attempt_ms_[index] < retry_ms_[index]))
        continue;
      record_attempt(static_cast<Sensor>(index), now);
      return static_cast<int>(index);
    }
    return -1;
  }

 private:
  uint32_t retry_ms_[kCount] = {};
  uint32_t last_attempt_ms_[kCount] = {};
  unsigned last_sensor_ = kCount - 1U;
};

}  // namespace desk_robot_room
