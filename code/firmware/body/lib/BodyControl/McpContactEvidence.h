#pragma once

#include <cstdint>
#include "AccessoryReadings.h"

namespace desk_robot {

// Optional reed/PIR edges must be confirmed by distinct MCP23017 GPIOB
// conversions, not by repeated 25 ms reads of the same cached conversion.
// This is cosmetic evidence only; the normally-closed bumper has its own
// immediate local motor interlock and is intentionally not sampled here.
class McpContactEvidence {
 public:
  bool observe(const McpOptionalRaw& sample, std::uint32_t now_ms) {
    if (!sample.present || !sample.valid || sample.sample_seq == 0U ||
        now_ms - sample.at_ms > 250U) {
      reset();
      return false;
    }
    if (!seen_) {
      baseline(sample);
      return true;
    }
    if (sample.sample_seq == last_seq_) {
      // A cached conversion cannot change its source time or raw levels.
      if (sample.at_ms != last_at_ms_ ||
          sample.reed_closed != last_reed_ ||
          sample.pir_active != last_pir_) {
        reset();
        return false;
      }
      return true;
    }
    const auto seq_step = static_cast<std::uint32_t>(sample.sample_seq - last_seq_);
    const auto time_step = static_cast<std::uint32_t>(sample.at_ms - last_at_ms_);
    if (seq_step >= 0x80000000U || time_step == 0U ||
        time_step >= 0x80000000U) {
      reset();
      return false;
    }
    if (time_step > 250U) {
      // No continuously observed event survives a missing acquisition gap.
      baseline(sample);
      return true;
    }
    last_seq_ = sample.sample_seq;
    last_at_ms_ = sample.at_ms;
    last_reed_ = sample.reed_closed;
    last_pir_ = sample.pir_active;
    confirm(sample.reed_closed, reed_, reed_candidate_, reed_streak_);
    confirm(sample.pir_active, pir_, pir_candidate_, pir_streak_);
    return true;
  }

  bool reed_closed() const { return reed_; }
  bool pir_active() const { return pir_; }

  void reset() {
    seen_ = false;
    last_seq_ = last_at_ms_ = 0;
    reed_ = pir_ = reed_candidate_ = pir_candidate_ = false;
    last_reed_ = last_pir_ = false;
    reed_streak_ = pir_streak_ = 0;
  }

 private:
  static void confirm(bool level, bool& stable, bool& candidate,
                      std::uint8_t& streak) {
    if (level != candidate) {
      candidate = level;
      streak = 1;
    } else if (streak < 3) {
      ++streak;
    }
    if (streak == 3) stable = candidate;
  }

  void baseline(const McpOptionalRaw& sample) {
    seen_ = true;
    last_seq_ = sample.sample_seq;
    last_at_ms_ = sample.at_ms;
    last_reed_ = reed_ = reed_candidate_ = sample.reed_closed;
    last_pir_ = pir_ = pir_candidate_ = sample.pir_active;
    reed_streak_ = pir_streak_ = 1;
  }

  bool seen_ = false;
  bool reed_ = false, pir_ = false;
  bool reed_candidate_ = false, pir_candidate_ = false;
  bool last_reed_ = false, last_pir_ = false;
  std::uint8_t reed_streak_ = 0, pir_streak_ = 0;
  std::uint32_t last_seq_ = 0, last_at_ms_ = 0;
};

} // namespace desk_robot
