#pragma once

#include "CliffGuard.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>

namespace desk_robot {

// Preserve the original WROOM v1 NVS layout, including its unused padding,
// without reading untrusted bytes into a native bool or struct.
using StoredCliffCalibration = std::array<std::uint8_t, 40>;
constexpr std::uint32_t kCalibrationMagic = 0x434C4635U;
constexpr std::uint32_t kCalibrationVersion = 1U;

template <std::size_t N>
inline std::uint32_t read_calibration_le(const std::array<std::uint8_t, N>& bytes,
                                         std::size_t offset, unsigned width) noexcept {
  std::uint32_t value = 0;
  for (unsigned i = 0; i < width; ++i)
    value |= static_cast<std::uint32_t>(bytes[offset + i]) << (8U * i);
  return value;
}

template <std::size_t N>
inline void write_calibration_le(std::array<std::uint8_t, N>& bytes, std::size_t offset,
                                 unsigned width, std::uint32_t value) noexcept {
  for (unsigned i = 0; i < width; ++i)
    bytes[offset + i] = static_cast<std::uint8_t>(value >> (8U * i));
}

inline std::uint32_t stored_calibration_checksum(const StoredCliffCalibration& bytes) noexcept {
  // Original v1 FNV-1a order: flag, four intervals, front limits, freshness.
  // Padding was never checksummed; do not reject legacy nonzero padding.
  std::uint32_t value = 2166136261U;
  auto add = [&value](std::uint8_t byte) { value = (value ^ byte) * 16777619U; };
  add(bytes[8]);
  for (std::size_t i = 10; i < 30; ++i) add(bytes[i]);
  for (std::size_t i = 32; i < 36; ++i) add(bytes[i]);
  return value;
}

inline StoredCliffCalibration encode_stored_calibration(const CliffConfig& config) noexcept {
  StoredCliffCalibration bytes{};
  write_calibration_le(bytes, 0, 4, kCalibrationMagic);
  write_calibration_le(bytes, 4, 4, kCalibrationVersion);
  bytes[8] = valid_stored_calibrated_flag(config) ? 1U : 0U;
  for (std::size_t i = 0; i < kFloorSensorCount; ++i) {
    write_calibration_le(bytes, 10 + 4 * i, 2, config.floor[i].min_mm);
    write_calibration_le(bytes, 12 + 4 * i, 2, config.floor[i].max_mm);
  }
  write_calibration_le(bytes, 26, 2, config.front_obstacle_mm);
  write_calibration_le(bytes, 28, 2, config.front_max_mm);
  write_calibration_le(bytes, 32, 4, config.freshness_ms);
  write_calibration_le(bytes, 36, 4, stored_calibration_checksum(bytes));
  return bytes;
}

inline bool decode_stored_calibration(const StoredCliffCalibration& bytes,
                                      CliffConfig& config) noexcept {
  if (read_calibration_le(bytes, 0, 4) != kCalibrationMagic ||
      read_calibration_le(bytes, 4, 4) != kCalibrationVersion ||
      read_calibration_le(bytes, 36, 4) != stored_calibration_checksum(bytes) ||
      bytes[8] != 1U) return false;
  CliffConfig decoded{};
  decoded.calibrated = true;
  for (std::size_t i = 0; i < kFloorSensorCount; ++i) {
    decoded.floor[i].min_mm = static_cast<std::uint16_t>(read_calibration_le(bytes, 10 + 4 * i, 2));
    decoded.floor[i].max_mm = static_cast<std::uint16_t>(read_calibration_le(bytes, 12 + 4 * i, 2));
  }
  decoded.front_obstacle_mm = static_cast<std::uint16_t>(read_calibration_le(bytes, 26, 2));
  decoded.front_max_mm = static_cast<std::uint16_t>(read_calibration_le(bytes, 28, 2));
  decoded.freshness_ms = read_calibration_le(bytes, 32, 4);
  if (!CliffGuard::valid_config(decoded)) return false;
  config = decoded;
  // Applying calibration still requires configure(), fresh samples and local rearm.
  return true;
}

// The production NVS record wraps the original payload with the factory
// WROOM eFuse MAC and an outer checksum. Never auto-adopt an unbound v1 blob:
// its thresholds might have been measured on a different physical unit.
using CliffCalibrationOwner = std::array<std::uint8_t, 6>;
constexpr std::size_t kCliffOwnerOffset = StoredCliffCalibration{}.size();
constexpr std::size_t kCliffOwnerChecksumOffset = kCliffOwnerOffset + CliffCalibrationOwner{}.size();
using BoundStoredCliffCalibration = std::array<std::uint8_t, kCliffOwnerChecksumOffset + 4>;

inline bool valid_cliff_calibration_owner(const CliffCalibrationOwner& owner) noexcept {
  return (owner[0] & 1U) == 0 &&
         std::any_of(owner.begin(), owner.end(), [](std::uint8_t byte) { return byte != 0; });
}

inline std::uint32_t bound_calibration_checksum(const BoundStoredCliffCalibration& bytes) noexcept {
  std::uint32_t value = 2166136261U;
  for (std::size_t i = 0; i < kCliffOwnerChecksumOffset; ++i)
    value = (value ^ bytes[i]) * 16777619U;
  return value;
}

inline BoundStoredCliffCalibration encode_bound_calibration(
    const CliffConfig& config, const CliffCalibrationOwner& owner) noexcept {
  BoundStoredCliffCalibration bytes{};
  const auto payload = encode_stored_calibration(config);
  std::copy(payload.begin(), payload.end(), bytes.begin());
  std::copy(owner.begin(), owner.end(), bytes.begin() + kCliffOwnerOffset);
  write_calibration_le(bytes, kCliffOwnerChecksumOffset, 4, bound_calibration_checksum(bytes));
  return bytes;
}

inline bool decode_bound_calibration(const BoundStoredCliffCalibration& bytes,
                                     const CliffCalibrationOwner& owner,
                                     CliffConfig& config) noexcept {
  if (!valid_cliff_calibration_owner(owner) ||
      !std::equal(owner.begin(), owner.end(), bytes.begin() + kCliffOwnerOffset) ||
      read_calibration_le(bytes, kCliffOwnerChecksumOffset, 4) !=
          bound_calibration_checksum(bytes)) return false;
  StoredCliffCalibration payload{};
  std::copy_n(bytes.begin(), payload.size(), payload.begin());
  return decode_stored_calibration(payload, config);
}

}  // namespace desk_robot
