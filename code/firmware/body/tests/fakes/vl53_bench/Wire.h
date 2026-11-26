#pragma once
#include "Arduino.h"

struct FakeWire {
  bool fail_begin = false, short_write = false, hold_after_stop = false;
  unsigned starts = 0, stops = 0, reads = 0;
  int mux_readback = 1;
  bool begin(int sda, int scl, unsigned hz) {
    initialized_ = !fail_begin && sda == 21 && scl == 22 && hz == 400000;
    transmitting_ = selected_ = readable_ = false;
    return initialized_;
  }
  void setTimeOut(unsigned) {}
  void beginTransmission(std::uint8_t address) {
    ++starts;
    address_ = address;
    transmitting_ = initialized_;
    writes_ = 0;
    selected_ = readable_ = false;
  }
  std::size_t write(std::uint8_t value) {
    if (!transmitting_ || short_write) return 0;
    ++writes_;
    value_ = value;
    return 1;
  }
  int endTransmission(bool stop) {
    if (stop) ++stops;
    const bool valid = transmitting_ && stop && address_ == 0x70 &&
        writes_ == 1 && value_ == 1;
    transmitting_ = false;
    selected_ = valid;
    if (stop && hold_after_stop) stuck_bus = true;
    return valid ? 0 : 4;
  }
  std::size_t requestFrom(std::uint8_t address, std::size_t count, bool stop) {
    ++reads;
    readable_ = selected_ && address == 0x70 && count == 1 && stop && !stuck_bus;
    return readable_ ? 1 : 0;
  }
  int available() const { return readable_ ? 1 : 0; }
  int read() {
    if (!readable_) return -1;
    readable_ = false;
    return mux_readback;
  }

 private:
  bool initialized_ = false, transmitting_ = false;
  bool selected_ = false, readable_ = false;
  std::uint8_t address_ = 0, value_ = 0;
  unsigned writes_ = 0;
};
inline FakeWire Wire;
