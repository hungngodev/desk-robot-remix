#pragma once

#include <cstddef>
#include <cstdint>

namespace desk_robot {

// Protocol and direction/PWM conventions adapted from VerdureBuddyRover (MIT).
// See ../../THIRD_PARTY_NOTICES.md. This controller adds a control lease and
// deliberately omits upstream commands that could bypass speed/time limits.
constexpr std::size_t kMaxLineLength = 95;
constexpr std::size_t kReplyCapacity = 384;
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

class BodyControl {
 public:
  const State& state() const { return state_; }
  void tick(std::uint32_t now_ms);
  void execute(const char* line, std::size_t length, std::uint32_t now_ms,
               char* reply, std::size_t capacity);
  // Hardware adapter may force disarm on a fault without renewing the lease.
  void force_disarm();
  std::uint32_t watchdog_remaining(std::uint32_t now_ms) const;
  std::uint32_t drive_remaining(std::uint32_t now_ms) const;

 private:
  State state_{};
  std::uint32_t last_control_ms_ = 0;
  std::uint32_t drive_started_ms_ = 0;
  std::uint32_t drive_duration_ms_ = 0;
  std::uint32_t last_servo_step_ms_ = 0;
  void stop_motion();
};

// Each transport has its own bounded receiver. It discards an entire malformed
// or overlong frame, including suffixes that happen to be valid commands.
class LineReceiver {
 public:
  // True only when a newline completes a response; reply has no newline.
  bool feed(char byte, std::uint32_t now_ms, BodyControl& control,
            char* reply, std::size_t capacity);

 private:
  char line_[kMaxLineLength + 1]{};
  std::size_t length_ = 0;
  bool saw_cr_ = false;
  bool invalid_ = false;
  bool overlong_ = false;
};

}  // namespace desk_robot
