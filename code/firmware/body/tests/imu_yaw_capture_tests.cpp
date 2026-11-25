#include "ImuYawCapture.h"
#include <cstdint>
#include <initializer_list>
#include <stdexcept>

using desk_robot::BerryModel;
using desk_robot::BerryReading;
using desk_robot::ImuYawCapture;
using Result = ImuYawCapture::Result;

static void check(bool ok) {
  if (!ok) throw std::runtime_error("MPU6050 yaw capture contract failed");
}
static ImuYawCapture::Calibration calibration(int sign = 1,
                                             std::uint32_t max_error = 500000) {
  ImuYawCapture::Calibration c{};
  c.axis = 2; c.sign = sign; c.bias_raw = 0;
  c.max_rate_raw = 500;
  c.bias_uncertainty_raw = 20;
  c.scale_error_ppm = 20000;
  c.accel_norm_min_raw = 12000;
  c.accel_norm_max_raw = 20000;
  c.temp_min_raw = -1000; c.temp_max_raw = 1000;
  c.max_gap_ms = 200; c.max_age_ms = 150;
  c.max_yaw_error_urad = max_error;
  return c;
}
static BerryReading sample(std::int16_t gyro, std::uint32_t time) {
  BerryReading r{};
  r.model = BerryModel::Mpu6050;
  r.valid = true;
  r.low_g_status_valid = true;
  r.accel[2] = 16384;
  r.gyro[2] = gyro;
  r.temperature_raw = 100;
  r.at_ms = time;
  return r;
}
static void yaw_and_replay() {
  ImuYawCapture cap;
  auto c = calibration();
  check(cap.observe(sample(131, 100), 100) == Result::Unqualified);
  c.axis = 3;
  check(!cap.configure(c));
  c = calibration();
  c.sign = 0;
  check(!cap.configure(c));
  check(cap.configure(calibration()));
  check(!cap.configure(calibration()));
  check(cap.observe(sample(131, 100), 100) == Result::Baseline);
  check(cap.observe(sample(131, 100), 110) == Result::Duplicate);
  check(cap.observe(sample(131, 200), 200) == Result::Delta);
  check(cap.last_delta_urad() == 1745);
  check(cap.yaw_urad() == 1745);
  check(cap.error_bound_urad() >= 300 &&
        cap.error_bound_urad() <= 310);
  check(cap.observe(sample(131, 300), 300) == Result::Delta);
  check(cap.yaw_urad() == 3490);
  check(!cap.fresh(500)); // stale receipt never becomes a new observation
  check(cap.observe(sample(131, 200), 500) == Result::Invalid);
  check(!cap.continuous() && cap.yaw_urad() == 0);
  check(cap.observe(sample(131, 350), 350) == Result::Baseline);
  check(cap.yaw_urad() == 0 && cap.segment() == 2);
  auto changed = sample(140, 350);
  check(cap.observe(changed, 350) == Result::Invalid);
  check(!cap.continuous());
}
static void handling_and_calibration_faults() {
  ImuYawCapture cap;
  check(cap.configure(calibration(-1)));
  check(cap.observe(sample(131, 100), 100) == Result::Baseline);
  check(cap.observe(sample(131, 200), 200) == Result::Delta);
  check(cap.yaw_urad() == -1745);
  auto low_g = sample(131, 300);
  low_g.low_g_irq = true;
  check(cap.observe(low_g, 300) == Result::Invalid);
  check(!cap.continuous());
  check(cap.observe(sample(131, 310), 310) == Result::Baseline);
  auto saturated = sample(32767, 320);
  check(cap.observe(saturated, 320) == Result::Invalid);
  auto no_irq_status = sample(131, 330);
  no_irq_status.low_g_status_valid = false;
  check(cap.observe(no_irq_status, 330) == Result::Invalid);
  auto invalid_temp = sample(131, 340);
  invalid_temp.temperature_raw = 1001;
  check(cap.observe(invalid_temp, 340) == Result::Invalid);
  auto invalid_accel = sample(131, 350);
  invalid_accel.accel[2] = 0;
  check(cap.observe(invalid_accel, 350) == Result::Invalid);
  check(cap.observe(sample(131, 360), 360) == Result::Baseline);
  check(cap.observe(sample(131, 570), 570) == Result::Invalid);
  check(cap.observe(sample(131, 580), 580) == Result::Baseline);
}
static void rollover_and_drift_latch() {
  ImuYawCapture wrap;
  check(wrap.configure(calibration()));
  check(wrap.observe(sample(131, 0xfffffff0U), 0xfffffff0U) ==
        Result::Baseline);
  check(wrap.observe(sample(131, 0), 0) == Result::Delta);
  check(wrap.last_delta_urad() >= 279 &&
        wrap.last_delta_urad() <= 280);
  check(wrap.observe(sample(131, 0x20), 0x20) == Result::Delta);

  ImuYawCapture drift;
  check(drift.configure(calibration(1, 500)));
  check(drift.observe(sample(131, 100), 100) == Result::Baseline);
  check(drift.observe(sample(131, 200), 200) == Result::Delta);
  check(drift.observe(sample(131, 300), 300) == Result::Invalid);
  check(drift.drift_latched() && !drift.continuous());
  check(drift.observe(sample(131, 400), 400) == Result::Invalid);
  drift.reset_for_boot();
  check(!drift.drift_latched());
  check(drift.observe(sample(131, 1), 1) == Result::Unqualified);
}
static void invalid_acquisition_fences_replay() {
  ImuYawCapture cap;
  check(cap.configure(calibration()));
  check(cap.observe(sample(131, 100), 100) == Result::Baseline);
  auto fault = sample(131, 200);
  fault.low_g_irq = true;
  check(cap.observe(fault, 200) == Result::Invalid);
  // A valid-looking delayed frame predating the fault cannot establish
  // a new segment; neither can a rewritten acquisition at the fault time.
  check(cap.observe(sample(131, 150), 200) == Result::Invalid);
  check(cap.observe(sample(131, 200), 200) == Result::Invalid);
  check(!cap.continuous() && cap.segment() == 1);
  check(cap.observe(sample(131, 201), 201) == Result::Baseline);
  check(cap.segment() == 2);

  ImuYawCapture wrap;
  check(wrap.configure(calibration()));
  check(wrap.observe(sample(131, 0xfffffff0U), 0xfffffff0U) ==
        Result::Baseline);
  fault = sample(131, 0x10U);
  fault.low_g_status_valid = false;
  check(wrap.observe(fault, 0x10U) == Result::Invalid);
  check(wrap.observe(sample(131, 0U), 0x10U) == Result::Invalid);
  check(wrap.observe(sample(131, 0x10U), 0x10U) == Result::Invalid);
  check(wrap.observe(sample(131, 0x11U), 0x11U) == Result::Baseline);
  // A future-dated frame is invalid but cannot advance the replay fence.
  check(wrap.observe(sample(131, 0x100U), 0x12U) == Result::Invalid);
  check(wrap.observe(sample(131, 0x13U), 0x13U) == Result::Baseline);
}

