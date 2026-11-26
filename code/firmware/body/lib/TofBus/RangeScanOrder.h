#pragma once

#include <cstdint>
#include "../../include/TofWireLimits.h"

namespace desk_robot {

// Preserve first-priority floor/forward sampling cadence while adding optional
// left/right/rear ToF channels. No I2C, GPIO or motion authority in this class.
class RangeScanOrder {
 public:
  explicit RangeScanOrder(bool full_eight) : full_eight_(full_eight) {}

  std::uint8_t next(std::uint32_t now_ms = 0,
                    std::uint32_t freshness_ms = kTofCriticalExpiryMs) {
    if (critical_index_ == 0) sweep_started_ms_ = now_ms;
    if (critical_index_ < 5) return critical_index_++;
    critical_index_ = 0;
    // Reserve at least half the freshness window for the next critical sweep.
    // This is an admission heuristic, not a bound on future I2C latency.
    if (!full_eight_ || now_ms - sweep_started_ms_ >= freshness_ms / 2U) {
      sweep_started_ms_ = now_ms;
      return critical_index_++;
    }
    const std::uint8_t channel = static_cast<std::uint8_t>(5 + extra_index_);
    extra_index_ = static_cast<std::uint8_t>((extra_index_ + 1) % 3);
    return channel;
  }

  // A shared bus failure revokes all critical readings. Revisit every
  // critical lane before any optional read, without resetting its rotation.
  void restart_critical() { critical_index_ = 0; }

  void transport_fault() {
    restart_critical();
    degraded_ = true;
    healthy_mask_ = healthy_sweeps_ = 0;
  }

  // Two complete critical transport sweeps, not two ACKs or two polls of
  // one lane. Optional lanes cannot qualify recovery. Optical validity and
  // explicit motion rearm remain independent in CliffGuard.
  void transport_succeeded(std::uint8_t channel) {
    if (!degraded_ || channel >= 5) return;
    healthy_mask_ |= static_cast<std::uint8_t>(1U << channel);
    if (healthy_mask_ != 0x1FU) return;
    healthy_mask_ = 0;
    if (++healthy_sweeps_ == 2U) degraded_ = false;
  }

  bool degraded() const { return degraded_; }

  void reset() {
    restart_critical();
    extra_index_ = 0;
    degraded_ = false;
    healthy_mask_ = healthy_sweeps_ = 0;
  }

 private:
  const bool full_eight_;
  std::uint8_t critical_index_ = 0;
  std::uint8_t extra_index_ = 0;
  std::uint32_t sweep_started_ms_ = 0;
  bool degraded_ = false;
  std::uint8_t healthy_mask_ = 0;
  std::uint8_t healthy_sweeps_ = 0;
};

}  // namespace desk_robot
