#include "WheelPoseIntegrator.h"
#include <stdexcept>
#include <cstdint>
#include <limits>

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
  check(pose.stationary_origin_ready_for_imu(305));
  check(!pose.stationary_origin_ready_for_imu(306));
  check(!pose.stationary_origin_ready_for_imu(304));
  check(pose.start_origin(310));
  check(!pose.stationary_origin_ready_for_imu(305));
  check(pose.state().origin == 1 &&
        pose.state().quality == WheelPoseIntegrator::Quality::Valid);
  check(!pose.start_origin(311));
  check(pose.observe(observed(4, 400, 10, -10), 410));
  check(pose.state().quality == WheelPoseIntegrator::Quality::Valid);
  check(pose.state().x_mm == 1 && pose.state().y_mm == 0 &&
        pose.state().yaw_mrad == 0 && pose.state().sample_seq == 4);
  check(pose.state().xy_error_mm > 0);
  check(pose.observe(observed(5, 500, -10, 10), 510));
  check(pose.state().x_mm == 0 && pose.state().y_mm == 0);
  check(pose.observe(observed(6, 600, 0, -10, 10000), 610));
  check(pose.state().yaw_mrad == 10 && pose.state().sample_seq == 6);
  check(pose.state().origin == 1);
  // A lost source cannot resurrect an earlier local origin. The next origin
  // requires three independent stationary paired acquisitions and a new
  // deliberate local call.
  pose.expire(900);
  check(pose.state().origin == 0);
  check(!pose.start_origin(901));
  check(pose.observe(observed(7, 920), 930));
  check(pose.observe(observed(8, 1020), 1030));
  check(pose.observe(observed(9, 1120), 1130));
  check(pose.start_origin(1130));
  check(pose.state().origin == 2 && pose.state().x_mm == 0 &&
        pose.state().y_mm == 0);
  // Must never invent an origin after reboot or stale times.
  pose.expire(1600);
  check(pose.state().quality == WheelPoseIntegrator::Quality::Unavailable);
  check(!pose.start_origin(1601));
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
  // A second wheel pair cannot reuse the same IMU conversion, even when
  // its gyro is still within the allowed skew and age envelope.
  WheelPoseIntegrator repeated_gyro;
  check(repeated_gyro.configure(calibration()));
  auto first_gyro = observed(1, 100);
  check(repeated_gyro.observe(first_gyro, 110));
  auto same_gyro = observed(2, 120);
  same_gyro.imu_at_ms = first_gyro.imu_at_ms;
  check(!repeated_gyro.observe(same_gyro, 130));
  check(repeated_gyro.state().origin == 0);
  // A forged small skew field cannot override actual wheel source clocks.
  WheelPoseIntegrator fake_skew;
  check(fake_skew.configure(calibration()));
  auto inconsistent = observed(1, 100);
  inconsistent.wheel.right_ms = 150; // actual 50 ms, claim only 10 ms
  check(!fake_skew.observe(inconsistent, 160));
  // Arbitrary IMU uncertainty must not overflow uint32 addition to "valid".
  WheelPoseIntegrator huge_error;
  check(huge_error.configure(calibration()));
  auto high = observed(1, 100);
  high.imu_error_urad = 0xffffffffU;
  check(!huge_error.observe(high, 110));
  auto bad_imu = observed(3, 300);
  bad_imu.imu_valid = false;
  check(!pose.observe(bad_imu, 310));
  auto old = observed(4, 400);
  check(!pose.observe(old, 1000)); // too old despite recent response
}
static void refuse_rotation_and_expired_imu_origin() {
  WheelPoseIntegrator rotation;
  check(rotation.configure(calibration()));
  // The IMU may have converted repeatedly between paired wheel samples.
  // A zero latest step does not prove zero cumulative rotation.
  for (std::uint32_t i = 1; i <= 3; ++i)
    check(rotation.observe(observed(i, i * 100, 0, 0, i * 2000), i * 100 + 10));
  check(!rotation.stationary_origin_ready());
  check(!rotation.start_origin(310));
  for (std::uint32_t i = 4; i <= 6; ++i)
    check(rotation.observe(observed(i, i * 100, 0, 0, 6000), i * 100 + 10));
  check(rotation.start_origin(610));

  WheelPoseIntegrator extreme;
  check(extreme.configure(calibration()));
  for (std::uint32_t i = 1; i <= 3; ++i) {
    auto e = observed(i, i * 100);
    e.imu_step_urad = std::numeric_limits<std::int64_t>::min();
    check(extreme.observe(e, i * 100 + 10));
  }
  check(!extreme.stationary_origin_ready());

  // Exercise both ordinary acquisition clocks and millis rollover.
  for (std::uint32_t base : {0U, 0xfffffec0U}) {
    WheelPoseIntegrator pose;
    check(pose.configure(calibration()));
    for (std::uint32_t i = 1; i <= 3; ++i) {
      auto e = observed(i, base + i * 100);
      e.imu_at_ms = e.wheel.left_ms - 20;
      check(pose.observe(e, e.wheel.right_ms));
    }
    check(pose.stationary_origin_ready());
    auto stale = pose;
    check(!stale.start_origin(base + 481));
    check(pose.start_origin(base + 480)); // exact oldest-source age limit
    pose.expire(base + 480);
    check(pose.state().origin == 1);
    pose.expire(base + 481);
    check(pose.state().origin == 0);
  }
}
static void refuse_future_wheel_acquisition() {
  // The older wheel and IMU can be fresh while the other wheel is
  // future-dated. Neither wheel ordering may create a stationary witness.
  for (std::uint32_t base : {0U, 0xffffff90U}) {
    for (bool reverse : {false, true}) {
      WheelPoseIntegrator pose;
      check(pose.configure(calibration()));
      auto e = observed(1, base + 100);
      if (reverse) {
        e.wheel.left_ms = base + 110;
        e.wheel.right_ms = base + 100;
      }
      check(!pose.observe(e, base + 105));
      check(!pose.stationary_origin_ready());
      // A rejected acquisition remains fenced even after time catches up.
      check(!pose.observe(e, base + 110));
      auto next = observed(2, base + 200);
      check(pose.observe(next, base + 210));
    }
  }
}

