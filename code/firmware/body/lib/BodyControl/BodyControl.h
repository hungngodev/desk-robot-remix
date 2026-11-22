#pragma once

#include <cstddef>
#include <cstdint>

#include "CliffGuard.h"
#include "BerryImu.h"
#include "OpticalRaw.h"
#include "AccessoryReadings.h"
#include "NecBurst.h"

namespace desk_robot {

// Protocol and direction/PWM conventions adapted from VerdureBuddyRover (MIT).
// See ../../THIRD_PARTY_NOTICES.md. This controller adds a control lease and
// deliberately omits upstream commands that could bypass speed/time limits.
constexpr std::size_t kMaxLineLength = 95;
constexpr std::size_t kReplyCapacity = 1800;  // Worst-case sensor JSON below Sense 1920-byte parser and 2048-byte UART ring
constexpr std::uint32_t kWatchdogMs = 500;
constexpr std::uint32_t kMaxDriveMs = 250;
constexpr int kSpeedLimitPercent = 40;
constexpr int kServoMinDegrees = 60;
constexpr int kServoMaxDegrees = 120;
constexpr std::uint32_t kServoStepMs = 20;  // at most 50 commanded degrees/sec

// Raw 9.7 fixed-point VL53L0X Mcps words, read-only. This does not
// extend cliff safety permission or imply optical calibration.
struct RangeOpticalRaw {
  bool present = false;
  bool valid = false;
  std::uint16_t ambient_97 = 0;
  std::uint16_t signal_97 = 0;
  std::uint32_t at_ms = 0;
};

// Calibrated from the installed, upright MPU6050 rather than assumed axes.
struct ImuAttitudeLimits {
  std::int16_t upright_accel[3]{};
  std::uint16_t min_projection_permille = 0;
  std::uint16_t min_accel_norm_raw = 0;
  std::uint16_t max_accel_norm_raw = 0;
};

// The mounted jaw's force polarity and mechanical travel come only from
// measured physical calibration. No arbitrary remote threshold is trusted.
struct JawForceLimits {
  int open_deg = 0;
  int closed_deg = 0;
  int baseline_adc = 0;
  int force_sign = 0;
  int max_delta_adc = 0;
};

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
  RangeOpticalRaw optical[8]{};
  std::uint16_t side_mm[3]{};
  std::uint32_t side_at_ms[3]{};
  bool side_present[3]{};
  bool side_valid[3]{};
  OpticalRaw paw_pulse{};
  AccessoryReadings accessories{};
  IrPairEvidence terminal_ir{}; // direct two RMT sources, never motion permission
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

enum class BodyProfile { DcPwm, StepperGuarded, DcGuarded };

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
  // A missed CPU heartbeat latches wheels off without dropping jaw PWM.
  // Only an authorized local USB recovery may clear this body fault.
  void motor_watchdog_trip();
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
  // Fresh physical dock switch + charger PGOOD is an independent local
  // DISARM interlock. It never enables charging, nor grants movement.
  void set_accessories(const AccessoryReadings& readings, std::uint32_t now_ms);
  void set_terminal_ir(const IrPairEvidence& evidence) {
    state_.terminal_ir = evidence; // entirely read-only; no arm or charge
  }
  // Full-feature build requires the dock input even if it failed at boot.
  // Cannot be activated or relaxed by UART, AI, or a peer message.
  void require_dock_monitor(bool required) { dock_monitor_required_ = required; }
  // Only the full guarded DRV8833 DC build enables this input at startup.
  // A missing, stale or LOW nFAULT sample latches wheel shutdown, requiring
  // fresh HIGH hardware evidence and local USB rearm, never an AI command.
  void require_dc_driver_fault_monitor(bool required) {
    dc_fault_required_ = required;
    // Even if an early arm request arrives before the first GPIOB poll,
    // startup is a latched unqualified condition. Fresh HIGH nFAULT and a
    // deliberate LOCAL USB rearm are required to enter motion for the first
    // time. Never treat a late healthy read as automatic recovery.
    if (required) dc_fault_latched_ = true;
  }
  // Raw data from the SAME verified VL53L0X conversion as cliff ranges.
  // A stale/broken shared mux immediately revokes valid flags but preserves
  // last raw words for the read-only optical diagnostic endpoint.
  void sample_range_optics(std::uint8_t channel, std::uint16_t ambient_97,
                           std::uint16_t signal_97, bool valid,
                           std::uint32_t now_ms);
  void invalidate_range_optics();

