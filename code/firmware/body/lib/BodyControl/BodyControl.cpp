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

void BodyControl::sample_side_range(std::uint8_t index, std::uint16_t mm,
                                    bool valid, std::uint32_t now_ms) {
  if (index >= 3) return;
  state_.side_present[index] = true;
  state_.side_valid[index] = valid;
  state_.side_mm[index] = mm;
  state_.side_at_ms[index] = now_ms;
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

void BodyControl::sample_optional_inputs(std::uint8_t enabled_mask, bool bumper,
                                         bool reed, bool pir) {
  enabled_mask &= 0x07U;
  state_.extra_mask = enabled_mask;
  state_.bumper_raw = (enabled_mask & 1U) && bumper;
  if (state_.bumper_raw) touch_trip(); // immediate local motor disarm
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

bool BodyControl::dock_telemetry_bad(std::uint32_t now_ms) const {
  const auto& dock = state_.accessories.dock;
  // Once the optional physical MCP23017 was found at boot, its I2C
  // acquisition, independent sequence and timestamp are compulsory for
  // moving. A missing module is NOT manufactured into a fake valid sample.
  return (dock.present || dock_monitor_required_) &&
         (!dock.present || !dock.valid || dock.sample_seq == 0U ||
          now_ms - dock.at_ms >= 500U);
}

void BodyControl::set_accessories(const AccessoryReadings& readings,
                                  std::uint32_t now_ms) {
  state_.accessories = readings;
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
  if (dock_power_lockout_) {
    force_disarm();
  } else if ((dock.present || dock_monitor_required_) &&
             (!state_.accessories.dock.valid || !dock.present ||
              dock.sample_seq == 0U)) {
    // A required but missing MCP23017 is not an optional absent sensor.
    // Preserve jaw PWM on transport loss to avoid dropping a held object.
    stop_motion();
    state_.armed = false;
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
  if (imu_motion_required_ && !imu_fresh(now_ms)) {
    // Missing, failed or stale compulsory motion sensor locally disarms.
    // This is not a tilt interlock: orientation calibration is still required.
    stop_motion();
    state_.armed = false;
    return;
  }
  if (dock_telemetry_bad(now_ms)) {
    // Optional installed dock input is a mandatory local interlock once
    // present. Never keep stepping toward contacts on stale input data.
    stop_motion();
    state_.armed = false;
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
  const bool halt = std::strcmp(command, "halt") == 0;
  const bool keepalive = std::strcmp(command, "keepalive") == 0;
  const bool ping = std::strcmp(command, "ping") == 0;
  const bool status = std::strcmp(command, "status") == 0;
  const bool aux = std::strcmp(command, "aux") == 0;
  const bool ir = std::strcmp(command, "ir") == 0;
  const bool calfloor = std::strcmp(command, "calfloor") == 0;
  const bool calfront = std::strcmp(command, "calfront") == 0;
  const bool calfresh = std::strcmp(command, "calfresh") == 0;
  const bool calcommit = std::strcmp(command, "calcommit") == 0;
  const bool calabort = std::strcmp(command, "calabort") == 0;
  const bool calibration = calfloor || calfront || calfresh || calcommit || calabort;
  if (!(drive || lift || grip || arm || rearm || disarm || stop || keepalive || ping || status || aux || ir || halt || calibration)) {
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
    const bool force_fresh = a.force.valid &&
                             now_ms - a.force.at_ms < 500U;
    const bool climate_fresh = a.climate.valid &&
                               now_ms - a.climate.at_ms < 1000U;
    const bool bmp_fresh = a.barometer.present && a.barometer.valid &&
                           now_ms - a.barometer.at_ms < 2000U;
    const bool fuel_fresh = a.gauge.fuel_valid &&
                            now_ms - a.gauge.at_ms < 500U;
    const bool monitor_fresh = a.gauge.monitor_valid &&
                               now_ms - a.gauge.at_ms < 500U;
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
        "\"red\":%lu,\"ir\":%lu,\"age_ms\":%lu,\"seq\":%lu,\"bpm\":null,\"medical\":false},"
        "\"angles\":{\"raw\":[%u,%u,%u],\"present_mask\":%u,"
        "\"valid_mask\":%u,\"magnet\":[%u,%u,%u]},"
        "\"force\":{\"adc\":[%d,%d],\"jaw_seq\":%lu,\"valid\":%s,\"calibrated\":false},"
        "\"climate\":{\"temp_centi\":%d,\"rh_centi\":%d,\"valid\":%s,\"seq\":%lu,\"age_ms\":%lu},"
        "\"bmp280\":{\"present\":%s,\"valid\":%s,\"chip_id\":%u,"
        "\"temp_centi\":%d,\"pressure_pa\":%u,\"seq\":%lu,\"age_ms\":%lu,"
        "\"physically_verified\":false},"
        "\"power\":{\"cell_mv\":%u,\"soc_centi\":%u,\"bus_mv\":%u,"
        "\"shunt_uv\":%d,\"fuel_valid\":%s,\"monitor_valid\":%s,"
        "\"current_calibrated\":false},"
        "\"proximity\":{\"raw\":%u,\"valid\":%s,\"gesture\":%u,\"gesture_events\":%lu,\"physically_qualified\":false},"
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
        static_cast<unsigned>(a.angle[0].angle),
        static_cast<unsigned>(a.angle[1].angle),
        static_cast<unsigned>(a.angle[2].angle),
        angle_present, angle_valid,
        static_cast<unsigned>(a.angle[0].magnet_status),
        static_cast<unsigned>(a.angle[1].magnet_status),
        static_cast<unsigned>(a.angle[2].magnet_status),
        static_cast<int>(a.force.adc[0]),
        static_cast<int>(a.force.adc[1]),
        static_cast<unsigned long>(a.force.jaw_sample_seq),
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
        monitor_fresh ? "true" : "false",
        static_cast<unsigned>(a.proximity.raw),
        proximity_fresh ? "true" : "false",
        static_cast<unsigned>(a.proximity.gesture_direction),
        static_cast<unsigned long>(a.proximity.gesture_events),
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
    const int written = std::snprintf(
        reply, capacity,
        "{\"armed\":%s,\"motor\":{\"m0\":%d,\"m1\":%d},"
        "\"servo\":{\"lift\":%d,\"grip\":%d,\"lift_target\":%d,"
        "\"grip_target\":%d,\"attached\":%s,\"position_source\":\"commanded\"},"
        "\"watchdog_ms\":%lu,\"drive_ms\":%lu,\"protocol\":2,"
        "\"backend\":\"%s\",\"touch\":{\"active\":%s,\"count\":%lu,\"tap_count\":%lu,\"double_count\":%lu,\"hold_count\":%lu},\"extras\":{\"mask\":%u,\"bumper\":%s,\"bumps\":%lu,\"reed\":%s,\"reed_count\":%lu,\"pir\":%s,\"pir_count\":%lu,\"cap\":%u,\"cap_ok\":%s,\"cap_events\":%lu},\"side_ranges\":{\"mm\":[%u,%u,%u],\"age_ms\":[%lu,%lu,%lu],\"present_mask\":%u,\"valid_mask\":%u,\"motion_certified\":false},\"imu\":{\"family\":%u,\"gyro_id\":%u,\"aux_id\":%u,\"valid\":%s,\"acc\":[%d,%d,%d],\"gyro\":[%d,%d,%d],\"age_ms\":%lu,\"sample_ms\":%lu,\"boot_id\":%lu},\"safety\":{\"required\":%s,\"ready\":%s,"
        "\"fault\":\"%s\",\"sensor\":%u},\"ranges\":{\"mm\":[%u,%u,%u,%u,%u],"
        "\"age_ms\":[%lu,%lu,%lu,%lu,%lu],\"present_mask\":%u,\"valid_mask\":%u}}",
        state_.armed ? "true" : "false", state_.left, state_.right,
        state_.lift, state_.grip, state_.lift_target, state_.grip_target,
        state_.servos_attached ? "true" : "false",
        static_cast<unsigned long>(watchdog_remaining(now_ms)),
        static_cast<unsigned long>(drive_remaining(now_ms)),
        profile_ == BodyProfile::StepperGuarded ? "stepper_28byj48" : "dc_pwm",
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
        side_present_mask, side_valid_mask,
        static_cast<unsigned>(state_.imu_family),
        static_cast<unsigned>(state_.imu_gyro_id),
        static_cast<unsigned>(state_.imu_aux_id),
        imu_valid ? "true" : "false",
        imu_.accel[0], imu_.accel[1], imu_.accel[2],
        imu_.gyro[0], imu_.gyro[1], imu_.gyro[2],
        static_cast<unsigned long>(imu_.valid ? imu_age : 0U),
        static_cast<unsigned long>(imu_.valid ? imu_.at_ms : 0U),
        static_cast<unsigned long>(boot_epoch_),
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
    if (profile_ != BodyProfile::StepperGuarded || guard_ == nullptr ||
        !guard_->try_rearm(now_ms)) {
      std::snprintf(reply, capacity, "ERR rearm safety_interlock");
      return;
    }
    std::snprintf(reply, capacity, "OK rearm");
  } else if (arm) {
    if (dock_power_lockout_) {
      std::snprintf(reply, capacity, "ERR arm dock_power_connected");
      return;
    }
    if (dock_telemetry_bad(now_ms)) {
      std::snprintf(reply, capacity, "ERR arm dock_gpio_missing_or_stale");
      return;
    }
    if (state_.extra_mask & 1U && (state_.bumper_raw || state_.bumper_active)) {
      std::snprintf(reply, capacity, "ERR arm bumper_active");
      return;
    }
    if (state_.touch_active || state_.touch_raw_active) {
      std::snprintf(reply, capacity, "ERR arm touch_active");
      return;
    }
    if (profile_ == BodyProfile::StepperGuarded &&
        (guard_ == nullptr || !guard_->evaluate(now_ms))) {
      std::snprintf(reply, capacity, "ERR arm safety_interlock");
      return;
    }
    if (imu_motion_required_ && !imu_fresh(now_ms)) {
      std::snprintf(reply, capacity, "ERR arm imu_missing_or_stale");
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
