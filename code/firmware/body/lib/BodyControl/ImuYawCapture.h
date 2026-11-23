#pragma once

#include <cstdint>
#include "BerryImu.h"

namespace desk_robot {

// Bounded MPU6050 raw gyro integration, never absolute heading. MPU6050
// FS_SEL=0 (BerryImu.cpp) is 131 LSB/(deg/s), per TDK MPU-6000/6050 spec:
// https://product.tdk.com/system/files/dam/doc/product/sensor/mortion-inertial/imu/data_sheet/mpu-6000-datasheet1.pdf
// A verified mounting axis, temperature range, zero-rate bias and drift
// allowance are REQUIRED from the installed board before configuration.
// This source never grants motor permission, a pose origin or navigation.
class ImuYawCapture {
 public:
  enum class Result { Unqualified, Invalid, Baseline, Duplicate, Delta };
  struct Calibration {
    std::uint8_t axis = 0; // measured body yaw axis in sensor x/y/z
    int sign = 0; // measured handedness: exactly +1 or -1
    std::int16_t bias_raw = 0; // same sensor axis, raw LSB
    std::uint16_t max_rate_raw = 0; // measured usable rate, below saturation
    std::uint16_t bias_uncertainty_raw = 0; // measured zero-rate error bound
    std::uint32_t scale_error_ppm = 0; // measured sensitivity error bound
    std::uint16_t accel_norm_min_raw = 0, accel_norm_max_raw = 0;
    std::int16_t temp_min_raw = 0, temp_max_raw = 0;
    std::uint32_t max_gap_ms = 0, max_age_ms = 0;
    std::uint32_t max_yaw_error_urad = 0;
  };

  bool configure(const Calibration& c) {
    if (configured_ || c.axis > 2 || (c.sign != 1 && c.sign != -1) ||
        c.bias_raw < -4096 || c.bias_raw > 4096 ||
        c.max_rate_raw == 0 || c.max_rate_raw > 32000 ||
        c.bias_uncertainty_raw == 0 ||
        c.bias_uncertainty_raw > c.max_rate_raw ||
        c.scale_error_ppm == 0 || c.scale_error_ppm > 100000 ||
        c.accel_norm_min_raw == 0 ||
        c.accel_norm_max_raw <= c.accel_norm_min_raw ||
        c.accel_norm_max_raw > 32767 ||
        c.temp_min_raw >= c.temp_max_raw ||
        c.max_gap_ms == 0 || c.max_gap_ms > 200 ||
        c.max_age_ms == 0 || c.max_age_ms > c.max_gap_ms ||
        c.max_yaw_error_urad == 0 || c.max_yaw_error_urad > 3141593U)
      return false;
    calibration_ = c;
    configured_ = true;
    return true;
  }

