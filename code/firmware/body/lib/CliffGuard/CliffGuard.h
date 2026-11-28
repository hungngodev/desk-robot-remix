#pragma once

#include <cstdint>
#include <cstring>

namespace desk_robot {

constexpr std::uint8_t kFloorSensorCount = 4;
constexpr std::uint8_t kCliffSensorCount = 5;
constexpr std::uint8_t kNoFaultSensor = 255;

struct FloorInterval {
  std::uint16_t min_mm = 0;
  std::uint16_t max_mm = 0;
};

// Read-only measurement diagnostics, never a motor permission or calibration.
// Missing readings have present=false. Invalid or stale readings retain raw
// distance and age for diagnosis; valid means fresh under the active local
// policy, never physical motor permission.
struct RangeDiagnostic {
  bool present = false;
  bool valid = false;
  std::uint16_t distance_mm = 0;
  std::uint32_t age_ms = 0;
};

// Values are per-robot measured qualification inputs, not universal thresholds.
// No calibrated configuration or sample is supplied by default.
struct CliffConfig {
  bool calibrated = false;
  FloorInterval floor[kFloorSensorCount]{};
  std::uint16_t front_obstacle_mm = 0;
  std::uint16_t front_max_mm = 0;
  std::uint32_t freshness_ms = 0;
};

// A native v1 NVS blob contains a bool. Inspect its object representation
// before any typed read (including checksum calculation): malformed bool bytes
// have undefined behavior. Only an explicitly calibrated record may load.
inline bool valid_stored_calibrated_flag(const CliffConfig& config) noexcept {
  const bool expected = true;
  return std::memcmp(&config.calibrated, &expected, sizeof(expected)) == 0;
}

enum class CliffFault : std::uint8_t {
  None,
  Unconfigured,
  MissingSample,
  InvalidSample,
  StaleSample,
  FloorOutOfRange,
  FrontObstacle,
  FrontOutOfRange,
  BusFailure,
  InvalidChannel
};

// Pure policy only: it neither reads I2C nor arms/moves hardware. The caller must
// evaluate before every output/control path and stop on false. A healthy update
// never clears a fault. Only an explicit, authorized try_rearm may clear it.
class CliffGuard {
 public:
  // Shared bounds policy for stored records and live configuration.
  static bool valid_config(const CliffConfig& config) noexcept;
  bool configure(const CliffConfig& config) noexcept;
  void sample(std::uint8_t channel, std::uint16_t distance_mm, bool valid,
              std::uint32_t now_ms) noexcept;
  void bus_fault() noexcept;
  bool evaluate(std::uint32_t now_ms) noexcept;
  bool try_rearm(std::uint32_t now_ms) noexcept;
  bool configured() const noexcept { return configured_; }
  const CliffConfig& configuration() const noexcept { return config_; }
  CliffFault fault() const noexcept { return fault_; }
  std::uint8_t fault_sensor() const noexcept { return fault_sensor_; }
  RangeDiagnostic diagnostic(std::uint8_t channel, std::uint32_t now_ms) const noexcept;
  static const char* fault_name(CliffFault fault) noexcept;

 private:
  struct Sample {
    bool present = false;
    bool valid = false;
    // Once observed stale, this conversion cannot become fresh on millis wrap.
    bool expired = false;
    std::uint16_t mm = 0;
    std::uint32_t at_ms = 0;
  };
  CliffConfig config_{};
  Sample samples_[kCliffSensorCount]{};
  bool configured_ = false;
  // Before the first successful USB rearm, a complete unsafe boot sweep
  // may replace the placeholder MissingSample with its true fault. Runtime
  // faults retain the original immutable latch semantics.
  bool initial_sweep_pending_rearm_ = true;
  CliffFault fault_ = CliffFault::Unconfigured;
  std::uint8_t fault_sensor_ = kNoFaultSensor;

  CliffFault sample_fault(std::uint8_t channel) const noexcept;
  bool current_health(std::uint32_t now_ms, CliffFault& reason,
                      std::uint8_t& sensor) noexcept;
  void latch(CliffFault reason, std::uint8_t sensor = kNoFaultSensor) noexcept;
  void classify_complete_initial_sweep(CliffFault reason,
                                       std::uint8_t sensor) noexcept;
};

}  // namespace desk_robot
