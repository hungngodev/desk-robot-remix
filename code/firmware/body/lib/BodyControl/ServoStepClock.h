#pragma once

#include <cstdint>

namespace desk_robot {

constexpr std::uint32_t kServoStepMs = 20;  // at most 50 commanded degrees/sec

// Consume at most one interval on a physical actuator. Discard missed time
// credit, including the fractional remainder, so a delayed loop cannot
// immediately replay another step. Unsigned elapsed handles millis rollover.
// The actuator-inert bench retains its historical simulated catch-up.
inline std::uint32_t take_servo_steps(std::uint32_t now_ms,
                                      std::uint32_t& last_ms,
                                      bool physical_profile) {
  const auto due = (now_ms - last_ms) / kServoStepMs;
  if (due == 0) return 0;
  if (physical_profile) {
    last_ms = now_ms;
    return 1;
  }
  last_ms += due * kServoStepMs;
  return due;
}

}  // namespace desk_robot
