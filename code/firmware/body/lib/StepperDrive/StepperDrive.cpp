#include "StepperDrive.h"

namespace desk_robot {
namespace {
// Bit positions are the four driver inputs, not a board-specific pin allocation.
constexpr std::uint8_t kHalfSteps[] = {1, 3, 2, 6, 4, 12, 8, 9};
constexpr std::uint64_t kPeriodScale = 1000000000000ULL;

int bounded_percent(int requested) {
  // Clamp before multiplication/absolute value, including INT_MIN input.
  if (requested > kStepperPercentLimit) return kStepperPercentLimit;
  if (requested < -kStepperPercentLimit) return -kStepperPercentLimit;
  return requested;
}
}  // namespace

std::uint8_t StepperDrive::update(std::uint32_t now_us, int requested_percent,
                                bool enabled) {
  const int percent = bounded_percent(requested_percent);
  if (!enabled || percent == 0) {
    // Fail-safe unqualified default is coil-off/coast, not claimed braking.
    // Preserve phase_ so a later enable does not reset the electrical sequence.
    active_ = false;
    rate_micro_ = 0;
    mask_ = 0;
    last_update_us_ = now_us;
    last_phase_us_ = now_us;
    return mask_;
  }
  if (!active_) {
    active_ = true;
    last_update_us_ = now_us;
    last_phase_us_ = now_us;
    mask_ = kHalfSteps[phase_];
    return mask_;
  }

  const std::uint32_t elapsed = now_us - last_update_us_;
  last_update_us_ = now_us;
  const std::uint32_t ramp_elapsed =
      elapsed < kStepperMaxRampElapsedUs ? elapsed : kStepperMaxRampElapsedUs;
  const std::int32_t delta = static_cast<std::int32_t>(
      ramp_elapsed * kStepperAccelerationHalfStepsPerSecondSquared);
  std::int32_t target = percent * kStepperFullScaleHalfStepsPerSecond * 10000;
  // Decelerate all the way to zero before adopting the opposite direction.
  if ((rate_micro_ > 0 && target < 0) || (rate_micro_ < 0 && target > 0)) target = 0;
  if (rate_micro_ < target) {
    rate_micro_ += target - rate_micro_ < delta ? target - rate_micro_ : delta;
  } else if (rate_micro_ > target) {
    rate_micro_ -= rate_micro_ - target < delta ? rate_micro_ - target : delta;
  }
  if (rate_micro_ == 0) {
    last_phase_us_ = now_us;
    return mask_;
  }

  const std::uint32_t magnitude = static_cast<std::uint32_t>(
      rate_micro_ < 0 ? -rate_micro_ : rate_micro_);
  const std::uint32_t period_us = static_cast<std::uint32_t>(
      (kPeriodScale + magnitude - 1) / magnitude);
  if (now_us - last_phase_us_ >= period_us) {
    phase_ = static_cast<std::uint8_t>((phase_ + (rate_micro_ > 0 ? 1 : 7)) % 8);
    mask_ = kHalfSteps[phase_];
    // No accumulated step debt: a delayed call emits at most one transition,
    // and the next transition must wait a complete current-rate interval.
    last_phase_us_ = now_us;
  }
  return mask_;
}
}  // namespace desk_robot
