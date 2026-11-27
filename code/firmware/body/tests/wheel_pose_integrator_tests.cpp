#include "WheelPoseIntegrator.h"
#include <stdexcept>
#include <cstdint>
#include <initializer_list>
#include <limits>
#include <type_traits>

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

static void origin_quality_respects_heading_uncertainty() {
  using Quality = WheelPoseIntegrator::Quality;
  // Alignment contributes 1000 urad to the 500000 urad total limit.
  // Verify both inclusive boundaries and a one-unit excess.
  for (std::uint32_t error : {248999U, 249000U, 249001U, 499000U, 499001U}) {
    WheelPoseIntegrator pose;
    check(pose.configure(calibration()));
    for (std::uint32_t i = 1; i <= 4; ++i) {
      auto e = observed(i, i * 100);
      e.imu_error_urad = error;
      if (error > 499000U) {
        check(!pose.observe(e, i * 100 + 10));
        check(!pose.start_origin(i * 100 + 10));
        check(pose.state().quality == Quality::Unavailable);
        continue;
      }
      check(pose.observe(e, i * 100 + 10));
      if (i == 3) check(pose.start_origin(i * 100 + 10));
      if (i >= 3) {
        const auto expected = error > 249000U ? Quality::Degraded : Quality::Valid;
        check(pose.state().quality == expected);
        check(pose.state().origin == 1);
        check(pose.state().yaw_error_mrad == (error + 1999U) / 1000U);
      }
    }
  }
}

static void refuse_reused_wheel_acquisition() {
  for (bool left : {false, true}) {
    for (int fault = 0; fault < 4; ++fault) {
      WheelPoseIntegrator pose;
      check(pose.configure(calibration()));
      for (std::uint32_t i = 1; i <= 3; ++i)
        check(pose.observe(observed(i, 100 + i * 10), 120 + i * 10));
      check(pose.start_origin(150));
      auto e = observed(4, 140);
      auto& seq = left ? e.wheel.left_seq : e.wheel.right_seq;
      auto& ms = left ? e.wheel.left_ms : e.wheel.right_ms;
      if (fault == 0) --seq;
      if (fault == 1) seq -= 2;
      if (fault == 2) ms -= 10;
      if (fault == 3) ms -= 11;
      e.wheel.skew_ms = e.wheel.left_ms > e.wheel.right_ms
          ? e.wheel.left_ms - e.wheel.right_ms
          : e.wheel.right_ms - e.wheel.left_ms;
      check(!pose.observe(e, 160));
      check(pose.state().quality == WheelPoseIntegrator::Quality::Unavailable);
      // A newly numbered pair cannot reuse the last accepted leg after loss.
      e.wheel.pair_seq = 5;
      check(!pose.observe(e, 160));
      for (std::uint32_t i = 6; i <= 8; ++i)
        check(pose.observe(observed(i, 200 + i * 10), 220 + i * 10));
      check(pose.start_origin(300));
      check(pose.state().origin == 2);
    }
  }
  WheelPoseIntegrator wrap;
  check(wrap.configure(calibration()));
  auto a = observed(1, 0xfffffff0U);
  a.wheel.left_seq = a.wheel.right_seq = 0xffffffffU;
  check(wrap.observe(a, a.wheel.right_ms));
  auto b = observed(2, 0U);
  b.wheel.left_seq = b.wheel.right_seq = 1;
  check(wrap.observe(b, b.wheel.right_ms));
}

