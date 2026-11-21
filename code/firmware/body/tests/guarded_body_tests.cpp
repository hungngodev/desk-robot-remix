#include "BodyControl.h"
#include "CliffGuard.h"
#include "StepperDrive.h"
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>

#define CHECK(expr) do { if (!(expr)) throw std::runtime_error(#expr); } while (false)

static std::string send(desk_robot::BodyControl& body, const std::string& line,
                        std::uint32_t now, bool local = false) {
  char reply[desk_robot::kReplyCapacity]{};
  body.execute(line.data(), line.size(), now, reply, sizeof(reply), local);
  return reply;
}

// Synthetic distances exercise policy only, not real table calibration.
static desk_robot::CliffConfig config() {
  desk_robot::CliffConfig c;
  c.calibrated = true;
  c.freshness_ms = 100;
  c.front_obstacle_mm = 30;
  c.front_max_mm = 1000;
  for (auto& interval : c.floor) { interval.min_mm = 40; interval.max_mm = 60; }
  return c;
}

static void fresh(desk_robot::CliffGuard& guard, std::uint32_t now) {
  for (std::uint8_t i = 0; i < 5; ++i)
    guard.sample(i, i < 4 ? 50 : 200, true, now);
}

static void unqualified_stepper_cutoff_never_claims_motion_ready() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 0);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.inhibit_unqualified_motor_cutoff();
  CHECK(send(body, "rearm", 0, true) == "OK rearm");
  const auto status = send(body, "status", 0);
  CHECK(status.find("\"ready\":false") != std::string::npos);
  CHECK(status.find("\"fault\":\"motor_cutoff_unqualified\"") !=
        std::string::npos);
  CHECK(send(body, "arm", 0) == "ERR arm motor_cutoff_unqualified");
  CHECK(send(body, "drive 30 30 200", 0) == "ERR drive disarmed");
  CHECK(!body.state().armed && !body.state().servos_attached &&
        body.state().left == 0 && body.state().right == 0);
  // A second recovery cannot clear a boot hardware qualification veto.
  fresh(guard, 1);
  CHECK(send(body, "rearm", 1, true) == "OK rearm");
  CHECK(send(body, "arm", 1) == "ERR arm motor_cutoff_unqualified");

  desk_robot::CliffGuard dc_guard;
  CHECK(dc_guard.configure(config()));
  fresh(dc_guard, 3);
  desk_robot::BodyControl dc(desk_robot::BodyProfile::DcGuarded, &dc_guard);
  dc.inhibit_unqualified_motor_cutoff();
  CHECK(send(dc, "rearm", 3, true) == "OK rearm");
  CHECK(send(dc, "status", 3).find("\"fault\":\"motor_cutoff_unqualified\"") !=
        std::string::npos);
  CHECK(send(dc, "status", 3).find("\"ready\":false") !=
        std::string::npos);
  CHECK(send(dc, "arm", 3) == "ERR arm motor_cutoff_unqualified");
  CHECK(!dc.state().armed && dc.state().left == 0 && dc.state().right == 0);

  // The ordinary guarded test fixture remains eligible for policy tests.
  desk_robot::CliffGuard qualified_guard;
  CHECK(qualified_guard.configure(config()));
  fresh(qualified_guard, 0);
  desk_robot::BodyControl qualified(desk_robot::BodyProfile::StepperGuarded,
                                    &qualified_guard);
  CHECK(send(qualified, "rearm", 0, true) == "OK rearm");
  CHECK(send(qualified, "arm", 0) == "OK arm");
}

static void cpu_heartbeat_fault_is_sticky_and_holds_gripper() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 0);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  CHECK(send(body, "rearm", 0, true) == "OK rearm");
  CHECK(send(body, "arm", 0) == "OK arm");
  CHECK(send(body, "drive 40 40 250", 0) ==
        "OK drive left=40 right=40 ms=250");
  send(body, "lift 120", 0);
  send(body, "grip 60", 0);
  body.tick(20);
  const auto grip = body.state().grip;
  const auto lift = body.state().lift;
  body.motor_watchdog_trip();
  CHECK(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0);
  CHECK(body.state().servos_attached && body.state().grip == grip &&
        body.state().lift == lift);
  CHECK(body.state().grip_target == grip && body.state().lift_target == lift);
  CHECK(send(body, "status", 20).find("motor_watchdog_latched") !=
        std::string::npos);
  CHECK(send(body, "arm", 20) == "ERR arm motor_watchdog_latched");
  CHECK(send(body, "rearm", 20) == "ERR rearm local_only");
  CHECK(send(body, "drive 20 20 100", 20) == "ERR drive disarmed");
  fresh(guard, 21);
  CHECK(send(body, "rearm", 21, true) == "OK rearm");
  CHECK(!body.state().armed && body.state().left == 0);
  CHECK(send(body, "status", 21).find("motor_watchdog_latched") ==
        std::string::npos);
  CHECK(send(body, "arm", 21) == "OK arm");
  CHECK(body.state().left == 0 && body.state().right == 0);
}

static void recovery_is_local_and_not_an_arm() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 0);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  // A job's automatic arm must not clear a fault using an older operator permit.
  CHECK(send(body, "arm", 0) == "ERR arm safety_interlock");
  CHECK(send(body, "rearm", 0) == "ERR rearm local_only");
  CHECK(send(body, "rearm", 0, true) == "OK rearm");
  CHECK(!body.state().armed && !body.state().servos_attached);
  CHECK(send(body, "arm", 0) == "OK arm");
  guard.sample(0, 1000, true, 1);
  body.tick(1);
  fresh(guard, 2);
  CHECK(send(body, "arm", 2) == "ERR arm safety_interlock");
  CHECK(send(body, "rearm", 2) == "ERR rearm local_only");
  CHECK(send(body, "rearm", 2, true) == "OK rearm");
  CHECK(!body.state().armed && body.state().left == 0);
}

static void usb_rearm_refuses_unsafe_physical_interlocks() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 100);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.sample_touch_input(true);
  CHECK(send(body, "rearm", 100, true) == "ERR rearm touch_active");
  CHECK(send(body, "arm", 100) == "ERR arm touch_active");
  body.sample_touch_input(false);
  body.sample_optional_inputs(1U, true, false, false);
  CHECK(send(body, "rearm", 100, true) == "ERR rearm bumper_active");
  body.sample_optional_inputs(1U, false, false, false);
  body.sample_optional_inputs(1U, false, false, false);
  body.sample_optional_inputs(1U, false, false, false);
  CHECK(send(body, "rearm", 100, true) == "OK rearm");
  CHECK(!body.state().armed);

  desk_robot::CliffGuard dock_guard;
  CHECK(dock_guard.configure(config()));
  fresh(dock_guard, 100);
  desk_robot::BodyControl dock(desk_robot::BodyProfile::StepperGuarded, &dock_guard);
  dock.require_dock_monitor(true);
  CHECK(send(dock, "rearm", 100, true) ==
        "ERR rearm dock_gpio_missing_or_stale");
  desk_robot::AccessoryReadings readings{};
  readings.dock.present = readings.dock.valid = true;
  readings.dock.left_seated = true;
  readings.dock.sample_seq = 1;
  readings.dock.at_ms = 100;
  dock.set_accessories(readings, 100);
  CHECK(send(dock, "rearm", 100, true) == "ERR rearm dock_power_connected");
  readings.dock.left_seated = false;
  readings.dock.sample_seq = 2;
  readings.dock.at_ms = 101;
  dock.set_accessories(readings, 101);
  CHECK(send(dock, "rearm", 101, true) == "OK rearm");
  CHECK(!dock.state().armed);

  desk_robot::CliffGuard imu_guard;
  CHECK(imu_guard.configure(config()));
  fresh(imu_guard, 100);
  desk_robot::BodyControl imu(desk_robot::BodyProfile::StepperGuarded, &imu_guard);
  imu.require_imu_for_motion(true);
  CHECK(send(imu, "rearm", 100, true) == "ERR rearm imu_missing_or_stale");
  CHECK(send(imu, "arm", 100) == "ERR arm safety_interlock");
}

static void receiver_recovery_authority_is_not_shared() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 0);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  desk_robot::LineReceiver usb(true), head;
  char reply[desk_robot::kReplyCapacity]{};
  for (char c : std::string("rearm\n")) head.feed(c, 0, body, reply, sizeof(reply));
  CHECK(std::string(reply) == "ERR rearm local_only");
  for (char c : std::string("rearm\n")) usb.feed(c, 0, body, reply, sizeof(reply));
  CHECK(std::string(reply) == "OK rearm");
  CHECK(!body.state().armed);
  send(body, "arm", 0);
  guard.bus_fault();
  body.tick(1);
  fresh(guard, 2);
  for (char c : std::string("arm\n")) head.feed(c, 2, body, reply, sizeof(reply));
  CHECK(std::string(reply) == "ERR arm safety_interlock");
  CHECK(!body.state().armed);
}

static void fault_holds_payload_and_requires_rearm() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 0);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  CHECK(send(body, "rearm", 0, true) == "OK rearm");
  CHECK(send(body, "arm", 0) == "OK arm");
  CHECK(send(body, "drive 40 -40 250", 0) == "OK drive left=40 right=-40 ms=250");
  send(body, "lift 120", 0);
  send(body, "grip 60", 0);
  body.tick(20);
  CHECK(body.state().lift == 91 && body.state().grip == 89);
  guard.sample(3, 500, true, 21);
  body.tick(21);
  CHECK(!body.state().armed && body.state().left == 0 && body.state().right == 0);
  CHECK(body.state().servos_attached);
  CHECK(body.state().lift == body.state().lift_target);
  CHECK(body.state().grip == body.state().grip_target);
  CHECK(body.state().lift == 91 && body.state().grip == 89);
  fresh(guard, 22);
  CHECK(send(body, "drive 40 40 250", 22) == "ERR drive disarmed");
  CHECK(send(body, "keepalive", 22) == "ERR keepalive disarmed");
  CHECK(send(body, "arm", 22) == "ERR arm safety_interlock");
  CHECK(send(body, "rearm", 22, true) == "OK rearm");
  CHECK(send(body, "arm", 22) == "OK arm");
  CHECK(body.state().left == 0 && body.state().right == 0);
  body.tick(40);
  CHECK(body.state().lift == 91 && body.state().grip == 89);
  send(body, "disarm", 40);
  CHECK(!body.state().servos_attached);
}

static void stale_read_stops_before_watchdog() {
  desk_robot::CliffGuard guard;
  guard.configure(config());
  fresh(guard, 0);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  send(body, "rearm", 0, true);
  send(body, "arm", 0);
  send(body, "drive 40 40 250", 0);
  body.tick(99);
  CHECK(body.state().left == 40);
  CHECK(body.watchdog_remaining(99) > 0);
  body.tick(101);
  CHECK(body.state().left == 0 && !body.state().armed);
  CHECK(guard.fault() == desk_robot::CliffFault::StaleSample);
  CHECK(body.state().servos_attached);
  CHECK(send(body, "arm", 101) == "ERR arm safety_interlock");
}

static void both_receivers_and_coils_respect_stop() {
  desk_robot::CliffGuard guard;
  guard.configure(config());
  fresh(guard, 0);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  desk_robot::LineReceiver usb, head;
  desk_robot::StepperDrive motor;
  send(body, "rearm", 0, true);
  send(body, "arm", 0);
  send(body, "drive 40 40 250", 0);
  std::uint8_t mask = 0;
  for (std::uint32_t ms = 0; ms < 50; ++ms) {
    body.tick(ms);
    mask = motor.update(ms * 1000, body.state().left, body.state().armed);
  }
  CHECK(mask != 0);
  guard.bus_fault();
  char reply[desk_robot::kReplyCapacity]{};
  for (const auto receiver : {&usb, &head}) {
    for (char c : std::string("drive 40 40 250\n"))
      receiver->feed(c, 50, body, reply, sizeof(reply));
    CHECK(std::string(reply) == "ERR drive disarmed");
  }
  CHECK(motor.update(50000, body.state().left, body.state().armed) == 0);
  fresh(guard, 51);
  CHECK(send(body, "status", 51).find("bus_failure") != std::string::npos);
  CHECK(!body.state().armed);
}

