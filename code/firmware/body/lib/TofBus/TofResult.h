#pragma once

#include <cstdint>

namespace desk_robot {

struct TofResult {
  std::uint16_t signal_97;
  std::uint16_t ambient_97;
  std::uint16_t distance_mm;
  bool accepted;
};

namespace detail {
// Single-return constexpr helpers also compile with the WROOM C++11 toolchain.
inline constexpr std::uint16_t tof_result_word(
    const std::uint8_t (&raw)[12], unsigned offset) noexcept {
  return static_cast<std::uint16_t>((static_cast<std::uint16_t>(raw[offset]) << 8) |
                                    raw[offset + 1]);
}

inline constexpr TofResult make_tof_result(std::uint8_t status, std::uint16_t signal,
                                           std::uint16_t ambient,
                                           std::uint16_t distance) noexcept {
  return {signal, ambient, distance,
          ((status & 0x78U) >> 3) == 11U && signal >= 32U &&
              distance >= 30U && distance <= 1300U};
}
}  // namespace detail

// ST VL53L0X_GetRangingMeasurementData: signal at 6..7, ambient at
// 8..9, range at 10..11. Pololu 1.3.1 init sets 0.25 Mcps (32 in Q9.7).
// Mirror that minimum, not a guessed SNR or physical qualification.
inline constexpr TofResult decode_tof_result(const std::uint8_t (&raw)[12]) noexcept {
  return detail::make_tof_result(raw[0], detail::tof_result_word(raw, 6),
                                 detail::tof_result_word(raw, 8),
                                 detail::tof_result_word(raw, 10));
}

}  // namespace desk_robot