static void unhealthy_magnet_or_cached_wheel_revokes_pose() {
  using desk_robot::AngleRaw;
  using desk_robot::WheelAngleCapture;
  using desk_robot::WheelPairCapture;
  using PairResult = WheelPairCapture::Result;
  for (bool left_fault : {false, true}) {
    for (unsigned fault = 0; fault < 10; ++fault) {
      if (fault == 4) continue;  // 0x20 is the only healthy magnet state.
      WheelAngleCapture left, right;
      WheelPairCapture pair;
      WheelPoseIntegrator pose;
      check(left.configure(4000, 100, 50));
      check(right.configure(4000, 100, 50));
      check(pair.configure(10));
      check(pose.configure(calibration()));
      const auto raw = [](std::uint32_t seq, std::uint32_t ms) {
        AngleRaw a{};
        a.present = a.valid = true;
        a.magnet_status = 0x20;
        a.angle = 123;
        a.sample_seq = seq;
        a.at_ms = ms;
        return a;
      };
      const auto observe = [&](const AngleRaw& l, const AngleRaw& r,
                               std::uint32_t now) {
        const auto lr = left.observe(l, now);
        const auto rr = right.observe(r, now);
        return pair.observe(lr, rr, l, r, left.last_delta(),
                            right.last_delta(), now);
      };
      check(observe(raw(1, 100), raw(1, 100), 100) == PairResult::Waiting);
      for (std::uint32_t i = 2; i <= 4; ++i) {
        const auto a = raw(i, 100 + 10 * i);
        check(observe(a, a, a.at_ms) == PairResult::Paired);
        auto e = observed(i - 1, a.at_ms);
        e.wheel = pair.receipt();
        e.imu_at_ms = a.at_ms;
        check(pose.observe(e, a.at_ms));
      }
      check(pose.start_origin(140));
      check(observe(raw(4, 140), raw(4, 140), 141) == PairResult::Waiting);
      auto good = raw(5, 150);
      auto bad = good;
      std::uint32_t now = 150;
      if (fault < 8) bad.magnet_status = static_cast<std::uint8_t>(fault << 3);
      if (fault == 8) bad.present = bad.valid = false;
      if (fault == 9) {
        bad = raw(4, 140);
        now = 191;  // 51 ms old, just past the 50 ms capture age.
        good.at_ms = now;
      }
      check(observe(left_fault ? bad : good, left_fault ? good : bad, now) ==
            PairResult::Invalid);
      check(!pair.receipt().valid && !pair.ready_for_origin());
      auto e = observed(4, now);
      e.wheel = pair.receipt();
      check(!pose.observe(e, now));
      check(pose.state().quality == WheelPoseIntegrator::Quality::Unavailable);
      check(!pose.start_origin(now));
    }
  }
}

static void signed_heading_wrap_and_projection() {
  constexpr std::int64_t pi = 3141593;
  for (int direction : {-1, 1}) {
    WheelPoseIntegrator pose;
    check(pose.configure(calibration()));
    const auto before = direction * (pi - 100000);
    const auto after = -before;
    for (std::uint32_t i = 1; i <= 3; ++i)
      check(pose.observe(observed(i, i * 100, 0, 0, before), i * 100 + 10));
    check(pose.start_origin(310));
    // The measured gyro crosses its wrap boundary during a 200 mrad turn.
    check(pose.observe(observed(4, 400, -100 * direction, -100 * direction,
                                after), 410));
    check(pose.state().yaw_mrad == 200 * direction);
    check(pose.state().x_mm == 0 && pose.state().y_mm == 0);
    check(pose.observe(observed(5, 500, 200, -200, after), 510));
    check(pose.state().x_mm == 19 && pose.state().y_mm == 3 * direction);
    check(pose.observe(observed(6, 600, -200, 200, after), 610));
    check(pose.state().x_mm == 0 && pose.state().y_mm == 0);
    check(pose.state().origin == 1);

    // Continue rotating until the local (origin-relative) heading wraps too.
    for (std::uint32_t i = 7; i <= 21; ++i) {
      const auto yaw = after + direction * 200000LL * (i - 6);
      check(pose.observe(observed(i, i * 100, -100 * direction,
                                  -100 * direction, yaw), i * 100 + 10));
    }
    check(pose.state().yaw_mrad == -3083 * direction);
    check(pose.state().origin == 1);
    check(pose.state().x_mm == 0 && pose.state().y_mm == 0);
  }
}

static void invalid_geometry_cannot_enable_pose() {
  const auto reject = [](const WheelPoseIntegrator::Calibration& c) {
    WheelPoseIntegrator pose;
    check(!pose.configure(c));
    check(!pose.configured());
    for (std::uint32_t i = 1; i <= 3; ++i)
      check(!pose.observe(observed(i, i * 100), i * 100 + 10));
    check(!pose.stationary_origin_ready());
    check(!pose.start_origin(310));
    check(pose.state().origin == 0 &&
          pose.state().quality == WheelPoseIntegrator::Quality::Unavailable);
    check(pose.configure(calibration())); // failed configuration is not latched
  };
  for (std::int32_t scale : {std::numeric_limits<std::int32_t>::min(),
                             -1, 0, 1000001}) {
    auto c = calibration();
    c.left_nm_per_count = scale;
    reject(c);
    c = calibration();
    c.right_nm_per_count = scale;
    reject(c);
  }
  for (std::uint32_t width : {0U, 19U, 501U,
                              static_cast<std::uint32_t>(-1),
                              static_cast<std::uint32_t>(-2147483647 - 1)}) {
    auto c = calibration();
    c.track_width_mm = width;
    reject(c);
  }
  for (std::int32_t scale : {1, 1000000}) {
    auto c = calibration();
    c.left_nm_per_count = c.right_nm_per_count = scale;
    WheelPoseIntegrator pose;
    check(pose.configure(c));
  }
}

