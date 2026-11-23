#include "WheelPoseIntegrator.h"
#include <stdexcept>
#include <cstdint>

using desk_robot::WheelPoseIntegrator;
static void check(bool ok) {
  if (!ok) throw std::runtime_error("wheel pose integration contract failed");
}
static WheelPoseIntegrator::Calibration calibration() {
  WheelPoseIntegrator::Calibration c{};
  c.left_nm_per_count = c.right_nm_per_count = 100000;
  c.left_forward_sign = 1;
  c.right_forward_sign = -1;
  c.track_width_mm = 100;
  c.max_pair_step_mm = 25;
  c.max_pair_skew_ms = 25;
  c.max_imu_skew_ms = 50;
  c.max_age_ms = 200;
  c.wheel_error_ppm = 10000;
  c.imu_alignment_error_urad = 1000;
  c.max_wheel_gyro_residual_urad = 50000;
  c.max_xy_error_mm = 30;
  c.max_yaw_error_urad = 500000;
  c.stationary_gyro_step_urad = 500;
  c.stationary_pairs_required = 3;
  return c;
}
static WheelPoseIntegrator::Evidence observed(
    std::uint32_t seq, std::uint32_t ms, int left = 0, int right = 0,
    std::int64_t yaw = 0, std::uint32_t segment = 1) {
  WheelPoseIntegrator::Evidence e{};
  e.wheel.valid = true;
  e.wheel.left_delta = left;
  e.wheel.right_delta = right;
  e.wheel.left_ms = ms;
  e.wheel.right_ms = ms + 10;
  e.wheel.left_seq = seq + 10;
  e.wheel.right_seq = seq + 20;
  e.wheel.skew_ms = 10;
  e.wheel.segment = segment;
  e.wheel.pair_seq = seq;
  e.imu_valid = true;
  e.imu_segment = segment;
  e.imu_at_ms = ms + 5;
  e.imu_yaw_urad = yaw;
  e.imu_step_urad = 0;
  e.imu_error_urad = 250;
  return e;
}
static void refuse_unqualified_and_reanchor() {
  WheelPoseIntegrator pose;
  check(!pose.observe(observed(1, 100), 110));
  auto bad = calibration(); bad.right_forward_sign = 0;
  check(!pose.configure(bad));
  check(pose.configure(calibration()));
  check(!pose.configure(calibration()));
  check(!pose.start_origin(120));
  check(pose.observe(observed(1, 100), 110));
  check(!pose.stationary_origin_ready());
  check(pose.observe(observed(2, 200), 210));
  check(pose.observe(observed(3, 300), 310));
  check(pose.stationary_origin_ready());
  check(pose.start_origin(310));
  check(pose.state().origin == 1 &&
        pose.state().quality == WheelPoseIntegrator::Quality::Valid);
  check(!pose.start_origin(311));
  // Must never invent an origin after reboot or stale times.
  pose.expire(601);
  check(pose.state().quality == WheelPoseIntegrator::Quality::Unavailable);
  check(!pose.start_origin(602));
  pose.reset_for_boot();
  check(!pose.configured() && pose.state().origin == 0);
}
static void refuse_skew_stale_and_replay() {
  WheelPoseIntegrator pose;
  check(pose.configure(calibration()));
  auto one = observed(1, 100);
  one.wheel.skew_ms = 80;
  check(!pose.observe(one, 110));
  check(pose.observe(observed(2, 200), 210));
  check(!pose.observe(observed(2, 200), 210)); // duplicate sequence
  check(!pose.stationary_origin_ready());
  auto bad_imu = observed(3, 300);
  bad_imu.imu_valid = false;
  check(!pose.observe(bad_imu, 310));
  auto old = observed(4, 400);
  check(!pose.observe(old, 1000)); // too old despite recent response
}
int main() {
  refuse_unqualified_and_reanchor();
  refuse_skew_stale_and_replay();
}