static void drive_expiry_stops_coils_even_with_keepalive() {
  desk_robot::CliffGuard guard;
  guard.configure(config());
  fresh(guard, 0);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  desk_robot::StepperDrive motor;
  send(body, "rearm", 0, true);
  send(body, "arm", 0);
  send(body, "drive 40 40 50", 0);
  // At t=0 the initial calibration sweep has already provided sensor
  // conversions. Replaying those same timestamps is now correctly rejected
  // as a duplicate, so only advance truly fresh sweeps from t=1 onward.
  for (std::uint32_t ms = 1; ms < 50; ++ms) {
    fresh(guard, ms);
    body.tick(ms);
    motor.update(ms * 1000, body.state().left, body.state().armed);
  }
  CHECK(motor.mask() != 0);
  send(body, "keepalive", 49);
  body.tick(50);
  CHECK(body.state().armed && body.state().left == 0);
  CHECK(motor.update(50000, body.state().left, body.state().armed) == 0);
}

static void measured_local_calibration_is_atomic_and_never_arms() {
  desk_robot::CliffGuard guard;
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  CHECK(send(body, "calfloor 0 40 60", 0) == "ERR calibration local_usb_only");
  CHECK(send(body, "calcommit", 0, true) == "ERR calcommit incomplete_stage");
  CHECK(send(body, "calfloor 4 40 60", 0, true).find("ERR calfloor") == 0);
  CHECK(send(body, "calfloor 0 60 40", 0, true).find("ERR calfloor") == 0);
  CHECK(send(body, "calfloor 0 1 15", 0, true).find("ERR calfloor") == 0);
  CHECK(send(body, "calfloor 0 29 60", 0, true).find("ERR calfloor") == 0);
  CHECK(send(body, "calfloor 0 30 1301", 0, true).find("ERR calfloor") == 0);
  CHECK(send(body, "calfront 1 100", 0, true).find("ERR calfront") == 0);
  CHECK(send(body, "calfront 29 100", 0, true).find("ERR calfront") == 0);
  CHECK(send(body, "calfront 30 1301", 0, true).find("ERR calfront") == 0);
  for (int i = 0; i < 4; ++i)
    CHECK(send(body, "calfloor " + std::to_string(i) + " 40 60", 0, true) ==
          "OK calfloor channel=" + std::to_string(i));
  CHECK(send(body, "calfront 30 1000", 0, true) == "OK calfront");
  CHECK(send(body, "calfresh 1000", 0, true).find("ERR calfresh") == 0);
  CHECK(send(body, "calfresh 100", 0, true) == "OK calfresh");
  CHECK(send(body, "calcommit", 0) == "ERR calibration local_usb_only");
  CHECK(!guard.configured());
  CHECK(send(body, "calcommit", 0, true) == "OK calcommit");
  CHECK(guard.configured());
  CHECK(guard.configuration().floor[0].min_mm == 40);
  CHECK(guard.configuration().front_obstacle_mm == 30);
  CHECK(guard.configuration().freshness_ms == 100);
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 1) == "ERR arm safety_interlock");
  fresh(guard, 2);
  CHECK(send(body, "rearm", 2) == "ERR rearm local_only");
  CHECK(send(body, "rearm", 2, true) == "OK rearm");
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 2) == "OK arm");
  CHECK(send(body, "calfloor 0 40 60", 3, true) ==
        "ERR calibration disarm_first");
  CHECK(send(body, "disarm", 3) == "OK disarm");
  CHECK(send(body, "calabort", 4, true) == "OK calabort");
  CHECK(send(body, "calcommit", 4, true) == "ERR calcommit incomplete_stage");
}

static void accessory_sensors_never_infer_grip_or_current_or_grant_arm() {
  desk_robot::CliffGuard guard;
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  desk_robot::AccessoryReadings readings{};
  readings.angle[0].present = true;
  readings.angle[0].valid = true;
  readings.angle[0].angle = 2000;
  readings.angle[0].magnet_status = 0x20;
  readings.angle[0].at_ms = 5;
  readings.force.present = true;
  readings.force.valid = true;
  readings.force.adc[0] = 123;
  readings.force.adc[1] = -456;
  readings.force.at_ms = 5;
  readings.gauge.fuel_present = true;
  readings.gauge.fuel_valid = true;
  readings.gauge.cell_mv = 3690;
  readings.gauge.soc_centi = 6400;
  readings.gauge.fuel_sample_seq = 1;
  readings.gauge.fuel_at_ms = 5;
  readings.gauge.at_ms = 5;
  readings.proximity.present = true;
  readings.proximity.valid = true;
  readings.proximity.raw = 90;
  readings.proximity.at_ms = 5;
  body.set_accessories(readings, 10);
  const std::string reply = send(body, "aux", 10);
  CHECK(reply.find("\"angles\":{\"raw\":[2000,0,0]") != std::string::npos);
  CHECK(reply.find("\"present_mask\":1,\"valid_mask\":1") != std::string::npos);
  CHECK(reply.find("\"adc\":[123,-456]") != std::string::npos);
  CHECK(reply.find("\"calibrated\":false") != std::string::npos);
  CHECK(reply.find("\"cell_mv\":3690") != std::string::npos);
  CHECK(reply.find("\"current_calibrated\":false") != std::string::npos);
  CHECK(reply.find("\"gesture\":0,\"gesture_events\":0,\"boot_id\":0") != std::string::npos);
  CHECK(send(body, "arm", 10) == "ERR arm safety_interlock");
  CHECK(!body.state().armed);
  const std::string stale = send(body, "aux", 400);
  CHECK(stale.find("\"valid_mask\":0") != std::string::npos);
}

static void independent_pack_sensor_freshness_never_crosses_devices() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded);
  desk_robot::AccessoryReadings readings{};
  auto& gauge = readings.gauge;
  gauge.fuel_present = gauge.fuel_valid = true;
  gauge.monitor_present = gauge.monitor_valid = true;
  gauge.cell_mv = 3720;
  gauge.soc_centi = 5700;
  gauge.fuel_sample_seq = 7;
  gauge.monitor_sample_seq = 8;
  gauge.fuel_at_ms = 10;
  gauge.monitor_at_ms = 700;
  gauge.at_ms = 700;  // Old shared timestamp incorrectly refreshed fuel.
  body.set_accessories(readings, 700);
  const auto only_monitor = send(body, "aux", 700);
  CHECK(only_monitor.find("\"fuel_valid\":false") != std::string::npos);
  CHECK(only_monitor.find("\"monitor_valid\":true") != std::string::npos);
  CHECK(only_monitor.find("\"current_calibrated\":false")
        != std::string::npos);

  gauge.fuel_at_ms = 701;
  gauge.fuel_sample_seq = 9;
  gauge.monitor_at_ms = 10;
  gauge.at_ms = 701;  // New fuel read must not refresh old shunt telemetry.
  body.set_accessories(readings, 701);
  const auto only_fuel = send(body, "aux", 701);
  CHECK(only_fuel.find("\"fuel_valid\":true") != std::string::npos);
  CHECK(only_fuel.find("\"monitor_valid\":false") != std::string::npos);

  gauge.fuel_sample_seq = 0;
  gauge.fuel_at_ms = 702;
  body.set_accessories(readings, 702);
  CHECK(send(body, "aux", 702).find("\"fuel_valid\":false")
        != std::string::npos);  // A timestamp with no completed read is not fresh.
}

static void optional_max30102_raw_never_authorizes_motion_or_diagnosis() {
  desk_robot::CliffGuard guard;
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  char response[desk_robot::kReplyCapacity]{};
  body.execute("aux", 3, 1, response, sizeof(response));
  CHECK(std::string(response).find("\"present\":false") != std::string::npos);
  CHECK(std::string(response).find("\"bpm\":null") != std::string::npos);
  desk_robot::OpticalRaw sample{};
  sample.present = true;
  sample.valid = true;
  sample.part_id = 0x15;
  sample.red = 11000;
  sample.ir = 55000;
  sample.at_ms = 100;
  sample.sample_seq = 18; // device FIFO sequence, never HTTP request number
  body.set_paw_pulse(sample);
  body.execute("aux", 3, 150, response, sizeof(response));
  CHECK(std::string(response).find("\"part_id\":21") != std::string::npos);
  CHECK(std::string(response).find("\"ir\":55000") != std::string::npos);
  CHECK(std::string(response).find("\"seq\":18,\"fifo_ir_first\":false,"
                                   "\"fifo_layout_physically_verified\":false,"
                                   "\"bpm\":null") != std::string::npos);
  CHECK(std::string(response).find("\"age_ms\":50") != std::string::npos);
  body.execute("aux", 3, 500, response, sizeof(response));
  CHECK(std::string(response).find("\"valid\":false") != std::string::npos);
  CHECK(send(body, "arm", 501) == "ERR arm safety_interlock");
  CHECK(!body.state().armed);
}

static void extra_three_ranging_channels_are_diagnostics_only() {
  desk_robot::CliffGuard guard;
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.set_boot_epoch(45);  // same per-boot source as the IMU status
  body.sample_side_range(0, 125, true, 10);
  body.sample_side_range(1, 0, false, 11);
  body.sample_side_range(2, 300, true, 12);
  body.sample_side_range(3, 150, true, 14); // invalid index ignored
  const std::string status = send(body, "status", 30);
  CHECK(status.find("\"side_ranges\":{") != std::string::npos);
  CHECK(status.find("\"mm\":[125,0,300]") != std::string::npos);
  CHECK(status.find("\"age_ms\":[20,19,18]") != std::string::npos);
  CHECK(status.find("\"sample_ms\":[10,11,12]") != std::string::npos);
  CHECK(status.find("\"boot_id\":45") != std::string::npos);
  CHECK(status.find("\"present_mask\":7,\"valid_mask\":5") != std::string::npos);
  CHECK(status.find("\"motion_certified\":false") != std::string::npos);
  // At 350ms source age a previously valid optional direction may still
  // be reported. After that, old physical data is only a raw diagnostic.
  const std::string borderline = send(body, "status", 360);
  CHECK(borderline.find("\"age_ms\":[350,349,348]") != std::string::npos);
  CHECK(borderline.find("\"present_mask\":7,\"valid_mask\":5") != std::string::npos);
  const std::string stale = send(body, "status", 363);
  CHECK(stale.find("\"age_ms\":[353,352,351]") != std::string::npos);
  CHECK(stale.find("\"present_mask\":7,\"valid_mask\":0") != std::string::npos);
  CHECK(stale.find("\"motion_certified\":false") != std::string::npos);
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 30) == "ERR arm safety_interlock");
}

static void side_range_validity_clears_on_shared_bus_fault_without_fake_samples() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.sample_side_range(0, 125, true, 10);
  body.sample_side_range(2, 300, true, 11);
  const auto observed = send(body, "status", 12);
  CHECK(observed.find("\"side_ranges\":{") != std::string::npos);
  CHECK(observed.find("\"present_mask\":5,\"valid_mask\":5") != std::string::npos);
  body.invalidate_side_ranges(); // called by WROOM only on new TofBus error
  const auto invalid = send(body, "status", 13);
  CHECK(invalid.find("\"mm\":[125,0,300]") != std::string::npos);
  CHECK(invalid.find("\"present_mask\":5,\"valid_mask\":0") != std::string::npos);
  CHECK(!body.state().armed);
  // Only a newly acquired independent side range can restore its validity.
  body.sample_side_range(0, 126, true, 14);
  const auto restored = send(body, "status", 15);
  CHECK(restored.find("\"present_mask\":5,\"valid_mask\":1") != std::string::npos);
  CHECK(!body.state().armed); // diagnostic input has no motor authority
}

static void cap_petting_zones_are_optional_and_never_arm() {
  desk_robot::CliffGuard guard;
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.set_cap(true, 1);
  CHECK(body.state().cap_valid);
  CHECK(body.state().cap_events == 0); // first sample is a baseline
  body.set_cap(true, 3);
  CHECK(body.state().cap_events == 1);
  body.set_cap(true, 3);
  CHECK(body.state().cap_events == 1);
  body.set_cap(true, 2);
  body.set_cap(true, 66);
  CHECK(body.state().cap_events == 2);
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 1) == "ERR arm safety_interlock");
  const auto status = send(body, "status", 1);
  CHECK(status.find("\"cap\":66") != std::string::npos);
  CHECK(status.find("\"cap_ok\":true") != std::string::npos);
  CHECK(status.find("\"cap_events\":2") != std::string::npos);
  body.set_cap(false, 0);
  CHECK(!body.state().cap_valid && body.state().cap_mask == 0);
  CHECK(send(body, "status", 2).find("\"cap_ok\":false") != std::string::npos);
}

