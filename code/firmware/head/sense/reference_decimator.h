#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <algorithm>

namespace desk_robot {
// Convert accepted signed Q16 PCM32 to PCM16 with ties away from zero.
// Widen before rounding: INT32_MAX + half a step exceeds int32_t, and
// rounding full-scale positive PCM can produce 32768 before saturation.
inline int16_t Pcm32ToReferenceSample(int32_t sample) noexcept {
  const int64_t wide = sample;
  const int64_t rounded = (wide + (wide < 0 ? -32768 : 32768)) / 65536;
  return static_cast<int16_t>(std::clamp<int64_t>(rounded, -32768, 32767));
}

// Causal, unity-DC-gain, Q15 equiripple FIR, 32 kHz -> 16 kHz.
// Design: scipy.signal.remez(63, [0,6000,8000,16000], [1,0],
// weight=[1,10], fs=32000), rounded to Q15 with center adjusted to sum 32768.
// Group delay: 31 input samples (0.969 ms); calibrate acoustic delay with it.
class ReferenceDecimator {
 public:
  bool Push(int16_t sample, int16_t& output) noexcept {
    history_[next_] = sample;
    next_ = (next_ + 1U) & 63U;
    const bool emit = emit_next_;
    emit_next_ = !emit_next_;
    if (!emit) return false;
    int64_t sum = 0;
    for (std::size_t i = 0; i < kTaps.size(); ++i) {
      const int32_t pair = static_cast<int32_t>(history_[(next_ + 63U - i) & 63U]) +
                           history_[(next_ + 1U + i) & 63U];
      sum += static_cast<int64_t>(kTaps[i]) * pair;
    }
    sum += static_cast<int64_t>(14080) * history_[(next_ + 32U) & 63U];
    const int64_t rounded = sum >= 0 ? (sum + 16384) / 32768 : (sum - 16384) / 32768;
    output = static_cast<int16_t>(std::clamp<int64_t>(rounded, -32768, 32767));
    return true;
  }
  // Whole reference-frame silence does not alter the input-pair phase.
  void ClearHistory() noexcept { history_.fill(0); }
  void Reset() noexcept { ClearHistory(); next_ = 0; emit_next_ = true; }
 private:
  static constexpr std::array<int16_t, 31> kTaps{
      1,15,21,-1,-34,-19,43,57,-34,-106,-9,151,96,-163,-221,111,
      362,35,-475,-291,497,649,-350,-1078,-64,1519,908,-1906,-2698,2170,10158};
  std::array<int16_t, 64> history_{};
  std::size_t next_ = 0;
  bool emit_next_ = true;
};
}  // namespace desk_robot
