#pragma once
#include <cstdint>
#include "Wire.h"

// Host-only stand-in for the pinned Pololu VL53L0X API.
// It never claims actual sensor bringup or optical cliff qualification.
class VL53L0X {
 public:
  int last_status = 0;
  void setBus(TwoWire*) {}
  void setTimeout(unsigned) {}
  // Injection points are host-only, shared between the fake translation
  // units. The real sensor still uses the unmodified pinned Pololu driver.
  static bool& fail_init() { static bool flag = false; return flag; }
  static bool& fail_timeout() { static bool flag = false; return flag; }
  static bool& fail_timing_budget() { static bool flag = false; return flag; }
  static bool& fail_start_status() { static bool flag = false; return flag; }
  bool init(bool = true) { return !fail_init(); }
  bool timeoutOccurred() { return fail_timeout(); }
  bool setMeasurementTimingBudget(std::uint32_t us) {
    return us >= 20000U && !fail_timing_budget();
  }
  void startContinuous(std::uint32_t = 0) {
    last_status = fail_start_status() ? 4 : 0;
  }
};
