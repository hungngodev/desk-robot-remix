#pragma once

#include <cstddef>
#include <cstdint>

#include "CliffGuard.h"

namespace desk_robot {

// Protocol and direction/PWM conventions adapted from VerdureBuddyRover (MIT).
// See ../../THIRD_PARTY_NOTICES.md. This controller adds a control lease and
// deliberately omits upstream commands that could bypass speed/time limits.
constexpr std::size_t kMaxLineLength = 95;
constexpr std::size_t kReplyCapacity = 640;
constexpr std::uint32_t kWatchdogMs = 500;
constexpr std::uint32_t kMaxDriveMs = 250;
constexpr int kSpeedLimitPercent = 40;
constexpr int kServoMinDegrees = 60;
constexpr int kServoMaxDegrees = 120;
constexpr std::uint32_t kServoStepMs = 20;  // at most 50 commanded degrees/sec

struct State {
  bool armed = false;
  bool servos_attached = false;
  int left = 0;
  int right = 0;
  int lift = 90;       // commanded angle, NOT a position measurement
  int grip = 90;
  int lift_target = 90;
  int grip_target = 90;
};

enum class BodyProfile { DcPwm, StepperGuarded };

class BodyControl {
 public:
  explicit BodyControl(BodyProfile profile = BodyProfile::DcPwm,
                       CliffGuard* guard = nullptr) : profile_(profile), guard_(guard) {}
  const State& state() const { return state_; }
  void tick(std::uint32_t now_ms);
  // Only the local USB receiver grants recovery authority. Network/head jobs
  // may arm an already-clear guard, but cannot clear a latched safety fault.
  void execute(const char* line, std::size_t length, std::uint32_t now_ms,
               char* reply, std::size_t capacity, bool local_safety_rearm = false);
  // Hardware adapter may force disarm on a fault without renewing the lease.
  void force_disarm();
  std::uint32_t watchdog_remaining(std::uint32_t now_ms) const;
  std::uint32_t drive_remaining(std::uint32_t now_ms) const;

 private:
  BodyProfile profile_;
  CliffGuard* guard_;
  State state_{};
  std::uint32_t last_control_ms_ = 0;
  std::uint32_t drive_started_ms_ = 0;
  std::uint32_t drive_duration_ms_ = 0;
  std::uint32_t last_servo_step_ms_ = 0;
  void stop_motion();
  // Local USB only: stage all five measured safety limits atomically.
  // No network or AI path can set or persist them.
  CliffConfig calibration_stage_{};
  std::uint8_t calibration_stage_mask_ = 0;
};

// Each transport has its own bounded receiver. It discards an entire malformed
// or overlong frame, including suffixes that happen to be valid commands.
class LineReceiver {
 public:
  explicit LineReceiver(bool local_safety_rearm = false)
      : local_safety_rearm_(local_safety_rearm) {}
  // True only when a newline completes a response; reply has no newline.
  bool feed(char byte, std::uint32_t now_ms, BodyControl& control,
            char* reply, std::size_t capacity);

 private:
  const bool local_safety_rearm_;
  char line_[kMaxLineLength + 1]{};
  std::size_t length_ = 0;
  bool saw_cr_ = false;
  bool invalid_ = false;
  bool overlong_ = false;
};

}  // namespace desk_robot