static void touch_telemetry_never_grants_motion() {
  desk_robot::CliffGuard guard;
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  CHECK(!body.state().armed && body.state().touch_count == 0);
  body.set_touch(true);
  body.set_touch(true);
  CHECK(body.state().touch_count == 1 && body.state().touch_active);
  CHECK(send(body, "status", 0).find("\"touch\":{\"active\":true,\"count\":1,\"tap_count\":0") !=
        std::string::npos);
  CHECK(send(body, "arm", 0) == "ERR arm touch_active");
  body.set_touch(false);
  CHECK(!body.state().touch_active && body.state().touch_count == 1);
  body.set_touch(true);
  CHECK(body.state().touch_count == 2);
  CHECK(send(body, "status", 0).find("\"touch\":{\"active\":true,\"count\":2,\"tap_count\":0") !=
        std::string::npos);
  CHECK(!body.state().armed);
}

static void raw_touch_trip_preempts_debounce_without_forging_a_tap() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 0);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  CHECK(send(body, "rearm", 0, true) == "OK rearm");
  CHECK(send(body, "arm", 0) == "OK arm");
  CHECK(send(body, "drive 30 30 250", 0).find("OK drive") == 0);
  CHECK(send(body, "grip 110", 0) == "OK grip angle=110");
  body.tick(20);
  const int commanded_hold = body.state().grip;
  CHECK(body.state().left != 0 && body.state().armed);
  body.sample_touch_input(true);  // one raw GPIO high, gesture state still false
  CHECK(!body.state().armed && body.state().left == 0);
  CHECK(body.state().right == 0);
  CHECK(body.state().servos_attached);
  CHECK(body.state().grip == commanded_hold &&
        body.state().grip_target == commanded_hold);
  CHECK(!body.state().touch_active && body.state().touch_raw_active);
  CHECK(body.state().touch_count == 0);
  CHECK(send(body, "status", 21).find("\"touch\":{\"active\":true,\"count\":0") !=
        std::string::npos);
  CHECK(send(body, "arm", 21) == "ERR arm touch_active");
  CHECK(body.state().touch_taps == 0 && body.state().touch_holds == 0);
  CHECK(send(body, "keepalive", 21) == "ERR keepalive disarmed");
  CHECK(send(body, "drive 30 30 250", 21) == "ERR drive disarmed");
  // The later debounced edge records the touch exactly once but never arms.
  body.set_touch(true, 75);
  CHECK(body.state().touch_active && body.state().touch_count == 1);
  CHECK(!body.state().armed && body.state().left == 0);
  CHECK(send(body, "arm", 75) == "ERR arm touch_active");
  body.set_touch(false, 160);
  body.sample_touch_input(false);  // one raw low still requires explicit arm
  CHECK(!body.state().armed);
  CHECK(send(body, "keepalive", 160) == "ERR keepalive disarmed");
}

static void touch_is_local_human_stop_and_requires_fresh_arm() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 0);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  CHECK(send(body, "rearm", 0, true) == "OK rearm");
  CHECK(send(body, "arm", 0) == "OK arm");
  CHECK(send(body, "drive 20 20 250", 0).find("OK drive") == 0);
  CHECK(send(body, "grip 110", 0) == "OK grip angle=110");
  body.tick(20);
  const int held = body.state().grip;
  CHECK(body.state().left != 0 && body.state().armed);
  body.set_touch(true);
  CHECK(!body.state().armed && body.state().left == 0 && body.state().right == 0);
  CHECK(body.state().grip == held && body.state().grip_target == held);
  CHECK(body.state().servos_attached);  // no deliberate payload drop
  CHECK(send(body, "keepalive", 21) == "ERR keepalive disarmed");
  CHECK(send(body, "drive 20 20 250", 21) == "ERR drive disarmed");
  CHECK(send(body, "arm", 21) == "ERR arm touch_active");
  body.set_touch(true);
  CHECK(body.state().touch_count == 1);
  body.set_touch(false);
  CHECK(!body.state().armed);
  CHECK(send(body, "keepalive", 22) == "ERR keepalive disarmed");
  // A new explicit arm is still needed after releasing touch. No auto-resume.
  fresh(guard, 22);
  CHECK(send(body, "arm", 22) == "OK arm");
  CHECK(body.state().left == 0 && body.state().right == 0);
}

static void five_range_status_reports_real_samples_not_a_permission() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 1);
  CHECK(guard.try_rearm(1));  // guard is healthy, but body was never armed
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  auto value = send(body, "status", 10);
  CHECK(value.size() < desk_robot::kReplyCapacity - 1);
  CHECK(value.find("\"mm\":[50,50,50,50,200]") != std::string::npos);
  CHECK(value.find("\"age_ms\":[9,9,9,9,9]") != std::string::npos);
  CHECK(value.find("\"present_mask\":31,\"valid_mask\":31") != std::string::npos);
  CHECK(!body.state().armed);
  CHECK(guard.fault() == desk_robot::CliffFault::None);
  guard.sample(3, 1000, false, 11);
  value = send(body, "status", 12);
  CHECK(value.find("\"mm\":[50,50,50,1000,200]") != std::string::npos);
  CHECK(value.find("\"present_mask\":31,\"valid_mask\":23") != std::string::npos);
  CHECK(value.find("\"invalid_sample\"") != std::string::npos);
  CHECK(!body.state().armed);
  guard.bus_fault();
  value = send(body, "status", 13);
  CHECK(value.find("\"present_mask\":0,\"valid_mask\":0") != std::string::npos);
  CHECK(value.find("\"mm\":[0,0,0,0,0]") != std::string::npos);
  CHECK(!body.state().armed);
}

static void imu_identity_is_diagnostic_only() {
  desk_robot::CliffGuard guard;
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.set_imu_identity(1, 0xd4, 0x49);
  auto status = send(body, "status", 0);
  CHECK(status.find("\"imu\":{\"family\":1,\"gyro_id\":212,\"aux_id\":73,\"valid\":false") !=
        std::string::npos);
  CHECK(status.size() < desk_robot::kReplyCapacity - 1);
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 1) == "ERR arm safety_interlock");
  body.set_imu_identity(255, 0, 0);
  status = send(body, "status", 2);
  CHECK(status.find("\"imu\":{\"family\":0,\"gyro_id\":0,\"aux_id\":0,\"valid\":false") !=
        std::string::npos);
  CHECK(!body.state().armed);
}

static void imu_status_preserves_physical_conversion_and_boot_identity() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.set_boot_epoch(123456789U);
  desk_robot::BerryReading reading{};
  reading.model = desk_robot::BerryModel::Mpu6050;
  reading.valid = true;
  reading.at_ms = 70;
  body.set_imu(reading);
  const auto force_source = send(body, "aux", 80);
  CHECK(force_source.find(
      "\"jaw_seq\":0,\"boot_id\":123456789,\"jaw_age_ms\":0,\"valid\":false") !=
      std::string::npos);
  CHECK(force_source.size() < desk_robot::kReplyCapacity - 1);
  const auto result = send(body, "status", 80);
  CHECK(result.find("\"age_ms\":10,\"sample_ms\":70,\"boot_id\":123456789") !=
        std::string::npos);
  CHECK(result.size() < desk_robot::kReplyCapacity - 1);
  CHECK(!body.state().armed); // identity is diagnostic and never authorizes motion
}

static void mpu_native_low_g_irq_vetoes_local_wheels() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 100);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.require_imu_for_motion(true);
  body.set_imu_identity(4, 0x68, 0);
  desk_robot::BerryReading imu{};
  imu.model = desk_robot::BerryModel::Mpu6050;
  imu.valid = true;
  imu.accel[2] = 16384;
  imu.at_ms = 100;
  imu.low_g_status_valid = true;
  body.set_imu(imu);
  CHECK(send(body, "rearm", 100, true) == "OK rearm");
  CHECK(send(body, "arm", 100) == "OK arm");
  CHECK(send(body, "drive 20 20 200", 100).find("OK drive") == 0);
  imu.low_g_irq = true; // native interrupt, not an inferred fall or tilt
  imu.low_g_event_seq = 1;
  imu.at_ms = 101;
  body.set_imu(imu);
  fresh(guard, 101);
  body.tick(101);
  CHECK(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0 && body.state().servos_attached);
  // Native MPU FF_INT is a sticky local fault, not just a stale sample.
  // It must outrank generic IMU freshness until deliberate USB recovery.
  CHECK(send(body, "arm", 101) == "ERR arm imu_low_g_latched");
  const auto low_g_status = send(body, "status", 101);
  CHECK(low_g_status.find("\"fault\":\"imu_low_g_latched\"") != std::string::npos);
  CHECK(low_g_status.find("\"valid\":false") != std::string::npos);
  CHECK(low_g_status.find("\"low_g_valid\":true,\"low_g_irq\":true,\"low_g_seq\":1") !=
        std::string::npos); // report the veto event, not fabricated clearance
  imu.low_g_irq = false;
  imu.at_ms = 102;
  body.set_imu(imu);
  fresh(guard, 102);
  CHECK(!body.state().armed); // no automatic restart on interrupt clearance
  CHECK(send(body, "arm", 102) == "ERR arm imu_low_g_latched");
  CHECK(send(body, "rearm", 102) == "ERR rearm local_only");
  CHECK(send(body, "status", 102).find(
      "\"fault\":\"imu_low_g_latched\"") != std::string::npos);
  CHECK(send(body, "rearm", 102, true) == "OK rearm");
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 102) == "OK arm");
  CHECK(body.state().left == 0 && body.state().right == 0);
}

static void missing_mpu_interrupt_status_cannot_authorize_wheels() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 100);
  // Isolate IMU fault reporting from the intentionally higher priority
  // boot-time cliff latch. This does not arm the BodyControl itself.
  CHECK(guard.try_rearm(100));
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.require_imu_for_motion(true);
  body.set_imu_identity(4, 0x68, 0);
  desk_robot::BerryReading imu{};
  imu.model = desk_robot::BerryModel::Mpu6050;
  imu.valid = true;
  imu.accel[2] = 16384;
  imu.at_ms = 100;
  // A completed axis conversion plus a FAILED INT_STATUS read is not safe
  // motion evidence, even if the previous interrupt value appeared clear.
  body.set_imu(imu);
  CHECK(!body.imu_fresh(100));
  CHECK(send(body, "rearm", 100, true) == "ERR rearm imu_missing_or_stale");
  CHECK(send(body, "status", 100).find(
      "\"fault\":\"imu_low_g_status_unavailable\"") != std::string::npos);
  imu.low_g_status_valid = true;
  body.set_imu(imu);
  CHECK(send(body, "rearm", 100, true) == "OK rearm");
  CHECK(send(body, "arm", 100) == "OK arm");
  CHECK(send(body, "drive 20 20 200", 100).find("OK drive") == 0);
  imu.low_g_status_valid = false;  // intermittent I2C/clone failure
  imu.at_ms = 101;
  body.set_imu(imu);
  fresh(guard, 101);
  body.tick(101);
  CHECK(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0 && body.state().servos_attached);
  CHECK(send(body, "arm", 101) == "ERR arm imu_sensor_fault_latched");
  const auto status = send(body, "status", 101);
  CHECK(status.find("\"fault\":\"imu_sensor_fault_latched\"") != std::string::npos);
  CHECK(status.find("\"low_g_valid\":false,\"low_g_irq\":false") !=
        std::string::npos);
}

static void zero_acceleration_mpu_does_not_authorize_motion() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 100);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.require_imu_for_motion(true);
  body.set_imu_identity(4, 0x68, 0);
  desk_robot::BerryReading imu{};
  imu.model = desk_robot::BerryModel::Mpu6050;
  imu.valid = true;
  imu.low_g_status_valid = true;
  imu.at_ms = 100;
  body.set_imu(imu);
  CHECK(send(body, "rearm", 100, true) == "ERR rearm imu_missing_or_stale");
  CHECK(!body.imu_fresh(100));
  imu.accel[2] = 16384; // source-scale synthetic 1g, not physical calibration
  body.set_imu(imu);
  CHECK(send(body, "rearm", 100, true) == "OK rearm");
  CHECK(send(body, "arm", 100) == "OK arm");
  CHECK(send(body, "drive 20 20 200", 100).find("OK drive") == 0);
  CHECK(body.state().servos_attached);
  imu.accel[2] = 0;
  imu.at_ms = 101;
  body.set_imu(imu);
  fresh(guard, 101);
  body.tick(101);
  CHECK(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0 && body.state().servos_attached);
  CHECK(send(body, "arm", 101) == "ERR arm imu_sensor_fault_latched");
  CHECK(send(body, "status", 101).find("\"fault\":\"imu_sensor_fault_latched\"") != std::string::npos);
}

