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
  bool init(bool = true) { return true; }
  bool timeoutOccurred() { return false; }
  bool setMeasurementTimingBudget(std::uint32_t us) { return us >= 20000U; }
  void startContinuous(std::uint32_t = 0) {}
};