  // Left/right/rear read-only ToF samples never grant motor permission.
  void sample_side_range(std::uint8_t index, std::uint16_t mm,
                         bool valid, std::uint32_t now_ms);
  // Shared I2C mux/bus fault invalidates all cached side/rear validity.
  // Preserve raw values and presence for diagnosis; no motion permission.
  void invalidate_side_ranges();
  // Optional active 3.3V digital inputs; no software can authorize motion.
  // Raw normally closed bumper line is sampled every WROOM loop, before
  // the slower debounce/event classifier. Open circuit stops tracks.
  void sample_bumper_input(bool active);
  void sample_optional_inputs(std::uint8_t enabled_mask, bool bumper,
                              bool reed, bool pir);
  // Boot-time read-only identity; does not confer tilt safety or arm privilege.
  void set_imu_identity(std::uint8_t family, std::uint8_t gyro, std::uint8_t aux);
  // Raw, read-only diagnostics. No tilt or motor permission follows from it.
  void set_imu(const BerryReading& reading);
  // Per-boot provenance for read-only IMU observations; never grants motion.
  void set_boot_epoch(std::uint32_t epoch) { boot_epoch_ = epoch; }
  // Physical WROOM assembly requires a fresh identified 6-axis sample, even
  // though actual tilt thresholds are NOT yet calibrated. DC test profile
  // and host policy tests opt in explicitly rather than changing their ABI.
  void require_imu_for_motion(bool required) { imu_motion_required_ = required; }
  // Full WROOM builds fail closed until an installed-board measurement exists.
  void require_imu_attitude_guard(bool required) { imu_attitude_required_ = required; }
  bool configure_imu_attitude_limits(const ImuAttitudeLimits& limits);
  // Physical full build must never advance an MG90S jaw toward a command
  // target without a recent, unclipped, independently acquired ADS1115
  // channel 1 value. The historical disconnected DC fixture opts out.
  void require_grip_feedback(bool required) { grip_feedback_required_ = required; }
  // Boot-only physical calibration, not a remote command. If omitted the
  // full-profile gripper cannot move; opening relief remains possible after
  // a calibrated high-force reading while ADC evidence is still fresh.
  bool configure_jaw_force_limits(const JawForceLimits& limits);
  // Boot-only, irreversible while running: the stock stepper board lacks
  // a qualified independent rail cutoff, so sensors alone cannot enable it.
  void inhibit_unqualified_motor_cutoff();
  // Only the full battery-powered build opts into this mandatory safety input.
  void require_fuel_monitor(bool required) { fuel_monitor_required_ = required; }
  bool fuel_monitor_fresh(std::uint32_t now_ms) const {
    const auto& f = state_.accessories.gauge;
    return !fuel_provenance_bad_ && f.fuel_present && f.fuel_valid &&
           f.fuel_sample_seq != 0U && now_ms - f.fuel_at_ms < 500U;
  }
  bool grip_feedback_fresh(std::uint32_t now_ms) const {
    const auto& f = state_.accessories.force;
    const bool jaw_valid = (f.valid_mask & 2U) != 0U || (f.valid_mask == 0U && f.valid);
    return f.present && jaw_valid &&
           f.jaw_sample_seq != 0U && now_ms - f.jaw_at_ms < 500U &&
           f.adc[1] != -32768 && f.adc[1] != 32767;
  }
  bool imu_fresh(std::uint32_t now_ms) const {
    // A fresh sample alone cannot authenticate the board. A previously
    // probed WROOM sensor family must agree with the live driver reading.
    // Unknown, absent or swapped identity fails closed for motor readiness.
    // A successful 14-byte I2C transaction can still return an all-zero
    // MPU6050 acceleration frame. That is not evidence of a healthy upright
    // robot: it may be a stuck sensor or a genuine low-g event. Either way
    // fail closed, without guessing a calibrated tilt or pickup threshold.
    const bool mpu_accel_plausible =
        imu_.model != BerryModel::Mpu6050 ||
        imu_.accel[0] != 0 || imu_.accel[1] != 0 || imu_.accel[2] != 0;
    // The MPU silicon already reports its native low-g interrupt. A
    // flagged event is a local wheel veto, never proof of a measured fall.
    // Do not require a Mac callback to notice it, or assume the unqualified
    // 300mg/40ms silicon settings are calibrated pickup thresholds.
    // A failed INT_STATUS read cannot prove that the MPU native free-fall
    // monitor was clear. Keep the wheels disabled until that status is
    // acquired successfully, not merely until the 14-byte axis read succeeds.
    const bool low_g_clear = imu_.model != BerryModel::Mpu6050 ||
        (imu_.low_g_status_valid && !imu_.low_g_irq);
    return state_.imu_family >= 1 && state_.imu_family <= 4 &&
           imu_.model == static_cast<BerryModel>(state_.imu_family) &&
           BerryImu::identify(state_.imu_gyro_id, state_.imu_aux_id) == imu_.model &&
           imu_.valid && !imu_provenance_bad_ &&
           mpu_accel_plausible && low_g_clear &&
           now_ms - imu_.at_ms <= 200U;
  }
  std::uint32_t watchdog_remaining(std::uint32_t now_ms) const;
  std::uint32_t drive_remaining(std::uint32_t now_ms) const;