static void pivot_at_track_width_boundaries() {
  // Zero center translation is valid; the track width must remain positive.
  for (std::uint32_t width : {20U, 500U}) {
    for (int direction : {-1, 1}) {
      auto c = calibration();
      c.track_width_mm = width;
      WheelPoseIntegrator pose;
      check(pose.configure(c));
      for (std::uint32_t i = 1; i <= 3; ++i)
        check(pose.observe(observed(i, i * 100), i * 100 + 10));
      check(pose.start_origin(310));
      const std::int64_t yaw = direction * (2000000LL / width);
      check(pose.observe(observed(4, 400, -10 * direction, -10 * direction,
                                  yaw), 410));
      check(pose.state().quality == WheelPoseIntegrator::Quality::Valid);
      check(pose.state().x_mm == 0 && pose.state().y_mm == 0);
      check(pose.state().yaw_mrad == yaw / 1000);
      check(pose.state().origin == 1);
    }
  }
}

static void expired_origin_cannot_be_refreshed_by_late_pair() {
  for (std::uint32_t base : {0U, 0xfffffee0U}) {
    WheelPoseIntegrator pose;
    check(pose.configure(calibration()));
    for (std::uint32_t i = 1; i <= 3; ++i)
      check(pose.observe(observed(i, base + i * 100), base + i * 100 + 10));
    check(pose.start_origin(base + 310));
    auto boundary = pose;
    check(boundary.observe(observed(4, base + 490, 10, -10), base + 500));
    check(boundary.state().origin == 1);
    // A fresh receipt after the previous source expires cannot bridge an
    // unobserved interval, even if the caller missed the periodic expire().
    auto late = observed(4, base + 491, 10, -10);
    check(!pose.observe(late, base + 501));
    check(pose.state().quality == WheelPoseIntegrator::Quality::Unavailable);
    check(!pose.observe(late, base + 501));
    check(!pose.start_origin(base + 501));
    for (std::uint32_t i = 5; i <= 7; ++i)
      check(pose.observe(observed(i, base + i * 100 + 100), base + i * 100 + 110));
    check(pose.start_origin(base + 810));
    check(pose.state().origin == 2);
  }
}

static void asymmetric_motion_requires_gyro_agreement() {
  using Quality = WheelPoseIntegrator::Quality;
  for (bool left_moves : {false, true}) {
    WheelPoseIntegrator pose;
    check(pose.configure(calibration()));
    for (std::uint32_t i = 1; i <= 3; ++i)
      check(pose.observe(observed(i, i * 100), i * 100 + 10));
    check(pose.start_origin(310));
    auto turn = pose;
    auto sample = observed(4, 400, left_moves ? 60 : 0, left_moves ? 0 : -60);
    // One shaft moves six mm while the other remains stationary. A measured
    // 60 mrad turn is consistent; zero gyro rotation is not.
    check(!pose.observe(sample, 410));
    check(pose.state().quality == Quality::Unavailable);
    sample.imu_yaw_urad = left_moves ? -60000 : 60000;
    check(turn.observe(sample, 410));
    check(turn.state().quality == Quality::Valid && turn.state().origin == 1);
    check(turn.state().yaw_mrad == sample.imu_yaw_urad / 1000);
  }
}

