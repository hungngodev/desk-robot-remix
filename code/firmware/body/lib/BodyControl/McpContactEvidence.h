#pragma once

#include <cstdint>
#include "AccessoryReadings.h"

namespace desk_robot {

// Optional reed/PIR edges must be confirmed by distinct MCP23017 GPIOB
// conversions spanning at least 50 ms, not by repeated cached reads or
// tightly spaced acquisitions during contact chatter.
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
    const auto expected_seq = last_seq_ == 0xffffffffU ? 1U : last_seq_ + 1U;
    if (time_step > 250U || sample.sample_seq != expected_seq) {
      // A gap breaks continuity. Mark this poll unavailable so BodyControl
      // rebaselines the recovered level instead of counting a false edge.
      baseline(sample);
      return false;
    }
    last_seq_ = sample.sample_seq;
    last_at_ms_ = sample.at_ms;
    last_reed_ = sample.reed_closed;
    last_pir_ = sample.pir_active;
    confirm(sample.reed_closed, reed_, reed_candidate_, reed_streak_,
            reed_since_ms_, sample.at_ms);
    confirm(sample.pir_active, pir_, pir_candidate_, pir_streak_,
            pir_since_ms_, sample.at_ms);
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
    reed_since_ms_ = pir_since_ms_ = 0;
  }

 private:
  static void confirm(bool level, bool& stable, bool& candidate,
                      std::uint8_t& streak, std::uint32_t& since_ms,
                      std::uint32_t at_ms) {
    if (level != candidate) {
      candidate = level;
      streak = 1;
      since_ms = at_ms;
    } else if (streak < 3) {
      ++streak;
    }
    // Use source time, not receipt time; unsigned subtraction handles wrap.
    // Match the existing three-sample, 25 ms spacing touch filter window.
    if (streak == 3 && at_ms - since_ms >= 50U) stable = candidate;
  }

  void baseline(const McpOptionalRaw& sample) {
    seen_ = true;
    last_seq_ = sample.sample_seq;
    last_at_ms_ = sample.at_ms;
    last_reed_ = reed_ = reed_candidate_ = sample.reed_closed;
    last_pir_ = pir_ = pir_candidate_ = sample.pir_active;
    reed_streak_ = pir_streak_ = 1;
    reed_since_ms_ = pir_since_ms_ = sample.at_ms;
  }

  bool seen_ = false;
  bool reed_ = false, pir_ = false;
  bool reed_candidate_ = false, pir_candidate_ = false;
  bool last_reed_ = false, last_pir_ = false;
  std::uint8_t reed_streak_ = 0, pir_streak_ = 0;
  std::uint32_t last_seq_ = 0, last_at_ms_ = 0;
  std::uint32_t reed_since_ms_ = 0, pir_since_ms_ = 0;
};

} // namespace desk_robot