 private:
  // The full sensor interlock is independent of the selected motor backend.
  // DcPwm is preserved ONLY for the isolated historical DC bench fixture.
  bool guarded_motion_profile() const { return profile_ != BodyProfile::DcPwm; }
  BodyProfile profile_;
  CliffGuard* guard_;
  State state_{};
  BerryReading imu_{};
  std::uint32_t boot_epoch_ = 0;
  bool imu_motion_required_ = false;
  bool imu_attitude_required_ = false;
  bool imu_attitude_configured_ = false;
  bool imu_attitude_latched_ = false;
  ImuAttitudeLimits imu_attitude_limits_{};
  std::uint8_t imu_attitude_bad_streak_ = 0;
  std::uint8_t imu_attitude_good_streak_ = 0;
  bool attitude_sample_unsafe(const BerryReading& reading) const;
  bool attitude_recovery_ready(std::uint32_t now_ms) const;
  bool grip_feedback_required_ = false;
  bool jaw_limits_configured_ = false;
  JawForceLimits jaw_limits_{};
  bool jaw_target_within_limits(int target) const;
  bool jaw_target_closes(int target) const;
  bool jaw_force_allows_closing() const;
  // Maximum four commanded degrees of jaw travel per distinct ADS1115
  // channel-1 conversion. Belly conversions never renew this movement grant.
  std::uint32_t jaw_servo_sample_seq_ = 0;
  std::uint8_t jaw_sample_motion_budget_ = 0;
  bool fuel_monitor_required_ = false;
  // A changed or regressed MAX17048 frame cannot claim a fresh
  // acquisition merely by reusing an already accepted sample identity.
  bool fuel_sample_seen_ = false;
  bool fuel_provenance_bad_ = false;
  std::uint32_t fuel_last_seq_ = 0, fuel_last_at_ms_ = 0;
  unsigned fuel_last_cell_mv_ = 0, fuel_last_soc_centi_ = 0;
  bool motor_cutoff_unqualified_ = false;
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
  bool dock_power_lockout_ = false;  // stays latched across missing I2C samples
  bool dock_sample_seen_ = false;
  std::uint32_t dock_last_seq_ = 0, dock_last_at_ms_ = 0;
  std::uint8_t dock_last_pins_ = 0;
  bool dock_provenance_fault_ = false;  // requires a new GPIOA acquisition
  bool dock_monitor_required_ = false; // full robot build, set at boot only
  bool dock_monitor_fault_latched_ = false; // loss during guarded ARM: USB only
  std::uint32_t dock_monitor_fault_seq_ = 0;
  std::uint32_t dock_monitor_fault_at_ms_ = 0;
  void latch_dock_monitor_fault();
  bool dc_fault_required_ = false;  // fail closed for DRV8833 full DC profile
  bool dc_fault_latched_ = false;   // only local USB may clear
  // A replayed or contradictory GPIOB sample cannot clear nFAULT shutdown.
  bool dc_fault_sample_seen_ = false;
  bool dc_fault_provenance_bad_ = false;
  std::uint32_t dc_fault_last_seq_ = 0, dc_fault_last_at_ms_ = 0;
  bool dc_fault_last_active_ = false;
  bool bumper_fault_latched_ = false; // collision requires local USB recovery
  bool battery_fault_latched_ = false; // guarded motion needs USB recovery
  bool fuel_monitor_fault_latched_ = false; // required physical gauge missing/stale
  std::uint32_t fuel_monitor_fault_seq_ = 0, fuel_monitor_fault_at_ms_ = 0;
  std::uint32_t battery_fault_seq_ = 0, battery_fault_at_ms_ = 0;
  bool motor_watchdog_latched_ = false;  // physical CPU stall, USB only
  bool command_timeout_latched_ = false; // silent head link, USB only
  bool imu_low_g_latched_ = false;  // native MPU event needs local USB rearm
  bool imu_sensor_fault_latched_ = false; // lost live IMU during motion: USB only
  // BerryImu is polled at a slower sensor cadence than the motor loop.
  // Permit identical cached readings, never reordered or contradictory ones.
  bool imu_sample_seen_ = false;
  bool imu_provenance_bad_ = false;
  std::uint32_t imu_last_at_ms_ = 0;
  bool dc_driver_fault_bad(std::uint32_t now_ms) const;
  bool dock_telemetry_bad(std::uint32_t now_ms) const;
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
