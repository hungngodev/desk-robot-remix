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
  // Conservative CPU scheduling deadline, NOT the measured CD74HC123 RC
  // cutoff. A missed deadline latches LOW even if the old drive lease lives.
  static constexpr std::uint32_t kMissedDeadlineMs = 45;

  // Startup or explicit successful local USB recovery ONLY. A routine stop
  // must not clear a missed heartbeat; the external one-shot can have expired.
  void reset() {
    idle();
    missed_deadline_ = false;
  }

  bool missed_deadline() const { return missed_deadline_; }

  // Caller must already have run local floor, dock and body guards.
  // Return LOW if disarmed, stopped, unavailable or any guard is false.
  bool update(std::uint32_t now_ms, bool local_motion_authorized) {
    // A CPU pause may let the external retriggerable one-shot expire.
    // Check the previous active interval before clearing it on STOP or lease
    // expiry: current permission may already be false when the CPU returns.
    if (active_ && now_ms - last_toggle_ms_ >= kMissedDeadlineMs)
      missed_deadline_ = true;
    if (!local_motion_authorized || missed_deadline_) {
      idle();
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
  void idle() {
    active_ = false;
    high_ = false;
    last_toggle_ms_ = 0;
  }
  bool active_ = false;
  bool high_ = false;
  bool missed_deadline_ = false;
  std::uint32_t last_toggle_ms_ = 0;
};

}  // namespace desk_robot
