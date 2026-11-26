#pragma once

#include <cstdint>

namespace desk_robot {

struct TofResult {
  std::uint16_t signal_97;
  std::uint16_t ambient_97;
  std::uint16_t distance_mm;
  bool accepted;
};

// ST VL53L0X_GetRangingMeasurementData: signal at 6..7, ambient at
// 8..9, range at 10..11. Pololu 1.3.1 init sets 0.25 Mcps (32 in Q9.7).
// Mirror that minimum, not a guessed SNR or physical qualification.
inline constexpr TofResult decode_tof_result(const std::uint8_t (&raw)[12]) noexcept {
  const auto word = [&raw](unsigned offset) constexpr {
    return static_cast<std::uint16_t>((static_cast<std::uint16_t>(raw[offset]) << 8) |
                                      raw[offset + 1]);
  };
  const auto signal = word(6);
  const auto ambient = word(8);
  const auto distance = word(10);
  const bool valid = ((raw[0] & 0x78U) >> 3) == 11U;
  return {signal, ambient, distance,
          valid && signal >= 32U && distance >= 30U && distance <= 1300U};
}

}  // namespace desk_robot