static void required_imu_is_a_local_freshness_interlock() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 50);
  CHECK(guard.try_rearm(50));
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.require_imu_for_motion(true);
  CHECK(send(body, "arm", 50) == "ERR arm imu_missing_or_stale");
  CHECK(!body.state().armed);
  desk_robot::BerryReading reading;
  reading.model = desk_robot::BerryModel::V1Lsm9ds0;
  reading.valid = true;
  reading.at_ms = 50;
  reading.accel[2] = 16384;  // synthetic raw 1g, not a physical orientation test
  body.set_imu(reading);
  // The reader is fresh but no startup WHO_AM_I identity was confirmed.
  CHECK(send(body, "arm", 50) == "ERR arm imu_missing_or_stale");
  body.set_imu_identity(2, 0x68, 0x3d);
  CHECK(send(body, "arm", 50) == "ERR arm imu_missing_or_stale");
  body.set_imu_identity(1, 0xd4, 0x00);
  CHECK(send(body, "arm", 50) == "ERR arm imu_missing_or_stale");
  body.set_imu_identity(1, 0xd4, 0x49);
  CHECK(send(body, "arm", 50) == "OK arm");
  CHECK(send(body, "drive 20 20 250", 50).find("OK drive") == 0);
  // Keep optical samples alive throughout the interval. CliffGuard
  // deliberately latches any missed 100ms deadline even if data later arrives.
  fresh(guard, 100);
  body.tick(100);
  fresh(guard, 150);
  body.tick(150);
  fresh(guard, 180);
  body.tick(180);
  CHECK(body.state().armed);
  CHECK(body.state().left != 0);
  fresh(guard, 230);
  body.tick(230);
  fresh(guard, 251);
  body.tick(251);  // stale IMU before the 500ms communication watchdog
  CHECK(!body.state().armed);
  CHECK(body.state().left == 0 && body.state().right == 0);
  CHECK(body.state().servos_attached);  // no deliberate drop of held object
  // The watchdog did not fire, but the live IMU safety fault is latched.
  // Status must explain why a remote command cannot resume movement.
  CHECK(send(body, "status", 251).find(
      "\"fault\":\"imu_sensor_fault_latched\"") != std::string::npos);
  // Identity changes and a fresh but invalid raw sample cannot clear the
  // latch or replace the required local USB recovery with an ordinary ARM.
  body.set_imu_identity(4, 0x68, 0);
  CHECK(send(body, "arm", 252) == "ERR arm imu_sensor_fault_latched");
  body.set_imu_identity(1, 0xd4, 0x49);
  CHECK(send(body, "arm", 252) == "ERR arm imu_sensor_fault_latched");
  reading.valid = false;
  reading.at_ms = 252;
  body.set_imu(reading);
  CHECK(send(body, "arm", 252) == "ERR arm imu_sensor_fault_latched");
  CHECK(send(body, "status", 252).find(
      "\"fault\":\"imu_sensor_fault_latched\"") != std::string::npos);
  reading.valid = true;
  body.set_imu(reading);
  CHECK(send(body, "arm", 252) == "ERR arm imu_sensor_fault_latched");
  CHECK(send(body, "status", 252).find(
      "\"fault\":\"imu_sensor_fault_latched\"") != std::string::npos);
  CHECK(send(body, "rearm", 252) == "ERR rearm local_only");
  CHECK(send(body, "rearm", 252, true) == "OK rearm");
  CHECK(send(body, "arm", 252) == "OK arm");
  CHECK(body.state().left == 0 && body.state().right == 0);
  // Unrecognized model cannot claim a valid raw sample.
  reading.model = desk_robot::BerryModel::Unknown;
  body.set_imu(reading);
  body.tick(253);
  CHECK(!body.state().armed);
}

static void touch_gesture_counters_survive_slow_status_polling() {
  desk_robot::BodyControl body;
  body.set_touch(true, 0);
  body.set_touch(false, 100);
  CHECK(body.state().touch_taps == 0);  // wait for possible second tap
  body.tick(451);
  CHECK(body.state().touch_taps == 1 && body.state().touch_double_taps == 0);

  body.set_touch(true, 1000);
  body.set_touch(false, 1090);
  body.set_touch(true, 1180);
  body.set_touch(false, 1280);
  body.tick(1750);
  CHECK(body.state().touch_double_taps == 1 && body.state().touch_taps == 1);

  body.set_touch(true, 2000);
  body.tick(2899);
  CHECK(body.state().touch_holds == 0);
  body.tick(2900);
  CHECK(body.state().touch_holds == 1);
  body.set_touch(false, 2950);
  CHECK(body.state().touch_holds == 1 && body.state().touch_taps == 1);

  // Unsigned elapsed arithmetic survives the 32-bit millis rollover.
  body.set_touch(true, 0xfffffff0U);
  body.set_touch(false, 0x00000040U);
  body.tick(0x000001a0U);
  CHECK(body.state().touch_taps == 2);
  CHECK(body.state().touch_count == 5);
  const auto status = send(body, "status", 0x000001a0U);
  CHECK(status.find("\"double_count\":1") != std::string::npos);
  CHECK(status.find("\"hold_count\":1") != std::string::npos);
}

static void real_dock_power_good_and_two_seat_switches_force_body_disarm() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  CHECK(send(body, "arm", 1) == "OK arm");
  CHECK(body.state().armed);
  desk_robot::AccessoryReadings read{};
  read.dock.present = true;
  read.dock.valid = true;
  read.dock.left_seated = true;
  read.dock.right_seated = true;
  read.dock.input_good = true; // actual MCP23017 and BQ PGOOD source
  read.dock.charge_indicated = false;
  read.dock.sample_seq = 1; // genuine completed GPIOA conversion
  read.dock.at_ms = 1;
  CHECK(send(body, "grip 60", 1) == "OK grip angle=60");
  CHECK(body.state().servos_attached);
  body.set_accessories(read, 1);
  CHECK(!body.state().armed);
  CHECK(body.state().servos_attached); // hold jaw PWM at contact
  CHECK(body.state().grip_target == body.state().grip);
  CHECK(send(body, "arm", 2) == "ERR arm dock_power_connected");
  read.dock.valid = false; // lost expander must not clear the contact latch
  body.set_accessories(read, 3);
  CHECK(send(body, "arm", 3) == "ERR arm dock_power_connected");
  read.dock.valid = true;
  read.dock.left_seated = false; // one switch not enough to clear
  body.set_accessories(read, 4);
  CHECK(send(body, "arm", 4) == "ERR arm dock_power_connected");
  read.dock.right_seated = false;
  read.dock.input_good = false;
  body.set_accessories(read, 5); // same cached acquisition, cannot clear
  CHECK(send(body, "arm", 5) == "ERR arm dock_power_connected");
  read.dock.sample_seq = 2; // independent completed GPIOA read
  read.dock.at_ms = 6;
  body.set_accessories(read, 6);
  CHECK(send(body, "arm", 7) == "OK arm");
  CHECK(body.state().armed);
  CHECK(send(body, "disarm", 8) == "OK disarm");
}


static void dock_removal_needs_new_fresh_real_gpio_sample() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.require_dock_monitor(true);
  desk_robot::AccessoryReadings r{};
  r.dock.present = r.dock.valid = true;
  r.dock.left_seated = true;
  r.dock.sample_seq = 7;
  r.dock.at_ms = 100;
  body.set_accessories(r, 101);
  CHECK(send(body, "arm", 102) == "ERR arm dock_power_connected");
  r.dock.left_seated = false;
  body.set_accessories(r, 103); // unchanged seq and timestamp
  CHECK(send(body, "arm", 104) == "ERR arm dock_power_connected");
  r.dock.sample_seq = 6;
  r.dock.at_ms = 105;  // reversed counter even with fresh time
  body.set_accessories(r, 106);
  CHECK(send(body, "arm", 107) == "ERR arm dock_power_connected");
  r.dock.sample_seq = 8;
  r.dock.at_ms = 100; // sequence advanced but timestamp did not
  body.set_accessories(r, 108);
  CHECK(send(body, "arm", 109) == "ERR arm dock_power_connected");
  r.dock.at_ms = 110;
  body.set_accessories(r, 610); // older than the 500ms safety window
  CHECK(send(body, "arm", 610) == "ERR arm dock_power_connected");
  r.dock.at_ms = 611;
  body.set_accessories(r, 612); // authentic newer complete read
  CHECK(!body.state().armed); // no automatic restart
  CHECK(send(body, "arm", 613) == "OK arm");
  CHECK(send(body, "disarm", 614) == "OK disarm");
}

static void dock_replayed_gpio_bits_do_not_preserve_arm_permission() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.require_dock_monitor(true);
  desk_robot::AccessoryReadings r{};
  r.dock.present = r.dock.valid = true;
  r.dock.sample_seq = 30;
  r.dock.at_ms = 50;
  body.set_accessories(r, 51);
  CHECK(send(body, "arm", 52) == "OK arm");
  CHECK(send(body, "drive 20 20 100", 53).find("OK drive") == 0);
  r.dock.left_seated = true; // same identity but changed bits is not a new read
  body.set_accessories(r, 54);
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 55) == "ERR arm dock_power_connected");
  r.dock.left_seated = false;
  body.set_accessories(r, 56);
  CHECK(send(body, "arm", 57) == "ERR arm dock_power_connected");
  r.dock.sample_seq = 31; // real new GPIOA conversion
  r.dock.at_ms = 58;
  body.set_accessories(r, 59);
  CHECK(!body.state().armed); // contact loss never automatically resumes
  CHECK(send(body, "arm", 60) == "OK arm");
  CHECK(send(body, "disarm", 61) == "OK disarm");

  // A forged changed record under the same acquisition cannot keep motors armed.
  r.dock.right_seated = true;
  body.set_accessories(r, 62);
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 63) == "ERR arm dock_power_connected");
}

static void inconsistent_dock_acquisition_requires_new_sample_to_recover() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.require_dock_monitor(true);
  desk_robot::AccessoryReadings r{};
  r.dock.present = r.dock.valid = true;
  r.dock.sample_seq = 12;
  r.dock.at_ms = 40;
  body.set_accessories(r, 41);
  CHECK(send(body, "arm", 42) == "OK arm");
  r.dock.charge_indicated = true;  // altered pin without GPIO read
  body.set_accessories(r, 43);
  // A forged identity must stop motors in the acquisition callback itself,
  // not only when a later command happens to call tick().
  CHECK(!body.state().armed);
  CHECK(body.state().left == 0 && body.state().right == 0);
  // An asserted CHG indication latches the motor-contact stop first;
  // malformed provenance does not clear it without a new GPIOA sample.
  CHECK(send(body, "arm", 44) == "ERR arm dock_power_connected");
  r.dock.charge_indicated = false; // replay of prior legitimate cache
  body.set_accessories(r, 45);
  CHECK(send(body, "arm", 46) == "ERR arm dock_power_connected");
  r.dock.sample_seq = 13;
  r.dock.at_ms = 47; // next true completed GPIOA acquisition
  body.set_accessories(r, 48);
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 49) == "OK arm");
  CHECK(send(body, "disarm", 50) == "OK disarm");
}

static void dock_charge_indication_alone_cannot_release_motion() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.require_dock_monitor(true);
  desk_robot::AccessoryReadings r{};
  r.dock.present = r.dock.valid = true;
  r.dock.sample_seq = 1;
  r.dock.at_ms = 100;
  body.set_accessories(r, 101);
  CHECK(send(body, "arm", 102) == "OK arm");
  CHECK(send(body, "drive 20 20 100", 103).find("OK drive") == 0);
  r.dock.charge_indicated = true; // CHG without PGOOD/seat is inconsistent
  r.dock.sample_seq = 2;
  r.dock.at_ms = 104;
  body.set_accessories(r, 105);
  CHECK(!body.state().armed);
  CHECK(body.state().left == 0 && body.state().right == 0);
  CHECK(send(body, "arm", 106) == "ERR arm dock_power_connected");
  r.dock.charge_indicated = false;
  r.dock.sample_seq = 3;
  r.dock.at_ms = 107;
  body.set_accessories(r, 108);
  CHECK(!body.state().armed); // no automatic motor rearm
  CHECK(send(body, "arm", 109) == "OK arm");
  CHECK(send(body, "disarm", 110) == "OK disarm");
}

