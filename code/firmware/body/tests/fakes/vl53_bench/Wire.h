#pragma once
#include "Arduino.h"

struct FakeWire {
  bool fail_begin = false, short_write = false, hold_after_stop = false;
  bool optional_installed = false, optional_stuck = false;
  bool fail_clear = false, short_result = false, hold_after_result = false;
  unsigned starts = 0, stops = 0, reads = 0, results = 0, clears = 0;
  unsigned timeout_ms = 0;
  int mux_readback = -1;
  uint8_t ranges = 0, extras = 0, interrupt_status = 7, raw_status = 11;
  uint16_t mm = 45, signal = 32;
  bool begin(int sda, int scl, unsigned hz) {
    initialized_ = !fail_begin && sda == 21 && scl == 22 && hz == 400000;
    return initialized_;
  }
  void setTimeOut(unsigned ms) { timeout_ms = ms; }
  void beginTransmission(uint8_t address) {
    ++starts;
    assert(!pending_);
    address_ = address;
    writes_ = 0;
  }
  std::size_t write(uint8_t value) {
    if (!initialized_ || short_write || writes_ == 2) return 0;
    data_[writes_++] = value;
    return 1;
  }
  int endTransmission(bool stop) {
    if (stop) ++stops;
    if (!initialized_ || stuck_bus) return 4;
    if (address_ == 0x70 || address_ == 0x71) {
      if (!stop || (address_ == 0x71 && !optional_installed)) return 4;
      if (hold_after_stop) stuck_bus = true;
      if (writes_ == 0) return 0;
      if (writes_ != 1 || data_[0] > 1) return 4;
      if (address_ == 0x70) ranges = data_[0];
      else if (!optional_stuck) extras = data_[0];
      return 0;
    }
    if (address_ != 0x29 || ranges != 1 || extras != 0) return 4;
    if (!stop && writes_ == 1) {
      pending_ = true;
      return 0;
    }
    if (stop && writes_ == 2 && data_[0] == 0x0B && data_[1] == 1) {
      ++clears;
      return fail_clear ? 4 : 0;
    }
    return 4;
  }
  // Match the pinned Arduino-ESP32 2.0.17 overload set. The unused
  // overloads are deleted so an ambiguous or incorrect address cannot
  // silently compile only against this host fake.
  std::size_t requestFrom(uint16_t, std::size_t, bool) = delete;
  uint8_t requestFrom(uint16_t, uint8_t, bool) = delete;
  uint8_t requestFrom(uint16_t, uint8_t, uint8_t) = delete;
  uint8_t requestFrom(uint8_t, uint8_t, uint8_t) = delete;
  uint8_t requestFrom(int, int, int) = delete;
  std::size_t requestFrom(uint8_t address, std::size_t count, bool stop) {
    ++reads;
    size_ = pos_ = 0;
    const bool pending = pending_;
    pending_ = false;
    if (!stop || stuck_bus) return 0;
    if (!pending && count == 1 && address == 0x70) {
      rx_[0] = mux_readback < 0 ? ranges : static_cast<uint8_t>(mux_readback);
      size_ = 1;
    } else if (!pending && count == 1 && address == 0x71 && optional_installed) {
      rx_[0] = extras;
      size_ = 1;
    } else if (pending && address == 0x29 && ranges == 1 && extras == 0) {
      if (data_[0] == 0x13 && count == 1) {
        rx_[0] = interrupt_status;
        size_ = 1;
      } else if (data_[0] == 0x14 && count == 12) {
        ++results;
        rx_.fill(0);
        rx_[0] = static_cast<uint8_t>(raw_status << 3);
        rx_[6] = static_cast<uint8_t>(signal >> 8);
        rx_[7] = static_cast<uint8_t>(signal);
        rx_[10] = static_cast<uint8_t>(mm >> 8);
        rx_[11] = static_cast<uint8_t>(mm);
        size_ = short_result ? 11 : 12;
        if (hold_after_result) stuck_bus = true;
      }
    }
    return size_;
  }
  int available() const { return static_cast<int>(size_ - pos_); }
  int read() { return pos_ < size_ ? rx_[pos_++] : -1; }

 private:
  bool initialized_ = false, pending_ = false;
  uint8_t address_ = 0, data_[2]{};
  unsigned writes_ = 0;
  std::array<uint8_t, 12> rx_{};
  std::size_t size_ = 0, pos_ = 0;
};
inline FakeWire Wire;
