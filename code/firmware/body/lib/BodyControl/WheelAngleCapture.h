#pragma once

#include <cstdint>
#include <limits>

#include "AccessoryReadings.h"

namespace desk_robot {

// AS5600 angle acquisition, not wheel displacement or a motor command. This
// tracker cannot prove gear ratio, wheel direction, magnet fit, or traction.
// Only an installed-wheel speed trial can supply an alias-safe rate bound.
class WheelAngleCapture {
 public:
  enum class Result { Unqualified, Invalid, Baseline, Duplicate, Delta };

  bool configure(std::uint32_t max_counts_per_second,
                 std::uint32_t max_gap_ms, std::uint32_t max_age_ms) {
    // Even the maximum permitted sampling gap must span LESS than half a
    // revolution. Otherwise a full turn can masquerade as a short delta.
    if (configured_ || max_counts_per_second == 0 || max_gap_ms == 0 ||
        max_gap_ms > 500 || max_age_ms == 0 || max_age_ms > max_gap_ms ||
        static_cast<std::uint64_t>(max_counts_per_second) * max_gap_ms >=
            2048000ULL) return false;
    max_rate_ = max_counts_per_second;
    max_gap_ = max_gap_ms;
    max_age_ = max_age_ms;
    configured_ = true;
    return true;
  }

  Result observe(const AngleRaw& reading, std::uint32_t now_ms) {
    delta_ = 0;
    if (!configured_) return Result::Unqualified;
    // millis() == 0 is a legitimate completed acquisition at uint32 wrap;
    // sample_seq != 0 distinguishes it from an uninitialized reading.
    if (!reading.present || !reading.valid || reading.magnet_status != 0x20 ||
        reading.angle > 4095 || reading.sample_seq == 0 ||
        now_ms - reading.at_ms > max_age_) {
      // A fresh rejected conversion still fences its acquisition identity.
      // Failed bus reads keep the previous successful sequence; stale,
      // future or replayed records must not advance that source fence.
      const std::uint32_t seq_delta = reading.sample_seq - last_seq_;
      const std::uint32_t time_delta = reading.at_ms - last_ms_;
      if (reading.sample_seq != 0 && now_ms - reading.at_ms <= max_age_ &&
          (!seen_ || (seq_delta != 0 && seq_delta < 0x80000000U &&
                      time_delta != 0 && time_delta < 0x80000000U))) {
        seen_ = true;
        last_seq_ = reading.sample_seq;
        last_ms_ = reading.at_ms;
        last_angle_ = reading.angle;
      }
      lose_continuity();
      return Result::Invalid;
    }
    if (seen_) {
      if (reading.sample_seq == last_seq_) {
        if (continuous_ && reading.at_ms == last_ms_ &&
            reading.angle == last_angle_) return Result::Duplicate;
        lose_continuity();
        return Result::Invalid;
      }
      const std::uint32_t seq_delta = reading.sample_seq - last_seq_;
      const std::uint32_t time_delta = reading.at_ms - last_ms_;
      if (seq_delta == 0 || seq_delta >= 0x80000000U ||
          time_delta == 0 || time_delta >= 0x80000000U) {
        lose_continuity();
        return Result::Invalid;
      }
      if (continuous_ && time_delta > max_gap_) {
        // A valid new acquisition starts a NEW segment, not a wheel jump.
        last_seq_ = reading.sample_seq;
        last_ms_ = reading.at_ms;
        last_angle_ = reading.angle;
        lose_continuity();
        return Result::Invalid;
      }
    }
    if (!continuous_) {
      seen_ = true;
      continuous_ = true;
      last_seq_ = reading.sample_seq;
      last_ms_ = reading.at_ms;
      last_angle_ = reading.angle;
      ticks_ = 0;
      // Acquisition time is stronger provenance than request time.
      ++segment_;
      if (segment_ == 0) ++segment_;
      return Result::Baseline;
    }
    const std::uint32_t elapsed = reading.at_ms - last_ms_;
    int delta = static_cast<int>(reading.angle) - static_cast<int>(last_angle_);
    if (delta > 2048) delta -= 4096;
    if (delta < -2048) delta += 4096;
    const std::uint32_t magnitude =
        static_cast<std::uint32_t>(delta < 0 ? -delta : delta);
    // Exactly 180 degrees is direction-ambiguous. Reject impossible jumps
    // rather than guessing one or several wraps between sparse I2C polls.
    if (magnitude == 2048 || elapsed > max_gap_ ||
        static_cast<std::uint64_t>(magnitude) * 1000ULL >
            static_cast<std::uint64_t>(max_rate_) * elapsed ||
        (delta > 0 && ticks_ > std::numeric_limits<std::int64_t>::max() - delta) ||
        (delta < 0 && ticks_ < std::numeric_limits<std::int64_t>::min() - delta)) {
      last_seq_ = reading.sample_seq;
      last_ms_ = reading.at_ms;
      last_angle_ = reading.angle;
      lose_continuity();
      return Result::Invalid;
    }
    last_seq_ = reading.sample_seq;
    last_ms_ = reading.at_ms;
    last_angle_ = reading.angle;
    ticks_ += delta;
    delta_ = delta;
    return Result::Delta;
  }

  void reset_for_boot() { *this = WheelAngleCapture(); }
  // Lost paired acquisition invalidates angular continuity but preserves
  // rate qualification and the source replay fence until a new baseline.
  void discard_continuity() { lose_continuity(); }
  bool continuous() const { return continuous_; }
  std::int64_t angular_counts() const { return continuous_ ? ticks_ : 0; }
  int last_delta() const { return continuous_ ? delta_ : 0; }
  std::uint32_t segment() const { return segment_; }

 private:
  void lose_continuity() {
    continuous_ = false;
    delta_ = 0;
    ticks_ = 0;
  }
  bool configured_ = false;
  bool seen_ = false;
  bool continuous_ = false;
  std::uint32_t max_rate_ = 0, max_gap_ = 0, max_age_ = 0;
  std::uint32_t last_seq_ = 0, last_ms_ = 0, segment_ = 0;
  std::uint16_t last_angle_ = 0;
  std::int64_t ticks_ = 0;
  int delta_ = 0;
};

}  // namespace desk_robot
