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
    const std::uint32_t later =
        (w.left_ms - w.right_ms < 0x80000000U) ? w.left_ms : w.right_ms;
    const std::uint32_t earlier =
        (later == w.left_ms) ? w.right_ms : w.left_ms;
    if (!w.valid || w.pair_seq == 0 || w.segment == 0 ||
        !e.imu_valid || e.imu_segment == 0 ||
        w.skew_ms > limits_.max_pair_skew_ms ||
        skew(later, e.imu_at_ms) > limits_.max_imu_skew_ms ||
        now_ms - earlier > limits_.max_age_ms ||
        now_ms - e.imu_at_ms > limits_.max_age_ms ||
        (have_source_ &&
         (w.pair_seq != last_pair_seq_ + 1U ||
          (w.segment != wheel_segment_ || e.imu_segment != imu_segment_) ||
          (earlier - last_sample_ms_ == 0U ||
           earlier - last_sample_ms_ >= 0x80000000U)))) {
      invalidate();
      return false;
    }
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
        abs64(left_nm) > bound_nm || abs64(right_nm) > bound_nm) {
      invalidate();
      return false;
    }
    if (!have_source_) {
      wheel_segment_ = w.segment;
      imu_segment_ = e.imu_segment;
      have_source_ = true;
    }
    last_pair_seq_ = w.pair_seq;
    last_sample_ms_ = earlier;
    last_imu_yaw_urad_ = e.imu_yaw_urad;
    latest_imu_error_urad_ = e.imu_error_urad;
    if (state_.origin == 0) {
      if (left_nm == 0 && right_nm == 0 &&
          abs64(e.imu_step_urad) <= limits_.stationary_gyro_step_urad) {
        if (stationary_streak_ < limits_.stationary_pairs_required)
          ++stationary_streak_;
      } else {
        stationary_streak_ = 0;
      }
      return true;
    }

    // NB: previous yaw must be retained independently from the fresh sample.
    // It is saved by observe() before the last update to source identities.
    return false;
  }

  bool stationary_origin_ready() const {
    return configured_ && have_source_ && state_.origin == 0 &&
           stationary_streak_ >= limits_.stationary_pairs_required;
  }

  // Only the physically verified local reanchor workflow may call this.
  // No UART/LLM handler uses it. It defines a fresh *local* odom frame,
  // not a verified global map location or motor arming permission.
  bool start_origin(std::uint32_t now_ms) {
    if (!stationary_origin_ready() ||
        now_ms - last_sample_ms_ > limits_.max_age_ms ||
        next_origin_ == 0 || next_origin_ == 0xffffffffU)
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
    if (have_source_ && now_ms - last_sample_ms_ > limits_.max_age_ms)
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
  static std::uint64_t abs64(std::int64_t value) {
    return static_cast<std::uint64_t>(value < 0 ? -value : value);
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
  std::uint32_t last_sample_ms_ = 0;
  std::uint32_t wheel_segment_ = 0, imu_segment_ = 0;
  std::uint32_t latest_imu_error_urad_ = 0;
  std::int64_t last_imu_yaw_urad_ = 0, origin_yaw_urad_ = 0;
  std::int64_t heading_urad_ = 0, x_nm_ = 0, y_nm_ = 0;
  std::uint64_t xy_error_nm_ = 0;
};
}  // namespace desk_robot