static void dock_removal_accepts_genuine_uint32_wrap() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.require_dock_monitor(true);
  desk_robot::AccessoryReadings r{};
  r.dock.present = r.dock.valid = true;
  r.dock.right_seated = true;
  r.dock.sample_seq = 0xfffffffeU;
  r.dock.at_ms = 0xfffffff0U;
  body.set_accessories(r, 0xfffffff1U);
  CHECK(send(body, "arm", 0xfffffff2U) == "ERR arm dock_power_connected");
  r.dock.right_seated = false;
  r.dock.sample_seq = 1; // skip reserved 0 after wrap
  r.dock.at_ms = 4;
  body.set_accessories(r, 5);
  CHECK(send(body, "arm", 6) == "OK arm");
  CHECK(send(body, "disarm", 7) == "OK disarm");
}

static void complete_robot_requires_boot_installed_and_fresh_dock_expander() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.require_dock_monitor(true);  // only the full physical firmware boot sets this
  CHECK(send(body, "arm", 1) == "ERR arm dock_gpio_missing_or_stale");
  CHECK(!body.state().armed);
  desk_robot::AccessoryReadings read{};
  read.dock.present = true;
  read.dock.valid = false;
  body.set_accessories(read, 2);
  CHECK(send(body, "arm", 2) == "ERR arm dock_gpio_missing_or_stale");
  read.dock.valid = true;
  read.dock.sample_seq = 1;
  read.dock.at_ms = 3;
  body.set_accessories(read, 3);
  CHECK(send(body, "arm", 4) == "OK arm");
  CHECK(send(body, "drive 20 20 200", 5).find("OK drive") == 0);
  read.dock.present = false; // module disappeared, not an optional absence
  body.set_accessories(read, 5);
  CHECK(!body.state().armed);
  CHECK(body.state().left == 0 && body.state().right == 0);
  CHECK(send(body, "arm", 6) == "ERR arm dock_gpio_missing_or_stale");
  read.dock.present = true;
  read.dock.valid = true;
  read.dock.sample_seq = 2;
  read.dock.at_ms = 7;
  body.set_accessories(read, 7);
  CHECK(send(body, "arm", 8) == "OK arm");
  CHECK(send(body, "disarm", 9) == "OK disarm");
}

static void installed_dock_i2c_loss_or_single_seat_stops_local_motors() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  desk_robot::AccessoryReadings read{};
  read.dock.present = true;
  read.dock.valid = false; // installed but no successful GPIO conversion yet
  body.set_accessories(read, 1);
  CHECK(send(body, "arm", 1) == "ERR arm dock_gpio_missing_or_stale");
  read.dock.valid = true;
  read.dock.sample_seq = 1;
  read.dock.at_ms = 2;
  body.set_accessories(read, 2);
  CHECK(send(body, "arm", 3) == "OK arm");
  CHECK(body.state().servos_attached);
  CHECK(send(body, "drive 20 20 100", 4).find("OK drive") == 0);
  CHECK(body.state().left == 20 && body.state().right == 20);
  read.dock.valid = false; // missing I2C read during physical motion
  body.set_accessories(read, 5);
  CHECK(!body.state().armed);
  CHECK(body.state().left == 0 && body.state().right == 0);
  CHECK(body.state().servos_attached); // keep jaw PWM on sensor dropout
  CHECK(send(body, "arm", 5) == "ERR arm dock_gpio_missing_or_stale");
  read.dock.valid = true;
  read.dock.sample_seq = 2;
  read.dock.at_ms = 6;
  body.set_accessories(read, 6);
  CHECK(send(body, "arm", 7) == "OK arm"); // manual explicit rearm
  body.tick(507); // 501ms since last physical expander read
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 508) == "ERR arm dock_gpio_missing_or_stale");
  read.dock.sample_seq = 3;
  read.dock.at_ms = 509;
  body.set_accessories(read, 509);
  CHECK(send(body, "arm", 510) == "OK arm");
  read.dock.left_seated = true; // even one seat without powered PGOOD
  read.dock.sample_seq = 4;
  read.dock.at_ms = 511;
  body.set_accessories(read, 511);
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 512) == "ERR arm dock_power_connected");
  read.dock.left_seated = false;
  read.dock.sample_seq = 5;
  read.dock.at_ms = 513;
  body.set_accessories(read, 513); // both open + no PGOOD is an observed removal
  CHECK(!body.state().armed); // no resume merely because contacts cleared
  CHECK(send(body, "arm", 514) == "OK arm");
  CHECK(send(body, "disarm", 515) == "OK disarm");
}

static void dock_gpio_aux_sample_sequence_is_bounded_and_not_charging_proof() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  desk_robot::AccessoryReadings read{};
  read.dock.present = true;
  read.dock.valid = true;
  read.dock.left_seated = true;
  read.dock.right_seated = true;
  read.dock.input_good = true;
  read.dock.charge_indicated = true;
  read.dock.sample_seq = 123;
  read.dock.at_ms = 150;
  body.set_accessories(read, 150);
  const std::string aux = send(body, "aux", 200);
  CHECK(!aux.empty() && aux.front() == '{' && aux.back() == '}');
  CHECK(aux.size() < desk_robot::kReplyCapacity - 1);
  CHECK(aux.find("\"dock\":{\"present\":true,\"valid\":true")
        != std::string::npos);
  CHECK(aux.find("\"seq\":123,\"age_ms\":50,\"charging_verified\":false")
        != std::string::npos);
  CHECK(send(body, "arm", 201) == "ERR arm dock_power_connected");
  CHECK(!body.state().armed);
  // A now-old sample cannot be passed off as current.
  const std::string old = send(body, "aux", 800);
  CHECK(old.find("\"valid\":false") != std::string::npos);
  CHECK(old.find("\"seq\":123,\"age_ms\":650")
        != std::string::npos);
}

static void dual_ir_evidence_never_authorizes_body_motion_or_charging() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  desk_robot::IrPairEvidence sample{};
  sample.left_fresh = sample.right_fresh = sample.same_code = true;
  sample.left_seq = 9;
  sample.right_seq = 12;
  sample.left_age_ms = 15;
  sample.right_age_ms = 21;
  sample.code = 0xcb34ed12U;
  body.set_terminal_ir(sample);
  const std::string data = send(body, "ir", 100);
  CHECK(data.find("\"match\":true") != std::string::npos);
  CHECK(data.find("\"left_seq\":9") != std::string::npos);
  CHECK(data.find("\"right_seq\":12") != std::string::npos);
  CHECK(data.find("\"motor_authorized\":false") != std::string::npos);
  CHECK(data.find("\"charging_authorized\":false") != std::string::npos);
  CHECK(!body.state().armed);
  CHECK(body.state().left == 0 && body.state().right == 0);
  CHECK(send(body, "ir 1", 101) == "ERR ir bad_arguments");
  // Even a matched NEC code is never a local calibration or arm permit.
  CHECK(send(body, "drive 20 20 100", 102) != "OK drive left=20 right=20 ms=100");
  sample.left_fresh = sample.same_code = false;
  sample.code = 0;
  body.set_terminal_ir(sample);
  CHECK(send(body, "ir", 103).find("\"match\":false") != std::string::npos);
}

static void belly_adc_does_not_refresh_stale_jaw_sample() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.set_boot_epoch(123U);
  desk_robot::AccessoryReadings readings{};
  readings.force.present = readings.force.valid = true;
  readings.force.valid_mask = 3U;
  readings.force.adc[0] = 111;
  readings.force.adc[1] = 555;
  readings.force.jaw_sample_seq = 4U;
  readings.force.jaw_at_ms = readings.force.at_ms = 100U;
  body.set_accessories(readings, 100U);
  CHECK(send(body, "aux", 120U).find(
      "\"jaw_seq\":4,\"boot_id\":123,\"jaw_age_ms\":20,\"valid\":true")
        != std::string::npos);
  readings.force.at_ms = 700U;  // only the belly conversion advanced
  body.set_accessories(readings, 700U);
  CHECK(send(body, "aux", 700U).find(
      "\"jaw_seq\":4,\"boot_id\":123,\"jaw_age_ms\":600,\"valid\":false")
        != std::string::npos);
  readings.force.jaw_sample_seq = 5U;
  readings.force.jaw_at_ms = 701U;
  body.set_accessories(readings, 701U);
  CHECK(send(body, "aux", 702U).find(
      "\"jaw_seq\":5,\"boot_id\":123,\"jaw_age_ms\":1,\"valid\":true")
        != std::string::npos);
  // Electrical clipping remains visible as raw ADC diagnostics but cannot
  // masquerade as usable force evidence for any Mac consumer.
  for (const int endpoint : {-32768, 32767}) {
    readings.force.adc[1] = static_cast<std::int16_t>(endpoint);
    readings.force.jaw_sample_seq += 1U;
    readings.force.jaw_at_ms = readings.force.at_ms = 703U;
    body.set_accessories(readings, 703U);
    const auto clipped = send(body, "aux", 704U);
    CHECK(clipped.find(
        "\"jaw_age_ms\":1,\"valid\":false,\"calibrated\":false")
          != std::string::npos);
    CHECK(clipped.find(std::string(",") + std::to_string(endpoint) + "]") !=
          std::string::npos);
  }
  CHECK(!body.state().armed);
}

static void gripper_jaw_consumes_at_most_four_degrees_per_adc_conversion() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.require_grip_feedback(true);
  CHECK(body.configure_jaw_force_limits({60, 120, 1000, 1, 300}));
  CHECK(send(body, "arm", 100) == "OK arm");
  desk_robot::AccessoryReadings r{};
  r.force.present = r.force.valid = true;
  r.force.valid_mask = 2U; // only channel 1 is a jaw sample
  r.force.adc[1] = 1000;
  r.force.jaw_sample_seq = 1U;
  r.force.at_ms = r.force.jaw_at_ms = 100U;
  body.set_accessories(r, 100U);
  CHECK(send(body, "grip 120", 100) == "OK grip angle=120");
  body.tick(180); // nine timer intervals cannot consume nine jaw degrees
  CHECK(body.state().grip == 94 && body.state().grip_target == 120);
  body.tick(260);
  CHECK(body.state().grip == 94 && body.state().servos_attached);

  // A duplicate jaw sequence with a forged recent timestamp cannot buy
  // another step. A new belly conversion cannot buy one either.
  r.force.at_ms = r.force.jaw_at_ms = 261U;
  body.set_accessories(r, 261U);
  body.tick(280);
  CHECK(body.state().grip == 94);
  r.force.jaw_sample_seq = 2U;
  r.force.at_ms = r.force.jaw_at_ms = 281U;
  body.set_accessories(r, 281U);
  body.tick(380); // five actual servo intervals, only four jaw degrees
  CHECK(body.state().grip == 98);
  r.force.jaw_sample_seq = 1U; // backwards replay is rejected
  r.force.at_ms = r.force.jaw_at_ms = 381U;
  body.set_accessories(r, 381U);
  body.tick(400);
  CHECK(body.state().grip == 98 && body.state().grip_target == 98);
  r.force.jaw_sample_seq = 3U;
  r.force.at_ms = r.force.jaw_at_ms = 401U;
  body.set_accessories(r, 401U);
  CHECK(send(body, "grip 120", 401) == "OK grip angle=120");
  body.tick(480);
  CHECK(body.state().grip == 102 && body.state().grip_target == 120);

  // A regressed conversion while a four-degree allowance is only partly
  // used revokes even its remaining credit and cancels the pending target.
  r.force.jaw_sample_seq = 4U;
  r.force.at_ms = r.force.jaw_at_ms = 481U;
  body.set_accessories(r, 481U);
  CHECK(send(body, "grip 120", 481) == "OK grip angle=120");
  body.tick(500);
  CHECK(body.state().grip == 103 && body.state().grip_target == 120);
  r.force.jaw_sample_seq = 3U;
  r.force.at_ms = r.force.jaw_at_ms = 501U;
  body.set_accessories(r, 501U);
  body.tick(520);
  CHECK(body.state().grip == 103 && body.state().grip_target == 103);

  // A failed jaw conversion freezes the commanded target and retains PWM.
  r.force.valid = false;
  body.set_accessories(r, 521U);
  body.tick(540);
  CHECK(body.state().grip == 103 && body.state().grip_target == 103);
  CHECK(body.state().servos_attached);
}