static void signed_residual_boundaries_retire_pose() {
  using Quality = WheelPoseIntegrator::Quality;
  // Test both directions and both contradictory sources. A zero latest
  // gyro step must not hide a nonzero cumulative yaw change between pairs.
  for (int direction : {-1, 1}) {
    for (bool wheel_only : {false, true}) {
      for (int residual : {24999, 25000, 25001, 49999, 50000, 50001}) {
        WheelPoseIntegrator pose;
        check(pose.configure(calibration()));
        for (std::uint32_t i = 1; i <= 3; ++i)
          check(pose.observe(observed(i, i * 100), i * 100 + 10));
        check(pose.start_origin(310));
        check(pose.observe(observed(4, 400, 10, -10), 410));
        check(pose.state().x_mm == 1);
        // One count is 1000 urad of differential heading. Use a 50 mrad
        // encoder pivot and adjust gyro yaw for exact one-urad boundaries.
        const int ticks = wheel_only ? -25 * direction : 0;
        const auto yaw = direction * ((wheel_only ? 50000 : 0) - residual);
        auto e = observed(5, 500, ticks, ticks, yaw);
        const bool accepted = pose.observe(e, 510);
        check(accepted == (residual <= 50000));
        if (accepted) {
          check(pose.state().quality == (residual > 25000
                    ? Quality::Degraded : Quality::Valid));
          check(pose.state().origin == 1 && pose.state().sample_seq == 5);
        } else {
          check(pose.state().quality == Quality::Unavailable);
          check(pose.state().origin == 0 && pose.state().sample_seq == 0);
          check(!pose.observe(e, 510));
          check(!pose.start_origin(510));
        }
      }
    }
  }
}

static void exact_arc_and_reverse() {
  for (int turn : {-1, 1}) {
    for (int travel : {-1, 1}) {
      auto c = calibration();
      c.left_nm_per_count = c.right_nm_per_count = 1000000;
      c.track_width_mm = 20;
      c.max_pair_step_mm = 100;
      WheelPoseIntegrator pose;
      check(pose.configure(c));
      for (std::uint32_t i = 1; i <= 3; ++i)
        check(pose.observe(observed(i, i * 100), i * 100 + 10));
      check(pose.start_origin(310));
      const int left = travel * 40 - turn * 20;
      const int right = -(travel * 40 + turn * 20);
      check(pose.observe(observed(4, 400, left, right, turn * 2000000LL), 410));
      // Signed radius 20 mm, angle 2 rad: x=18.1859, y=28.3229 mm.
      check(pose.state().x_mm == travel * 18);
      check(pose.state().y_mm == travel * turn * 28);
      check(pose.state().yaw_mrad == turn * 2000);
      check(pose.state().origin == 1);
      check(pose.observe(observed(5, 500, -left, -right, 0), 510));
      check(pose.state().x_mm == 0 && pose.state().y_mm == 0);
      check(pose.state().yaw_mrad == 0 && pose.state().origin == 1);
    }
  }
}

static void tiny_signed_turns_accumulate() {
  for (int turn : {-1, 1}) {
    auto c = calibration();
    c.left_nm_per_count = turn > 0 ? 999999 : 1000000;
    c.right_nm_per_count = turn > 0 ? 1000000 : 999999;
    c.track_width_mm = 20;
    c.wheel_error_ppm = 1;
    c.imu_alignment_error_urad = 1;
    WheelPoseIntegrator pose;
    check(pose.configure(c));
    for (std::uint32_t i = 1; i <= 3; ++i)
      check(pose.observe(observed(i, i * 100), i * 100 + 10));
    check(pose.start_origin(310));
    for (std::uint32_t i = 4; i <= 2148; ++i) {
      auto e = observed(i, i * 100, 20, -20,
                        turn * static_cast<std::int64_t>(i - 3));
      e.imu_error_urad = 0;
      check(pose.observe(e, i * 100 + 10));
    }
    // 2145 arcs of 19.99999 mm and 1 urad each. Analytic endpoint
    // is (42899.94565, +/-46.01021) mm; truncating half-urad gives 45.
    check(pose.state().x_mm == 42899);
    check(pose.state().y_mm == turn * 46);
    check(pose.state().yaw_mrad == turn * 2 && pose.state().origin == 1);
  }
}

