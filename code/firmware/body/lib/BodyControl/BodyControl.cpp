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

  char* tokens[16]{};
  std::size_t count = 0;
  char* position = buffer;
  while (*position != '\0') {
    while (*position == ' ') ++position;
    if (*position == '\0') break;
    if (count == 16) {
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
  const bool ranges = std::strcmp(command, "ranges") == 0;
  const bool calibrate = std::strcmp(command, "calibrate") == 0;
  const bool calclear = std::strcmp(command, "calclear") == 0;
  if (!(drive || lift || grip || arm || rearm || disarm || stop || keepalive || ping || status || ranges || calibrate || calclear)) {
    // Do not interpolate attacker-controlled input into reply lines.
    std::snprintf(reply, capacity, "ERR input unknown_command");
    return;
  }
  if ((drive && count != 3 && count != 4) ||
      ((lift || grip) && count != 2) ||
      (calibrate && count != 12) ||
      (!(drive || lift || grip || calibrate) && count != 1)) {
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

  if (calibrate) {
    if (!local_safety_rearm) {
      std::snprintf(reply, capacity, "ERR calibrate local_only");
      return;
    }
    if (state_.armed || state_.servos_attached) {
      std::snprintf(reply, capacity, "ERR calibrate disarm_first");
      return;
    }
    if (profile_ != BodyProfile::StepperGuarded || guard_ == nullptr) {
      std::snprintf(reply, capacity, "ERR calibrate unavailable");
      return;
    }
    // Eleven values are measured on this real robot by a human operator,
    // not inferred from photos, test fixtures, or Mac suggestions.
    int values[11]{};
    for (int i = 0; i < 11; ++i) {
      if (!parse_integer(tokens[i + 1], values[i]) ||
          values[i] <= 0 || values[i] > 65000) {
        std::snprintf(reply, capacity, "ERR calibrate integer_range");
        return;
      }
    }
    CliffConfig next{};
    next.calibrated = true;
    for (int i = 0; i < 4; ++i) {
      next.floor[i].min_mm = static_cast<std::uint16_t>(values[i * 2]);
      next.floor[i].max_mm = static_cast<std::uint16_t>(values[i * 2 + 1]);
    }
    next.front_obstacle_mm = static_cast<std::uint16_t>(values[8]);
    next.front_max_mm = static_cast<std::uint16_t>(values[9]);
    next.freshness_ms = static_cast<std::uint32_t>(values[10]);
    if (next.freshness_ms > 250 || !guard_->configure(next)) {
      std::snprintf(reply, capacity, "ERR calibrate invalid_intervals");
      return;
    }
    // Config is now incomplete until fresh 5-channel samples and local rearm.
    std::snprintf(reply, capacity, "OK calibrate");
  } else if (calclear) {
    if (!local_safety_rearm) {
      std::snprintf(reply, capacity, "ERR calclear local_only");
      return;
    }
    if (state_.armed || state_.servos_attached || guard_ == nullptr) {
      std::snprintf(reply, capacity, "ERR calclear disarm_first");
      return;
    }
    guard_->configure(CliffConfig{});
    std::snprintf(reply, capacity, "OK calclear");
  } else if (ranges) {
    if (guard_ == nullptr) {
      std::snprintf(reply, capacity, "ERR ranges no_sensors");
      return;
    }
    unsigned valid_mask = 0;
    for (std::uint8_t i = 0; i < kCliffSensorCount; ++i) {
      if (guard_->sample_valid(i)) valid_mask |= 1U << i;
    }
    std::snprintf(reply, capacity,
        "{\"ranges_mm\":[%u,%u,%u,%u,%u],"
        "\"valid_mask\":%u,\"ages_ms\":[%lu,%lu,%lu,%lu,%lu]}",
        static_cast<unsigned>(guard_->distance_mm(0)),
        static_cast<unsigned>(guard_->distance_mm(1)),
        static_cast<unsigned>(guard_->distance_mm(2)),
        static_cast<unsigned>(guard_->distance_mm(3)),
        static_cast<unsigned>(guard_->distance_mm(4)), valid_mask,
        static_cast<unsigned long>(guard_->age_ms(0, now_ms)),
        static_cast<unsigned long>(guard_->age_ms(1, now_ms)),
        static_cast<unsigned long>(guard_->age_ms(2, now_ms)),
        static_cast<unsigned long>(guard_->age_ms(3, now_ms)),
        static_cast<unsigned long>(guard_->age_ms(4, now_ms)));
  } else if (ping) {
    std::snprintf(reply, capacity, "OK ping");
  } else if (status) {
    std::snprintf(
        reply, capacity,
        "{\"armed\":%s,\"motor\":{\"m0\":%d,\"m1\":%d},"
        "\"servo\":{\"lift\":%d,\"grip\":%d,\"lift_target\":%d,"
        "\"grip_target\":%d,\"attached\":%s,\"position_source\":\"commanded\"},"
        "\"watchdog_ms\":%lu,\"drive_ms\":%lu,\"protocol\":2,"
        "\"backend\":\"%s\",\"safety\":{\"required\":%s,\"ready\":%s,"
        "\"fault\":\"%s\",\"sensor\":%u}}",
        state_.armed ? "true" : "false", state_.left, state_.right,
        state_.lift, state_.grip, state_.lift_target, state_.grip_target,
        state_.servos_attached ? "true" : "false",
        static_cast<unsigned long>(watchdog_remaining(now_ms)),
        static_cast<unsigned long>(drive_remaining(now_ms)),
        profile_ == BodyProfile::StepperGuarded ? "stepper_28byj48" : "dc_pwm",
        profile_ == BodyProfile::StepperGuarded ? "true" : "false",
        profile_ == BodyProfile::StepperGuarded && guard_ != nullptr &&
            guard_->evaluate(now_ms) ? "true" : "false",
        profile_ != BodyProfile::StepperGuarded ? "not_required" :
            guard_ == nullptr ? "missing_guard" : CliffGuard::fault_name(guard_->fault()),
        static_cast<unsigned>(guard_ == nullptr ? kNoFaultSensor : guard_->fault_sensor()));
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
