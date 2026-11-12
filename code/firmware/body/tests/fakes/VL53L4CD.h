#pragma once
#include <cstdint>
#include "Wire.h"

// Host-only vendor stub. No physical ranging or sensor initialization is
// established by this mock; tests exercise the adapter's mux and guard wiring.
class VL53L4CD {
 public:
  int last_status = 0;
  void setBus(TwoWire*) {}
  void setTimeout(unsigned) {}
  bool init() { return true; }
  bool timeoutOccurred() { return false; }
  bool setRangeTiming(unsigned, unsigned) { return true; }
  void startContinuous() {}
};
