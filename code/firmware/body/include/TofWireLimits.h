#pragma once

#include <cstdint>

namespace desk_robot {

// Raw VL53L0X driver acceptance, not a calibrated clearance envelope.
constexpr std::uint16_t kTofMinRangeMm = 30U;
constexpr std::uint16_t kTofMaxRangeMm = 1300U;
constexpr std::uint16_t kTofMinSignal97 = 32U;
constexpr std::uint32_t kTofCriticalExpiryMs = 200U;
constexpr std::uint32_t kTofSideExpiryMs = 351U;

// Includes rejection of the device's 8190 mm invalid range word.
constexpr bool tof_range_in_bounds(std::uint16_t mm) noexcept {
  return mm >= kTofMinRangeMm && mm <= kTofMaxRangeMm;
}

}  // namespace desk_robot
