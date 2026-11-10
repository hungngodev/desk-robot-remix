#pragma once

#include <cstddef>
#include <cstdint>

#include "CliffGuard.h"
#include "BerryImu.h"
#include "OpticalRaw.h"

namespace desk_robot {

// Protocol and direction/PWM conventions adapted from VerdureBuddyRover (MIT).
// See ../../THIRD_PARTY_NOTICES.md. This controller adds a control lease and
// deliberately omits upstream commands that could bypass speed/time limits.
constexpr std::size_t kMaxLineLength = 95;
constexpr std::size_t kReplyCapacity = 1100;  // under the Sense bridge 1152-byte UART limit
constexpr std::uint32_t kWatchdogMs = 500;
constexpr std::uint32_t kMaxDriveMs = 250;
constexpr int kSpeedLimitPercent = 40;
constexpr int kServoMinDegrees = 60;
constexpr int kServoMaxDegrees = 120;
constexpr std::uint32_t kServoStepMs = 20;  // at most 50 commanded degrees/sec

struct State {
  bool armed = false;
  bool servos_attached = false;
  bool touch_active = false;       // gesture-debounced input
  bool touch_raw_active = false;   // immediate electrical interlock
  std::uint32_t touch_count = 0;  // debounced rising edges
  std::uint32_t touch_taps = 0;
  std::uint32_t touch_double_taps = 0;
  std::uint32_t touch_holds = 0;
  bool cap_valid = false; // read-only CAP1188 zones, never a motor permit
  std::uint8_t cap_mask = 0;
  std::uint32_t cap_events = 0;
  std::uint16_t side_mm[3]{};
  std::uint32_t side_at_ms[3]{};
  bool side_present[3]{};
  bool side_valid[3]{};
  OpticalRaw paw_pulse{};
  std::uint8_t extra_mask = 0; // bumper bit0, reed bit1, PIR bit2
  bool bumper_raw = false;
  bool bumper_active = false;
  bool reed_active = false;
  bool pir_active = false;
  std::uint32_t bumper_events = 0;
  std::uint32_t reed_events = 0;
  std::uint32_t pir_events = 0;
  std::uint8_t imu_family = 0;   // 0 unverified, 1..3 BerryIMU, 4 MPU6050
  std::uint8_t imu_gyro_id = 0;
  std::uint8_t imu_aux_id = 0;
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
  // Hardware GPIO input only; never grants or clears a motion permit.
  void set_touch(bool active, std::uint32_t now_ms = 0);
  // Un-debounced local reflex: even one sensed high stops wheels and ramp,
  // without fabricating a recognized gesture or releasing servo holding PWM.
  void touch_trip();
  void sample_touch_input(bool active);  // raw GPIO level, no gesture count
  // Optional multi-zone petting. No movement authority and no fabricated reads.
  void set_cap(bool valid, std::uint8_t zones);
  // Raw optical paw telemetry; never infer BPM or heartbeat from one FIFO read.
  void set_paw_pulse(const OpticalRaw& sample) { state_.paw_pulse = sample; }
  // Left/right/rear read-only ToF samples never grant motor permission.
  void sample_side_range(std::uint8_t index, std::uint16_t mm,
                         bool valid, std::uint32_t now_ms);
  // Optional active 3.3V digital inputs; no software can authorize motion.
  void sample_optional_inputs(std::uint8_t enabled_mask, bool bumper,
                              bool reed, bool pir);
  // Boot-time read-only identity; does not confer tilt safety or arm privilege.
  void set_imu_identity(std::uint8_t family, std::uint8_t gyro, std::uint8_t aux);
  // Raw, read-only diagnostics. No tilt or motor permission follows from it.
  void set_imu(const BerryReading& reading) { imu_ = reading; }
  // Physical WROOM assembly requires a fresh identified 6-axis sample, even
  // though actual tilt thresholds are NOT yet calibrated. DC test profile
  // and host policy tests opt in explicitly rather than changing their ABI.
  void require_imu_for_motion(bool required) { imu_motion_required_ = required; }
  bool imu_fresh(std::uint32_t now_ms) const {
    return imu_.valid && imu_.model != BerryModel::Unknown &&
           imu_.model != BerryModel::Unsupported320G &&
           now_ms - imu_.at_ms <= 200U;
  }
  std::uint32_t watchdog_remaining(std::uint32_t now_ms) const;
  std::uint32_t drive_remaining(std::uint32_t now_ms) const;

 private:
  BodyProfile profile_;
  CliffGuard* guard_;
  State state_{};
  BerryReading imu_{};
  bool imu_motion_required_ = false;
  std::uint32_t last_control_ms_ = 0;
  std::uint32_t drive_started_ms_ = 0;
  std::uint32_t drive_duration_ms_ = 0;
  std::uint32_t last_servo_step_ms_ = 0;
  std::uint32_t touch_started_ms_ = 0;
  std::uint32_t touch_released_ms_ = 0;
  bool touch_pending_tap_ = false;
  bool touch_hold_emitted_ = false;
  bool cap_initialized_ = false;
  bool extras_initialized_ = false;
  bool extra_candidates_[3]{};
  std::uint8_t extra_streaks_[3]{};
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
