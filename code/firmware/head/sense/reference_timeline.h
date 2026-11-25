#pragma once

#include <algorithm>
#include <cstdint>
#include <limits>

// Small pure timing core reused by the Sense AEC codec and its native host
// regression. This is sample accounting, not physical speaker playback
// confirmation or an acoustic echo-delay calibration.
namespace desk_robot {
class PlaybackReferenceClock {
 public:
  static constexpr std::uint32_t kReferenceRate = 16000;
  static constexpr std::uint32_t kOutputRate = 32000;

  // The end timestamp includes all accepted output PCM already represented
  // in the ring. Reads must not add silence for that SAME audio duration.
  std::uint64_t silence_frames(std::int64_t now_us,
                               std::uint64_t max_frames) {
    if (!initialized_) {
      end_us_ = now_us;
      initialized_ = true;
      return 0;
    }
    if (now_us <= end_us_) return 0;
    // Ordered signed timestamps can span the full uint64_t range. Subtract
    // in unsigned space, then split whole seconds before multiplying.
    auto elapsed_us = static_cast<std::uint64_t>(now_us) -
        static_cast<std::uint64_t>(end_us_);
    // Keep the fractional sample phase between irregular PDM reads without
    // overflowing either the elapsed-time product or a caller-supplied cap.
    // The queued output end can contain a fractional microsecond. Subtract
    // that fraction before re-anchoring to the integer microphone clock.
    // Borrow a whole microsecond before splitting to avoid unsigned underflow.
    std::uint64_t fractional_gap = 0;
    if (output_remainder_ != 0) {
      --elapsed_us;
      fractional_gap = (kOutputRate - output_remainder_) / 2U;
    }
    const auto numerator = (elapsed_us % 1000000U) * kReferenceRate +
        silence_remainder_ + fractional_gap;
    output_remainder_ = 0;
    const auto frames = (elapsed_us / 1000000U) * kReferenceRate +
        numerator / 1000000U;
    end_us_ = now_us;
    silence_remainder_ = numerator % 1000000U;
    if (frames > max_frames) {
      silence_remainder_ = 0;
      return max_frames;
    }
    return frames;
  }

  void accepted_output_frames(int samples) {
    if (samples > 0) {
      initialized_ = true;
      // Accepted I2S chunks may be partial. Carry sub-microsecond residue,
      // rather than truncating every 32 kHz frame to 31 microseconds.
      const auto numerator = static_cast<std::uint64_t>(samples) * 1000000U
          + output_remainder_;
      const auto duration = static_cast<std::int64_t>(numerator / kOutputRate);
      if (end_us_ > std::numeric_limits<std::int64_t>::max() - duration) {
        end_us_ = std::numeric_limits<std::int64_t>::max();
        output_remainder_ = 0;
        return;
      }
      end_us_ += duration;
      output_remainder_ = end_us_ == std::numeric_limits<std::int64_t>::max()
          ? 0 : numerator % kOutputRate;
    }
  }

  // PCM accepted by I2S can represent future playback, not microphone-time
  // audio. Select the reference window at capture time, not the newest ring
  // entry, or rapid successive Opus chunks can feed AEC premature speech.
  // This is a bounded software timing estimate, not physical DAC playback.
  std::uint64_t future_reference_frames(std::int64_t now_us,
                                        std::uint64_t cap) const {
    if (!initialized_ || end_us_ < now_us) return 0;
    if (end_us_ == now_us && output_remainder_ == 0) return 0;
    if (now_us < 0) return cap;
    const auto ahead_us = static_cast<std::uint64_t>(end_us_ - now_us);
    // Round up: never expose a queued PCM sample as already played. Split
    // the duration so even INT64_MAX and UINT64_MAX caps are safe.
    return std::min(cap, (ahead_us / 1000000U) * kReferenceRate +
        ((ahead_us % 1000000U) * kReferenceRate +
         output_remainder_ / 2U + 999999U) / 1000000U);
  }

  void reset() {
    end_us_ = 0;
    initialized_ = false;
    silence_remainder_ = 0;
    output_remainder_ = 0;
  }
  std::int64_t represented_end_us() const { return end_us_; }

 private:
  std::int64_t end_us_ = 0;
  bool initialized_ = false;
  std::uint64_t silence_remainder_ = 0;
  std::uint64_t output_remainder_ = 0;
};
}  // namespace desk_robot
