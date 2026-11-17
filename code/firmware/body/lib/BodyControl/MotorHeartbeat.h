#pragma once

#include <cstdint>

namespace desk_robot {

// A CPU-driven changing output for an EXTERNAL independently timed motor
// driver nSLEEP gate. Never use a peripheral PWM, LEDC timer, I2C latch or
// network keepalive as watchdog evidence: those can keep toggling or stay high
// while the application is stalled. The physical timeout is not verified here.
class MotorHeartbeat {
 public:
  static constexpr std::uint32_t kToggleIntervalMs = 15;

  void reset() {
    active_ = false;
    high_ = false;
    last_toggle_ms_ = 0;
  }

  // Caller must already have run local floor, dock and body guards.
  // Return LOW if disarmed, stopped, unavailable or any guard is false.
  bool update(std::uint32_t now_ms, bool local_motion_authorized) {
    if (!local_motion_authorized) {
      reset();
      return false;
    }
    if (!active_) {
      active_ = true;
      high_ = true;
      last_toggle_ms_ = now_ms;
      return high_;
    }
    if (now_ms - last_toggle_ms_ >= kToggleIntervalMs) {
      high_ = !high_;
      last_toggle_ms_ = now_ms;
    }
    return high_;
  }

 private:
  bool active_ = false;
  bool high_ = false;
  std::uint32_t last_toggle_ms_ = 0;
};

}  // namespace desk_robot
