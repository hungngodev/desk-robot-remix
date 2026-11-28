#pragma once

#include <cstdint>
#include "WheelAngleCapture.h"

namespace desk_robot {

// Synchronized raw AS5600 shaft increments only. A paired conversion is not
// calibrated wheel travel, wheel slip evidence, or a navigation permit.
class WheelPairCapture {
 public:
  enum class Result { Waiting, Paired, Invalid };
  struct Receipt {
    bool valid = false;
    int left_delta = 0, right_delta = 0;
    std::uint32_t left_ms = 0, right_ms = 0;
    std::uint32_t left_seq = 0, right_seq = 0;
    std::uint32_t skew_ms = 0, segment = 0, pair_seq = 0;
  };
  bool configure(std::uint32_t measured_max_skew_ms) {
    // A real pair must be observed with a measured maximum latency skew.
    // A loose 500ms control watchdog window is NOT an encoder timebase.
    if (configured_ || measured_max_skew_ms == 0 ||
        measured_max_skew_ms > 100U) return false;
    max_skew_ms_ = measured_max_skew_ms;
    configured_ = true;
    return true;
  }
  void reset_for_boot() { *this = WheelPairCapture(); }
  // Retain boot-time measured skew limits, but revoke an old successful
  // wheel pair immediately on pickup, MPU invalidation or CPU watchdog.
  void discard_continuity() { invalidate(); }
  const Receipt& receipt() const { return receipt_; }
  // A historical pair can remain readable while a new one is incomplete.
  // Do not use it to establish a new origin across an unmatched interval.
  bool ready_for_origin() const {
    return synchronized_ && receipt_.valid && !pending_[0] && !pending_[1];
  }

  Result observe(WheelAngleCapture::Result left_result,
                 WheelAngleCapture::Result right_result,
                 const AngleRaw& left, const AngleRaw& right,
                 int left_delta, int right_delta, std::uint32_t now_ms) {
    if (!configured_) return Result::Invalid;
    if (left_result == WheelAngleCapture::Result::Invalid ||
        left_result == WheelAngleCapture::Result::Unqualified ||
        right_result == WheelAngleCapture::Result::Invalid ||
        right_result == WheelAngleCapture::Result::Unqualified)
      return invalidate();

    const bool left_base = left_result == WheelAngleCapture::Result::Baseline;
    const bool right_base = right_result == WheelAngleCapture::Result::Baseline;
    const bool left_new = left_result == WheelAngleCapture::Result::Delta;
    const bool right_new = right_result == WheelAngleCapture::Result::Delta;
    // Never publish an ambiguous half-turn or an out-of-range shaft delta,
    // even if a caller mistakenly labels it as a completed conversion.
    if ((left_new && (left_delta < -2047 || left_delta > 2047)) ||
        (right_new && (right_delta < -2047 || right_delta > 2047)))
      return invalidate();
    if ((left_base || right_base) && (synchronized_ || left_new || right_new))
      return invalidate();
    if (left_base) { baseline_[0] = true; baseline_ms_[0] = left.at_ms; }
    if (right_base) { baseline_[1] = true; baseline_ms_[1] = right.at_ms; }
    if (!synchronized_) {
      if (left_new || right_new) return invalidate();
      // Baselines establish the start of each delta interval. Apply the
      // same acquisition-age bound used for pending deltas, including wrap.
      for (int i = 0; i < 2; ++i)
        if (baseline_[i] && now_ms - baseline_ms_[i] > max_skew_ms_)
          return invalidate();
      if (!baseline_[0] || !baseline_[1]) return Result::Waiting;
      if (skew(baseline_ms_[0], baseline_ms_[1]) > max_skew_ms_)
        return invalidate();
      synchronized_ = true;
      ++segment_;
      if (segment_ == 0) return invalidate();
    }
    if (left_new) {
      if (pending_[0]) return invalidate(); // cannot silently skip ticks
      pending_[0] = true; pending_delta_[0] = left_delta;
      pending_ms_[0] = left.at_ms; pending_seq_[0] = left.sample_seq;
    }
    if (right_new) {
      if (pending_[1]) return invalidate();
      pending_[1] = true; pending_delta_[1] = right_delta;
      pending_ms_[1] = right.at_ms; pending_seq_[1] = right.sample_seq;
    }
    for (int i = 0; i < 2; ++i)
      if (pending_[i] && now_ms - pending_ms_[i] > max_skew_ms_)
        return invalidate();
    if (!pending_[0] || !pending_[1]) return Result::Waiting;
    const std::uint32_t delay = skew(pending_ms_[0], pending_ms_[1]);
    if (delay > max_skew_ms_ || pair_seq_ == 0xffffffffU)
      return invalidate();
    ++pair_seq_;
    receipt_.valid = true;
    receipt_.left_delta = pending_delta_[0];
    receipt_.right_delta = pending_delta_[1];
    receipt_.left_ms = pending_ms_[0];
    receipt_.right_ms = pending_ms_[1];
    receipt_.left_seq = pending_seq_[0];
    receipt_.right_seq = pending_seq_[1];
    receipt_.skew_ms = delay;
    receipt_.segment = segment_;
    receipt_.pair_seq = pair_seq_;
    pending_[0] = pending_[1] = false;
    return Result::Paired;
  }

 private:
  static std::uint32_t skew(std::uint32_t a, std::uint32_t b) {
    const std::uint32_t ab = a - b;
    const std::uint32_t ba = b - a;
    return ab < ba ? ab : ba; // bounded distance, including uint32 rollover
  }
  Result invalidate() {
    synchronized_ = false;
    baseline_[0] = baseline_[1] = false;
    pending_[0] = pending_[1] = false;
    receipt_.valid = false;
    return Result::Invalid;
  }
  bool configured_ = false, synchronized_ = false;
  bool baseline_[2]{}, pending_[2]{};
  std::uint32_t max_skew_ms_ = 0, baseline_ms_[2]{};
  std::uint32_t pending_ms_[2]{}, pending_seq_[2]{};
  int pending_delta_[2]{};
  std::uint32_t segment_ = 0, pair_seq_ = 0;
  Receipt receipt_{};
};
}  // namespace desk_robot