  Result observe(const BerryReading& r, std::uint32_t now_ms) {
    last_delta_urad_ = 0;
    if (!configured_) return Result::Unqualified;
    if (drift_latched_) return Result::Invalid;
    const std::int32_t axis_raw = r.gyro[calibration_.axis];
    const std::int32_t corrected = axis_raw - calibration_.bias_raw;
    const std::int64_t ax = r.accel[0], ay = r.accel[1], az = r.accel[2];
    const std::int64_t norm2 = ax * ax + ay * ay + az * az;
    const std::int64_t norm_min = calibration_.accel_norm_min_raw;
    const std::int64_t norm_max = calibration_.accel_norm_max_raw;
    if (r.model != BerryModel::Mpu6050 || !r.valid ||
        !r.low_g_status_valid || r.low_g_irq ||
        r.gyro[calibration_.axis] == -32768 ||
        r.gyro[calibration_.axis] == 32767 ||
        corrected > calibration_.max_rate_raw ||
        corrected < -static_cast<std::int32_t>(calibration_.max_rate_raw) ||
        r.temperature_raw < calibration_.temp_min_raw ||
        r.temperature_raw > calibration_.temp_max_raw ||
        norm2 < norm_min * norm_min || norm2 > norm_max * norm_max ||
        now_ms - r.at_ms > calibration_.max_age_ms) {
      invalidate();
      return Result::Invalid;
    }
    if (seen_) {
      if (r.at_ms == last_.at_ms) {
        if (continuous_ && same_sample(r, last_))
          return Result::Duplicate;
        invalidate();
        return Result::Invalid;
      }
      const std::uint32_t elapsed = r.at_ms - last_.at_ms;
      if (elapsed >= 0x80000000U) {
        invalidate();
        return Result::Invalid;
      }
      if (continuous_ && elapsed > calibration_.max_gap_ms) {
        last_ = r; // newest complete acquisition fences old replay
        invalidate();
        return Result::Invalid;
      }
    }
    if (!continuous_) {
      if (segment_ == 0xffffffffU) {
        invalidate();
        return Result::Invalid;
      }
      last_ = r;
      seen_ = continuous_ = true;
      yaw_urad_ = 0;
      yaw_error_bound_urad_ = 0;
      ++segment_;
      return Result::Baseline;
    }
    const std::uint32_t dt_ms = r.at_ms - last_.at_ms;
    const std::int64_t previous_corrected =
        static_cast<std::int32_t>(last_.gyro[calibration_.axis]) -
        calibration_.bias_raw;
    const std::int64_t signed_rates =
        (previous_corrected + corrected) * calibration_.sign;
    // Trapezoid integration of 131 LSB/(deg/s), using fixed integer
    // microradians and a nearest-integer division, with no floating point.
    constexpr std::int64_t kPiUrad = 3141593LL;
    constexpr std::int64_t kRateDenominator = 47160000LL; // 2*131*180*1000
    const std::int64_t numerator =
        signed_rates * dt_ms * kPiUrad;
    const std::int64_t delta =
        numerator >= 0 ? (numerator + kRateDenominator / 2) / kRateDenominator
                       : (numerator - kRateDenominator / 2) / kRateDenominator;
    // Calibrated conservative error growth, not a statistical covariance.
    // Quantization adds 1 urad per distinct sample. No stationary bias
    // reset is allowed without a separately qualified stationary interval.
    const std::uint64_t bias_numerator =
        static_cast<std::uint64_t>(calibration_.bias_uncertainty_raw) *
        dt_ms * static_cast<std::uint64_t>(kPiUrad);
    const std::uint64_t bias_error =
        (bias_numerator + 23580000ULL - 1) / 23580000ULL;
    const std::uint64_t absolute_delta =
        static_cast<std::uint64_t>(delta < 0 ? -delta : delta);
    const std::uint64_t scale_error =
        (absolute_delta * calibration_.scale_error_ppm + 999999ULL) /
        1000000ULL;
    const std::uint64_t increment = bias_error + scale_error + 1ULL;
    if (increment > calibration_.max_yaw_error_urad ||
        yaw_error_bound_urad_ >
            calibration_.max_yaw_error_urad - increment) {
      // A drifted origin may not quietly restart from the same calibration.
      drift_latched_ = true;
      invalidate();
      return Result::Invalid;
    }
    last_ = r;
    yaw_error_bound_urad_ += static_cast<std::uint32_t>(increment);
    yaw_urad_ += delta;
    constexpr std::int64_t kFullTurnUrad = 2 * kPiUrad;
    if (yaw_urad_ > kPiUrad) yaw_urad_ -= kFullTurnUrad;
    if (yaw_urad_ < -kPiUrad) yaw_urad_ += kFullTurnUrad;
    last_delta_urad_ = delta;
    return Result::Delta;
  }

  void invalidate() {
    continuous_ = false;
    last_delta_urad_ = 0;
    yaw_urad_ = 0;
    yaw_error_bound_urad_ = 0;
  }
  void reset_for_boot() { *this = ImuYawCapture(); }
  bool continuous() const { return continuous_; }
  bool fresh(std::uint32_t now_ms) const {
    return continuous_ && now_ms - last_.at_ms <= calibration_.max_age_ms;
  }
  bool drift_latched() const { return drift_latched_; }
  std::int64_t yaw_urad() const { return continuous_ ? yaw_urad_ : 0; }
  std::int64_t last_delta_urad() const {
    return continuous_ ? last_delta_urad_ : 0;
  }
  std::uint32_t error_bound_urad() const {
    return continuous_ ? yaw_error_bound_urad_ : 0;
  }
  std::uint32_t segment() const { return segment_; }

 private:
  static bool same_sample(const BerryReading& a, const BerryReading& b) {
    if (a.model != b.model || a.valid != b.valid ||
        a.at_ms != b.at_ms || a.temperature_raw != b.temperature_raw ||
        a.low_g_status_valid != b.low_g_status_valid ||
        a.low_g_irq != b.low_g_irq ||
        a.low_g_event_seq != b.low_g_event_seq) return false;
    for (int i = 0; i < 3; ++i)
      if (a.accel[i] != b.accel[i] || a.gyro[i] != b.gyro[i])
        return false;
    return true;
  }

  Calibration calibration_{};
  BerryReading last_{};
  bool configured_ = false, seen_ = false, continuous_ = false;
  bool drift_latched_ = false;
  std::uint32_t segment_ = 0, yaw_error_bound_urad_ = 0;
  std::int64_t yaw_urad_ = 0, last_delta_urad_ = 0;
};
}  // namespace desk_robot