static void physical_gripper_stops_ramping_when_adc_is_not_trustworthy() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.require_grip_feedback(true);
  CHECK(body.configure_jaw_force_limits({120, 60, 1000, 1, 300}));
  CHECK(send(body, "arm", 100) == "OK arm");
  CHECK(send(body, "grip 60", 100) == "ERR grip force_missing_or_stale");
  desk_robot::AccessoryReadings readings{};
  readings.force.present = readings.force.valid = true;
  readings.force.valid_mask = 3U;
  readings.force.jaw_sample_seq = 1U;
  readings.force.at_ms = readings.force.jaw_at_ms = 100U;
  readings.force.adc[1] = 1000;
  body.set_accessories(readings, 100U);
  CHECK(send(body, "grip 60", 100) == "OK grip angle=60");
  body.tick(120);
  CHECK(body.state().grip == 89 && body.state().grip_target == 60);
  // A failed conversion during a pending jaw motion must freeze locally,
  // even with no corrective Mac callback arriving on the head UART.
  readings.force.valid = false;
  body.set_accessories(readings, 121U);
  body.tick(140U);
  CHECK(body.state().grip == 89 && body.state().grip_target == 89);
  CHECK(body.state().armed && body.state().servos_attached);
  CHECK(send(body, "grip 60", 140U) == "ERR grip force_missing_or_stale");
  readings.force.valid = true;
  readings.force.jaw_sample_seq = 2U;
  readings.force.at_ms = readings.force.jaw_at_ms = 141U;
  body.set_accessories(readings, 141U);
  CHECK(send(body, "grip 60", 141U) == "OK grip angle=60");
  for (int endpoint : {-32768, 32767}) {
    readings.force.adc[1] = static_cast<std::int16_t>(endpoint);
    ++readings.force.jaw_sample_seq;
    readings.force.at_ms = readings.force.jaw_at_ms = 142U;
    body.set_accessories(readings, 142U);
    body.tick(142U);
    CHECK(body.state().grip == 89 && body.state().grip_target == 89);
    CHECK(send(body, "grip 60", 142U) == "ERR grip force_missing_or_stale");
  }
}

static void jaw_force_ceiling_is_local_and_direction_aware() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.require_grip_feedback(true);
  CHECK(!body.configure_jaw_force_limits({90, 90, 1000, 1, 300}));
  CHECK(!body.configure_jaw_force_limits({60, 120, 1000, 0, 300}));
  CHECK(!body.configure_jaw_force_limits({60, 120, 32767, 1, 300}));
  CHECK(!body.configure_jaw_force_limits({60, 120, 1000, 1, 32000}));
  CHECK(send(body, "arm", 100) == "OK arm");

  desk_robot::AccessoryReadings r{};
  r.force.present = r.force.valid = true;
  r.force.valid_mask = 2U;
  r.force.adc[1] = 1000;
  r.force.jaw_sample_seq = 1U;
  r.force.at_ms = r.force.jaw_at_ms = 100U;
  body.set_accessories(r, 100);
  CHECK(send(body, "grip 120", 100) == "ERR grip local_force_limits_missing");
  CHECK(body.state().grip == 90 && body.state().grip_target == 90);
  CHECK(!body.configure_jaw_force_limits({60, 120, 1000, 1, 300}));
  CHECK(send(body, "disarm", 100) == "OK disarm");
  CHECK(body.configure_jaw_force_limits({70, 120, 1000, 1, 300}));
  CHECK(!body.configure_jaw_force_limits({120, 60, 1000, 1, 300}));
  CHECK(send(body, "arm", 100) == "OK arm");
  // The generic servo parser rejects angles outside 60..120 first.
  // 69 is globally valid but outside this specific mounted jaw's
  // measured 70..120 travel, so it exercises the local endstop guard.
  CHECK(send(body, "grip 69", 100) == "ERR grip outside_measured_endstops");
  CHECK(send(body, "grip 120", 100) == "OK grip angle=120");
  body.tick(180);
  CHECK(body.state().grip == 94);

  // Overloaded sample arrives while the remote controller is stalled.
  r.force.adc[1] = 1300;
  r.force.jaw_sample_seq = 2U;
  r.force.at_ms = r.force.jaw_at_ms = 181U;
  body.set_accessories(r, 181);
  body.tick(200);
  CHECK(body.state().grip == 94 && body.state().grip_target == 94);
  CHECK(send(body, "grip 120", 200) ==
        "ERR grip local_force_limit_or_reversal");
  // Opening away from measured closed angle is a safe bounded relief path.
  CHECK(send(body, "grip 90", 200) == "OK grip angle=90");
  body.tick(220);
  CHECK(body.state().grip == 93);

  // Large polarity reversal is not permission to squeeze harder.
  r.force.adc[1] = 700;
  r.force.jaw_sample_seq = 3U;
  r.force.at_ms = r.force.jaw_at_ms = 221U;
  body.set_accessories(r, 221);
  CHECK(send(body, "grip 120", 221) ==
        "ERR grip local_force_limit_or_reversal");
  CHECK(send(body, "grip 90", 221) == "OK grip angle=90");
  r.force.adc[1] = 32767; // clipped ADC revokes all movement credit
  r.force.jaw_sample_seq = 4U;
  r.force.at_ms = r.force.jaw_at_ms = 222U;
  body.set_accessories(r, 222);
  body.tick(240);
  CHECK(body.state().grip_target == body.state().grip);
  CHECK(send(body, "grip 120", 240) == "ERR grip force_missing_or_stale");
  CHECK(body.state().servos_attached);
}

static void optional_nfc_and_fresh_ambient_fit_existing_bounded_aux_contract() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  desk_robot::AccessoryReadings readings{};
  readings.nfc.present = readings.nfc.valid = readings.nfc.tag_visible = true;
  readings.nfc.uid_length = 4;
  readings.nfc.tag_token = 0x12345678U;
  readings.nfc.tag_events = 3;
  readings.nfc.scan_seq = 17;
  readings.nfc.at_ms = 100;
  readings.climate.present = readings.climate.valid = true;
  readings.climate.temp_centi = 2200;
  readings.climate.humidity_centi = 4850;
  readings.climate.sample_seq = 10;
  readings.climate.at_ms = 95;
  readings.barometer.present = readings.barometer.valid = true;
  readings.barometer.chip_id = 0x58;
  readings.barometer.temp_centi = 2400;
  readings.barometer.pressure_pa = 100653;
  readings.barometer.sample_seq = 5;  // real successful compensated acquisition
  readings.barometer.at_ms = 95;
  body.set_accessories(readings, 120);
  desk_robot::OpticalRaw paw{};
  paw.present = paw.valid = true;
  paw.part_id = 0x15;
  paw.red = 24000;
  paw.ir = 33000;
  paw.at_ms = 100;
  paw.sample_seq = 8;
  body.set_paw_pulse(paw);
  const auto aux = send(body, "aux", 120);
  CHECK(!aux.empty() && aux.front() == '{' && aux.back() == '}');
  CHECK(aux.size() < desk_robot::kReplyCapacity - 1);
  CHECK(aux.find("\"seq\":8,\"fifo_ir_first\":false,"
                 "\"fifo_layout_physically_verified\":false,"
                 "\"bpm\":null") != std::string::npos);
  CHECK(aux.find("\"valid\":true,\"seq\":10,\"age_ms\":25")
        != std::string::npos);
  CHECK(aux.find("\"nfc\":{\"v\":true,\"t\":305419896,\"e\":3,\"s\":17}")
        != std::string::npos);
  CHECK(aux.find("\"pressure_pa\":100653,\"seq\":5,\"age_ms\":25") != std::string::npos);
  // Optional pressure is read-only; it cannot approve movement or charge. It cannot arm a physical guard.
  CHECK(send(body, "disarm", 121) == "OK disarm");
  readings.nfc.valid = false;
  body.set_accessories(readings, 125);
  const auto stale = send(body, "aux", 125);
  CHECK(stale.find("\"nfc\":{\"v\":false,\"t\":0,\"e\":3,\"s\":17}")
        != std::string::npos);
}


static void raw_bumper_trip_preempts_debounce_and_preserves_payload() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 0);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.sample_optional_inputs(1U, false, false, false); // event baseline
  CHECK(send(body, "rearm", 0, true) == "OK rearm");
  CHECK(send(body, "arm", 0) == "OK arm");
  CHECK(send(body, "drive 30 30 250", 0).find("OK drive") == 0);
  CHECK(send(body, "grip 110", 0) == "OK grip angle=110");
  body.tick(20);
  const int held_grip = body.state().grip;
  body.sample_bumper_input(true); // first raw GPIO read, before 25 ms classifier
  CHECK(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0);
  CHECK(body.state().servos_attached &&
        body.state().grip == held_grip &&
        body.state().grip_target == held_grip);
  CHECK(body.state().bumper_raw && !body.state().bumper_active &&
        body.state().bumper_events == 0);
  CHECK(send(body, "arm", 21) == "ERR arm bumper_latched");
  body.sample_bumper_input(false);
  CHECK(!body.state().armed); // no automatic travel after the contact clears
  CHECK(send(body, "arm", 22) == "ERR arm bumper_latched");
  CHECK(send(body, "status", 22).find("\"fault\":\"bumper_latched\"") !=
        std::string::npos);
  CHECK(send(body, "status", 22).find("\"ready\":false") !=
        std::string::npos);
  CHECK(send(body, "rearm", 22) == "ERR rearm local_only");
  CHECK(send(body, "rearm", 22, true) == "OK rearm");
  CHECK(send(body, "arm", 22) == "OK arm");
  CHECK(body.state().left == 0 && body.state().right == 0);

  // The raw local interlock must also work before the first 25 ms
  // classifier sample sets the optional-input mask after boot.
  desk_robot::BodyControl startup(desk_robot::BodyProfile::DcPwm);
  startup.sample_bumper_input(true);
  CHECK(send(startup, "arm", 0) == "ERR arm bumper_active");
}

static void accessory_reconnect_does_not_invent_petting_events() {
  // A reed hat switch or PIR can stay HIGH while its MCP23017 transport
  // disappears. Recovered data is an initial state, not a new physical tap.
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.sample_optional_inputs(6U, false, true, true); // high at boot
  CHECK(body.state().reed_events == 0 && body.state().pir_events == 0);
  for (int i = 0; i < 3; ++i)
    body.sample_optional_inputs(6U, false, false, false);
  for (int i = 0; i < 3; ++i)
    body.sample_optional_inputs(6U, false, true, true);
  CHECK(body.state().reed_events == 1 && body.state().pir_events == 1);
  body.sample_optional_inputs(0U, false, false, false); // expander read expired
  CHECK(body.state().extra_mask == 0U);
  body.sample_optional_inputs(6U, false, true, true); // same physical HIGH
  CHECK(body.state().reed_active && body.state().pir_active);
  CHECK(body.state().reed_events == 1 && body.state().pir_events == 1);
  for (int i = 0; i < 3; ++i)
    body.sample_optional_inputs(6U, false, true, true);
  CHECK(body.state().reed_events == 1 && body.state().pir_events == 1);
  for (int i = 0; i < 3; ++i)
    body.sample_optional_inputs(6U, false, false, false);
  for (int i = 0; i < 3; ++i)
    body.sample_optional_inputs(6U, false, true, true);
  CHECK(body.state().reed_events == 2 && body.state().pir_events == 2);
  CHECK(!body.state().armed); // neither source has motor authority
}

static void optional_sensor_inputs_never_arm_or_forge_boot_events() {
  using desk_robot::BodyControl;
  BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.sample_optional_inputs(7, false, false, false); // initial baseline
  CHECK(body.state().bumper_events == 0 && body.state().reed_events == 0);
  CHECK(send(body, "arm", 1) == "OK arm");
  body.sample_optional_inputs(7, true, false, false);
  CHECK(!body.state().armed && body.state().bumper_raw);
  CHECK(body.state().bumper_events == 0);
  body.sample_optional_inputs(7, true, false, false);
  body.sample_optional_inputs(7, true, false, false);
  CHECK(body.state().bumper_events == 1);
  CHECK(send(body, "arm", 20) == "ERR arm bumper_active");
  for (int i = 0; i < 3; ++i) body.sample_optional_inputs(7, false, false, false);
  for (int i = 0; i < 3; ++i) body.sample_optional_inputs(7, false, true, true);
  CHECK(body.state().reed_events == 1 && body.state().pir_events == 1);
  CHECK(send(body, "arm", 40) == "OK arm");
  const auto output = send(body, "status", 41);
  CHECK(output.find("\"extras\":{\"mask\":7,\"bumper\":false,\"bumps\":1") != std::string::npos);
  CHECK(output.find("\"reed_count\":1,\"pir\":true,\"pir_count\":1") != std::string::npos);
  CHECK(output.size() < desk_robot::kReplyCapacity - 1);
  body.sample_optional_inputs(0, false, false, false);
  const auto disabled = send(body, "status", 45);
  CHECK(disabled.find("\"extras\":{\"mask\":0") != std::string::npos);
}

