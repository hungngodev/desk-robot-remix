#pragma once

#include <cstdint>

namespace desk_robot {

// Scheduling targets only, not measured output speed, torque or odometry.
// Independent conservative scheduling ceiling. The 5 V 28BYJ-48 data sheet
// quotes unloaded pull-in/out frequencies (>600/>1000 Hz), not a loaded
// pull-out torque curve. Do not raise this ceiling from those figures alone.
// https://www.sparkfun.com/step-motor-5v.html
constexpr int kStepperMaxHalfStepsPerSecond = 160;
constexpr int kStepperPercentLimit = 40;
constexpr int kStepperFullScaleHalfStepsPerSecond = 400;
static_assert(kStepperPercentLimit > 0 && kStepperPercentLimit <= 100 &&
                  kStepperFullScaleHalfStepsPerSecond > 0 &&
                  static_cast<std::int64_t>(kStepperPercentLimit) *
                          kStepperFullScaleHalfStepsPerSecond <=
                      100LL * kStepperMaxHalfStepsPerSecond,
              "Stepper command scaling exceeds the unqualified rate ceiling");
constexpr int kStepperAccelerationHalfStepsPerSecondSquared = 320;
constexpr std::uint32_t kStepperMaxRampElapsedUs = 20000;

// Nonblocking half-step sequencing for an unmodified 28BYJ-48 / ULN2003 pair.
// Bits 0..3 correspond to IN1..IN4; actual motor order/polarity needs bench tests.
class StepperDrive {
 public:
  // First activation energizes the retained phase without advancing it. The
  // caller must enforce its own bounded drive lease and local safety interlock.
  std::uint8_t update(std::uint32_t now_us, int requested_percent, bool enabled);
  std::uint8_t mask() const { return mask_; }
  int rate_milli_steps_per_second() const { return rate_micro_ / 1000; }

 private:
  std::uint8_t phase_ = 0;
  std::uint8_t mask_ = 0;
  bool active_ = false;
  std::int32_t rate_micro_ = 0;
  std::uint32_t last_update_us_ = 0;
  std::uint32_t last_phase_us_ = 0;
};

}  // namespace desk_robot
