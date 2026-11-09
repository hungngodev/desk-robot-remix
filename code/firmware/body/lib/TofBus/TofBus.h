#pragma once

// Five independent ST VL53L4CD measurements via TCA9548A channels 0..4.
// Reuse the pinned Pololu implementation for sensor initialization/ranging,
// but use bounded checked Wire reads on the safety path. The upstream helper
// divides by the reported SPAD count without guarding against zero, so do NOT
// call its read() method in an edge-critical loop.
// Source: https://github.com/pololu/vl53l4cd-arduino
// License: ST/Pololu BSD 3-Clause Clear. This adapter adds no motion authority.

#include <Arduino.h>
#include <Wire.h>
#include <VL53L4CD.h>
#include "CliffGuard.h"

namespace desk_robot {

class TofBus {
 public:
  // These are board pins, not alternate addresses; every device is 0x29.
  bool begin(int sda, int scl, int mux_reset_pin);
  // Poll exactly one channel per call. Never block waiting for ready.
  // Any bus fault or invalid data immediately feeds the local CliffGuard.
  void poll(CliffGuard& guard, std::uint32_t now_ms);
  bool ready() const { return initialized_; }
  std::uint8_t last_channel() const { return next_channel_; }
  std::uint32_t errors() const { return bus_errors_; }

 private:
  static constexpr std::uint8_t kMuxAddress = 0x70;
  static constexpr std::uint8_t kSensorAddress = 0x29;
  static constexpr std::uint8_t kFloorAndFrontCount = 5;
  static constexpr std::uint8_t kMaxSampleBytes = 15;
  TwoWire& wire_ = Wire;
  VL53L4CD device_{};
  std::uint8_t next_channel_ = 0;
  bool initialized_ = false;
  std::uint32_t bus_errors_ = 0;

  bool select(std::uint8_t channel);
  bool read_register(std::uint16_t reg, std::uint8_t* dest, std::uint8_t bytes);
  bool write_byte(std::uint16_t reg, std::uint8_t value);
  void failed(CliffGuard& guard);
};

}  // namespace desk_robot
