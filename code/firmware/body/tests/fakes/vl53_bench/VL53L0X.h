#pragma once
#include "Wire.h"

struct VL53L0X {
  int last_status = 0;
  bool fail_start = false, timed_out = false;
  unsigned starts = 0;
  void setBus(FakeWire*) {}
  void setTimeout(unsigned) {}
  bool init() { return Wire.ranges == 1 && Wire.extras == 0; }
  bool setMeasurementTimingBudget(unsigned) { return true; }
  void startContinuous() { ++starts; last_status = fail_start ? 4 : 0; }
  bool timeoutOccurred() { return timed_out; }
};
