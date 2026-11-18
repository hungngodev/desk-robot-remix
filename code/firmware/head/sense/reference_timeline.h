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
    if (end_us_ <= 0) {
      end_us_ = now_us;
      return 0;
    }
    if (now_us <= end_us_) return 0;
    const auto elapsed_us = static_cast<std::uint64_t>(now_us - end_us_);
    const auto frames = elapsed_us * kReferenceRate / 1000000U;
    end_us_ = now_us;
    return std::min<std::uint64_t>(frames, max_frames);
  }

  void accepted_output_frames(int samples) {
    if (samples > 0) {
      end_us_ += static_cast<std::int64_t>(samples) * 1000000 / kOutputRate;
    }
  }

  void reset() { end_us_ = 0; }
  std::int64_t represented_end_us() const { return end_us_; }

 private:
  std::int64_t end_us_ = 0;
};
}  // namespace desk_robot
