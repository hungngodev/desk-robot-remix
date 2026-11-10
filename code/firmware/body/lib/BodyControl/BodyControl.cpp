#include "BodyControl.h"
#include "CliffGuard.h"

#include <cstdio>
#include <cstring>

namespace desk_robot {
namespace {

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

void BodyControl::stop_motion() {
  state_.left = 0;
  state_.right = 0;
  drive_duration_ms_ = 0;
  state_.lift_target = state_.lift;
  state_.grip_target = state_.grip;
}

void BodyControl::set_touch(bool active, std::uint32_t now_ms) {
  if (active == state_.touch_active) return;
  state_.touch_active = active;
  if (active) {
    ++state_.touch_count;
    touch_started_ms_ = now_ms;
    touch_hold_emitted_ = false;
    // A touched moving robot stops locally; no Mac event or model is needed.
    if (state_.armed) {
      stop_motion();
      state_.armed = false;
    }
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
  if (profile_ == BodyProfile::StepperGuarded &&
      (guard_ == nullptr || !guard_->evaluate(now_ms))) {
    stop_motion();
    state_.armed = false;
    // A floor/bus fault must not deliberately release a held payload.
    return;
  }
  if (!state_.armed) return;
  // Unsigned elapsed arithmetic remains correct when millis() wraps.
  if (now_ms - last_control_ms_ >= kWatchdogMs) {
    stop_motion();
    state_.armed = false;
    // Keep the last servo PWM on communication loss: detaching could drop a
    // held object. Only explicit disarm/hardware fault detaches the servos.
    return;
  }
  if (drive_duration_ms_ != 0 && now_ms - drive_started_ms_ >= drive_duration_ms_) {
    state_.left = 0;
    state_.right = 0;
    drive_duration_ms_ = 0;
  }
  const std::uint32_t steps = (now_ms - last_servo_step_ms_) / kServoStepMs;
  if (steps != 0) {
    last_servo_step_ms_ += steps * kServoStepMs;
    move_toward(state_.lift, state_.lift_target, steps);
    move_toward(state_.grip, state_.grip_target, steps);
  }
}

void BodyControl::execute(const char* line, std::size_t length,
                          std::uint32_t now_ms, char* reply,
                          std::size_t capacity, bool local_safety_rearm) {
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
  const bool keepalive = std::strcmp(command, "keepalive") == 0;
  const bool ping = std::strcmp(command, "ping") == 0;
  const bool status = std::strcmp(command, "status") == 0;
  const bool calfloor = std::strcmp(command, "calfloor") == 0;
  const bool calfront = std::strcmp(command, "calfront") == 0;
  const bool calfresh = std::strcmp(command, "calfresh") == 0;
  const bool calcommit = std::strcmp(command, "calcommit") == 0;
  const bool calabort = std::strcmp(command, "calabort") == 0;
  const bool calibration = calfloor || calfront || calfresh || calcommit || calabort;
  if (!(drive || lift || grip || arm || rearm || disarm || stop || keepalive || ping || status || calibration)) {
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
    if (!local_safety_rearm || profile_ != BodyProfile::StepperGuarded || guard_ == nullptr) {
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
          minimum < 1 || maximum < minimum || maximum > 1300) {
        std::snprintf(reply, capacity, "ERR calfloor channel_0to3_min_max_1to1300");
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
          near_mm < 1 || far_mm <= near_mm || far_mm > 1300) {
        std::snprintf(reply, capacity, "ERR calfront near_far_1to1300");
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
    const bool imu_valid = imu_.valid && imu_.model != BerryModel::Unknown &&
                           imu_age <= 200U;
    std::snprintf(
        reply, capacity,
        "{\"armed\":%s,\"motor\":{\"m0\":%d,\"m1\":%d},"
        "\"servo\":{\"lift\":%d,\"grip\":%d,\"lift_target\":%d,"
        "\"grip_target\":%d,\"attached\":%s,\"position_source\":\"commanded\"},"
        "\"watchdog_ms\":%lu,\"drive_ms\":%lu,\"protocol\":2,"
        "\"backend\":\"%s\",\"touch\":{\"active\":%s,\"count\":%lu,\"tap_count\":%lu,\"double_count\":%lu,\"hold_count\":%lu},\"imu\":{\"model\":%u,\"valid\":%s,\"acc\":[%d,%d,%d],\"gyro\":[%d,%d,%d],\"age_ms\":%lu},\"safety\":{\"required\":%s,\"ready\":%s,"
        "\"fault\":\"%s\",\"sensor\":%u},\"ranges\":{\"mm\":[%u,%u,%u,%u,%u],"
        "\"age_ms\":[%lu,%lu,%lu,%lu,%lu],\"present_mask\":%u,\"valid_mask\":%u}}",
        state_.armed ? "true" : "false", state_.left, state_.right,
        state_.lift, state_.grip, state_.lift_target, state_.grip_target,
        state_.servos_attached ? "true" : "false",
        static_cast<unsigned long>(watchdog_remaining(now_ms)),
        static_cast<unsigned long>(drive_remaining(now_ms)),
        profile_ == BodyProfile::StepperGuarded ? "stepper_28byj48" : "dc_pwm",
        state_.touch_active ? "true" : "false",
        static_cast<unsigned long>(state_.touch_count),
        static_cast<unsigned long>(state_.touch_taps),
        static_cast<unsigned long>(state_.touch_double_taps),
        static_cast<unsigned long>(state_.touch_holds),
        static_cast<unsigned>(imu_.model), imu_valid ? "true" : "false",
        imu_.accel[0], imu_.accel[1], imu_.accel[2],
        imu_.gyro[0], imu_.gyro[1], imu_.gyro[2],
        static_cast<unsigned long>(imu_.valid ? imu_age : 0U),
        profile_ == BodyProfile::StepperGuarded ? "true" : "false",
        profile_ == BodyProfile::StepperGuarded && guard_ != nullptr &&
            guard_->evaluate(now_ms) ? "true" : "false",
        profile_ != BodyProfile::StepperGuarded ? "not_required" :
            guard_ == nullptr ? "missing_guard" : CliffGuard::fault_name(guard_->fault()),
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
  } else if (rearm) {
    // Head/HTTP/MCP jobs may arm only an already-clear body. A new local USB
    // action is required after a fault; an older job permit cannot clear it.
    if (!local_safety_rearm) {
      std::snprintf(reply, capacity, "ERR rearm local_only");
      return;
    }
    stop_motion();
    state_.armed = false;
    if (profile_ != BodyProfile::StepperGuarded || guard_ == nullptr ||
        !guard_->try_rearm(now_ms)) {
      std::snprintf(reply, capacity, "ERR rearm safety_interlock");
      return;
    }
    std::snprintf(reply, capacity, "OK rearm");
  } else if (arm) {
    if (state_.touch_active) {
      std::snprintf(reply, capacity, "ERR arm touch_active");
      return;
    }
    if (profile_ == BodyProfile::StepperGuarded &&
        (guard_ == nullptr || !guard_->evaluate(now_ms))) {
      std::snprintf(reply, capacity, "ERR arm safety_interlock");
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
  } else if (stop) {
    stop_motion();
    if (state_.armed) last_control_ms_ = now_ms;
    std::snprintf(reply, capacity, "OK stop");
  } else if (!state_.armed) {
    std::snprintf(reply, capacity, "ERR %s disarmed", command);
  } else {
    last_control_ms_ = now_ms;
    if (drive) {
      state_.left = limited_speed(first);
      state_.right = limited_speed(second);
      drive_started_ms_ = now_ms;
      drive_duration_ms_ = static_cast<std::uint32_t>(duration);
      std::snprintf(reply, capacity, "OK drive left=%d right=%d ms=%d",
                    state_.left, state_.right, duration);
    } else if (lift || grip) {
      (lift ? state_.lift_target : state_.grip_target) = first;
      std::snprintf(reply, capacity, "OK %s angle=%d", command, first);
    } else {
      std::snprintf(reply, capacity, "OK keepalive");
    }
  }
}

bool LineReceiver::feed(char byte, std::uint32_t now_ms, BodyControl& control,
                        char* reply, std::size_t capacity) {
  control.tick(now_ms);
  if (byte == '\n') {
    if (overlong_) {
      std::snprintf(reply, capacity, "ERR input line_too_long");
    } else if (invalid_) {
      std::snprintf(reply, capacity, "ERR input invalid_ascii");
    } else {
      control.execute(line_, length_, now_ms, reply, capacity, local_safety_rearm_);
    }
    length_ = 0;
    saw_cr_ = false;
    invalid_ = false;
    overlong_ = false;
    return true;
  }
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
