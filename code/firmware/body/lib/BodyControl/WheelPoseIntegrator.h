#pragma once

#include <cmath>
#include <cstdint>
#include "WheelPairCapture.h"

namespace desk_robot {

// Differential wheel evidence plus measured gyro yaw. Inspired by the
// wheel-feedback-only odometry model of ROS 2 diff_drive_controller (Apache
// 2.0), adapted as small bounded native C++ for WROOM without ROS runtime:
// https://control.ros.org/rolling/doc/api/classdiff__drive__controller_1_1Odometry.html
// This class NEVER consumes commanded velocity or stepper pulse positions.
// Without explicitly measured per-unit calibration and deliberate reanchor
// the only honest answer is unavailable.
class WheelPoseIntegrator {
 public:
  enum class Quality { Unavailable, Degraded, Valid };
  struct Calibration {
    std::int32_t left_nm_per_count = 0, right_nm_per_count = 0;
    int left_forward_sign = 0, right_forward_sign = 0;
    std::uint32_t track_width_mm = 0;
    std::uint32_t max_pair_step_mm = 0;
    std::uint32_t max_pair_skew_ms = 0, max_imu_skew_ms = 0;
    std::uint32_t max_age_ms = 0;
    std::uint32_t wheel_error_ppm = 0;
    std::uint32_t imu_alignment_error_urad = 0;
    std::uint32_t max_wheel_gyro_residual_urad = 0;
    std::uint32_t max_xy_error_mm = 0, max_yaw_error_urad = 0;
    std::uint32_t stationary_gyro_step_urad = 0;
    std::uint8_t stationary_pairs_required = 0;
  };
  struct Evidence {
    WheelPairCapture::Receipt wheel{};
    bool imu_valid = false;
    std::uint32_t imu_segment = 0, imu_at_ms = 0;
    std::int64_t imu_yaw_urad = 0, imu_step_urad = 0;
    std::uint32_t imu_error_urad = 0;
  };
  struct State {
    Quality quality = Quality::Unavailable;
    std::uint32_t origin = 0, sample_seq = 0, sample_ms = 0;
    std::int32_t x_mm = 0, y_mm = 0, yaw_mrad = 0;
    std::uint32_t xy_error_mm = 0, yaw_error_mrad = 0;
  };

  bool configure(const Calibration& c) {
    if (configured_ ||
        c.left_nm_per_count <= 0 || c.right_nm_per_count <= 0 ||
        c.left_nm_per_count > 1000000 || c.right_nm_per_count > 1000000 ||
        (c.left_forward_sign != 1 && c.left_forward_sign != -1) ||
        (c.right_forward_sign != 1 && c.right_forward_sign != -1) ||
        c.track_width_mm < 20 || c.track_width_mm > 500 ||
        c.max_pair_step_mm == 0 || c.max_pair_step_mm > 100 ||
        c.max_pair_skew_ms == 0 || c.max_pair_skew_ms > 100 ||
        c.max_imu_skew_ms == 0 || c.max_imu_skew_ms > 150 ||
        c.max_age_ms == 0 || c.max_age_ms > 500 ||
        c.wheel_error_ppm == 0 || c.wheel_error_ppm > 1000000 ||
        c.imu_alignment_error_urad == 0 ||
        c.imu_alignment_error_urad > 100000 ||
        c.max_wheel_gyro_residual_urad == 0 ||
        c.max_wheel_gyro_residual_urad > 500000 ||
        c.max_xy_error_mm == 0 || c.max_xy_error_mm > 1000 ||
        c.max_yaw_error_urad == 0 || c.max_yaw_error_urad > 3141593 ||
        c.stationary_gyro_step_urad == 0 ||
        c.stationary_gyro_step_urad > 10000 ||
        c.stationary_pairs_required < 3 || c.stationary_pairs_required > 10)
      return false;
    limits_ = c;
    configured_ = true;
    return true;
  }