static void battery_readiness_matches_stricter_arm_voltage() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 100);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.require_fuel_monitor(true);
  desk_robot::AccessoryReadings readings{};
  readings.gauge.fuel_present = readings.gauge.fuel_valid = true;
  readings.gauge.fuel_sample_seq = 1;
  readings.gauge.fuel_at_ms = 100;
  readings.gauge.cell_mv = 3250;
  body.set_accessories(readings, 100);
  CHECK(send(body, "rearm", 100, true) == "OK rearm");
  CHECK(send(body, "status", 100).find("\"ready\":false") !=
        std::string::npos);
  CHECK(send(body, "status", 100).find("\"fault\":\"battery_low\"") !=
        std::string::npos);
  CHECK(send(body, "arm", 100) == "ERR arm battery_low");

  readings.gauge.fuel_sample_seq = 2;
  readings.gauge.fuel_at_ms = 101;
  readings.gauge.cell_mv = 3350;
  body.set_accessories(readings, 101);
  CHECK(send(body, "status", 101).find("\"ready\":true") !=
        std::string::npos);
  CHECK(send(body, "arm", 101) == "OK arm");
}

static void battery_undervoltage_rejects_arm_and_stops_motion() {
  using desk_robot::BodyControl;
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 0);
  BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  send(body, "rearm", 0, true);
  CHECK(send(body, "arm", 0) == "OK arm");

  desk_robot::AccessoryReadings readings{};
  readings.gauge.fuel_present = readings.gauge.fuel_valid = true;
  readings.gauge.fuel_sample_seq = 1;
  readings.gauge.fuel_at_ms = 1;
  readings.gauge.cell_mv = 0; // Collapsed 0 mV reading must fail closed
  body.set_accessories(readings, 1);
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 1) == "ERR arm battery_low_latched");

  readings.gauge.fuel_sample_seq = 2;
  readings.gauge.fuel_at_ms = 2;
  readings.gauge.cell_mv = 3190;
  body.set_accessories(readings, 2);
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 2) == "ERR arm battery_low_latched");

  // Changing the voltage but reusing the last low sample is NOT evidence
  // of recovery. Neither a remote permit nor a local command may bypass it.
  readings.gauge.cell_mv = 3350;
  body.set_accessories(readings, 3);
  CHECK(send(body, "arm", 3) == "ERR arm battery_low_latched");
  CHECK(send(body, "rearm", 3, true) ==
        "ERR rearm battery_unsafe_or_stale");
  CHECK(send(body, "status", 3).find("\"fault\":\"battery_low_latched\"") !=
        std::string::npos);
  readings.gauge.fuel_valid = false;
  body.set_accessories(readings, 4);
  CHECK(send(body, "rearm", 4, true) ==
        "ERR rearm battery_unsafe_or_stale");

  // A new independently completed healthy gauge conversion plus deliberate
  // local recovery is required. It cannot resume the old motion command.
  readings.gauge.fuel_valid = true;
  readings.gauge.fuel_sample_seq = 3;
  readings.gauge.fuel_at_ms = 5;
  body.set_accessories(readings, 5);
  CHECK(send(body, "arm", 5) == "ERR arm battery_low_latched");
  CHECK(send(body, "rearm", 5) == "ERR rearm local_only");
  CHECK(send(body, "rearm", 505, true) ==
        "ERR rearm battery_unsafe_or_stale");
  readings.gauge.fuel_sample_seq = 4;
  readings.gauge.fuel_at_ms = 506;
  body.set_accessories(readings, 506);
  fresh(guard, 506);
  CHECK(send(body, "rearm", 506, true) == "OK rearm");
  CHECK(send(body, "arm", 506) == "OK arm");
  CHECK(body.state().armed);
}


static void required_fuel_gauge_loss_stops_and_requires_local_rearm() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 100);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.require_fuel_monitor(true);
  CHECK(send(body, "arm", 100) == "ERR arm fuel_monitor_missing_or_stale");
  CHECK(send(body, "rearm", 100, true) ==
        "ERR rearm fuel_monitor_missing_or_stale");

  desk_robot::AccessoryReadings readings{};
  body.set_accessories(readings, 101);
  // Optical guard has not yet been locally rearmed. Its existing fault
  // outranks the simultaneous missing gauge in the shared status, while
  // both conditions still independently prevent motor readiness.
  CHECK(send(body, "status", 101).find("\"fault\":\"missing_sample\"") !=
        std::string::npos);
  CHECK(send(body, "status", 101).find("\"ready\":false") !=
        std::string::npos);
  readings.gauge.fuel_present = readings.gauge.fuel_valid = true;
  readings.gauge.cell_mv = 3700;
  readings.gauge.fuel_sample_seq = 1;
  readings.gauge.fuel_at_ms = 102;
  body.set_accessories(readings, 102);
  CHECK(send(body, "arm", 102) == "ERR arm fuel_monitor_latched");
  CHECK(send(body, "rearm", 102) == "ERR rearm local_only");
  CHECK(send(body, "rearm", 102, true) == "OK rearm");
  CHECK(send(body, "arm", 102) == "OK arm");
  CHECK(send(body, "drive 30 30 200", 102).find("OK drive") == 0);
  CHECK(send(body, "grip 110", 102) == "OK grip angle=110");
  body.tick(103);
  const int held = body.state().grip;

  readings.gauge.fuel_valid = false;
  body.set_accessories(readings, 104);
  CHECK(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0);
  CHECK(body.state().servos_attached && body.state().grip == held);
  readings.gauge.fuel_valid = true; // same old sample is NOT a recovery
  body.set_accessories(readings, 105);
  CHECK(send(body, "arm", 105) == "ERR arm fuel_monitor_latched");
  CHECK(send(body, "rearm", 105, true) ==
        "ERR rearm fuel_monitor_no_new_sample");

  readings.gauge.fuel_sample_seq = 2;
  readings.gauge.fuel_at_ms = 106;
  body.set_accessories(readings, 106);
  CHECK(send(body, "rearm", 106, true) == "OK rearm");
  CHECK(send(body, "arm", 106) == "OK arm");
  for (std::uint32_t at = 146; at <= 626; at += 40) {
    fresh(guard, at);
    body.tick(at);
  }
  CHECK(!body.state().armed && body.state().left == 0);
  CHECK(send(body, "status", 626).find("\"fault\":\"fuel_monitor_latched\"") !=
        std::string::npos);
  CHECK(send(body, "arm", 626) == "ERR arm fuel_monitor_latched");
  CHECK(send(body, "rearm", 626, true) ==
        "ERR rearm fuel_monitor_missing_or_stale");
  readings.gauge.fuel_sample_seq = 3;
  readings.gauge.fuel_at_ms = 627;
  body.set_accessories(readings, 627);
  fresh(guard, 627);
  CHECK(send(body, "rearm", 627, true) == "OK rearm");
  CHECK(send(body, "arm", 627) == "OK arm");
}

static void guarded_dc_has_identical_cliff_touch_and_usb_rearm_contract() {
  // This is a policy/command contract test, not a load or PWM hardware test.
  using desk_robot::BodyControl;
  using desk_robot::BodyProfile;
  BodyControl no_guard(BodyProfile::DcGuarded);
  CHECK(send(no_guard, "arm", 0) == "ERR arm safety_interlock");
  CHECK(send(no_guard, "rearm", 0, true) == "ERR rearm safety_interlock");
  CHECK(send(no_guard, "status", 0).find("dc_pwm_guarded") != std::string::npos);
  CHECK(send(no_guard, "status", 0).find("missing_guard") != std::string::npos);

  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 0);
  BodyControl dc(BodyProfile::DcGuarded, &guard);
  CHECK(send(dc, "arm", 0) == "ERR arm safety_interlock");
  CHECK(send(dc, "rearm", 0) == "ERR rearm local_only");
  CHECK(send(dc, "rearm", 0, true) == "OK rearm");
  CHECK(send(dc, "arm", 0) == "OK arm");
  CHECK(send(dc, "drive 40 40 250", 0) ==
        "OK drive left=40 right=40 ms=250");
  CHECK(dc.state().left == 40 && dc.state().armed);
  dc.sample_touch_input(true);
  dc.tick(1);
  CHECK(dc.state().left == 0 && dc.state().right == 0 && !dc.state().armed);
  CHECK(send(dc, "arm", 2) == "ERR arm touch_active");
  dc.sample_touch_input(false);
  fresh(guard, 3);
  CHECK(send(dc, "rearm", 3, true) == "OK rearm");
  CHECK(send(dc, "arm", 3) == "OK arm");
  CHECK(send(dc, "drive 30 30 250", 3) ==
        "OK drive left=30 right=30 ms=250");
  guard.bus_fault();
  dc.tick(4);
  CHECK(!dc.state().armed && dc.state().left == 0);
  CHECK(send(dc, "arm", 5) == "ERR arm safety_interlock");
  CHECK(send(dc, "status", 5).find("dc_pwm_guarded") != std::string::npos);
}


static void full_dc_driver_nfault_is_fresh_sticky_and_usb_only() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 100);
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcGuarded, &guard);
  body.require_dc_driver_fault_monitor(true);

  // Missing expander data is never fabricated as a healthy GPIOB pin.
  CHECK(send(body, "arm", 100) == "ERR arm dc_driver_fault_interlock");
  CHECK(send(body, "rearm", 100, true) ==
        "ERR rearm dc_driver_fault_unhealthy");

  desk_robot::AccessoryReadings readings{};
  auto& fault = readings.optional_inputs;
  fault.present = fault.valid = true;
  fault.sample_seq = 1;
  fault.at_ms = 100;
  fault.driver_fault_active = false;
  body.set_accessories(readings, 100);
  CHECK(send(body, "arm", 100) == "ERR arm dc_driver_fault_interlock");
  CHECK(send(body, "rearm", 100, true) == "OK rearm");
  CHECK(send(body, "arm", 100) == "OK arm");
  CHECK(send(body, "drive 40 40 200", 100) ==
        "OK drive left=40 right=40 ms=200");
  CHECK(body.state().servos_attached);

  fault.driver_fault_active = true;
  fault.sample_seq = 2;
  fault.at_ms = 101;
  body.set_accessories(readings, 101);
  CHECK(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0 && body.state().servos_attached);
  const auto status = send(body, "status", 101);
  CHECK(status.find("\"dc_driver_fault_latched\"") != std::string::npos);
  CHECK(status.find("\"ready\":false") != std::string::npos);
  CHECK(send(body, "rearm", 101, true) ==
        "ERR rearm dc_driver_fault_unhealthy");

  fault.driver_fault_active = false;
  fault.sample_seq = 3;
  fault.at_ms = 102;
  body.set_accessories(readings, 102);
  CHECK(send(body, "arm", 102) == "ERR arm dc_driver_fault_interlock");
  CHECK(send(body, "rearm", 102) == "ERR rearm local_only");
  CHECK(send(body, "rearm", 102, true) == "OK rearm");
  CHECK(send(body, "arm", 102) == "OK arm");

  // A stale sample cannot authorize continued drive after the 250 ms bound.
  fresh(guard, 400);
  body.tick(400);
  CHECK(!body.state().armed && body.state().left == 0);
  CHECK(send(body, "arm", 400) == "ERR arm dc_driver_fault_interlock");
  CHECK(send(body, "rearm", 400, true) ==
        "ERR rearm dc_driver_fault_unhealthy");
  fault.sample_seq = 4;
  fault.at_ms = 401;
  body.set_accessories(readings, 401);
  fresh(guard, 401);
  CHECK(send(body, "rearm", 401, true) == "OK rearm");
  CHECK(send(body, "arm", 401) == "OK arm");
  fault.valid = false;
  body.set_accessories(readings, 402);
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 402) == "ERR arm dc_driver_fault_interlock");

  // The old HIGH nFAULT frame remains young enough to pass an age-only
  // check, but cannot clear the latch after a failed GPIOB transaction.
  fault.valid = true;
  body.set_accessories(readings, 403);
  CHECK(send(body, "rearm", 403, true) ==
        "ERR rearm dc_driver_fault_unhealthy");
  fault.sample_seq = 5;
  fault.at_ms = 404;
  body.set_accessories(readings, 404);
  CHECK(send(body, "rearm", 404, true) == "OK rearm");
  CHECK(send(body, "arm", 404) == "OK arm");

  // A contradictory LOW pin on the same sequence is a provenance fault.
  // Replaying HIGH under the same identity must not grant USB rearm.
  fault.driver_fault_active = true;
  body.set_accessories(readings, 405);
  CHECK(!body.state().armed && body.state().left == 0);
  fault.driver_fault_active = false;
  body.set_accessories(readings, 406);
  CHECK(send(body, "rearm", 406, true) ==
        "ERR rearm dc_driver_fault_unhealthy");
  fault.sample_seq = 6;
  fault.at_ms = 407;
  body.set_accessories(readings, 407);
  CHECK(send(body, "rearm", 407, true) == "OK rearm");
  fault.sample_seq = 5;
  fault.at_ms = 404;
  body.set_accessories(readings, 408);  // an older but still fresh frame
  CHECK(send(body, "rearm", 408, true) ==
        "ERR rearm dc_driver_fault_unhealthy");
}


