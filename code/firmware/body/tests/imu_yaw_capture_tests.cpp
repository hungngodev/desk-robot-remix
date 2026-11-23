#include "ImuYawCapture.h"
#include <cstdint>
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
int main() {
  yaw_and_replay();
  handling_and_calibration_faults();
  rollover_and_drift_latch();
}
