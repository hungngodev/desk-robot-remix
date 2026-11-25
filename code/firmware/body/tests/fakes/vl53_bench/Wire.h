#pragma once
#include "Arduino.h"

struct FakeWire {
  bool fail_begin = false, short_write = false, hold_after_stop = false;
  unsigned starts = 0, stops = 0, reads = 0;
  int mux_readback = 1;
  bool begin(int, int, unsigned) { return !fail_begin; }
  void setTimeOut(unsigned) {}
  void beginTransmission(uint8_t) { ++starts; }
  size_t write(uint8_t) { return short_write ? 0 : 1; }
  int endTransmission(bool stop) {
    assert(stop);
    ++stops;
    if (hold_after_stop) stuck_bus = true;
    return 0;
  }
  size_t requestFrom(uint8_t, size_t, bool) { ++reads; return 1; }
  int available() { return 1; }
  int read() { return mux_readback; }
};
inline FakeWire Wire;
