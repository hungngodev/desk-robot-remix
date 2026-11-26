#pragma once

#include <cstdint>

namespace desk_robot {

// A first sample has no predecessor. Subsequent timestamps must advance
// within the unambiguous half of the uint32_t clock domain.
constexpr bool range_sample_accepts(bool present, std::uint32_t now_ms,
                                    std::uint32_t previous_ms) {
  const auto elapsed = now_ms - previous_ms;
  return !present || (elapsed != 0U && elapsed < 0x80000000U);
}

// Critical optical diagnostics expire at 200 ms; read-only side/rear
// diagnostics retain the existing inclusive 350 ms freshness window.
constexpr bool range_sample_expired(bool present, bool critical,
                                    std::uint32_t now_ms,
                                    std::uint32_t sample_ms) {
  const auto age = now_ms - sample_ms;
  return present && (critical ? age >= 200U : age > 350U);
}

}  // namespace desk_robot