static void large_straight_pose_retires_at_coordinate_bound() {
  for (int travel : {-1, 1}) {
    auto c = calibration();
    c.left_nm_per_count = c.right_nm_per_count = 1000000;
    c.max_pair_step_mm = 100;
    c.wheel_error_ppm = 1;
    c.imu_alignment_error_urad = 1;
    WheelPoseIntegrator pose;
    check(pose.configure(c));
    for (std::uint32_t i = 1; i <= 3; ++i)
      check(pose.observe(observed(i, i * 100), i * 100 + 10));
    check(pose.start_origin(310));
    for (std::uint32_t i = 4; i <= 10004; ++i) {
      auto e = observed(i, i * 100, travel * 100, -travel * 100);
      e.imu_error_urad = 0;
      check(pose.observe(e, i * 100 + 10) == (i < 10004));
      if (i < 10004) {
        check(pose.state().x_mm == travel * static_cast<int>(i - 3) * 100);
        check(pose.state().y_mm == 0 && pose.state().yaw_mrad == 0);
        check(pose.state().origin == 1);
      }
    }
    check(pose.state().origin == 0);
    check(pose.state().quality == WheelPoseIntegrator::Quality::Unavailable);
  }
}

static void pivot_then_straight_at_new_heading() {
  for (int turn : {-1, 1}) {
    auto c = calibration();
    c.left_nm_per_count = c.right_nm_per_count = 1000000;
    c.track_width_mm = 20;
    WheelPoseIntegrator pose;
    check(pose.configure(c));
    for (std::uint32_t i = 1; i <= 3; ++i)
      check(pose.observe(observed(i, i * 100), i * 100 + 10));
    check(pose.start_origin(310));
    check(pose.observe(observed(4, 400, -10 * turn, -10 * turn,
                                 turn * 1000000LL), 410));
    check(pose.state().x_mm == 0 && pose.state().y_mm == 0);
    check(pose.state().yaw_mrad == turn * 1000);
    check(pose.observe(observed(5, 500, 20, -20, turn * 1000000LL), 510));
    check(pose.state().x_mm == 10 && pose.state().y_mm == turn * 16);
    check(pose.state().origin == 1);
  }
}

static void paired_step_limit_retires_moving_pose() {
  using Quality = WheelPoseIntegrator::Quality;
  // Equal physical travel keeps gyro agreement independent of the step limit.
  // With 100000 nm/count, 250 counts is exactly the 25 mm calibrated limit.
  for (int direction : {-1, 1}) {
    WheelPoseIntegrator pose;
    check(pose.configure(calibration()));
    for (std::uint32_t i = 1; i <= 3; ++i)
      check(pose.observe(observed(i, i * 100), i * 100 + 10));
    check(pose.start_origin(310));
    check(pose.observe(observed(4, 400, direction * 250, -direction * 250), 410));
    check(pose.state().x_mm == direction * 25 && pose.state().origin == 1);
    const auto excess = observed(5, 500, direction * 251, -direction * 251);
    check(!pose.observe(excess, 510));
    check(pose.state().quality == Quality::Unavailable && pose.state().origin == 0);
    check(pose.state().x_mm == 0 && pose.state().sample_seq == 0);
    check(!pose.observe(excess, 510));
    check(!pose.start_origin(510));
    for (std::uint32_t i = 6; i <= 8; ++i)
      check(pose.observe(observed(i, i * 100), i * 100 + 10));
    check(pose.start_origin(810));
    check(pose.state().origin == 2 && pose.state().x_mm == 0);
  }
}

static void shaft_delta_boundary_retires_moving_pose() {
  // A tiny scale keeps the physical travel bound from masking the raw limit.
  for (int direction : {-1, 1}) {
    for (bool left_fault : {false, true}) {
      auto c = calibration();
      c.left_nm_per_count = c.right_nm_per_count = 1000;
      WheelPoseIntegrator pose;
      check(pose.configure(c));
      for (std::uint32_t i = 1; i <= 3; ++i)
        check(pose.observe(observed(i, i * 100), i * 100 + 10));
      check(pose.start_origin(310));
      check(pose.observe(observed(4, 400, direction * 2047, -direction * 2047), 410));
      check(pose.state().x_mm == direction * 2);
      auto bad = observed(5, 500, direction * 2047, -direction * 2047);
      if (left_fault) bad.wheel.left_delta = direction * 2048;
      else bad.wheel.right_delta = -direction * 2048;
      check(!pose.observe(bad, 510));
      check(pose.state().quality == WheelPoseIntegrator::Quality::Unavailable);
      check(pose.state().origin == 0 && !pose.start_origin(510));
    }
  }
}