static void dc_nfault_acquisition_wrap_preserves_forward_order() {
  // Hardware GPIOB sequences and uptime wrap, but a previously completed
  // pre-wrap acquisition must not count as another healthy sensor read.
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 0xfffffff0U);
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcGuarded, &guard);
  body.require_dc_driver_fault_monitor(true);
  desk_robot::AccessoryReadings readings{};
  auto& fault = readings.optional_inputs;
  fault.present = fault.valid = true;
  fault.driver_fault_active = false;
  fault.sample_seq = 0xffffffffU;
  fault.at_ms = 0xfffffff0U;
  body.set_accessories(readings, 0xfffffff0U);
  CHECK(send(body, "rearm", 0xfffffff0U, true) == "OK rearm");
  CHECK(send(body, "arm", 0xfffffff0U) == "OK arm");
  CHECK(send(body, "drive 20 20 100", 0xfffffff0U) ==
        "OK drive left=20 right=20 ms=100");
  fault.sample_seq = 1U;
  fault.at_ms = 5U;
  body.set_accessories(readings, 5U);
  fresh(guard, 5U);
  body.tick(5U);
  CHECK(body.state().armed && body.state().left == 20);
  fault.sample_seq = 0xfffffffeU;
  fault.at_ms = 0xfffffff0U;
  body.set_accessories(readings, 6U);
  CHECK(!body.state().armed && body.state().left == 0);
  CHECK(send(body, "rearm", 6U, true) ==
        "ERR rearm dc_driver_fault_unhealthy");
  fault.sample_seq = 2U;
  fault.at_ms = 7U;
  body.set_accessories(readings, 7U);
  CHECK(send(body, "rearm", 7U, true) == "OK rearm");
  CHECK(!body.state().armed && body.state().left == 0);
}

static void status_readiness_matches_local_arm_interlocks() {
  // Read-only HTTP/voice clients see safety.ready. A clear five-range guard
  // must not hide a missing dock GPIO, stale IMU, contact or touch trip.
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 0);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  CHECK(send(body, "rearm", 0, true) == "OK rearm");
  CHECK(send(body, "status", 0).find("\"ready\":true") != std::string::npos);
  body.sample_touch_input(true);
  CHECK(send(body, "status", 1).find("\"ready\":false") != std::string::npos);
  CHECK(send(body, "status", 1).find("\"fault\":\"touch_active\"") !=
        std::string::npos);
  CHECK(send(body, "arm", 1) == "ERR arm touch_active");
  body.sample_touch_input(false);

  body.sample_optional_inputs(1U, true, false, false);
  CHECK(send(body, "status", 2).find("\"fault\":\"bumper_active\"") !=
        std::string::npos);
  CHECK(send(body, "arm", 2) == "ERR arm bumper_latched");
  body.sample_optional_inputs(0U, false, false, false);
  // The collision stop survives release; only a new local USB decision
  // clears it before subsequent independent IMU fault checks.
  CHECK(send(body, "status", 2).find("\"fault\":\"bumper_latched\"") !=
        std::string::npos);
  CHECK(send(body, "arm", 2) == "ERR arm bumper_latched");
  CHECK(send(body, "rearm", 2, true) == "OK rearm");

  body.require_imu_for_motion(true);
  CHECK(send(body, "status", 3).find("\"fault\":\"imu_missing_or_stale\"") !=
        std::string::npos);
  CHECK(send(body, "arm", 3) == "ERR arm imu_missing_or_stale");
  // Even if both a missing IMU and a touch are present, retain the true
  // high priority local cliff fault in the shared safety context.
  body.sample_touch_input(true);
  guard.bus_fault();
  CHECK(send(body, "status", 4).find("\"fault\":\"bus_failure\"") !=
        std::string::npos);

  desk_robot::CliffGuard dock_guard;
  CHECK(dock_guard.configure(config()));
  fresh(dock_guard, 0);
  desk_robot::BodyControl dock_body(desk_robot::BodyProfile::StepperGuarded, &dock_guard);
  CHECK(send(dock_body, "rearm", 0, true) == "OK rearm");
  dock_body.require_dock_monitor(true);
  CHECK(send(dock_body, "status", 1).find(
      "\"fault\":\"dock_gpio_missing_or_stale\"") != std::string::npos);
  CHECK(send(dock_body, "arm", 1) == "ERR arm dock_gpio_missing_or_stale");
  desk_robot::AccessoryReadings readings{};
  readings.dock.present = readings.dock.valid = true;
  readings.dock.sample_seq = 1;
  readings.dock.at_ms = 2;
  dock_body.set_accessories(readings, 2);
  CHECK(send(dock_body, "status", 2).find("\"ready\":true") != std::string::npos);
  readings.dock.left_seated = true;
  readings.dock.sample_seq = 2;
  readings.dock.at_ms = 3;
  dock_body.set_accessories(readings, 3);
  CHECK(send(dock_body, "status", 3).find(
      "\"fault\":\"dock_power_connected\"") != std::string::npos);
  CHECK(send(dock_body, "arm", 3) == "ERR arm dock_power_connected");
}

static void eight_lane_optical_words_are_read_only_and_expire() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded);
  CHECK(send(body, "optics", 0).find(
      "\"present_mask\":0,\"valid_mask\":0") != std::string::npos);
  body.sample_range_optics(0, 0x0123, 0x4567, true, 10);
  body.sample_range_optics(5, 0x0020, 0x0400, true, 10);
  const auto fresh = send(body, "optics", 10);
  CHECK(fresh.front() == '{' && fresh.back() == '}');
  CHECK(fresh.find("\"ambient_97\":[291,0,0,0,0,32,0,0]") != std::string::npos);
  CHECK(fresh.find("\"signal_97\":[17767,0,0,0,0,1024,0,0]") != std::string::npos);
  CHECK(fresh.find("\"present_mask\":33,\"valid_mask\":33") != std::string::npos);
  CHECK(fresh.find("\"physical_qualified\":false") != std::string::npos);
  CHECK(fresh.find("\"motor_authorized\":false") != std::string::npos);
  CHECK(send(body, "optics 1", 11) == "ERR optics bad_arguments");

  const auto critical_expired = send(body, "optics", 210);
  CHECK(critical_expired.find(
      "\"present_mask\":33,\"valid_mask\":32") != std::string::npos);
  const auto side_fresh = send(body, "optics", 360);
  CHECK(side_fresh.find(
      "\"present_mask\":33,\"valid_mask\":32") != std::string::npos);
  const auto side_expired = send(body, "optics", 361);
  CHECK(side_expired.find(
      "\"present_mask\":33,\"valid_mask\":0") != std::string::npos);
  body.sample_range_optics(7, 65535, 65535, true, 362);
  body.invalidate_range_optics();
  const auto invalid = send(body, "optics", 362);
  CHECK(invalid.find("\"present_mask\":161,\"valid_mask\":0") != std::string::npos);
  CHECK(invalid.find("\"signal_97\":[17767,0,0,0,0,1024,0,65535]") != std::string::npos);
  CHECK(!body.state().armed); // diagnostic cannot grant any motor authority
}

int main() {
  try {
    desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded);
    CHECK(send(body, "arm", 0) == "ERR arm safety_interlock");
    CHECK(!body.state().armed && !body.state().servos_attached);
    const auto status = send(body, "status", 0);
    CHECK(status.find("\"protocol\":2") != std::string::npos);
    CHECK(status.find("stepper_28byj48") != std::string::npos);
    CHECK(status.find("missing_guard") != std::string::npos);
    CHECK(status.front() == '{' && status.back() == '}');
    CHECK(status.size() < desk_robot::kReplyCapacity - 1);
    CHECK(status.find("\"present_mask\":0,\"valid_mask\":0") != std::string::npos);
    std::cout << "PASS guarded profile cannot arm without a guard\n";
    guarded_dc_has_identical_cliff_touch_and_usb_rearm_contract();
    full_dc_driver_nfault_is_fresh_sticky_and_usb_only();
    dc_nfault_acquisition_wrap_preserves_forward_order();
    status_readiness_matches_local_arm_interlocks();
    std::cout << "PASS guarded DC uses same real cliff and USB recovery policy\n";
    real_dock_power_good_and_two_seat_switches_force_body_disarm();
    dock_removal_needs_new_fresh_real_gpio_sample();
    dock_removal_accepts_genuine_uint32_wrap();
    dock_charge_indication_alone_cannot_release_motion();
    dock_replayed_gpio_bits_do_not_preserve_arm_permission();
    inconsistent_dock_acquisition_requires_new_sample_to_recover();
    installed_dock_i2c_loss_or_single_seat_stops_local_motors();
    complete_robot_requires_boot_installed_and_fresh_dock_expander();
    dock_gpio_aux_sample_sequence_is_bounded_and_not_charging_proof();
    belly_adc_does_not_refresh_stale_jaw_sample();
    physical_gripper_stops_ramping_when_adc_is_not_trustworthy();
    gripper_jaw_consumes_at_most_four_degrees_per_adc_conversion();
    jaw_force_ceiling_is_local_and_direction_aware();
    optional_nfc_and_fresh_ambient_fit_existing_bounded_aux_contract();
    dual_ir_evidence_never_authorizes_body_motion_or_charging();
    raw_bumper_trip_preempts_debounce_and_preserves_payload();
    accessory_reconnect_does_not_invent_petting_events();
    optional_sensor_inputs_never_arm_or_forge_boot_events();
    battery_readiness_matches_stricter_arm_voltage();
    battery_undervoltage_rejects_arm_and_stops_motion();
    required_fuel_gauge_loss_stops_and_requires_local_rearm();
    accessory_sensors_never_infer_grip_or_current_or_grant_arm();
    independent_pack_sensor_freshness_never_crosses_devices();
    optional_max30102_raw_never_authorizes_motion_or_diagnosis();
    extra_three_ranging_channels_are_diagnostics_only();
    eight_lane_optical_words_are_read_only_and_expire();
    side_range_validity_clears_on_shared_bus_fault_without_fake_samples();
    cap_petting_zones_are_optional_and_never_arm();
    touch_telemetry_never_grants_motion();
    raw_touch_trip_preempts_debounce_without_forging_a_tap();
    touch_is_local_human_stop_and_requires_fresh_arm();
    touch_gesture_counters_survive_slow_status_polling();
    five_range_status_reports_real_samples_not_a_permission();
    imu_identity_is_diagnostic_only();
    required_imu_is_a_local_freshness_interlock();
    zero_acceleration_mpu_does_not_authorize_motion();
    mpu_native_low_g_irq_vetoes_local_wheels();
    missing_mpu_interrupt_status_cannot_authorize_wheels();
    imu_status_preserves_physical_conversion_and_boot_identity();
    std::cout << "PASS touch gestures, rollover and local stop interlock\\n";
    measured_local_calibration_is_atomic_and_never_arms();
    std::cout << "PASS USB calibration staged atomically with no arming\\n";
    unqualified_stepper_cutoff_never_claims_motion_ready();
    cpu_heartbeat_fault_is_sticky_and_holds_gripper();
    std::cout << "PASS CPU heartbeat fault latches drive and holds gripper\n";
    recovery_is_local_and_not_an_arm();
    usb_rearm_refuses_unsafe_physical_interlocks();
    std::cout << "PASS only local recovery can clear a healthy fault latch\n";
    receiver_recovery_authority_is_not_shared();
    std::cout << "PASS head receiver cannot borrow USB recovery authority\n";
    fault_holds_payload_and_requires_rearm();
    std::cout << "PASS fault holds payload and requires explicit rearm\n";
    stale_read_stops_before_watchdog();
    std::cout << "PASS stale sensor stops before communication watchdog\n";
    both_receivers_and_coils_respect_stop();
    std::cout << "PASS both receivers and coil output respect bus fault\n";
    drive_expiry_stops_coils_even_with_keepalive();
    std::cout << "PASS drive expiry stops coils despite keepalive\n";
  } catch (const std::exception& e) {
    std::cerr << "FAIL " << e.what() << '\n';
    return 1;
  }
}