  // Exactly one receipt per new genuinely paired wheel acquisition.
  // A repeated, skipped, old or contradictory receipt permanently retires
  // the current origin; only fresh stationary evidence and explicit local
  // reanchor can create a new frame.
  bool observe(const Evidence& e, std::uint32_t now_ms) {
    if (!configured_) return false;
    const auto& w = e.wheel;
    const auto reject = [this, &w]() {
      // Even a rejected complete packet must not be replayed as a new
      // stationary origin witness on a later call.
      if (w.pair_seq > last_pair_seq_) last_pair_seq_ = w.pair_seq;
      invalidate();
      return false;
    };
    const std::uint32_t later =
        (w.left_ms - w.right_ms < 0x80000000U) ? w.left_ms : w.right_ms;
    const std::uint32_t earlier =
        (later == w.left_ms) ? w.right_ms : w.left_ms;
    if (!w.valid || w.pair_seq == 0 || w.segment == 0 ||
        w.left_seq == 0 || w.right_seq == 0 ||
        (last_pair_seq_ == 0 ? w.pair_seq != 1U
                             : w.pair_seq != last_pair_seq_ + 1U) ||
        !e.imu_valid || e.imu_segment == 0 ||
        e.imu_yaw_urad < -3141593LL || e.imu_yaw_urad > 3141593LL ||
        w.skew_ms != skew(w.left_ms, w.right_ms) ||
        w.skew_ms > limits_.max_pair_skew_ms ||
        skew(later, e.imu_at_ms) > limits_.max_imu_skew_ms ||
        now_ms - earlier > limits_.max_age_ms ||
        now_ms - e.imu_at_ms > limits_.max_age_ms ||
        static_cast<std::uint64_t>(e.imu_error_urad) +
                limits_.imu_alignment_error_urad >
            limits_.max_yaw_error_urad ||
        (have_source_ &&
         (w.segment != wheel_segment_ || e.imu_segment != imu_segment_ ||
          (e.imu_at_ms - last_imu_ms_ == 0U ||
           e.imu_at_ms - last_imu_ms_ >= 0x80000000U) ||
          earlier - last_sample_ms_ == 0U ||
          earlier - last_sample_ms_ >= 0x80000000U)))
      return reject();
    const std::int64_t left_nm =
        static_cast<std::int64_t>(w.left_delta) *
        limits_.left_nm_per_count * limits_.left_forward_sign;
    const std::int64_t right_nm =
        static_cast<std::int64_t>(w.right_delta) *
        limits_.right_nm_per_count * limits_.right_forward_sign;
    const std::int64_t bound_nm =
        static_cast<std::int64_t>(limits_.max_pair_step_mm) * 1000000LL;
    if (w.left_delta < -2047 || w.left_delta > 2047 ||
        w.right_delta < -2047 || w.right_delta > 2047 ||
        abs64(left_nm) > static_cast<std::uint64_t>(bound_nm) ||
        abs64(right_nm) > static_cast<std::uint64_t>(bound_nm))
      return reject();

    // The latest IMU conversion alone can miss rotation between wheel pairs.
    const bool gyro_stationary = !have_source_ ||
        abs64(normalize(e.imu_yaw_urad - last_imu_yaw_urad_)) <=
            limits_.stationary_gyro_step_urad;
    if (!have_source_) {
      wheel_segment_ = w.segment;
      imu_segment_ = e.imu_segment;
      have_source_ = true;
    }
    if (state_.origin == 0) {
      if (left_nm == 0 && right_nm == 0 && gyro_stationary &&
          abs64(e.imu_step_urad) <= limits_.stationary_gyro_step_urad) {
        if (stationary_streak_ < limits_.stationary_pairs_required)
          ++stationary_streak_;
      } else {
        stationary_streak_ = 0;
      }
    } else {
      const std::int64_t gyro_delta =
          normalize(e.imu_yaw_urad - last_imu_yaw_urad_);
      const std::int64_t wheel_delta =
          (right_nm - left_nm) / limits_.track_width_mm;
      const std::uint64_t residual = abs64(wheel_delta - gyro_delta);
      if (residual > limits_.max_wheel_gyro_residual_urad)
        return reject();
      const std::uint32_t heading_error_urad =
          e.imu_error_urad + limits_.imu_alignment_error_urad;
      const std::int64_t traveled_nm = (left_nm + right_nm) / 2;
      const std::int64_t midpoint_yaw =
          normalize(heading_urad_ + gyro_delta / 2);
      // Bounded one-pair midpoint integration, not motor open-loop steps.
      // Max travel per pair and source skew are separately checked above.
      const double mid_rad = static_cast<double>(midpoint_yaw) / 1000000.0;
      const double dx_real = static_cast<double>(traveled_nm) *
                             std::cos(mid_rad);
      const double dy_real = static_cast<double>(traveled_nm) *
                             std::sin(mid_rad);
      if (!std::isfinite(dx_real) || !std::isfinite(dy_real))
        return reject();
      const std::int64_t new_x = x_nm_ + std::llround(dx_real);
      const std::int64_t new_y = y_nm_ + std::llround(dy_real);
      const std::int64_t max_coordinate_nm = 1000000000000LL;
      if (abs64(new_x) > static_cast<std::uint64_t>(max_coordinate_nm) ||
          abs64(new_y) > static_cast<std::uint64_t>(max_coordinate_nm))
        return reject();
      const std::uint64_t avg_abs_nm =
          (abs64(left_nm) + abs64(right_nm) + 1ULL) / 2ULL;
      const std::uint64_t wheel_error_nm =
          (avg_abs_nm * limits_.wheel_error_ppm + 999999ULL) / 1000000ULL;
      const std::uint64_t heading_error_nm =
          (abs64(traveled_nm) * heading_error_urad + 999999ULL) / 1000000ULL;
      const std::uint64_t error_increment_nm =
          wheel_error_nm + heading_error_nm + 1000ULL;
      const std::uint64_t max_xy_error_nm =
          static_cast<std::uint64_t>(limits_.max_xy_error_mm) * 1000000ULL;
      if (xy_error_nm_ > max_xy_error_nm ||
          error_increment_nm > max_xy_error_nm - xy_error_nm_)
        return reject();
      xy_error_nm_ += error_increment_nm;
      x_nm_ = new_x;
      y_nm_ = new_y;
      heading_urad_ = normalize(heading_urad_ + gyro_delta);
      state_.x_mm = static_cast<std::int32_t>(x_nm_ / 1000000LL);
      state_.y_mm = static_cast<std::int32_t>(y_nm_ / 1000000LL);
      state_.yaw_mrad = static_cast<std::int32_t>(heading_urad_ / 1000LL);
      state_.xy_error_mm =
          static_cast<std::uint32_t>((xy_error_nm_ + 999999ULL) / 1000000ULL);
      state_.yaw_error_mrad = (heading_error_urad + 999U) / 1000U;
      const bool degraded =
          xy_error_nm_ > max_xy_error_nm / 2ULL ||
          heading_error_urad > limits_.max_yaw_error_urad / 2U ||
          residual > limits_.max_wheel_gyro_residual_urad / 2U;
      state_.quality = degraded ? Quality::Degraded : Quality::Valid;
      state_.sample_seq = w.pair_seq;
      state_.sample_ms = earlier;
    }
    last_pair_seq_ = w.pair_seq;
    last_sample_ms_ = earlier;
    last_imu_ms_ = e.imu_at_ms;
    last_imu_yaw_urad_ = e.imu_yaw_urad;
    latest_imu_error_urad_ = e.imu_error_urad;
    return true;
  }