static void integer_encoder_evidence_contract() {
  // Nonfinite sensor values cannot enter the fixed-point API. Never cast
  // NaN to an integer to manufacture a reading: that conversion is undefined.
  static_assert(std::is_integral<decltype(desk_robot::AngleRaw::angle)>::value, "integral");
  static_assert(
      std::is_integral<decltype(desk_robot::WheelPairCapture::Receipt::left_delta)>::value,
      "integral");
  static_assert(
      std::is_integral<decltype(desk_robot::WheelPairCapture::Receipt::right_delta)>::value,
      "integral");
  static_assert(
      std::is_integral<decltype(WheelPoseIntegrator::Calibration::left_nm_per_count)>::value,
      "integral");
  static_assert(
      std::is_integral<decltype(WheelPoseIntegrator::Calibration::right_nm_per_count)>::value,
      "integral");
}

static void zero_elapsed_encoder_retires_paired_pose() {
  using desk_robot::AngleRaw;
  using desk_robot::WheelAngleCapture;
  using desk_robot::WheelPairCapture;
  using PairResult = WheelPairCapture::Result;
  for (bool left_fault : {false, true}) {
    for (std::uint32_t start : {100U, 0xffffffd8U}) {
      WheelAngleCapture left, right;
      WheelPairCapture pair;
      WheelPoseIntegrator pose;
      check(left.configure(4000, 100, 60));
      check(right.configure(4000, 100, 60));
      check(pair.configure(10));
      check(pose.configure(calibration()));
      const auto raw = [](std::uint32_t seq, std::uint32_t at) {
        AngleRaw a{};
        a.present = a.valid = true;
        a.angle = 100;
        a.magnet_status = 0x20;
        a.sample_seq = seq;
        a.at_ms = at;
        return a;
      };
      const auto capture = [&](AngleRaw l, AngleRaw r, std::uint32_t now) {
        const auto lr = left.observe(l, now);
        const auto rr = right.observe(r, now);
        return pair.observe(lr, rr, l, r, left.last_delta(), right.last_delta(), now);
      };
      check(capture(raw(1, start), raw(1, start), start) == PairResult::Waiting);
      for (std::uint32_t i = 2; i <= 4; ++i) {
        auto a = raw(i, start + i * 10);
        check(capture(a, a, a.at_ms) == PairResult::Paired);
        auto e = observed(i - 1, a.at_ms);
        e.wheel = pair.receipt();
        e.imu_at_ms = a.at_ms;
        check(pose.observe(e, a.at_ms));
      }
      check(pose.start_origin(start + 40));
      auto stale = raw(5, start + 40);
      auto fresh = raw(5, start + 45);
      check(capture(left_fault ? stale : fresh, left_fault ? fresh : stale,
                    fresh.at_ms) == PairResult::Invalid);
      check(!pair.receipt().valid && !pair.ready_for_origin());
      auto e = observed(4, fresh.at_ms);
      e.wheel = pair.receipt();
      e.imu_at_ms = fresh.at_ms;
      check(!pose.observe(e, fresh.at_ms));
      check(pose.state().quality == WheelPoseIntegrator::Quality::Unavailable);
      check(pose.state().origin == 0 && !pose.start_origin(fresh.at_ms));
    }
  }
}

int main() {
  zero_elapsed_encoder_retires_paired_pose();
  integer_encoder_evidence_contract();
  paired_step_limit_retires_moving_pose();
  shaft_delta_boundary_retires_moving_pose();
  exact_arc_and_reverse();
  tiny_signed_turns_accumulate();
  large_straight_pose_retires_at_coordinate_bound();
  pivot_then_straight_at_new_heading();
  signed_residual_boundaries_retire_pose();
  asymmetric_motion_requires_gyro_agreement();
  expired_origin_cannot_be_refreshed_by_late_pair();
  invalid_geometry_cannot_enable_pose();
  pivot_at_track_width_boundaries();
  signed_heading_wrap_and_projection();
  unhealthy_magnet_or_cached_wheel_revokes_pose();
  refuse_reused_wheel_acquisition();
  origin_quality_respects_heading_uncertainty();
  stationary_pairs_do_not_accumulate_translation_error();
  refuse_future_wheel_acquisition();
  refuse_rotation_and_expired_imu_origin();
  refuse_unqualified_and_reanchor();
  refuse_skew_stale_and_replay();
}
