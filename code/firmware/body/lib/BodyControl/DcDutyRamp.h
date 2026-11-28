#pragma once

#include <cstdint>

namespace desk_robot {

// Duty scheduling only: the loaded wheel speed and traction need bench trials.
class DcDutyRamp {
 public:
  int update(std::uint32_t now_us, int requested, bool enabled) {
    constexpr int kLimit = 40;
    constexpr std::int32_t kScale = 1000000;
    constexpr std::uint32_t kMaxElapsedUs = 20000;
    constexpr std::int32_t kPercentPerSecond = 80;
    if (!enabled || requested == 0) {
      reset();
      return 0;
    }
    if (requested > kLimit) requested = kLimit;
    if (requested < -kLimit) requested = -kLimit;
    const auto target = requested * kScale;
    if (!active_ || (duty_ > 0 && target < 0) || (duty_ < 0 && target > 0)) {
      // Start or reverse from coast; no accumulated duty or elapsed-time debt.
      active_ = true;
      duty_ = 0;
      last_us_ = now_us;
      return 0;
    }
    const auto elapsed = now_us - last_us_;
    last_us_ = now_us;
    const auto bounded = elapsed < kMaxElapsedUs ? elapsed : kMaxElapsedUs;
    const auto delta = static_cast<std::int32_t>(bounded) * kPercentPerSecond;
    if (duty_ < target) {
      duty_ += target - duty_ < delta ? target - duty_ : delta;
    } else if (duty_ > target) {
      duty_ -= duty_ - target < delta ? duty_ - target : delta;
    }
    return duty_ / kScale;
  }

  void reset() {
    active_ = false;
    duty_ = 0;
  }

 private:
  bool active_ = false;
  std::uint32_t last_us_ = 0;
  std::int32_t duty_ = 0;
};

}  // namespace desk_robot
