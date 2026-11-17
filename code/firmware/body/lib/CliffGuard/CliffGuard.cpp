#include "CliffGuard.h"

namespace desk_robot {

bool CliffGuard::valid_config(const CliffConfig& config) {
  // Enforce the SAME 30..200 ms admissible range as the local USB
  // "calfresh" command. This guard also validates calibration restored from
  // NVS, so its former 1000 ms ceiling could silently accept a stored
  // policy that the operator command rightly refuses. Actual certified
  // freshness may need to be STRICTER given sensor cadence and wheel speed.
  if (!config.calibrated || config.freshness_ms < 30 ||
      config.freshness_ms > 200 || config.front_obstacle_mm < 30 ||
      config.front_max_mm > 1300 ||
      config.front_obstacle_mm >= config.front_max_mm) return false;
  for (const auto& floor : config.floor) {
    // Match the active VL53L0X TofBus 30..1300mm valid range; never
    // accept a staged calibration no actual sensor sample can satisfy.
    if (floor.min_mm < 30 || floor.min_mm > floor.max_mm ||
        floor.max_mm > 1300) return false;
  }
  return true;
}

bool CliffGuard::configure(const CliffConfig& config) {
  config_ = config;
  configured_ = valid_config(config);
  for (auto& sample : samples_) sample = Sample{};
  // Replacing calibration cannot retain a clear/armed state or old readings.
  fault_ = configured_ ? CliffFault::MissingSample : CliffFault::Unconfigured;
  fault_sensor_ = configured_ ? 0 : kNoFaultSensor;
  return configured_;
}

void CliffGuard::latch(CliffFault reason, std::uint8_t sensor) {
  if (fault_ == CliffFault::None && reason != CliffFault::None) {
    fault_ = reason;
    fault_sensor_ = sensor;
  }
}

CliffFault CliffGuard::sample_fault(std::uint8_t channel) const {
  const auto& sample = samples_[channel];
  if (!sample.present) return CliffFault::MissingSample;
  if (!sample.valid || sample.mm == 0) return CliffFault::InvalidSample;
  if (channel < kFloorSensorCount) {
    const auto& floor = config_.floor[channel];
    if (sample.mm < floor.min_mm || sample.mm > floor.max_mm)
      return CliffFault::FloorOutOfRange;
  } else {
    if (sample.mm <= config_.front_obstacle_mm) return CliffFault::FrontObstacle;
    if (sample.mm > config_.front_max_mm) return CliffFault::FrontOutOfRange;
  }
  return CliffFault::None;
}

bool CliffGuard::current_health(std::uint32_t now_ms, CliffFault& reason,
                                std::uint8_t& sensor) const {
  reason = CliffFault::Unconfigured;
  sensor = kNoFaultSensor;
  if (!configured_) return false;
  for (std::uint8_t i = 0; i < kCliffSensorCount; ++i) {
    sensor = i;
    reason = sample_fault(i);
    if (reason != CliffFault::None) return false;
    // Unsigned elapsed arithmetic works across millis rollover; the adapter
    // must supply monotonic samples/evaluations without a full wrap hiatus.
    if (now_ms - samples_[i].at_ms >= config_.freshness_ms) {
      reason = CliffFault::StaleSample;
      return false;
    }
  }
  reason = CliffFault::None;
  sensor = kNoFaultSensor;
  return true;
}

void CliffGuard::sample(std::uint8_t channel, std::uint16_t distance_mm,
                        bool valid, std::uint32_t now_ms) {
  // A newly arriving sample must not erase evidence that earlier data already
  // expired during a stalled loop. Check pre-update health before replacement.
  CliffFault previous_reason;
  std::uint8_t previous_sensor;
  if (fault_ == CliffFault::None &&
      !current_health(now_ms, previous_reason, previous_sensor))
    latch(previous_reason, previous_sensor);
  if (channel >= kCliffSensorCount) {
    latch(CliffFault::InvalidChannel);
    return;
  }
  auto& sample = samples_[channel];
  sample.present = true;
  sample.valid = valid;
  sample.mm = distance_mm;
  sample.at_ms = now_ms;
  if (configured_) latch(sample_fault(channel), channel);
}

void CliffGuard::bus_fault() {
  latch(CliffFault::BusFailure);
  // Even a transient bus recovery requires all-new observations before rearm.
  for (auto& sample : samples_) sample = Sample{};
}

RangeDiagnostic CliffGuard::diagnostic(std::uint8_t channel,
                                       std::uint32_t now_ms) const {
  if (channel >= kCliffSensorCount) return {};
  const auto& sample = samples_[channel];
  RangeDiagnostic result;
  result.present = sample.present;
  result.distance_mm = sample.mm;
  result.age_ms = sample.present ? now_ms - sample.at_ms : 0U;
  // Status JSON must not advertise an expired measurement as live sensor
  // evidence. Raw mm and age remain available to diagnose a stale lane.
  // Motor permission still comes ONLY from the independent latched guard.
  result.valid = sample.present && sample.valid && configured_ &&
                 result.age_ms < config_.freshness_ms;
  return result;
}

bool CliffGuard::evaluate(std::uint32_t now_ms) {
  CliffFault reason;
  std::uint8_t sensor;
  if (!current_health(now_ms, reason, sensor)) latch(reason, sensor);
  return fault_ == CliffFault::None;
}

bool CliffGuard::try_rearm(std::uint32_t now_ms) {
  CliffFault reason;
  std::uint8_t sensor;
  if (!current_health(now_ms, reason, sensor)) {
    latch(reason, sensor);
    return false;
  }
  fault_ = CliffFault::None;
  fault_sensor_ = kNoFaultSensor;
  return true;
}

const char* CliffGuard::fault_name(CliffFault fault) {
  switch (fault) {
    case CliffFault::None: return "none";
    case CliffFault::Unconfigured: return "unconfigured";
    case CliffFault::MissingSample: return "missing_sample";
    case CliffFault::InvalidSample: return "invalid_sample";
    case CliffFault::StaleSample: return "stale_sample";
    case CliffFault::FloorOutOfRange: return "floor_out_of_range";
    case CliffFault::FrontObstacle: return "front_obstacle";
    case CliffFault::FrontOutOfRange: return "front_out_of_range";
    case CliffFault::BusFailure: return "bus_failure";
    case CliffFault::InvalidChannel: return "invalid_channel";
  }
  return "unknown";
}

}  // namespace desk_robot
