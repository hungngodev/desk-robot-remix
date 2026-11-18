#pragma once

#if (defined(DESK_ROBOT_STEPPER) && DESK_ROBOT_STEPPER) || \
    (defined(DESK_ROBOT_FULL_SENSORS) && DESK_ROBOT_FULL_SENSORS)
#include <Arduino.h>
#include <Wire.h>

namespace desk_robot {
// Bounded, read-only CAP1188 8 electrode polling. Datasheet ID: 0xFD=0x50,
// 0xFE=0x5D, sensor input register 0x03. Prefer common breakout default
// 0x29; also accept 0x28 only after real chip ID verification. The optional
// 0x71 lane is isolated from range 0x70 before probing either address.
// No local motor permission or stop override is implemented here.
class ExpansionTouch {
 public:
  bool begin(TwoWire& wire);
  bool poll(std::uint32_t now_ms, std::uint8_t& zones);
  bool present() const { return present_; }
  bool verified() const { return verified_; }
 private:
  static constexpr std::uint8_t kRangeMux = 0x70;
  static constexpr std::uint8_t kExpansionMux = 0x71;
  static constexpr std::uint8_t kPreferredAddress = 0x29;
  static constexpr std::uint8_t kAlternativeAddress = 0x28;
  std::uint8_t address_ = kPreferredAddress;
  TwoWire* wire_ = nullptr;
  bool present_ = false;
  bool verified_ = false;
  bool polled_ = false;
  std::uint32_t last_ms_ = 0;
  bool mux(std::uint8_t address, std::uint8_t mask);
  bool select();
  bool close();
  bool read(std::uint8_t reg, std::uint8_t& value);
  bool write(std::uint8_t reg, std::uint8_t value);
};
} // namespace desk_robot
#endif
