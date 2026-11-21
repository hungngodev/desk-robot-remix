#pragma once

#include <algorithm>
#include <cstdint>

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
    const auto elapsed_us = static_cast<std::uint64_t>(now_us - end_us_);
    // Keep the fractional sample phase between irregular PDM reads. Rounding
    // each 10.007 ms read independently would lose fractional frames on
    // every callback, accumulating false AEC drift over a long conversation.
    // Huge unattended gaps are bounded: do not multiply unbounded uptime.
    const auto available_us = (max_frames / kReferenceRate + 1U) * 1000000U;
    if (elapsed_us > available_us) {
      end_us_ = now_us;
      silence_remainder_ = 0;
      return max_frames;
    }
    const auto numerator = elapsed_us * kReferenceRate + silence_remainder_;
    const auto frames = numerator / 1000000U;
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
      end_us_ += static_cast<std::int64_t>(numerator / kOutputRate);
      output_remainder_ = numerator % kOutputRate;
    }
  }

  // PCM accepted by I2S can represent future playback, not microphone-time
  // audio. Select the reference window at capture time, not the newest ring
  // entry, or rapid successive Opus chunks can feed AEC premature speech.
  // This is a bounded software timing estimate, not physical DAC playback.
  std::uint64_t future_reference_frames(std::int64_t now_us,
                                        std::uint64_t cap) const {
    if (end_us_ <= now_us) return 0;
    if (now_us < 0) return cap;
    const auto ahead_us = static_cast<std::uint64_t>(end_us_ - now_us);
    const auto bounded_us = (cap / kReferenceRate + 1U) * 1000000U;
    if (ahead_us > bounded_us) return cap;
    // Round up: never expose a queued PCM sample as already played.
    return std::min(cap, (ahead_us * kReferenceRate + 999999U) / 1000000U);
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
