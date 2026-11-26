#pragma once
#include <cstddef>
#include <cstdint>
#include "MuxWrite.h"

namespace desk_robot {
constexpr std::uint8_t kTofSensorAddress = 0x29;

// STOP activates the mux mask. Never read back on held bus lines.
template <typename WireType, typename Idle>
bool checked_mux_mask(WireType& wire, std::uint8_t address,
                      std::uint8_t mask, Idle idle) {
  return idle() && write_mux_mask(wire, address, mask).ok() && idle() &&
      wire.requestFrom(address, static_cast<std::size_t>(1), true) == 1 &&
      wire.available() >= 1 && wire.read() == mask && idle();
}

template <typename WireType>
bool read_tof_register(WireType& wire, std::uint8_t reg,
                       std::uint8_t* out, std::uint8_t length) {
  if (!out || length == 0 || length > 12) return false;
  wire.beginTransmission(kTofSensorAddress);
  const bool written = wire.write(reg) == 1;
  const int result = wire.endTransmission(!written);
  if (!written || result != 0) return false;
  if (wire.requestFrom(kTofSensorAddress, static_cast<std::size_t>(length), true) != length)
    return false;
  for (std::uint8_t n = 0; n < length; ++n) {
    if (wire.available() < 1) return false;
    const int sample = wire.read();
    if (sample < 0) return false;
    out[n] = static_cast<std::uint8_t>(sample);
  }
  return true;
}

template <typename WireType>
bool write_tof_byte(WireType& wire, std::uint8_t reg, std::uint8_t value) {
  wire.beginTransmission(kTofSensorAddress);
  const bool written = wire.write(reg) == 1 && wire.write(value) == 1;
  const int result = wire.endTransmission(true);
  return written && result == 0;
}
}  // namespace desk_robot
