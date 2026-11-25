#pragma once
#include "Wire.h"

struct VL53L0X {
  int last_status = 0;
  bool fail_start = false, timed_out = false, fail_sample = false;
  uint16_t mm = 45;
  unsigned starts = 0, reads = 0;
  void setBus(FakeWire*) {}
  void setTimeout(unsigned) {}
  bool init() { return true; }
  bool setMeasurementTimingBudget(unsigned) { return true; }
  void startContinuous() { ++starts; last_status = fail_start ? 4 : 0; }
  bool timeoutOccurred() { return timed_out; }
  uint16_t readRangeContinuousMillimeters() {
    ++reads;
    last_status = fail_sample ? 4 : 0;
    return mm;
  }
};
