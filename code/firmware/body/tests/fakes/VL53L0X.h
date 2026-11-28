#pragma once
#include <cstdint>
#include "Wire.h"

// Host-only stand-in for the pinned Pololu VL53L0X API.
// It never claims actual sensor bringup or optical cliff qualification.
class VL53L0X {
 public:
  std::uint8_t last_status = 0;
  void setBus(TwoWire* bus) { bus_ = bus; }
  TwoWire* getBus() { return bus_; }
  void setTimeout(std::uint16_t ms) { timeout_ms_ = ms; }
  std::uint16_t getTimeout() { return timeout_ms_; }
  // Injection points are host-only, shared between the fake translation
  // units. The real sensor still uses the unmodified pinned Pololu driver.
  static bool& fail_init() { static bool flag = false; return flag; }
  static bool& fail_timeout() { static bool flag = false; return flag; }
  static bool& fail_timing_budget() { static bool flag = false; return flag; }
  static bool& fail_start_status() { static bool flag = false; return flag; }
  bool init(bool = true) {
    if (!bus_ || !bus_->connected(0x29)) return false;
    bus_->tof_init_timeouts.push_back(timeout_ms_);
    // Pololu 1.3.1 rejects a non-0xEE model ID before calibration.
    // SPAD discovery and reference phase calibration return false on expiry,
    // without setting the range-read timeoutOccurred() flag.
    if (fail_init() || (bus_->ranges & bus_->tof_wrong_model_lanes)) return false;
    if (bus_->ranges & (bus_->tof_spad_timeout_lanes | bus_->tof_phase_timeout_lanes)) {
      if (timeout_ms_ != 0)
        fake_arduino_millis() += static_cast<std::uint32_t>(timeout_ms_) + 1U;
      return false;
    }
    return true;
  }
  bool timeoutOccurred() {
    const bool timed_out = fail_timeout();
    fail_timeout() = false; // Pololu 1.3.1 consumes the timeout indication
    return timed_out;
  }
  bool setMeasurementTimingBudget(std::uint32_t us) {
    return us >= 20000U && !fail_timing_budget();
  }
  void startContinuous(std::uint32_t = 0) {
    last_status = fail_start_status() ? 4 : 0;
  }

 private:
  TwoWire* bus_ = &Wire;
  std::uint16_t timeout_ms_ = 0;
};