static void stationary_pairs_do_not_accumulate_translation_error() {
  WheelPoseIntegrator pose;
  auto c = calibration();
  c.max_xy_error_mm = 1;
  check(pose.configure(c));
  for (std::uint32_t i = 1; i <= 3; ++i)
    check(pose.observe(observed(i, i * 100), i * 100 + 10));
  check(pose.start_origin(310));
  for (std::uint32_t i = 4; i <= 1100; ++i) {
    auto e = observed(i, i * 100);
    // Increasing measured gyro uncertainty is not erased by zero travel.
    e.imu_error_urad = i * 10;
    check(pose.observe(e, i * 100 + 10));
    check(pose.state().origin == 1);
    check(pose.state().x_mm == 0 && pose.state().y_mm == 0);
    check(pose.state().xy_error_mm == 0);
  }
  check(pose.state().yaw_error_mrad == 12);
  // Actual translation must still consume the position error budget.
  check(pose.observe(observed(1101, 110100, 10, -10), 110110));
  check(pose.state().x_mm == 1 && pose.state().xy_error_mm > 0);
  // Opposite wheel travel still has wheel uncertainty without translation.
  WheelPoseIntegrator rotation;
  check(rotation.configure(c));
  for (std::uint32_t i = 1; i <= 3; ++i)
    check(rotation.observe(observed(i, i * 100), i * 100 + 10));
  check(rotation.start_origin(310));
  check(rotation.observe(observed(4, 400, -10, -10, 20000), 410));
  check(rotation.state().x_mm == 0 && rotation.state().y_mm == 0);
  check(rotation.state().yaw_mrad == 20 && rotation.state().xy_error_mm > 0);
}

int main() {
  stationary_pairs_do_not_accumulate_translation_error();
  refuse_future_wheel_acquisition();
  refuse_rotation_and_expired_imu_origin();
  refuse_unqualified_and_reanchor();
  refuse_skew_stale_and_replay();
}