  bool stationary_origin_ready() const {
    return configured_ && have_source_ && state_.origin == 0 &&
           stationary_streak_ >= limits_.stationary_pairs_required;
  }

  // A newer unpaired gyro conversion may contain rotation after the last
  // stationary wheel pair. Require that exact current acquisition first.
  bool stationary_origin_ready_for_imu(std::uint32_t acquisition_ms) const {
    return stationary_origin_ready() && acquisition_ms == last_imu_ms_;
  }

  // Only the physically verified local reanchor workflow may call this.
  // No UART/LLM handler uses it. It defines a fresh *local* odom frame,
  // not a verified global map location or motor arming permission.
  bool start_origin(std::uint32_t now_ms) {
    if (!stationary_origin_ready() ||
        !sources_fresh(now_ms) ||
        next_origin_ == 0 || next_origin_ == 0xffffffffU)
      return false;
    if (static_cast<std::uint64_t>(latest_imu_error_urad_) +
            limits_.imu_alignment_error_urad >
        limits_.max_yaw_error_urad)
      return false;
    state_ = State{};
    state_.origin = next_origin_++;
    state_.quality = Quality::Valid;
    state_.sample_seq = last_pair_seq_;
    state_.sample_ms = last_sample_ms_;
    state_.yaw_error_mrad =
        (latest_imu_error_urad_ + limits_.imu_alignment_error_urad + 999U) /
        1000U;
    origin_yaw_urad_ = last_imu_yaw_urad_;
    heading_urad_ = 0;
    x_nm_ = y_nm_ = 0;
    xy_error_nm_ = 0;
    return true;
  }

  void expire(std::uint32_t now_ms) {
    if (have_source_ && !sources_fresh(now_ms))
      invalidate();
  }
  void invalidate() {
    state_ = State{};
    have_source_ = false;
    stationary_streak_ = 0;
    x_nm_ = y_nm_ = heading_urad_ = 0;
    xy_error_nm_ = 0;
    // Last pair sequence is kept as the replay fence until body reboot.
  }
  void reset_for_boot() { *this = WheelPoseIntegrator(); }
  const State& state() const { return state_; }
  bool configured() const { return configured_; }

 private:
  bool sources_fresh(std::uint32_t now_ms) const {
    return now_ms - last_sample_ms_ <= limits_.max_age_ms &&
           now_ms - last_imu_ms_ <= limits_.max_age_ms;
  }
  static std::uint64_t abs64(std::int64_t value) {
    const auto bits = static_cast<std::uint64_t>(value);
    return value < 0 ? 0ULL - bits : bits;
  }
  static std::uint32_t skew(std::uint32_t a, std::uint32_t b) {
    const std::uint32_t ab = a - b, ba = b - a;
    return ab < ba ? ab : ba;
  }
  static std::int64_t normalize(std::int64_t yaw) {
    constexpr std::int64_t kPi = 3141593LL, kFull = 6283186LL;
    while (yaw > kPi) yaw -= kFull;
    while (yaw < -kPi) yaw += kFull;
    return yaw;
  }

  Calibration limits_{};
  State state_{};
  bool configured_ = false, have_source_ = false;
  std::uint8_t stationary_streak_ = 0;
  std::uint32_t next_origin_ = 1, last_pair_seq_ = 0;
  std::uint32_t last_sample_ms_ = 0, last_imu_ms_ = 0;
  std::uint32_t wheel_segment_ = 0, imu_segment_ = 0;
  std::uint32_t latest_imu_error_urad_ = 0;
  std::int64_t last_imu_yaw_urad_ = 0, origin_yaw_urad_ = 0;
  std::int64_t heading_urad_ = 0, x_nm_ = 0, y_nm_ = 0;
  std::uint64_t xy_error_nm_ = 0;
};
}  // namespace desk_robot
