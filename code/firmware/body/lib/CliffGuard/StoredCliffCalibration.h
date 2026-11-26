#pragma once

#include "CliffGuard.h"

#include <array>
#include <cstddef>
#include <cstdint>

namespace desk_robot {

// Preserve the original WROOM v1 NVS layout, including its unused padding,
// without reading untrusted bytes into a native bool or struct.
using StoredCliffCalibration = std::array<std::uint8_t, 40>;
constexpr std::uint32_t kCalibrationMagic = 0x434C4635U;
constexpr std::uint32_t kCalibrationVersion = 1U;

inline std::uint32_t read_calibration_le(const StoredCliffCalibration& bytes,
                                         std::size_t offset, unsigned width) noexcept {
  std::uint32_t value = 0;
  for (unsigned i = 0; i < width; ++i)
    value |= static_cast<std::uint32_t>(bytes[offset + i]) << (8U * i);
  return value;
}

inline void write_calibration_le(StoredCliffCalibration& bytes, std::size_t offset,
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
  config = decoded;
  // The caller must apply CliffGuard::configure to validate physical bounds.
  return true;
}

}  // namespace desk_robot
