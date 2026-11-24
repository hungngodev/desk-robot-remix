#include "BodyControl.h"
#include "CliffGuard.h"

#include <cstdio>
#include <cstring>

namespace desk_robot {
namespace {
// This is a compile choice for the selected MAX30102 FIFO carrier, not
// an optical proof that the received PCB routes its red and IR LEDs that way.
#if defined(DESK_ROBOT_MAX30102_FIFO_IR_FIRST) && DESK_ROBOT_MAX30102_FIFO_IR_FIRST
constexpr const char* kPulseIrFirstJson = "true";
#else
constexpr const char* kPulseIrFirstJson = "false";
#endif

bool parse_integer(const char* value, int& result) {
  bool negative = false;
  if (*value == '-') {
    negative = true;
    ++value;
  }
  if (*value == '\0') return false;
  int parsed = 0;
  for (; *value != '\0'; ++value) {
    if (*value < '0' || *value > '9') return false;
    const int digit = *value - '0';
    // Bound before multiplication: prevents signed overflow for hostile input.
    if (parsed > (1000000 - digit) / 10) return false;
    parsed = parsed * 10 + digit;
  }
  result = negative ? -parsed : parsed;
  return true;
}

int limited_speed(int speed) {
  if (speed > kSpeedLimitPercent) return kSpeedLimitPercent;
  if (speed < -kSpeedLimitPercent) return -kSpeedLimitPercent;
  return speed;
}

void move_toward(int& current, int target, std::uint32_t steps) {
  const int difference = target - current;
  if (difference > 0) {
    current += steps >= static_cast<std::uint32_t>(difference)
                   ? difference
                   : static_cast<int>(steps);
  } else if (difference < 0) {
    current -= steps >= static_cast<std::uint32_t>(-difference)
                   ? -difference
                   : static_cast<int>(steps);
  }
}

}  // namespace

bool BodyControl::configure_lift_travel_limits(const LiftTravelLimits& limits) {
  // Limit selection is a boot-time physical measurement, not a UART or
  // model command. Never adjust a live attached servo's safety envelope.
  if (lift_limits_configured_ || state_.armed || state_.servos_attached ||
      state_.lift != state_.lift_target ||
      limits.min_deg < kServoMinDegrees ||
      limits.max_deg > kServoMaxDegrees ||
      limits.min_deg >= limits.max_deg ||
      state_.lift < limits.min_deg || state_.lift > limits.max_deg) {
    return false;
  }
  lift_limits_ = limits;
  lift_limits_configured_ = true;
  return true;
}

bool BodyControl::configure_jaw_force_limits(const JawForceLimits& limits) {
  // A running session cannot revise its own jaw safety authority.
  if (jaw_limits_configured_ || state_.armed ||
      state_.grip != state_.grip_target ||
      limits.open_deg < kServoMinDegrees ||
      limits.open_deg > kServoMaxDegrees ||
      limits.closed_deg < kServoMinDegrees ||
      limits.closed_deg > kServoMaxDegrees ||
      limits.open_deg == limits.closed_deg ||
      limits.baseline_adc <= -32768 || limits.baseline_adc >= 32767 ||
      (limits.force_sign != 1 && limits.force_sign != -1) ||
      limits.max_delta_adc < 1 || limits.max_delta_adc > 30000) {
    return false;
  }
  const int32_t limit_adc = static_cast<int32_t>(limits.baseline_adc) +
      static_cast<int32_t>(limits.force_sign) * limits.max_delta_adc;
  if (limit_adc <= -32768 || limit_adc >= 32767 ||
      state_.grip < (limits.open_deg < limits.closed_deg ?
                     limits.open_deg : limits.closed_deg) ||
      state_.grip > (limits.open_deg > limits.closed_deg ?
                     limits.open_deg : limits.closed_deg)) return false;
  jaw_limits_ = limits;
  jaw_limits_configured_ = true;
  jaw_sample_motion_budget_ = 0;
  return true;
}

bool BodyControl::jaw_target_within_limits(int target) const {
  if (!jaw_limits_configured_) return false;
  const int low = jaw_limits_.open_deg < jaw_limits_.closed_deg ?
      jaw_limits_.open_deg : jaw_limits_.closed_deg;
  const int high = jaw_limits_.open_deg > jaw_limits_.closed_deg ?
      jaw_limits_.open_deg : jaw_limits_.closed_deg;
  return target >= low && target <= high;
}

bool BodyControl::jaw_target_closes(int target) const {
  return (target - state_.grip) *
      (jaw_limits_.closed_deg - jaw_limits_.open_deg) > 0;
}

bool BodyControl::jaw_force_allows_closing() const {
  if (!jaw_limits_configured_) return false;
  const auto& force = state_.accessories.force;
  const int32_t delta = (static_cast<int32_t>(force.adc[1]) -
                         jaw_limits_.baseline_adc) * jaw_limits_.force_sign;
  // A large reverse signal is not proof of zero load. Permit bounded
  // measurement noise without accepting reversed/saturated contact data.
  const int32_t tolerance = jaw_limits_.max_delta_adc / 3 > 40 ?
      jaw_limits_.max_delta_adc / 3 : 40;
  return delta < jaw_limits_.max_delta_adc && delta >= -tolerance;
}

bool BodyControl::configure_imu_attitude_limits(const ImuAttitudeLimits& limits) {
  if (imu_attitude_configured_ || state_.armed ||
      limits.min_projection_permille < 500U ||
      limits.min_projection_permille > 990U ||
      limits.min_accel_norm_raw < 8000U ||
      limits.max_accel_norm_raw > 30000U ||
      limits.max_accel_norm_raw <= limits.min_accel_norm_raw) return false;
  std::int64_t norm_sq = 0;
  for (const auto axis : limits.upright_accel)
    norm_sq += static_cast<std::int64_t>(axis) * axis;
  const auto low = static_cast<std::int64_t>(limits.min_accel_norm_raw);
  const auto high = static_cast<std::int64_t>(limits.max_accel_norm_raw);
  if (norm_sq < low * low || norm_sq > high * high) return false;
  imu_attitude_limits_ = limits;
  imu_attitude_configured_ = true;
  imu_attitude_bad_streak_ = 0;
  imu_attitude_good_streak_ = 0;
  return true;
}

// Floor integer square root, using the classical base-four bit method.
// Each accelerometer vector is bounded to three signed 16-bit axes; this
// preserves deterministic WROOM behavior without floating-point sensor
// authorization or an intermediate squared-product overflow.
static std::uint32_t attitude_norm_root(std::uint64_t value) {
  std::uint64_t root = 0;
  std::uint64_t bit = static_cast<std::uint64_t>(1) << 62;
  while (bit > value) bit >>= 2;
  while (bit != 0) {
    if (value >= root + bit) {
      value -= root + bit;
      root = (root >> 1) + bit;
    } else {
      root >>= 1;
    }
    bit >>= 2;
  }
  return static_cast<std::uint32_t>(root);
}

bool BodyControl::attitude_sample_unsafe(const BerryReading& reading) const {
  if (!imu_attitude_configured_ || reading.model != BerryModel::Mpu6050 ||
      !reading.valid || !reading.low_g_status_valid || reading.low_g_irq)
    return true;
  std::int64_t norm_sq = 0, upright_sq = 0, projection = 0;
  for (unsigned i = 0; i < 3; ++i) {
    const auto axis = static_cast<std::int64_t>(reading.accel[i]);
    const auto upright = static_cast<std::int64_t>(imu_attitude_limits_.upright_accel[i]);
    norm_sq += axis * axis;
    upright_sq += upright * upright;
    projection += axis * upright;
  }
  const auto low = static_cast<std::int64_t>(imu_attitude_limits_.min_accel_norm_raw);
  const auto high = static_cast<std::int64_t>(imu_attitude_limits_.max_accel_norm_raw);
  if (norm_sq < low * low || norm_sq > high * high) return true;
  // Normalize the dot product by BOTH magnitudes. Using upright_sq alone
  // would admit a tilted but accelerated vector inside a wide norm envelope.
  // Round roots upward to avoid a weak (unsafe) boundary from truncation.
  auto measured_norm = attitude_norm_root(static_cast<std::uint64_t>(norm_sq));
  auto upright_norm = attitude_norm_root(static_cast<std::uint64_t>(upright_sq));
  if (static_cast<std::int64_t>(measured_norm) * measured_norm < norm_sq)
    ++measured_norm;
  if (static_cast<std::int64_t>(upright_norm) * upright_norm < upright_sq)
    ++upright_norm;
  const auto minimum_projection =
      static_cast<std::int64_t>(upright_norm) * measured_norm *
      imu_attitude_limits_.min_projection_permille;
  return projection * 1000 < minimum_projection;
}

bool BodyControl::attitude_recovery_ready(std::uint32_t now_ms) const {
  return imu_attitude_configured_ && imu_fresh(now_ms) &&
         imu_attitude_good_streak_ >= 2 && imu_attitude_bad_streak_ == 0;
}

void BodyControl::stop_motion() {
  state_.left = 0;
  state_.right = 0;
  drive_duration_ms_ = 0;
  state_.lift_target = state_.lift;
  state_.grip_target = state_.grip;
  jaw_sample_motion_budget_ = 0; // canceled commands cannot reuse jaw credit
}

void BodyControl::touch_trip() {
  if (state_.armed) {
    // Never touch servo PWM attachment here: gripper may hold a key.
    stop_motion();
    state_.armed = false;
  }
}

void BodyControl::sample_touch_input(bool active) {
  state_.touch_raw_active = active;
  if (active) touch_trip();  // before debounce and before motor output
}

void BodyControl::sample_range_optics(
    std::uint8_t channel, std::uint16_t ambient_97,
    std::uint16_t signal_97, bool valid, std::uint32_t now_ms) {
  if (channel >= 8) return;
  auto& sample = state_.optical[channel];
  if (sample.present) {
    // A late or duplicate conversion cannot replace the newest raw
    // observation or regain valid read-only optical provenance. A genuinely
    // newer measurement restores validity; uint32 millis rollover is safe.
    const std::uint32_t elapsed = now_ms - sample.at_ms;
    if (elapsed == 0U || elapsed >= 0x80000000U) {
      sample.valid = false;
      return;
    }
  }
  sample.present = true;
  sample.valid = valid;
  sample.ambient_97 = ambient_97;
  sample.signal_97 = signal_97;
  sample.at_ms = now_ms;
}

void BodyControl::invalidate_range_optics() {
  for (auto& sample : state_.optical) sample.valid = false;
}

void BodyControl::sample_side_range(std::uint8_t index, std::uint16_t mm,
                                    bool valid, std::uint32_t now_ms) {
  if (index >= 3) return;
  if (state_.side_present[index]) {
    // These lanes never authorize motion, but a replay must not appear as
    // current side/rear evidence to the Mac. Preserve the latest raw sample
    // for diagnosis and require a truly newer conversion to restore valid.
    const std::uint32_t elapsed = now_ms - state_.side_at_ms[index];
    if (elapsed == 0U || elapsed >= 0x80000000U) {
      state_.side_valid[index] = false;
      return;
    }
  }
  state_.side_present[index] = true;
  state_.side_valid[index] = valid;
  state_.side_mm[index] = mm;
  state_.side_at_ms[index] = now_ms;
}

void BodyControl::invalidate_side_ranges() {
  for (auto& valid : state_.side_valid) valid = false;
}

void BodyControl::set_cap(bool valid, std::uint8_t zones) {
  if (!valid) {
    state_.cap_valid = false;
    state_.cap_mask = 0;
    cap_initialized_ = false;
    return;
  }
  if (cap_initialized_) {
    const std::uint8_t rising = zones & static_cast<std::uint8_t>(~state_.cap_mask);
    for (int index = 0; index < 8; ++index) {
      if ((rising & (1U << index)) != 0U) ++state_.cap_events;
    }
  }
  state_.cap_valid = true;
  state_.cap_mask = zones;
  cap_initialized_ = true;
}

void BodyControl::sample_bumper_input(bool active) {
  state_.bumper_raw = active;
  if (active) {
    // A released switch is not a new operator permission. The guarded
    // robot must keep wheels off until a deliberate local USB recovery.
    if (guarded_motion_profile()) bumper_fault_latched_ = true;
    touch_trip(); // immediate stop; preserve payload holding PWM
  }
}

void BodyControl::sample_optional_inputs(std::uint8_t enabled_mask, bool bumper,
                                         bool reed, bool pir,
                                         bool qualified_optional) {
  enabled_mask &= 0x07U;
  const std::uint8_t previously_enabled = state_.extra_mask;
  state_.extra_mask = enabled_mask;
  sample_bumper_input((enabled_mask & 1U) != 0U && bumper);
  const bool levels[3] = {bool((enabled_mask & 1U) && bumper),
                          bool((enabled_mask & 2U) && reed),
                          bool((enabled_mask & 4U) && pir)};
  bool* stable[3] = {&state_.bumper_active, &state_.reed_active, &state_.pir_active};
  std::uint32_t* counts[3] = {&state_.bumper_events, &state_.reed_events, &state_.pir_events};
  if (!extras_initialized_) {
    for (int i = 0; i < 3; ++i) {
      *stable[i] = levels[i];
      extra_candidates_[i] = levels[i];
      extra_streaks_[i] = 1;
    }
    extras_initialized_ = true;
    return; // boot baseline, not a real new event
  }
  for (int i = 0; i < 3; ++i) {
    const auto bit = static_cast<std::uint8_t>(1U << i);
    if (!(enabled_mask & bit) || !(previously_enabled & bit)) {
      // A missing/expired expander reading is NOT a new low contact, and a
      // subsequently recovered high value is NOT a fresh rising event.
      // Rebaseline only the affected input without touching unrelated
      // bumper, reed, or PIR history. Raw bumper still trips immediately.
      *stable[i] = levels[i];
      extra_candidates_[i] = levels[i];
      extra_streaks_[i] = 1;
      continue;
    }
    if (qualified_optional && i > 0) {
      // The MCP23017 filter already required three different, ordered GPIOB
      // conversions for this stable state. A cached 25ms poll must neither
      // add a second debounce delay nor invent another physical edge.
      if (levels[i] != *stable[i]) {
        *stable[i] = levels[i];
        if (levels[i]) ++*counts[i];
      }
      extra_candidates_[i] = levels[i];
      extra_streaks_[i] = 3;
      continue;
    }
    if (levels[i] != extra_candidates_[i]) {
      extra_candidates_[i] = levels[i];
      extra_streaks_[i] = 1;
    } else if (extra_streaks_[i] < 3) {
      ++extra_streaks_[i];
    }
    if (extra_streaks_[i] == 3 && levels[i] != *stable[i]) {
      *stable[i] = levels[i];
      if (levels[i]) ++*counts[i];
    }
  }
}

void BodyControl::set_touch(bool active, std::uint32_t now_ms) {
  if (active == state_.touch_active) return;
  state_.touch_active = active;
  if (active) {
    ++state_.touch_count;
    touch_started_ms_ = now_ms;
    touch_hold_emitted_ = false;
    // The un-debounced GPIO path normally tripped already. Keep a second
    // stop here for any alternative adapter invoking only set_touch().
    touch_trip();
    return;
  }

  const std::uint32_t held_ms = now_ms - touch_started_ms_;
  if (held_ms >= 900 && !touch_hold_emitted_) {
    ++state_.touch_holds;
    touch_hold_emitted_ = true;
  }
  if (touch_hold_emitted_ || held_ms > 600) {
    if (touch_pending_tap_) ++state_.touch_taps;
    touch_pending_tap_ = false;
    return;
  }
  if (touch_pending_tap_ && now_ms - touch_released_ms_ <= 350) {
    ++state_.touch_double_taps;
    touch_pending_tap_ = false;
  } else {
    if (touch_pending_tap_) ++state_.touch_taps;
    touch_pending_tap_ = true;
    touch_released_ms_ = now_ms;
  }
}

void BodyControl::set_imu_identity(std::uint8_t family, std::uint8_t gyro,
                                   std::uint8_t aux) {
  state_.imu_family = family <= 4 ? family : 0;
  state_.imu_gyro_id = gyro;
  state_.imu_aux_id = aux;
  // This merely records chip identification. It never arms or clears a guard.
}

bool BodyControl::dc_driver_fault_bad(std::uint32_t now_ms) const {
  if (!dc_fault_required_) return false;
  const auto& fault = state_.accessories.optional_inputs;
  // A B3 HIGH reading is meaningful only from a fresh MCP23017 GPIOB
  // transaction. No cached I2C value, boot default or malformed read
  // can authorize a moving DC bridge.
  return dc_fault_provenance_bad_ ||
         !fault.present || !fault.valid || fault.sample_seq == 0U ||
         now_ms - fault.at_ms >= 250U || fault.driver_fault_active;
}

bool BodyControl::dock_telemetry_bad(std::uint32_t now_ms) const {
  const auto& dock = state_.accessories.dock;
  // Once the optional physical MCP23017 was found at boot, its I2C
  // acquisition, independent sequence and timestamp are compulsory for
  // moving. A missing module is NOT manufactured into a fake valid sample.
  return (dock_sample_seen_ || dock.present || dock_monitor_required_) &&
         (!dock.present || !dock.valid || dock.sample_seq == 0U ||
          now_ms - dock.at_ms >= 500U);
}

void BodyControl::latch_dock_monitor_fault() {
  // Every detected loss retires the most recent trusted GPIOA identity.
  // Another loss before local recovery cannot reuse a pre-loss reading.
  if (dock_sample_seen_) {
    dock_monitor_fault_seq_ = dock_last_seq_;
    dock_monitor_fault_at_ms_ = dock_last_at_ms_;
  }
  dock_monitor_fault_latched_ = true;
}

bool BodyControl::configure_imu_yaw_capture(
    const ImuYawCapture::Calibration& calibration) {
  // An identified MPU6050 and measured installed yaw axis/bias/thermal and
  // drift limits are required. No UART or LLM code may create them.
  if (boot_epoch_ == 0 || state_.imu_family != 4 ||
      BerryImu::identify(state_.imu_gyro_id, state_.imu_aux_id) !=
          BerryModel::Mpu6050 ||
      imu_yaw_configured_ || state_.armed || state_.servos_attached)
    return false;
  ImuYawCapture qualified;
  if (!qualified.configure(calibration)) return false;
  imu_yaw_ = qualified;
  imu_yaw_configured_ = true;
  return true;
}

bool BodyControl::configure_wheel_angle_capture(
    std::uint32_t left_max_counts_per_s,
    std::uint32_t right_max_counts_per_s,
    std::uint32_t max_gap_ms, std::uint32_t max_age_ms) {
  // Boot-time measured shaft speed, not a remotely configurable limit.
  // Validate both sensors atomically; no partial left-only admission.
  if (boot_epoch_ == 0 || wheel_capture_configured_ ||
      state_.armed || state_.servos_attached) return false;
  WheelAngleCapture left, right;
  if (!left.configure(left_max_counts_per_s, max_gap_ms, max_age_ms) ||
      !right.configure(right_max_counts_per_s, max_gap_ms, max_age_ms))
    return false;
  wheel_angles_[0] = left;
  wheel_angles_[1] = right;
  wheel_capture_configured_ = true;
  return true;
}

void BodyControl::invalidate_pose_continuity() {
  if (wheel_pose_configured_) wheel_pose_.invalidate();
  if (wheel_pair_configured_) wheel_pairs_.discard_continuity();
  if (wheel_capture_configured_) {
    wheel_angles_[0].discard_continuity();
    wheel_angles_[1].discard_continuity();
  }
}

bool BodyControl::configure_wheel_pose(
    const WheelPoseIntegrator::Calibration& calibration) {
  if (boot_epoch_ == 0 || !wheel_capture_configured_ ||
      !wheel_pair_configured_ || !imu_yaw_configured_ ||
      wheel_pose_configured_ || state_.armed || state_.servos_attached)
    return false;
  WheelPoseIntegrator candidate;
  if (!candidate.configure(calibration)) return false;
  wheel_pose_ = candidate;
  wheel_pose_configured_ = true;
  return true;
}

bool BodyControl::start_local_pose_origin(std::uint32_t now_ms) {
  if (!wheel_pose_configured_ || state_.armed || state_.servos_attached ||
      state_.touch_raw_active || state_.bumper_raw ||
      imu_low_g_latched_ || imu_attitude_latched_ ||
      imu_sensor_fault_latched_ || motor_watchdog_latched_ ||
      command_timeout_latched_ || imu_provenance_bad_ ||
      !imu_yaw_.fresh(now_ms))
    return false;
  return wheel_pose_.start_origin(now_ms);
}

bool BodyControl::configure_wheel_pair_skew(
    std::uint32_t measured_max_skew_ms) {
  if (boot_epoch_ == 0 || !wheel_capture_configured_ ||
      wheel_pair_configured_ || state_.armed || state_.servos_attached)
    return false;
  WheelPairCapture configured;
  if (!configured.configure(measured_max_skew_ms)) return false;
  wheel_pairs_ = configured;
  wheel_pair_configured_ = true;
  return true;
}

void BodyControl::set_accessories(const AccessoryReadings& readings,
                                  std::uint32_t now_ms) {
  // Other simultaneous faults must not hide a dock GPIOA loss that happened
  // while a guarded motion session was still armed.
  const bool was_armed = state_.armed;
  state_.accessories = readings;
  if (wheel_capture_configured_) {
    // Capture only real per-conversion AS5600 provenance from the 0x71 bus.
    // Independent channels may be sampled at different times, so these
    // angular counts NEVER create a paired metric pose or motor permit.
    const auto left = wheel_angles_[0].observe(readings.angle[1], now_ms);
    const auto right = wheel_angles_[1].observe(readings.angle[2], now_ms);
    if (wheel_pair_configured_) {
      const auto result =
          wheel_pairs_.observe(left, right, readings.angle[1], readings.angle[2],
                               wheel_angles_[0].last_delta(),
                               wheel_angles_[1].last_delta(), now_ms);
      if (result == WheelPairCapture::Result::Invalid) {
        // Dropping either leg invalidates the entire movement interval.
        // Next successful acquisitions must establish two new baselines.
        invalidate_pose_continuity();
      } else if (result == WheelPairCapture::Result::Paired &&
                 wheel_pose_configured_) {
        WheelPoseIntegrator::Evidence sample{};
        sample.wheel = wheel_pairs_.receipt();
        sample.imu_valid = imu_yaw_.fresh(now_ms) &&
                           !imu_provenance_bad_ && !imu_attitude_latched_ &&
                           !imu_low_g_latched_;
        sample.imu_segment = imu_yaw_.segment();
        sample.imu_at_ms = imu_yaw_.acquisition_ms();
        sample.imu_yaw_urad = imu_yaw_.yaw_urad();
        sample.imu_step_urad = imu_yaw_.last_delta_urad();
        sample.imu_error_urad = imu_yaw_.error_bound_urad();
        if (!wheel_pose_.observe(sample, now_ms)) {
          // A rejected source step must revoke both raw histories and its
          // previously successful pair receipt *in the same sensor call*.
          invalidate_pose_continuity();
        }
      }
    }
  }
  const auto& force = readings.force;
  const bool belly_valid = (force.valid_mask & 1U) != 0U ||
      (force.valid_mask == 0U && force.valid);
  const bool belly_current = force.present && belly_valid &&
      force.belly_sample_seq != 0U && now_ms - force.belly_at_ms < 500U &&
      force.adc[0] != -32768 && force.adc[0] != 32767;
  const std::uint32_t belly_seq_delta =
      force.belly_sample_seq - belly_last_seq_;
  const std::uint32_t belly_time_delta =
      force.belly_at_ms - belly_last_at_ms_;
  const bool belly_repeated = belly_current && belly_sample_seen_ &&
      force.belly_sample_seq == belly_last_seq_ &&
      force.belly_at_ms == belly_last_at_ms_ &&
      force.adc[0] == belly_last_adc_;
  const bool belly_new = belly_current &&
      (!belly_sample_seen_ ||
       (belly_seq_delta != 0U && belly_seq_delta < 0x80000000U &&
        belly_time_delta != 0U && belly_time_delta < 0x80000000U));
  if (belly_new) {
    belly_sample_seen_ = true;
    belly_last_seq_ = force.belly_sample_seq;
    belly_last_at_ms_ = force.belly_at_ms;
    belly_last_adc_ = force.adc[0];
    belly_provenance_bad_ = false;
  } else if ((belly_current && !belly_repeated) ||
             (belly_sample_seen_ && !belly_current)) {
    // Cached or altered readings are not new user contact. A genuinely
    // newer completed channel-0 conversion restores read-only validity.
    belly_provenance_bad_ = true;
  }
  const bool jaw_valid = (force.valid_mask & 2U) != 0U ||
      (force.valid_mask == 0U && force.valid);
  const bool jaw_current = force.present && jaw_valid &&
      force.jaw_sample_seq != 0U && now_ms - force.jaw_at_ms < 500U &&
      force.adc[1] != -32768 && force.adc[1] != 32767;
  const std::uint32_t jaw_seq_delta =
      force.jaw_sample_seq - jaw_last_seq_;
  const std::uint32_t jaw_time_delta =
      force.jaw_at_ms - jaw_last_at_ms_;
  const bool jaw_repeated = jaw_current && jaw_sample_seen_ &&
      force.jaw_sample_seq == jaw_last_seq_ &&
      force.jaw_at_ms == jaw_last_at_ms_ &&
      force.adc[1] == jaw_last_adc_;
  const bool jaw_new = jaw_current &&
      (!jaw_sample_seen_ ||
       (jaw_seq_delta != 0U && jaw_seq_delta < 0x80000000U &&
        jaw_time_delta != 0U && jaw_time_delta < 0x80000000U));
  if (jaw_new) {
    jaw_sample_seen_ = true;
    jaw_last_seq_ = force.jaw_sample_seq;
    jaw_last_at_ms_ = force.jaw_at_ms;
    jaw_last_adc_ = force.adc[1];
    jaw_provenance_bad_ = false;
  } else if ((jaw_current && !jaw_repeated) ||
             (jaw_sample_seen_ && !jaw_current)) {
    // Failed conversions, replays and changed raw values under one
    // sequence cannot silently become trusted by a later cached reply.
    // Only a NEW, independently timed conversion restores jaw evidence.
    jaw_provenance_bad_ = true;
  }
  if (grip_feedback_required_ && !grip_feedback_fresh(now_ms)) {
    // Stop immediately, before the next PWM ramp. Retain the output
    // attachment to hold an already grasped object without extra travel.
    state_.grip_target = state_.grip;
    jaw_sample_motion_budget_ = 0;
  }
  const auto& fuel = readings.gauge;
  // The MAX17048 producer advances both sequence and acquisition time
  // only after its cell-voltage and SOC registers have been read. A cached
  // conversion is normal, but changing its values or replaying an older
  // acquisition is not new evidence for motor or battery authorization.
  const bool fuel_current = fuel.fuel_present && fuel.fuel_valid &&
      fuel.fuel_sample_seq != 0U && now_ms - fuel.fuel_at_ms < 500U;
  const std::uint32_t fuel_seq_delta =
      fuel.fuel_sample_seq - fuel_last_seq_;
  const std::uint32_t fuel_time_delta = fuel.fuel_at_ms - fuel_last_at_ms_;
  const bool fuel_repeated = fuel_current && fuel_sample_seen_ &&
      fuel.fuel_sample_seq == fuel_last_seq_ &&
      fuel.fuel_at_ms == fuel_last_at_ms_ &&
      fuel.cell_mv == fuel_last_cell_mv_ &&
      fuel.soc_centi == fuel_last_soc_centi_;
  const bool fuel_new = fuel_current &&
      (!fuel_sample_seen_ ||
       (fuel_seq_delta != 0U && fuel_seq_delta < 0x80000000U &&
        fuel_time_delta != 0U && fuel_time_delta < 0x80000000U));
  if (fuel_new) {
    fuel_sample_seen_ = true;
    fuel_last_seq_ = fuel.fuel_sample_seq;
    fuel_last_at_ms_ = fuel.fuel_at_ms;
    fuel_last_cell_mv_ = fuel.cell_mv;
    fuel_last_soc_centi_ = fuel.soc_centi;
    fuel_provenance_bad_ = false;
  } else if (fuel_current && !fuel_repeated) {
    // Requiring a newer completed conversion prevents a repeated low-cell
    // sample from being rewritten as a healthy voltage under the same ID.
    fuel_provenance_bad_ = true;
  }
  if (imu_attitude_required_ &&
      (!imu_attitude_configured_ || imu_attitude_latched_)) {
    // Attitude HOLD cannot suppress independent dock, nFAULT, fuel,
    // or battery latches. Keep sampling those before any safe recovery.
    stop_motion();
    state_.armed = false;
  }
  if (fuel_monitor_required_ && !fuel_monitor_fresh(now_ms)) {
    // Anchor recovery to the last accepted conversion, not an invalid
    // incoming identity. If another acquisition is lost while already
    // latched, require a conversion newer than that latest trusted one.
    if (fuel_sample_seen_) {
      fuel_monitor_fault_seq_ = fuel_last_seq_;
      fuel_monitor_fault_at_ms_ = fuel_last_at_ms_;
    }
    fuel_monitor_fault_latched_ = true;
    stop_motion();
    state_.armed = false; // retain jaw holding PWM on pack telemetry loss
  }
  if (dc_fault_required_) {
    const auto& fault = readings.optional_inputs;
    const bool current = fault.present && fault.valid &&
        fault.sample_seq != 0U && now_ms - fault.at_ms < 250U;
    const std::uint32_t seq_delta = fault.sample_seq - dc_fault_last_seq_;
    const std::uint32_t time_delta = fault.at_ms - dc_fault_last_at_ms_;
    const bool repeated = current && dc_fault_sample_seen_ &&
        fault.sample_seq == dc_fault_last_seq_ &&
        fault.at_ms == dc_fault_last_at_ms_ &&
        fault.driver_fault_active == dc_fault_last_active_;
    const bool newer = current &&
        (!dc_fault_sample_seen_ ||
         (seq_delta != 0U && seq_delta < 0x80000000U &&
          time_delta != 0U && time_delta < 0x80000000U));
    if (newer) {
      dc_fault_sample_seen_ = true;
      dc_fault_last_seq_ = fault.sample_seq;
      dc_fault_last_at_ms_ = fault.at_ms;
      dc_fault_last_active_ = fault.driver_fault_active;
      dc_fault_provenance_bad_ = false;
    } else if (!repeated) {
      // A failed read or changed GPIOB bits under the same identity may
      // not be repaired by replaying previously healthy cached data.
      dc_fault_provenance_bad_ = true;
    }
  }
  if (dc_driver_fault_bad(now_ms)) {
    // Missing/stale or asserted nFAULT immediately cancels wheels. Never
    // detach holding servo PWM merely because the driver reported a fault.
    // The latch survives a later HIGH read until a fresh local USB rearm.
    dc_fault_latched_ = true;
    stop_motion();
    state_.armed = false;
  }
  const auto& dock = readings.dock;
  // CHG alone is not proof of net cell charging, but if it asserts while
  // both seat switches and PGOOD appear clear, treating the pins as a safe
  // undock could resume wheels on inconsistent charger telemetry. Hold.
  const bool contact = dock.input_good || dock.left_seated ||
                       dock.right_seated || dock.charge_indicated;
  // An unchanged cached MCP23017 reading is NOT a new removal observation.
  // Half-range comparisons permit uint32_t sequence and millis() rollover
  // while rejecting old, reordered, and inconsistent source evidence.
  const bool current = dock.present && dock.valid && dock.sample_seq != 0U &&
                       now_ms - dock.at_ms < 500U;
  const std::uint32_t seq_delta = dock.sample_seq - dock_last_seq_;
  const std::uint32_t time_delta = dock.at_ms - dock_last_at_ms_;
  const std::uint8_t pins =
      static_cast<std::uint8_t>((dock.left_seated ? 1U : 0U) |
                                (dock.right_seated ? 2U : 0U) |
                                (dock.input_good ? 4U : 0U) |
                                (dock.charge_indicated ? 8U : 0U));
  const bool repeated = current && dock_sample_seen_ &&
      dock.sample_seq == dock_last_seq_ && dock.at_ms == dock_last_at_ms_ &&
      pins == dock_last_pins_;
  const bool new_sample = current &&
      (!dock_sample_seen_ || (seq_delta != 0U && seq_delta < 0x80000000U &&
                             time_delta != 0U && time_delta < 0x80000000U));
  if (dock.present && dock.valid && dock.sample_seq != 0U && contact) {
    // Any observed seat or PGOOD is a stop, including inconsistent records.
    dock_power_lockout_ = true;
  }
  if (new_sample) {
    dock_last_seq_ = dock.sample_seq;
    dock_last_at_ms_ = dock.at_ms;
    dock_last_pins_ = pins;
    dock_sample_seen_ = true;
    dock_provenance_fault_ = false;
    if (!contact) {
      // Only a truly new, fresh, fully unseated read clears the latch.
      // Clearing the latch does NOT automatically rearm or enable charging.
      dock_power_lockout_ = false;
    }
  } else if (current && dock_sample_seen_ && !repeated) {
    // A corrupted or out-of-order record is not repaired by replaying an
    // earlier cached value. Recovery requires a NEW completed GPIOA read.
    dock_provenance_fault_ = true;
  }
  // A changed GPIO value under the same sample identity, an older sample,
  // or an expired timestamp cannot substantiate a local safety interlock.
  // Preserve the last latch and fail closed until a fresh acquisition.
  state_.accessories.dock.valid =
      (new_sample || repeated) && !dock_provenance_fault_;
  if (guarded_motion_profile() &&
      (was_armed || dock_sample_seen_ || dock_monitor_fault_latched_) &&
      dock_telemetry_bad(now_ms)) {
    // Once a GPIOA source has been observed, every loss requires fresh
    // local recovery, including another loss while already disarmed.
    latch_dock_monitor_fault();
  }
  if (dock_power_lockout_) {
    // Contact must veto wheel motion without detaching holding servo PWM.
    // Only an explicit disarm should deliberately release a grasped payload.
    stop_motion();
    state_.armed = false;
  } else if (dock_telemetry_bad(now_ms)) {
    // A required but missing MCP23017 is not an optional absent sensor.
    // Preserve jaw PWM on transport loss to avoid dropping a held object.
    stop_motion();
    state_.armed = false;
  }
  if (readings.gauge.fuel_valid &&
      readings.gauge.cell_mv < 3200U) {
    if (guarded_motion_profile()) {
      const auto& fuel = readings.gauge;
      const auto seq_delta = fuel.fuel_sample_seq - battery_fault_seq_;
      const auto time_delta = fuel.fuel_at_ms - battery_fault_at_ms_;
      if (!battery_fault_latched_ ||
          (seq_delta != 0U && seq_delta < 0x80000000U &&
           time_delta != 0U && time_delta < 0x80000000U)) {
        battery_fault_seq_ = fuel.fuel_sample_seq;
        battery_fault_at_ms_ = fuel.fuel_at_ms;
      }
      // A later missing/invalid/healthy gauge result cannot let an old
      // head request restart motion. Local recovery needs a newer valid read.
      battery_fault_latched_ = true;
    }
    stop_motion();
    state_.armed = false;
  }
}

void BodyControl::set_imu(const BerryReading& reading) {
  // WROOM forwards the same cached conversion on many faster motor cycles.
  // Its unchanged timestamp must also retain the same raw evidence. A
  // changed or older sample cannot silently replace the safety input.
  bool identical = imu_sample_seen_ && reading.at_ms == imu_last_at_ms_ &&
      reading.model == imu_.model && reading.valid == imu_.valid &&
      reading.temperature_raw == imu_.temperature_raw &&
      reading.low_g_status_valid == imu_.low_g_status_valid &&
      reading.low_g_irq == imu_.low_g_irq &&
      reading.low_g_event_seq == imu_.low_g_event_seq;
  for (unsigned i = 0; i < 3; ++i) {
    identical = identical && reading.accel[i] == imu_.accel[i] &&
                reading.gyro[i] == imu_.gyro[i];
  }
  const std::uint32_t advance = reading.at_ms - imu_last_at_ms_;
  const bool newly_acquired = !imu_sample_seen_ ||
      (advance != 0U && advance < 0x80000000U);
  if (newly_acquired) {
    imu_sample_seen_ = true;
    imu_last_at_ms_ = reading.at_ms;
    imu_provenance_bad_ = false;
  } else if (!identical) {
    imu_provenance_bad_ = true;
    if (imu_motion_required_ && state_.armed) {
      imu_sensor_fault_latched_ = true;
      stop_motion();
      state_.armed = false; // preserve holding PWM on an unsafe IMU replay
    }
  }
  imu_ = reading;
  if (imu_yaw_configured_) {
    // Use the original IMU acquisition clock, never UART poll time. A
    // contradictory cached frame cannot add yaw even if its age is small.
    if (imu_provenance_bad_) imu_yaw_.invalidate();
    else imu_yaw_.observe(reading, reading.at_ms);
    if (wheel_pose_configured_ && !imu_yaw_.continuous())
      invalidate_pose_continuity();
  }
  if (imu_attitude_required_ && newly_acquired) {
    if (!imu_attitude_configured_ || !reading.valid ||
        reading.model != BerryModel::Mpu6050 || !reading.low_g_status_valid) {
      imu_attitude_bad_streak_ = 0;
      imu_attitude_good_streak_ = 0;
    } else if (attitude_sample_unsafe(reading)) {
      imu_attitude_good_streak_ = 0;
      if (imu_attitude_bad_streak_ < 2) ++imu_attitude_bad_streak_;
      if (imu_attitude_bad_streak_ >= 2) {
        // Two separate 50 ms conversions; not cached motor-loop reads.
        imu_attitude_latched_ = true;
        stop_motion();
        state_.armed = false;  // keep gripper holding PWM
      }
    } else {
      imu_attitude_bad_streak_ = 0;
      if (imu_attitude_good_streak_ < 2) ++imu_attitude_good_streak_;
    }
  }
  // Native FF_INT is read-to-clear. A following healthy poll cannot erase
  // the safety stop: only a deliberate local USB rearm may resume wheels.
  if (imu_motion_required_ && reading.model == BerryModel::Mpu6050 &&
      reading.valid && reading.low_g_status_valid && reading.low_g_irq) {
    imu_low_g_latched_ = true;
    stop_motion();
    state_.armed = false; // retain servo PWM on a held key
  }
  if (wheel_pose_configured_ &&
      (imu_low_g_latched_ || imu_attitude_latched_ ||
       imu_sensor_fault_latched_))
    invalidate_pose_continuity();
}

void BodyControl::inhibit_unqualified_motor_cutoff() {
  motor_cutoff_unqualified_ = true;
  stop_motion();
  state_.armed = false;
}

void BodyControl::motor_watchdog_trip() {
  // The wheel may coast while the CPU cannot sample either encoder.
  // Retire the local odometry origin and every old encoder pair immediately.
  invalidate_pose_continuity();
  // A recovered CPU must never restart its old drive lease after cutoff.
  // Retain servo holding PWM instead of dropping a held payload.
  motor_watchdog_latched_ = true;
  stop_motion();
  state_.armed = false;
}

void BodyControl::force_disarm() {
  stop_motion();
  state_.armed = false;
  state_.servos_attached = false;
}

std::uint32_t BodyControl::watchdog_remaining(std::uint32_t now_ms) const {
  if (!state_.armed) return 0;
  const std::uint32_t elapsed = now_ms - last_control_ms_;
  return elapsed >= kWatchdogMs ? 0 : kWatchdogMs - elapsed;
}

std::uint32_t BodyControl::drive_remaining(std::uint32_t now_ms) const {
  if (!state_.armed || drive_duration_ms_ == 0) return 0;
  const std::uint32_t elapsed = now_ms - drive_started_ms_;
  return elapsed >= drive_duration_ms_ ? 0 : drive_duration_ms_ - elapsed;
}

void BodyControl::tick(std::uint32_t now_ms) {
  if (wheel_pose_configured_) wheel_pose_.expire(now_ms);
  // Local gesture classification survives slow Mac camera polling.
  // Unsigned subtraction also handles millis rollover.
  if (state_.touch_active && !touch_hold_emitted_ &&
      now_ms - touch_started_ms_ >= 900) {
    ++state_.touch_holds;
    touch_hold_emitted_ = true;
    if (touch_pending_tap_) ++state_.touch_taps;
    touch_pending_tap_ = false;
  }
  if (touch_pending_tap_ && !state_.touch_active &&
      now_ms - touch_released_ms_ > 350) {
    ++state_.touch_taps;
    touch_pending_tap_ = false;
  }
  if (guarded_motion_profile() &&
      (state_.armed || dock_sample_seen_ || dock_monitor_fault_latched_) &&
      dock_telemetry_bad(now_ms)) {
    // Capture independently even when a simultaneous cliff fault wins the
    // immediate return below. Never make another safety lane mask GPIOA loss.
    latch_dock_monitor_fault();
  }
  if (guarded_motion_profile() &&
      (guard_ == nullptr || !guard_->evaluate(now_ms))) {
    stop_motion();
    state_.armed = false;
    // A floor/bus fault must not deliberately release a held payload.
    return;
  }
  if (imu_motion_required_ && !imu_fresh(now_ms)) {
    // A compulsory sensor going stale DURING active motion must not be
    // repaired by an old queued head ARM after I2C recovers. Keep local
    // recovery authority separate from the normal remote arm lease.
    if (state_.armed) imu_sensor_fault_latched_ = true;
    stop_motion();
    state_.armed = false;
    // This is not a measured tilt interlock: orientation qualification
    // remains a separate physical release gate.
    return;
  }
  if (fuel_monitor_required_ && !fuel_monitor_fresh(now_ms)) {
    // Anchor recovery to the last accepted conversion, not an invalid
    // incoming identity. If another acquisition is lost while already
    // latched, require a conversion newer than that latest trusted one.
    if (fuel_sample_seen_) {
      fuel_monitor_fault_seq_ = fuel_last_seq_;
      fuel_monitor_fault_at_ms_ = fuel_last_at_ms_;
    }
    fuel_monitor_fault_latched_ = true;
  }
  if (bumper_fault_latched_ || battery_fault_latched_ ||
      fuel_monitor_fault_latched_) {
    stop_motion();
    state_.armed = false;
    return;
  }
  if (dc_fault_latched_ || dc_driver_fault_bad(now_ms)) {
    dc_fault_latched_ = dc_fault_latched_ || dc_driver_fault_bad(now_ms);
    stop_motion();
    state_.armed = false;
    return;
  }
  if (dock_monitor_fault_latched_ || dock_telemetry_bad(now_ms)) {
    // A recovered expander cannot restore a cancelled motion session
    // without a new unseated acquisition and local USB recovery.
    stop_motion();
    state_.armed = false;
    return;
  }
  if (motor_watchdog_latched_ || command_timeout_latched_) {
    stop_motion();
    state_.armed = false;
    return;
  }
  if (state_.armed && state_.accessories.gauge.fuel_valid &&
      state_.accessories.gauge.cell_mv < 3200U) {
    stop_motion();
    state_.armed = false;
    return;
  }
  if (!state_.armed) return;
  // Unsigned elapsed arithmetic remains correct when millis() wraps.
  if (now_ms - last_control_ms_ >= kWatchdogMs) {
    // The head link expired. In a physically guarded build, a reconnecting
    // head must not silently restore drive permission with an old ARM.
    // A fresh USB recovery is required, even when ranges remain healthy.
    if (guarded_motion_profile()) command_timeout_latched_ = true;
    stop_motion();
    state_.armed = false;
    // Preserve holding PWM so a held object is not deliberately dropped.
    return;
  }
  if (drive_duration_ms_ != 0 && now_ms - drive_started_ms_ >= drive_duration_ms_) {
    state_.left = 0;
    state_.right = 0;
    drive_duration_ms_ = 0;
  }
  // If the jaw feedback disappears AFTER a valid command, freeze
  // the target before the next servo ramp. Leave PWM attached to retain
  // an already held object rather than dropping it on I2C loss.
  if (grip_feedback_required_ && state_.grip != state_.grip_target &&
      (!grip_feedback_fresh(now_ms) ||
       !jaw_target_within_limits(state_.grip_target) ||
       (jaw_target_closes(state_.grip_target) &&
        !jaw_force_allows_closing()))) {
    // Local feedback, not an outstanding Mac callback, cancels closure.
    // Preserve holding PWM; an explicitly commanded opening can relieve load.
    state_.grip_target = state_.grip;
    jaw_sample_motion_budget_ = 0;
  }
  const std::uint32_t due_steps =
      (now_ms - last_servo_step_ms_) / kServoStepMs;
  if (due_steps != 0) {
    // A delayed WROOM loop can still be within its valid 200 ms cliff
    // freshness and 500 ms link watchdog window. Catching up eight missed
    // 20 ms intervals in ONE MG90S PWM write would bypass the commanded
    // 50 degrees/s rate limit even though the sensors remain healthy.
    // In physically guarded profiles issue ONE degree per executed tick
    // and abandon old time credit; immediate subsequent ticks cannot replay
    // a burst. The preserved actuator-inert DC bench profile retains its
    // historic simulated catch-up semantics.
    const bool physical_profile = guarded_motion_profile();
    const std::uint32_t steps = physical_profile ? 1U : due_steps;
    if (physical_profile) {
      last_servo_step_ms_ = now_ms;
    } else {
      last_servo_step_ms_ += due_steps * kServoStepMs;
    }
    move_toward(state_.lift, state_.lift_target, steps);
    std::uint32_t jaw_steps = steps;
    if (grip_feedback_required_) {
      jaw_steps = 0;
      if (state_.grip != state_.grip_target && grip_feedback_fresh(now_ms)) {
        const auto seq = state_.accessories.force.jaw_sample_seq;
        const std::uint32_t delta = seq - jaw_servo_sample_seq_;
        // Sequence 0 is never a valid conversion; permit UINT32 rollover
        // but reject duplicates, backwards reads and stale HTTP replay.
        if (jaw_servo_sample_seq_ != 0 &&
            delta >= 0x80000000U) {
          // Replayed or regressed sensor identity invalidates even the
          // unused part of a previously trusted movement allowance.
          // Require a fresh command and newer conversion; never resume
          // the old target after a backwards hardware sample.
          state_.grip_target = state_.grip;
          jaw_sample_motion_budget_ = 0;
        } else {
          if (jaw_sample_motion_budget_ == 0 &&
              (jaw_servo_sample_seq_ == 0 || delta != 0U)) {
            jaw_servo_sample_seq_ = seq;
            jaw_sample_motion_budget_ = 4;
          }
          jaw_steps = steps < jaw_sample_motion_budget_ ?
              steps : jaw_sample_motion_budget_;
        }
      }
    }
    const int previous_grip = state_.grip;
    move_toward(state_.grip, state_.grip_target, jaw_steps);
    if (grip_feedback_required_) {
      const int delta = state_.grip > previous_grip ?
          state_.grip - previous_grip : previous_grip - state_.grip;
      jaw_sample_motion_budget_ -= static_cast<std::uint8_t>(delta);
    }
  }
}

void BodyControl::execute(const char* line, std::size_t length,
                          std::uint32_t now_ms, char* reply,
                          std::size_t capacity, bool local_safety_rearm,
                          std::uint64_t sample_us) {
  tick(now_ms);
  if (length > kMaxLineLength) {
    std::snprintf(reply, capacity, "ERR input line_too_long");
    return;
  }
  char buffer[kMaxLineLength + 1]{};
  for (std::size_t i = 0; i < length; ++i) {
    const unsigned char byte = static_cast<unsigned char>(line[i]);
    if (byte < 32 || byte > 126) {
      std::snprintf(reply, capacity, "ERR input invalid_ascii");
      return;
    }
    buffer[i] = line[i];
  }

  char* tokens[5]{};
  std::size_t count = 0;
  char* position = buffer;
  while (*position != '\0') {
    while (*position == ' ') ++position;
    if (*position == '\0') break;
    if (count == 5) {
      std::snprintf(reply, capacity, "ERR input trailing_tokens");
      return;
    }
    tokens[count++] = position;
    while (*position != '\0' && *position != ' ') ++position;
    if (*position != '\0') *position++ = '\0';
  }
  if (count == 0) {
    std::snprintf(reply, capacity, "ERR input empty");
    return;
  }
  const char* command = tokens[0];
  const bool drive = std::strcmp(command, "drive") == 0;
  const bool lift = std::strcmp(command, "lift") == 0;
  const bool grip = std::strcmp(command, "grip") == 0;
  const bool arm = std::strcmp(command, "arm") == 0;
  const bool rearm = std::strcmp(command, "rearm") == 0;
  const bool disarm = std::strcmp(command, "disarm") == 0;
  const bool stop = std::strcmp(command, "stop") == 0;
  const bool halt = std::strcmp(command, "halt") == 0;
  const bool keepalive = std::strcmp(command, "keepalive") == 0;
  const bool ping = std::strcmp(command, "ping") == 0;
  const bool status = std::strcmp(command, "status") == 0;
  const bool aux = std::strcmp(command, "aux") == 0;
  const bool ir = std::strcmp(command, "ir") == 0;
  const bool optics = std::strcmp(command, "optics") == 0;
  const bool pose = std::strcmp(command, "pose") == 0;
  const bool calfloor = std::strcmp(command, "calfloor") == 0;
  const bool calfront = std::strcmp(command, "calfront") == 0;
  const bool calfresh = std::strcmp(command, "calfresh") == 0;
  const bool calcommit = std::strcmp(command, "calcommit") == 0;
  const bool calabort = std::strcmp(command, "calabort") == 0;
  const bool calibration = calfloor || calfront || calfresh || calcommit || calabort;
  if (!(drive || lift || grip || arm || rearm || disarm || stop || keepalive || ping || status || aux || ir || optics || pose || halt || calibration)) {
    // Do not interpolate attacker-controlled input into reply lines.
    std::snprintf(reply, capacity, "ERR input unknown_command");
    return;
  }
  if ((drive && count != 3 && count != 4) ||
      ((lift || grip || calfresh) && count != 2) ||
      (calfront && count != 3) ||
      (calfloor && count != 4) ||
      (!(drive || lift || grip || calfloor || calfront || calfresh) && count != 1)) {
    std::snprintf(reply, capacity, "ERR %s bad_arguments", command);
    return;
  }

  if (pose) {
    // Until two installed encoders and calibrated yaw actually prove wheel
    // displacement, only a clocked, explicitly unavailable observation may
    // cross the Sense/Mac interface. Origin zero has NO navigation authority.
    // ESP-IDF monotonic esp_timer_get_time() is sampled at UART frame close;
    // never infer time from the 32-bit millis() control watchdog clock.
    constexpr std::uint64_t kMaxJsonExactUs = 9007199254740991ULL;
    if (boot_epoch_ == 0 || sample_us == 0 ||
        sample_us > kMaxJsonExactUs ||
        sample_us <= pose_last_sample_us_ ||
        pose_seq_ == UINT32_MAX) {
      std::snprintf(reply, capacity, "ERR pose clock_or_sequence_unavailable");
      return;
    }
    // A reply that cannot be framed must not consume a source sequence
    // or timestamp: the next complete read can still observe that sample.
    const std::uint32_t next_seq = pose_seq_ + 1U;
    const int written = std::snprintf(reply, capacity,
        "{\"v\":1,\"body_boot\":%lu,\"origin\":0,\"seq\":%lu,"
        "\"sample_us\":%llu,\"x_mm\":0,\"y_mm\":0,"
        "\"yaw_mrad\":0,\"quality\":\"unavailable\"}",
        static_cast<unsigned long>(boot_epoch_),
        static_cast<unsigned long>(next_seq),
        static_cast<unsigned long long>(sample_us));
    if (written < 0 || static_cast<std::size_t>(written) >= capacity) {
      std::snprintf(reply, capacity, "ERR pose reply_capacity");
      return;
    }
    pose_seq_ = next_seq;
    pose_last_sample_us_ = sample_us;
    return;
  }

  int first = 0;
  int second = 0;
  int duration = static_cast<int>(kMaxDriveMs);
  if (drive) {
    if (!parse_integer(tokens[1], first) || !parse_integer(tokens[2], second) ||
        (count == 4 && !parse_integer(tokens[3], duration))) {
      std::snprintf(reply, capacity, "ERR drive integer_required");
      return;
    }
    if (first < -100 || first > 100 || second < -100 || second > 100 ||
        duration < 1 || duration > static_cast<int>(kMaxDriveMs)) {
      std::snprintf(reply, capacity, "ERR drive out_of_range");
      return;
    }
  } else if (lift || grip) {
    if (!parse_integer(tokens[1], first)) {
      std::snprintf(reply, capacity, "ERR %s integer_required", command);
      return;
    }
    if (first < kServoMinDegrees || first > kServoMaxDegrees) {
      std::snprintf(reply, capacity, "ERR %s out_of_range", command);
      return;
    }
  }

  if (calibration) {
    if (!local_safety_rearm || !guarded_motion_profile() || guard_ == nullptr) {
      std::snprintf(reply, capacity, "ERR calibration local_usb_only");
      return;
    }
    if (state_.armed) {
      std::snprintf(reply, capacity, "ERR calibration disarm_first");
      return;
    }
    if (calabort) {
      calibration_stage_ = CliffConfig{};
      calibration_stage_mask_ = 0;
      std::snprintf(reply, capacity, "OK calabort");
      return;
    }
    if (calfloor) {
      int channel = 0, minimum = 0, maximum = 0;
      if (!parse_integer(tokens[1], channel) ||
          !parse_integer(tokens[2], minimum) ||
          !parse_integer(tokens[3], maximum) ||
          channel < 0 || channel >= kFloorSensorCount ||
          minimum < 30 || maximum < minimum || maximum > 1300) {
        std::snprintf(reply, capacity, "ERR calfloor channel_0to3_min_max_30to1300");
        return;
      }
      calibration_stage_.floor[channel].min_mm = static_cast<std::uint16_t>(minimum);
      calibration_stage_.floor[channel].max_mm = static_cast<std::uint16_t>(maximum);
      calibration_stage_mask_ |= static_cast<std::uint8_t>(1U << channel);
      std::snprintf(reply, capacity, "OK calfloor channel=%d", channel);
      return;
    }
    if (calfront) {
      int near_mm = 0, far_mm = 0;
      if (!parse_integer(tokens[1], near_mm) ||
          !parse_integer(tokens[2], far_mm) ||
          near_mm < 30 || far_mm <= near_mm || far_mm > 1300) {
        std::snprintf(reply, capacity, "ERR calfront near_far_30to1300");
        return;
      }
      calibration_stage_.front_obstacle_mm = static_cast<std::uint16_t>(near_mm);
      calibration_stage_.front_max_mm = static_cast<std::uint16_t>(far_mm);
      calibration_stage_mask_ |= 0x10U;
      std::snprintf(reply, capacity, "OK calfront");
      return;
    }
    if (calfresh) {
      int max_age_ms = 0;
      if (!parse_integer(tokens[1], max_age_ms) ||
          max_age_ms < 30 || max_age_ms > 200) {
        std::snprintf(reply, capacity, "ERR calfresh measured_30to200ms");
        return;
      }
      calibration_stage_.freshness_ms = static_cast<std::uint32_t>(max_age_ms);
      calibration_stage_mask_ |= 0x20U;
      std::snprintf(reply, capacity, "OK calfresh");
      return;
    }
    // All four measured floor intervals, front clearance and sample-age
    // policy must be staged before a SINGLE atomic configure. No default
    // sensor geometry is silently adopted or committed by a network command.
    if (calibration_stage_mask_ != 0x3fU) {
      std::snprintf(reply, capacity, "ERR calcommit incomplete_stage");
      return;
    }
    calibration_stage_.calibrated = true;
    if (!guard_->configure(calibration_stage_)) {
      std::snprintf(reply, capacity, "ERR calcommit invalid_intervals");
      return;
    }
    force_disarm();
    calibration_stage_ = CliffConfig{};
    calibration_stage_mask_ = 0;
    std::snprintf(reply, capacity, "OK calcommit");
    return;
  }

  if (ping) {
    std::snprintf(reply, capacity, "OK ping");
  } else if (ir) {
    const auto& e = state_.terminal_ir;
    // RMT observation is read-only. A matching IR code is not an estimate
    // of mechanical bearing or proof of a powered/accepted charging dock.
    const int written = std::snprintf(
        reply, capacity,
        "{\"left_valid\":%s,\"right_valid\":%s,\"match\":%s,"
        "\"left_seq\":%lu,\"right_seq\":%lu,"
        "\"left_age_ms\":%lu,\"right_age_ms\":%lu,\"code\":%lu,"
        "\"motor_authorized\":false,\"charging_authorized\":false,"
        "\"physical_qualified\":false}",
        e.left_fresh ? "true" : "false",
        e.right_fresh ? "true" : "false",
        e.same_code ? "true" : "false",
        static_cast<unsigned long>(e.left_seq),
        static_cast<unsigned long>(e.right_seq),
        static_cast<unsigned long>(e.left_age_ms),
        static_cast<unsigned long>(e.right_age_ms),
        static_cast<unsigned long>(e.code));
    if (written < 0 || static_cast<std::size_t>(written) >= capacity)
      std::snprintf(reply, capacity, "ERR ir response_too_long");
  } else if (optics) {
    unsigned present_mask = 0, valid_mask = 0;
    std::uint32_t age[8]{};
    for (unsigned i = 0; i < 8; ++i) {
      const auto& sample = state_.optical[i];
      if (!sample.present) continue;
      present_mask |= 1U << i;
      age[i] = now_ms - sample.at_ms;
      const auto fresh = i < 5 ? age[i] < 200U : age[i] <= 350U;
      if (sample.valid && fresh) valid_mask |= 1U << i;
    }
    // Compact source words already read by ToF: never sensor calibration,
    // never a new motor or charging permit. A 512B reply is ample.
    const int written = std::snprintf(
        reply, capacity,
        "{\"optics\":{\"ambient_97\":[%u,%u,%u,%u,%u,%u,%u,%u],"
        "\"signal_97\":[%u,%u,%u,%u,%u,%u,%u,%u],"
        "\"age_ms\":[%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu],"
        "\"present_mask\":%u,\"valid_mask\":%u,"
        "\"physical_qualified\":false,\"motor_authorized\":false}}",
        static_cast<unsigned>(state_.optical[0].ambient_97),
        static_cast<unsigned>(state_.optical[1].ambient_97),
        static_cast<unsigned>(state_.optical[2].ambient_97),
        static_cast<unsigned>(state_.optical[3].ambient_97),
        static_cast<unsigned>(state_.optical[4].ambient_97),
        static_cast<unsigned>(state_.optical[5].ambient_97),
        static_cast<unsigned>(state_.optical[6].ambient_97),
        static_cast<unsigned>(state_.optical[7].ambient_97),
        static_cast<unsigned>(state_.optical[0].signal_97),
        static_cast<unsigned>(state_.optical[1].signal_97),
        static_cast<unsigned>(state_.optical[2].signal_97),
        static_cast<unsigned>(state_.optical[3].signal_97),
        static_cast<unsigned>(state_.optical[4].signal_97),
        static_cast<unsigned>(state_.optical[5].signal_97),
        static_cast<unsigned>(state_.optical[6].signal_97),
        static_cast<unsigned>(state_.optical[7].signal_97),
        static_cast<unsigned long>(age[0]),
        static_cast<unsigned long>(age[1]),
        static_cast<unsigned long>(age[2]),
        static_cast<unsigned long>(age[3]),
        static_cast<unsigned long>(age[4]),
        static_cast<unsigned long>(age[5]),
        static_cast<unsigned long>(age[6]),
        static_cast<unsigned long>(age[7]),
        present_mask, valid_mask);
    if (written < 0 || static_cast<std::size_t>(written) >= capacity)
      std::snprintf(reply, capacity, "ERR optics response_too_long");
  } else if (aux) {
    const auto& raw = state_.paw_pulse;
    const auto& a = state_.accessories;
    const std::uint32_t age = raw.valid ? now_ms - raw.at_ms : 0U;
    unsigned angle_present = 0, angle_valid = 0;
    for (unsigned i = 0; i < 3; ++i) {
      if (a.angle[i].present) angle_present |= 1U << i;
      if (a.angle[i].present && a.angle[i].valid &&
          now_ms - a.angle[i].at_ms < 350U) angle_valid |= 1U << i;
    }
    // A completed belly ADC conversion must never refresh an old jaw
    // sample or certify a current grasp contact, and an invalid or clipped
    // jaw channel must not suppress independent belly squeeze observation.
    const bool belly_unclipped = a.force.adc[0] != -32768 &&
                                 a.force.adc[0] != 32767;
    const bool belly_fresh = !belly_provenance_bad_ && a.force.present && ((a.force.valid_mask & 1U) != 0U ||
                              (a.force.valid_mask == 0U && a.force.valid)) &&
                             belly_unclipped &&
                             a.force.belly_sample_seq != 0U &&
                             now_ms - a.force.belly_at_ms < 500U;
    const bool jaw_unclipped = a.force.adc[1] != -32768 &&
                               a.force.adc[1] != 32767;
    const bool jaw_fresh = !jaw_provenance_bad_ &&
                           ((a.force.valid_mask & 2U) != 0U ||
                            (a.force.valid_mask == 0U && a.force.valid)) &&
                           jaw_unclipped &&
                           a.force.jaw_sample_seq != 0U &&
                           now_ms - a.force.jaw_at_ms < 500U;
    const bool force_fresh = belly_fresh && jaw_fresh;
    const bool climate_fresh = a.climate.valid &&
                               now_ms - a.climate.at_ms < 1000U;
    const bool bmp_fresh = a.barometer.present && a.barometer.valid &&
                           now_ms - a.barometer.at_ms < 2000U;
    const bool fuel_fresh = !fuel_provenance_bad_ &&
                            a.gauge.fuel_present && a.gauge.fuel_valid &&
                            a.gauge.fuel_sample_seq != 0U &&
                            now_ms - a.gauge.fuel_at_ms < 500U;
    const bool monitor_fresh = a.gauge.monitor_valid &&
                               a.gauge.monitor_sample_seq != 0U &&
                               now_ms - a.gauge.monitor_at_ms < 500U;
    const bool proximity_fresh = a.proximity.valid &&
                                 now_ms - a.proximity.at_ms < 350U;
    const bool dock_fresh = a.dock.present && a.dock.valid &&
                            now_ms - a.dock.at_ms < 500U;
    const bool nfc_fresh = a.nfc.present && a.nfc.valid &&
                           a.nfc.scan_seq != 0U && now_ms - a.nfc.at_ms < 1500U;
    // Independent bounded read-only telemetry. No synthesized heartbeat,
    // grip force, wheel odometry, current amps or gesture direction.
    const int written = std::snprintf(
        reply, capacity,
        "{\"pulse\":{\"present\":%s,\"valid\":%s,\"part_id\":%u,"
        "\"red\":%lu,\"ir\":%lu,\"age_ms\":%lu,\"seq\":%lu,"
        "\"fifo_ir_first\":%s,\"fifo_layout_physically_verified\":false,"
        "\"bpm\":null,\"medical\":false},"
        "\"angles\":{\"raw\":[%u,%u,%u],\"present_mask\":%u,"
        "\"valid_mask\":%u,\"magnet\":[%u,%u,%u],"
        "\"seq\":[%lu,%lu,%lu],\"age_ms\":[%lu,%lu,%lu],"
        "\"boot_id\":%lu,\"wheel_travel_qualified\":false},"
        "\"force\":{\"adc\":[%d,%d],\"belly_seq\":%lu,\"belly_age_ms\":%lu,\"belly_valid\":%s,\"jaw_seq\":%lu,\"boot_id\":%lu,\"jaw_age_ms\":%lu,\"jaw_valid\":%s,\"valid\":%s,\"calibrated\":false},"
        "\"climate\":{\"temp_centi\":%d,\"rh_centi\":%d,\"valid\":%s,\"seq\":%lu,\"age_ms\":%lu},"
        "\"bmp280\":{\"present\":%s,\"valid\":%s,\"chip_id\":%u,"
        "\"temp_centi\":%d,\"pressure_pa\":%u,\"seq\":%lu,\"age_ms\":%lu,"
        "\"physically_verified\":false},"
        "\"power\":{\"cell_mv\":%u,\"soc_centi\":%u,\"bus_mv\":%u,"
        "\"shunt_uv\":%d,\"fuel_valid\":%s,\"fuel_seq\":%lu,\"fuel_age_ms\":%lu,"
        "\"monitor_valid\":%s,"
        "\"pack_ma\":%d,\"pack_valid\":%s,\"pack_seq\":%lu,"
        "\"pack_age_ms\":%lu,\"current_calibrated\":false},"
        "\"proximity\":{\"raw\":%u,\"valid\":%s,\"gesture\":%u,\"gesture_events\":%lu,\"boot_id\":%lu,\"physically_qualified\":false},"
        "\"dock\":{\"present\":%s,\"valid\":%s,\"left_seated\":%s,\"right_seated\":%s,"
        "\"input_good\":%s,\"charge_indicated\":%s,\"seq\":%lu,\"age_ms\":%lu,"
        "\"charging_verified\":false},\"nfc\":{\"v\":%s,\"t\":%lu,\"e\":%lu,\"s\":%lu}}",
        raw.present ? "true" : "false",
        raw.valid && age <= 250U ? "true" : "false",
        static_cast<unsigned>(raw.part_id),
        static_cast<unsigned long>(raw.red),
        static_cast<unsigned long>(raw.ir),
        static_cast<unsigned long>(age),
        static_cast<unsigned long>(raw.sample_seq),
        kPulseIrFirstJson,
        static_cast<unsigned>(a.angle[0].angle),
        static_cast<unsigned>(a.angle[1].angle),
        static_cast<unsigned>(a.angle[2].angle),
        angle_present, angle_valid,
        static_cast<unsigned>(a.angle[0].magnet_status),
        static_cast<unsigned>(a.angle[1].magnet_status),
        static_cast<unsigned>(a.angle[2].magnet_status),
        static_cast<unsigned long>(a.angle[0].sample_seq),
        static_cast<unsigned long>(a.angle[1].sample_seq),
        static_cast<unsigned long>(a.angle[2].sample_seq),
        static_cast<unsigned long>(a.angle[0].sample_seq != 0U ?
            now_ms - a.angle[0].at_ms : 0U),
        static_cast<unsigned long>(a.angle[1].sample_seq != 0U ?
            now_ms - a.angle[1].at_ms : 0U),
        static_cast<unsigned long>(a.angle[2].sample_seq != 0U ?
            now_ms - a.angle[2].at_ms : 0U),
        static_cast<unsigned long>(boot_epoch_),
        static_cast<int>(a.force.adc[0]),
        static_cast<int>(a.force.adc[1]),
        static_cast<unsigned long>(a.force.belly_sample_seq),
        static_cast<unsigned long>(a.force.belly_sample_seq != 0U ?
            now_ms - a.force.belly_at_ms : 0U),
        belly_fresh ? "true" : "false",
        static_cast<unsigned long>(a.force.jaw_sample_seq),
        static_cast<unsigned long>(boot_epoch_),
        static_cast<unsigned long>(a.force.jaw_sample_seq != 0U ?
            now_ms - a.force.jaw_at_ms : 0U),
        jaw_fresh ? "true" : "false",
        force_fresh ? "true" : "false",
        a.climate.temp_centi, a.climate.humidity_centi,
        climate_fresh ? "true" : "false",
        static_cast<unsigned long>(a.climate.sample_seq),
        static_cast<unsigned long>(a.climate.present ? now_ms - a.climate.at_ms : 0U),
        a.barometer.present ? "true" : "false",
        bmp_fresh ? "true" : "false",
        static_cast<unsigned>(a.barometer.chip_id),
        bmp_fresh ? a.barometer.temp_centi : 0,
        bmp_fresh ? a.barometer.pressure_pa : 0U,
        static_cast<unsigned long>(a.barometer.sample_seq),
        static_cast<unsigned long>(a.barometer.present ?
            now_ms - a.barometer.at_ms : 0U),
        a.gauge.cell_mv, a.gauge.soc_centi, a.gauge.bus_mv,
        a.gauge.shunt_uv, fuel_fresh ? "true" : "false",
        static_cast<unsigned long>(a.gauge.fuel_sample_seq),
        static_cast<unsigned long>(a.gauge.fuel_sample_seq != 0U ?
            now_ms - a.gauge.fuel_at_ms : 0U),
        monitor_fresh ? "true" : "false",
        monitor_fresh && a.gauge.pack_current_valid ?
            a.gauge.pack_current_ma : 0,
        monitor_fresh && a.gauge.pack_current_valid ? "true" : "false",
        static_cast<unsigned long>(a.gauge.monitor_sample_seq),
        static_cast<unsigned long>(a.gauge.monitor_sample_seq != 0U ?
            now_ms - a.gauge.monitor_at_ms : 0U),
        static_cast<unsigned>(a.proximity.raw),
        proximity_fresh ? "true" : "false",
        static_cast<unsigned>(a.proximity.gesture_direction),
        static_cast<unsigned long>(a.proximity.gesture_events),
        static_cast<unsigned long>(boot_epoch_),
        a.dock.present ? "true" : "false", dock_fresh ? "true" : "false",
        dock_fresh && a.dock.left_seated ? "true" : "false",
        dock_fresh && a.dock.right_seated ? "true" : "false",
        dock_fresh && a.dock.input_good ? "true" : "false",
        dock_fresh && a.dock.charge_indicated ? "true" : "false",
        static_cast<unsigned long>(a.dock.sample_seq),
        static_cast<unsigned long>(
            a.dock.present ? now_ms - a.dock.at_ms : 0U),
        nfc_fresh ? "true" : "false",
        static_cast<unsigned long>(nfc_fresh && a.nfc.tag_visible ? a.nfc.tag_token : 0U),
        static_cast<unsigned long>(a.nfc.tag_events),
        static_cast<unsigned long>(a.nfc.scan_seq));
    if (written < 0 || static_cast<std::size_t>(written) >= capacity)
      std::snprintf(reply, capacity, "ERR aux response_too_long");
  } else if (status) {
    // Five read-only measurements retain missing/invalid/age information
    // separately. Never use these values to bypass the local cliff latch.
    RangeDiagnostic ranges[kCliffSensorCount]{};
    unsigned present_mask = 0;
    unsigned valid_mask = 0;
    if (guard_ != nullptr) {
      for (std::uint8_t i = 0; i < kCliffSensorCount; ++i) {
        ranges[i] = guard_->diagnostic(i, now_ms);
        if (ranges[i].present) present_mask |= 1U << i;
        if (ranges[i].present && ranges[i].valid) valid_mask |= 1U << i;
      }
    }
    const std::uint32_t imu_age = now_ms - imu_.at_ms;
    unsigned side_present_mask = 0, side_valid_mask = 0;
    for (int i = 0; i < 3; ++i) {
      if (state_.side_present[i]) side_present_mask |= 1U << i;
      // Validity is an observation age, not a sticky historical success.
      // Keep the present mask and raw distance for diagnostics, but do not
      // publish stale side/rear readings as current physical evidence.
      if (state_.side_valid[i] &&
          now_ms - state_.side_at_ms[i] <= 350U)
        side_valid_mask |= 1U << i;
    }
    const bool imu_valid = imu_fresh(now_ms);
    // Sensor evidence remains reportable when an asserted MPU interrupt
    // correctly makes that same frame unsafe for motor permission. Retain
    // chip identity and age guards so a stale or swapped board cannot
    // manufacture a current low-g observation in the shared Mac brain.
    // Do not present a duplicate or out-of-order conversion as fresh raw
    // MPU evidence while the independent motion gate rejects its provenance.
    const bool imu_raw_fresh = imu_.valid && !imu_provenance_bad_ &&
        now_ms - imu_.at_ms <= 200U &&
        state_.imu_family >= 1U && state_.imu_family <= 4U &&
        imu_.model == static_cast<BerryModel>(state_.imu_family) &&
        BerryImu::identify(state_.imu_gyro_id, state_.imu_aux_id) == imu_.model;
    // Report actual LOCAL motion readiness. A healthy optical guard alone
    // cannot make the robot ready while its dock, IMU, touch or physical
    // driver fault interlock would reject an ARM request.
    const bool cliff_ready = guarded_motion_profile() && guard_ != nullptr &&
        guard_->evaluate(now_ms);
    const bool driver_unhealthy = dc_fault_latched_ || dc_driver_fault_bad(now_ms);
    const bool dock_unhealthy = dock_power_lockout_ ||
        dock_monitor_fault_latched_ || dock_telemetry_bad(now_ms);
    const bool bumper_hit = state_.bumper_raw ||
        ((state_.extra_mask & 1U) != 0U && state_.bumper_active);
    const bool touch_hit = state_.touch_active || state_.touch_raw_active;
    // Movement already in progress uses the 3200 mV emergency stop, but
    // a NEW arm requires 3300 mV. Do not tell Mac the robot is ready at
    // 3250 mV when the very next arm command will be rejected.
    const bool battery_below_arm_min = state_.accessories.gauge.fuel_valid &&
        state_.accessories.gauge.cell_mv < 3300U;
    const bool local_motion_ready = cliff_ready && !driver_unhealthy &&
        !motor_cutoff_unqualified_ &&
        // Guarded ARM attaches BOTH MG90S channels. One unmeasured lifting
        // link makes that attachment unsafe even if jaw limits are known.
        (!lift_limits_required_ || lift_limits_configured_) &&
        (!grip_feedback_required_ || jaw_limits_configured_) &&
        !bumper_fault_latched_ && !battery_fault_latched_ &&
        !fuel_monitor_fault_latched_ &&
        (!fuel_monitor_required_ || fuel_monitor_fresh(now_ms)) &&
        !motor_watchdog_latched_ && !command_timeout_latched_ &&
        !imu_low_g_latched_ && !imu_attitude_latched_ &&
        !imu_sensor_fault_latched_ &&
        (!imu_attitude_required_ || attitude_recovery_ready(now_ms)) &&
        !dock_unhealthy && !bumper_hit && !touch_hit &&
        !battery_below_arm_min &&
        (!imu_motion_required_ || imu_valid);
    // A critical cliff/bus fault takes precedence over a simultaneous
    // cosmetic or optional-input event in the Mac's multimodal context.
    const char* local_fault =
        dc_fault_latched_ ? "dc_driver_fault_latched" :
        dc_driver_fault_bad(now_ms) ? "dc_driver_fault_unavailable" :
        motor_watchdog_latched_ ? "motor_watchdog_latched" :
        command_timeout_latched_ ? "command_timeout_latched" :
        motor_cutoff_unqualified_ ? "motor_cutoff_unqualified" :
        guarded_motion_profile() && !cliff_ready ?
            guard_ == nullptr ? "missing_guard" :
            CliffGuard::fault_name(guard_->fault()) :
        dock_power_lockout_ ? "dock_power_connected" :
        dock_monitor_fault_latched_ ? "dock_monitor_latched" :
        dock_telemetry_bad(now_ms) ? "dock_gpio_missing_or_stale" :
        bumper_hit ? "bumper_active" :
        bumper_fault_latched_ ? "bumper_latched" :
        touch_hit ? "touch_active" :
        imu_low_g_latched_ ? "imu_low_g_latched" :
        imu_attitude_latched_ ? "imu_attitude_latched" :
        imu_attitude_required_ && !imu_attitude_configured_ ?
            "imu_attitude_unqualified" :
        imu_attitude_required_ && !attitude_recovery_ready(now_ms) ?
            "imu_attitude_not_upright" :
        // Once motion trips this local latch, report mandatory USB recovery
        // ahead of mutable raw IMU symptoms; raw telemetry remains available.
        imu_sensor_fault_latched_ ? "imu_sensor_fault_latched" :
        imu_motion_required_ && imu_raw_fresh &&
            imu_.model == BerryModel::Mpu6050 &&
            imu_.low_g_status_valid && imu_.low_g_irq ?
            "imu_low_g_candidate" :
        imu_motion_required_ && imu_raw_fresh &&
            imu_.model == BerryModel::Mpu6050 &&
            !imu_.low_g_status_valid ? "imu_low_g_status_unavailable" :
        imu_motion_required_ && imu_.valid &&
            imu_.model == BerryModel::Mpu6050 &&
            imu_.accel[0] == 0 && imu_.accel[1] == 0 &&
            imu_.accel[2] == 0 ? "imu_zero_accel" :
        imu_motion_required_ && imu_provenance_bad_ ? "imu_sample_unordered" :
        imu_motion_required_ && !imu_valid ? "imu_missing_or_stale" :
        // Persistent physical protection faults outrank transient voltage.
        // A recovered or still-low cell does not silently clear USB rearm.
        battery_fault_latched_ ? "battery_low_latched" :
        fuel_monitor_fault_latched_ ? "fuel_monitor_latched" :
        battery_below_arm_min ? "battery_low" :
        fuel_monitor_required_ && !fuel_monitor_fresh(now_ms) ?
            "fuel_monitor_missing_or_stale" :
        guarded_motion_profile() && lift_limits_required_ &&
            !lift_limits_configured_ ? "lift_limits_unqualified" :
        guarded_motion_profile() && grip_feedback_required_ &&
            !jaw_limits_configured_ ? "jaw_limits_unqualified" :
        !guarded_motion_profile() ? "not_required" : "none";
    const int written = std::snprintf(
        reply, capacity,
        "{\"armed\":%s,\"motor\":{\"m0\":%d,\"m1\":%d},"
        "\"servo\":{\"lift\":%d,\"grip\":%d,\"lift_target\":%d,"
        "\"grip_target\":%d,\"attached\":%s,\"position_source\":\"commanded\"},"
        "\"watchdog_ms\":%lu,\"drive_ms\":%lu,\"protocol\":2,"
        "\"backend\":\"%s\",\"touch\":{\"active\":%s,\"count\":%lu,\"tap_count\":%lu,\"double_count\":%lu,\"hold_count\":%lu},\"extras\":{\"mask\":%u,\"bumper\":%s,\"bumps\":%lu,\"reed\":%s,\"reed_count\":%lu,\"pir\":%s,\"pir_count\":%lu,\"cap\":%u,\"cap_ok\":%s,\"cap_events\":%lu},\"side_ranges\":{\"mm\":[%u,%u,%u],\"age_ms\":[%lu,%lu,%lu],\"sample_ms\":[%lu,%lu,%lu],\"boot_id\":%lu,\"present_mask\":%u,\"valid_mask\":%u,\"motion_certified\":false},\"imu\":{\"family\":%u,\"gyro_id\":%u,\"aux_id\":%u,\"valid\":%s,\"acc\":[%d,%d,%d],\"gyro\":[%d,%d,%d],\"temp_raw\":%d,\"temp_valid\":%s,\"low_g_valid\":%s,\"low_g_irq\":%s,\"low_g_seq\":%lu,\"age_ms\":%lu,\"sample_ms\":%lu,\"boot_id\":%lu},\"safety\":{\"required\":%s,\"ready\":%s,"
        "\"fault\":\"%s\",\"sensor\":%u},\"ranges\":{\"mm\":[%u,%u,%u,%u,%u],"
        "\"age_ms\":[%lu,%lu,%lu,%lu,%lu],\"present_mask\":%u,\"valid_mask\":%u}}",
        state_.armed ? "true" : "false", state_.left, state_.right,
        state_.lift, state_.grip, state_.lift_target, state_.grip_target,
        state_.servos_attached ? "true" : "false",
        static_cast<unsigned long>(watchdog_remaining(now_ms)),
        static_cast<unsigned long>(drive_remaining(now_ms)),
        profile_ == BodyProfile::StepperGuarded ? "stepper_28byj48" :
          profile_ == BodyProfile::DcGuarded ? "dc_pwm_guarded" : "dc_pwm",
        (state_.touch_active || state_.touch_raw_active) ? "true" : "false",
        static_cast<unsigned long>(state_.touch_count),
        static_cast<unsigned long>(state_.touch_taps),
        static_cast<unsigned long>(state_.touch_double_taps),
        static_cast<unsigned long>(state_.touch_holds),
        static_cast<unsigned>(state_.extra_mask),
        (state_.bumper_active || state_.bumper_raw) ? "true" : "false",
        static_cast<unsigned long>(state_.bumper_events),
        state_.reed_active ? "true" : "false",
        static_cast<unsigned long>(state_.reed_events),
        state_.pir_active ? "true" : "false",
        static_cast<unsigned long>(state_.pir_events),
        static_cast<unsigned>(state_.cap_mask),
        state_.cap_valid ? "true" : "false",
        static_cast<unsigned long>(state_.cap_events),
        static_cast<unsigned>(state_.side_mm[0]),
        static_cast<unsigned>(state_.side_mm[1]),
        static_cast<unsigned>(state_.side_mm[2]),
        static_cast<unsigned long>(state_.side_present[0] ? now_ms - state_.side_at_ms[0] : 0),
        static_cast<unsigned long>(state_.side_present[1] ? now_ms - state_.side_at_ms[1] : 0),
        static_cast<unsigned long>(state_.side_present[2] ? now_ms - state_.side_at_ms[2] : 0),
        static_cast<unsigned long>(state_.side_present[0] ? state_.side_at_ms[0] : 0),
        static_cast<unsigned long>(state_.side_present[1] ? state_.side_at_ms[1] : 0),
        static_cast<unsigned long>(state_.side_present[2] ? state_.side_at_ms[2] : 0),
        static_cast<unsigned long>(boot_epoch_),
        side_present_mask, side_valid_mask,
        static_cast<unsigned>(state_.imu_family),
        static_cast<unsigned>(state_.imu_gyro_id),
        static_cast<unsigned>(state_.imu_aux_id),
        imu_valid ? "true" : "false",
        imu_.accel[0], imu_.accel[1], imu_.accel[2],
        imu_.gyro[0], imu_.gyro[1], imu_.gyro[2],
        imu_.temperature_raw,
        (imu_raw_fresh && imu_.model == BerryModel::Mpu6050) ? "true" : "false",
        (imu_raw_fresh && imu_.model == BerryModel::Mpu6050 &&
         imu_.low_g_status_valid) ? "true" : "false",
        (imu_raw_fresh && imu_.model == BerryModel::Mpu6050 &&
         imu_.low_g_status_valid && imu_.low_g_irq) ? "true" : "false",
        static_cast<unsigned long>(imu_.low_g_event_seq),
        static_cast<unsigned long>(imu_.valid ? imu_age : 0U),
        static_cast<unsigned long>(imu_.valid ? imu_.at_ms : 0U),
        static_cast<unsigned long>(boot_epoch_),
        guarded_motion_profile() ? "true" : "false",
        local_motion_ready ? "true" : "false",
        local_fault,
        static_cast<unsigned>(guard_ == nullptr ? kNoFaultSensor : guard_->fault_sensor()),
        static_cast<unsigned>(ranges[0].distance_mm),
        static_cast<unsigned>(ranges[1].distance_mm),
        static_cast<unsigned>(ranges[2].distance_mm),
        static_cast<unsigned>(ranges[3].distance_mm),
        static_cast<unsigned>(ranges[4].distance_mm),
        static_cast<unsigned long>(ranges[0].age_ms),
        static_cast<unsigned long>(ranges[1].age_ms),
        static_cast<unsigned long>(ranges[2].age_ms),
        static_cast<unsigned long>(ranges[3].age_ms),
        static_cast<unsigned long>(ranges[4].age_ms),
        present_mask, valid_mask);
    if (written < 0 || static_cast<std::size_t>(written) >= capacity)
      std::snprintf(reply, capacity, "ERR status response_too_long");
  } else if (rearm) {
    // Head/HTTP/MCP jobs may arm only an already-clear body. A new local USB
    // action is required after a fault; an older job permit cannot clear it.
    if (!local_safety_rearm) {
      std::snprintf(reply, capacity, "ERR rearm local_only");
      return;
    }
    stop_motion();
    state_.armed = false;
    if (dc_driver_fault_bad(now_ms)) {
      std::snprintf(reply, capacity, "ERR rearm dc_driver_fault_unhealthy");
      return;
    }
    // Local recovery is an explicit SAFE resume decision, not a preapproval
    // while the robot is still in contact, docked or without live sensors.
    // Otherwise an old USB rearm could clear the cliff latch during pickup,
    // and a later head command could arm immediately after putdown.
    if (dock_power_lockout_) {
      std::snprintf(reply, capacity, "ERR rearm dock_power_connected");
      return;
    }
    if (dock_telemetry_bad(now_ms)) {
      std::snprintf(reply, capacity, "ERR rearm dock_gpio_missing_or_stale");
      return;
    }
    if (dock_monitor_fault_latched_) {
      // A cached previously good unseated GPIOA packet is not independent
      // post-fault evidence. Require forward-moving sequence AND acquisition
      // timestamp, including uint32 wrap, before the LOCAL USB can recover.
      const std::uint32_t seq_delta = dock_last_seq_ - dock_monitor_fault_seq_;
      const std::uint32_t time_delta =
          dock_last_at_ms_ - dock_monitor_fault_at_ms_;
      if (!dock_sample_seen_ || dock_last_pins_ != 0U ||
          seq_delta == 0U || seq_delta >= 0x80000000U ||
          time_delta == 0U || time_delta >= 0x80000000U) {
        std::snprintf(reply, capacity, "ERR rearm dock_monitor_no_new_sample");
        return;
      }
    }
    if (state_.bumper_raw ||
        ((state_.extra_mask & 1U) && state_.bumper_active)) {
      std::snprintf(reply, capacity, "ERR rearm bumper_active");
      return;
    }
    if (state_.touch_active || state_.touch_raw_active) {
      std::snprintf(reply, capacity, "ERR rearm touch_active");
      return;
    }
    if (imu_motion_required_ && !imu_fresh(now_ms)) {
      std::snprintf(reply, capacity, "ERR rearm imu_missing_or_stale");
      return;
    }
    if (imu_attitude_required_ && !attitude_recovery_ready(now_ms)) {
      std::snprintf(reply, capacity, "ERR rearm imu_attitude_not_upright");
      return;
    }
    if (fuel_monitor_required_ && !fuel_monitor_fresh(now_ms)) {
      std::snprintf(reply, capacity, "ERR rearm fuel_monitor_missing_or_stale");
      return;
    }
    if (fuel_monitor_fault_latched_) {
      const auto& fuel = state_.accessories.gauge;
      const auto seq_delta = fuel.fuel_sample_seq - fuel_monitor_fault_seq_;
      const auto time_delta = fuel.fuel_at_ms - fuel_monitor_fault_at_ms_;
      if (seq_delta == 0U || seq_delta >= 0x80000000U ||
          time_delta == 0U || time_delta >= 0x80000000U) {
        std::snprintf(reply, capacity, "ERR rearm fuel_monitor_no_new_sample");
        return;
      }
    }
    if (battery_fault_latched_) {
      const auto& fuel = state_.accessories.gauge;
      const auto seq_delta = fuel.fuel_sample_seq - battery_fault_seq_;
      const auto time_delta = fuel.fuel_at_ms - battery_fault_at_ms_;
      if (!fuel.fuel_present || !fuel.fuel_valid ||
          fuel.fuel_sample_seq == 0U || now_ms - fuel.fuel_at_ms >= 500U ||
          fuel.cell_mv < 3300U || seq_delta == 0U ||
          seq_delta >= 0x80000000U || time_delta == 0U ||
          time_delta >= 0x80000000U) {
        std::snprintf(reply, capacity, "ERR rearm battery_unsafe_or_stale");
        return;
      }
    }
    if (!guarded_motion_profile() || guard_ == nullptr ||
        !guard_->try_rearm(now_ms)) {
      std::snprintf(reply, capacity, "ERR rearm safety_interlock");
      return;
    }
    dc_fault_latched_ = false;  // local USB only, after fresh HIGH nFAULT
    dock_monitor_fault_latched_ = false; // local USB after new unseated GPIOA
    bumper_fault_latched_ = false; // only USB, after released raw contact
    battery_fault_latched_ = false; // after newer measured safe fuel sample
    fuel_monitor_fault_latched_ = false; // after fresh independently acquired data
    motor_watchdog_latched_ = false; // no old drive resumed
    command_timeout_latched_ = false; // local USB recovery only
    imu_low_g_latched_ = false; // after a truly fresh, clear MPU status
    imu_attitude_latched_ = false; // two upright samples and local USB
    imu_sensor_fault_latched_ = false; // after fresh sensor and USB recovery
    std::snprintf(reply, capacity, "OK rearm");
  } else if (arm) {
    if (motor_cutoff_unqualified_) {
      std::snprintf(reply, capacity, "ERR arm motor_cutoff_unqualified");
      return;
    }
    if (guarded_motion_profile() && lift_limits_required_ &&
        !lift_limits_configured_) {
      std::snprintf(reply, capacity, "ERR arm lift_limits_unqualified");
      return;
    }
    if (guarded_motion_profile() && grip_feedback_required_ &&
        !jaw_limits_configured_) {
      std::snprintf(reply, capacity, "ERR arm jaw_limits_unqualified");
      return;
    }
    if (fuel_monitor_fault_latched_) {
      std::snprintf(reply, capacity, "ERR arm fuel_monitor_latched");
      return;
    }
    if (fuel_monitor_required_ && !fuel_monitor_fresh(now_ms)) {
      std::snprintf(reply, capacity, "ERR arm fuel_monitor_missing_or_stale");
      return;
    }
    if (battery_fault_latched_) {
      std::snprintf(reply, capacity, "ERR arm battery_low_latched");
      return;
    }
    if (bumper_fault_latched_) {
      std::snprintf(reply, capacity, "ERR arm bumper_latched");
      return;
    }
    if (imu_sensor_fault_latched_) {
      std::snprintf(reply, capacity, "ERR arm imu_sensor_fault_latched");
      return;
    }
    if (imu_low_g_latched_) {
      std::snprintf(reply, capacity, "ERR arm imu_low_g_latched");
      return;
    }
    if (imu_attitude_latched_) {
      std::snprintf(reply, capacity, "ERR arm imu_attitude_latched");
      return;
    }
    if (imu_attitude_required_ && !imu_attitude_configured_) {
      std::snprintf(reply, capacity, "ERR arm imu_attitude_unqualified");
      return;
    }
    if (motor_watchdog_latched_) {
      std::snprintf(reply, capacity, "ERR arm motor_watchdog_latched");
      return;
    }
    if (command_timeout_latched_) {
      std::snprintf(reply, capacity, "ERR arm command_timeout_latched");
      return;
    }
    if (dc_fault_latched_ || dc_driver_fault_bad(now_ms)) {
      std::snprintf(reply, capacity, "ERR arm dc_driver_fault_interlock");
      return;
    }
    if (dock_power_lockout_) {
      std::snprintf(reply, capacity, "ERR arm dock_power_connected");
      return;
    }
    if (dock_monitor_fault_latched_) {
      std::snprintf(reply, capacity, "ERR arm dock_monitor_latched");
      return;
    }
    if (dock_telemetry_bad(now_ms)) {
      std::snprintf(reply, capacity, "ERR arm dock_gpio_missing_or_stale");
      return;
    }
    if (state_.bumper_raw ||
        ((state_.extra_mask & 1U) && state_.bumper_active)) {
      std::snprintf(reply, capacity, "ERR arm bumper_active");
      return;
    }
    if (state_.touch_active || state_.touch_raw_active) {
      std::snprintf(reply, capacity, "ERR arm touch_active");
      return;
    }
    if (guarded_motion_profile() &&
        (guard_ == nullptr || !guard_->evaluate(now_ms))) {
      std::snprintf(reply, capacity, "ERR arm safety_interlock");
      return;
    }
    if (imu_motion_required_ && !imu_fresh(now_ms)) {
      std::snprintf(reply, capacity, "ERR arm imu_missing_or_stale");
      return;
    }
    if (imu_attitude_required_ && !attitude_recovery_ready(now_ms)) {
      std::snprintf(reply, capacity, "ERR arm imu_attitude_not_upright");
      return;
    }
    if (state_.accessories.gauge.fuel_valid &&
        state_.accessories.gauge.cell_mv < 3300U) {
      std::snprintf(reply, capacity, "ERR arm battery_low");
      return;
    }
    // Explicit re-arm also clears earlier targets; it never resumes old motion.
    stop_motion();
    state_.armed = true;
    state_.servos_attached = true;
    last_control_ms_ = now_ms;
    last_servo_step_ms_ = now_ms;
    std::snprintf(reply, capacity, "OK arm");
  } else if (disarm) {
    force_disarm();
    std::snprintf(reply, capacity, "OK disarm");
  } else if (halt) {
    // Terminal operator/user cancellation: unlike the short-pulse STOP,
    // a late abandoned job must NOT drive on the same armed session.
    // Preserve servo PWM only to avoid deliberately dropping a held key.
    stop_motion();
    state_.armed = false;
    std::snprintf(reply, capacity, "OK halt");
  } else if (stop) {
    stop_motion();
    if (state_.armed) last_control_ms_ = now_ms;
    std::snprintf(reply, capacity, "OK stop");
  } else if (!state_.armed) {
    std::snprintf(reply, capacity, "ERR %s disarmed", command);
  } else {
    if (drive) {
      // The installed three side/rear ToF lanes are READ-ONLY context, not
      // a qualified reverse/pivot swept-footprint safety guard. Even with
      // fresh floor/front ranges, reject rearward travel and any turn until
      // physical coverage and stopping clearance are explicitly qualified.
      // Rejecting a live direction change stops both wheels immediately.
      // It does NOT renew the 500 ms control lease or release grasp PWM.
      if (guarded_motion_profile() &&
          (first < 0 || second < 0 || first != second)) {
        stop_motion();
        std::snprintf(reply, capacity,
                      "ERR drive directional_clearance_unqualified");
        return;
      }
      state_.left = limited_speed(first);
      state_.right = limited_speed(second);
      drive_started_ms_ = now_ms;
      drive_duration_ms_ = static_cast<std::uint32_t>(duration);
      std::snprintf(reply, capacity, "OK drive left=%d right=%d ms=%d",
                    state_.left, state_.right, duration);
    } else if (lift || grip) {
      if (lift && lift_limits_required_) {
        if (!lift_limits_configured_) {
          std::snprintf(reply, capacity, "ERR lift travel_unqualified");
          return;
        }
        if (first < lift_limits_.min_deg || first > lift_limits_.max_deg) {
          std::snprintf(reply, capacity, "ERR lift outside_measured_endstops");
          return;
        }
      }
      if (grip && grip_feedback_required_ && !grip_feedback_fresh(now_ms)) {
        std::snprintf(reply, capacity, "ERR grip force_missing_or_stale");
        return;
      }
      if (grip && grip_feedback_required_) {
        if (!jaw_limits_configured_) {
          std::snprintf(reply, capacity, "ERR grip local_force_limits_missing");
          return;
        }
        if (!jaw_target_within_limits(first)) {
          std::snprintf(reply, capacity, "ERR grip outside_measured_endstops");
          return;
        }
        if (jaw_target_closes(first) && !jaw_force_allows_closing()) {
          std::snprintf(reply, capacity, "ERR grip local_force_limit_or_reversal");
          return;
        }
        // A newly accepted command requires another independent conversion.
        jaw_sample_motion_budget_ = 0;
      }
      (lift ? state_.lift_target : state_.grip_target) = first;
      std::snprintf(reply, capacity, "OK %s angle=%d", command, first);
    } else {
      std::snprintf(reply, capacity, "OK keepalive");
    }
    // A rejected feedback/endstop/force command is NOT a valid keepalive.
    // Renew the remote control lease only after successful authorization.
    last_control_ms_ = now_ms;
  }
}

bool LineReceiver::feed(char byte, std::uint32_t now_ms, BodyControl& control,
                        char* reply, std::size_t capacity, std::uint64_t sample_us) {
  control.tick(now_ms);
  // The link may stall or reconnect between bytes. Reject the WHOLE stale
  // line rather than joining an old command prefix to a later command.
  // The uint32 elapsed comparison also works across millis() rollover.
  if (frame_started_ && now_ms - last_byte_ms_ >= kWatchdogMs)
    frame_timed_out_ = true;
  if (byte == '\n') {
    if (frame_timed_out_) {
      std::snprintf(reply, capacity, "ERR input interbyte_timeout");
    } else if (overlong_) {
      std::snprintf(reply, capacity, "ERR input line_too_long");
    } else if (invalid_) {
      std::snprintf(reply, capacity, "ERR input invalid_ascii");
    } else {
      control.execute(line_, length_, now_ms, reply, capacity, local_safety_rearm_,
                      sample_us);
    }
    length_ = 0;
    saw_cr_ = false;
    invalid_ = false;
    overlong_ = false;
    frame_started_ = false;
    frame_timed_out_ = false;
    return true;
  }
  frame_started_ = true;
  last_byte_ms_ = now_ms;
  if (saw_cr_) invalid_ = true;  // CR is allowed only immediately before LF.
  if (byte == '\r') {
    saw_cr_ = true;
    return false;
  }
  const unsigned char ascii = static_cast<unsigned char>(byte);
  if (ascii < 32 || ascii > 126) invalid_ = true;
  if (length_ == kMaxLineLength) {
    overlong_ = true;
  } else {
    line_[length_++] = byte;
  }
  return false;
}

}  // namespace desk_robot