static void extreme_axes_and_stationary_bias() {
  const std::int16_t extremes[] = {-32768, -32767, 0, 32766, 32767};
  for (const auto x : extremes) {
    for (const auto y : extremes) {
      for (const auto z : extremes) {
        ImuYawCapture cap;
        check(cap.configure(calibration()));
        auto r = sample(0, 100);
        r.accel[0] = x; r.accel[1] = y; r.accel[2] = z;
        check(cap.observe(r, 100) == Result::Invalid);
      }
    }
  }
  for (const int sign : {-1, 1}) {
    ImuYawCapture cap;
    auto c = calibration(sign, 5000);
    c.bias_raw = 4096;
    check(cap.configure(c));
    check(cap.observe(sample(4096, 100), 100) == Result::Baseline);
    std::uint32_t previous_error = 0;
    for (std::uint32_t t = 150; t <= 1000; t += 50) {
      check(cap.observe(sample(4096, t), t) == Result::Delta);
      check(cap.yaw_urad() == 0 && cap.last_delta_urad() == 0);
      check(cap.error_bound_urad() > previous_error);
      previous_error = cap.error_bound_urad();
      check(cap.observe(sample(4096, t), t) == Result::Duplicate);
      check(cap.error_bound_urad() == previous_error);
    }
  }
}
// A clipped roll or pitch axis makes planar yaw evidence untrustworthy,
// even when the configured yaw channel and acceleration norm look quiet.
static void saturation_on_every_gyro_axis() {
  for (std::uint8_t yaw_axis = 0; yaw_axis < 3; ++yaw_axis) {
    for (std::uint8_t clipped_axis = 0; clipped_axis < 3; ++clipped_axis) {
      for (const std::int16_t rail : {-32768, 32767}) {
        ImuYawCapture cap;
        auto c = calibration();
        c.axis = yaw_axis;
        check(cap.configure(c));
        auto clipped = sample(0, 100);
        clipped.gyro[clipped_axis] = rail;
        check(cap.observe(clipped, 100) == Result::Invalid);
        check(!cap.continuous() && cap.segment() == 0);
        check(cap.observe(sample(0, 100), 100) == Result::Invalid);
        check(cap.observe(sample(0, 150), 150) == Result::Baseline);
        check(cap.observe(sample(0, 200), 200) == Result::Delta);
        clipped.at_ms = 250;
        check(cap.observe(clipped, 250) == Result::Invalid);
        check(!cap.fresh(250) && cap.last_delta_urad() == 0);
        check(cap.observe(sample(0, 250), 250) == Result::Invalid);
        check(cap.observe(sample(0, 300), 300) == Result::Baseline);
        check(cap.segment() == 2);
      }
    }
  }
}

int main() {
  saturation_on_every_gyro_axis();
  yaw_and_replay();
  handling_and_calibration_faults();
  rollover_and_drift_latch();
  invalid_acquisition_fences_replay();
  extreme_axes_and_stationary_bias();
}
