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
  for (std::uint32_t ms = 0; ms < 50; ++ms) {
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
  readings.gauge.at_ms = 5;
  readings.proximity.present = true;
  readings.proximity.valid = true;
  readings.proximity.raw = 90;
  readings.proximity.at_ms = 5;
  body.set_accessories(readings);
  const std::string reply = send(body, "aux", 10);
  CHECK(reply.find("\"angles\":{\"raw\":[2000,0,0]") != std::string::npos);
  CHECK(reply.find("\"present_mask\":1,\"valid_mask\":1") != std::string::npos);
  CHECK(reply.find("\"adc\":[123,-456]") != std::string::npos);
  CHECK(reply.find("\"calibrated\":false") != std::string::npos);
  CHECK(reply.find("\"cell_mv\":3690") != std::string::npos);
  CHECK(reply.find("\"current_calibrated\":false") != std::string::npos);
  CHECK(reply.find("\"gesture\":0,\"gesture_events\":0") != std::string::npos);
  CHECK(send(body, "arm", 10) == "ERR arm safety_interlock");
  CHECK(!body.state().armed);
  const std::string stale = send(body, "aux", 400);
  CHECK(stale.find("\"valid_mask\":0") != std::string::npos);
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
  body.set_paw_pulse(sample);
  body.execute("aux", 3, 150, response, sizeof(response));
  CHECK(std::string(response).find("\"part_id\":21") != std::string::npos);
  CHECK(std::string(response).find("\"ir\":55000") != std::string::npos);
  CHECK(std::string(response).find("\"age_ms\":50") != std::string::npos);
  body.execute("aux", 3, 500, response, sizeof(response));
  CHECK(std::string(response).find("\"valid\":false") != std::string::npos);
  CHECK(send(body, "arm", 501) == "ERR arm safety_interlock");
  CHECK(!body.state().armed);
}

static void extra_three_ranging_channels_are_diagnostics_only() {
  desk_robot::CliffGuard guard;
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.sample_side_range(0, 125, true, 10);
  body.sample_side_range(1, 0, false, 11);
  body.sample_side_range(2, 300, true, 12);
  body.sample_side_range(3, 150, true, 14); // invalid index ignored
  const std::string status = send(body, "status", 30);
  CHECK(status.find("\"side_ranges\":{") != std::string::npos);
  CHECK(status.find("\"mm\":[125,0,300]") != std::string::npos);
  CHECK(status.find("\"age_ms\":[20,19,18]") != std::string::npos);
  CHECK(status.find("\"present_mask\":7,\"valid_mask\":5") != std::string::npos);
  CHECK(status.find("\"motion_certified\":false") != std::string::npos);
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 30) == "ERR arm safety_interlock");
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
  CHECK(send(body, "arm", 252) == "ERR arm imu_missing_or_stale");
  reading.valid = false;
  reading.at_ms = 252;
  body.set_imu(reading);
  CHECK(send(body, "arm", 252) == "ERR arm imu_missing_or_stale");
  reading.valid = true;
  body.set_imu(reading);
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
  body.set_accessories(read);
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 2) == "ERR arm dock_power_connected");
  read.dock.valid = false; // lost expander must not clear the contact latch
  body.set_accessories(read);
  CHECK(send(body, "arm", 3) == "ERR arm dock_power_connected");
  read.dock.valid = true;
  read.dock.left_seated = false; // one switch not enough to clear
  body.set_accessories(read);
  CHECK(send(body, "arm", 4) == "ERR arm dock_power_connected");
  read.dock.right_seated = false;
  read.dock.input_good = false;
  body.set_accessories(read);
  CHECK(send(body, "arm", 5) == "OK arm");
  CHECK(body.state().armed);
  CHECK(send(body, "disarm", 6) == "OK disarm");
}

static void installed_dock_i2c_loss_or_single_seat_stops_local_motors() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  desk_robot::AccessoryReadings read{};
  read.dock.present = true;
  read.dock.valid = false; // installed but no successful GPIO conversion yet
  body.set_accessories(read);
  CHECK(send(body, "arm", 1) == "ERR arm dock_gpio_missing_or_stale");
  read.dock.valid = true;
  read.dock.sample_seq = 1;
  read.dock.at_ms = 2;
  body.set_accessories(read);
  CHECK(send(body, "arm", 3) == "OK arm");
  CHECK(body.state().servos_attached);
  CHECK(send(body, "drive 20 20 100", 4).find("OK drive") == 0);
  CHECK(body.state().left == 20 && body.state().right == 20);
  read.dock.valid = false; // missing I2C read during physical motion
  body.set_accessories(read);
  CHECK(!body.state().armed);
  CHECK(body.state().left == 0 && body.state().right == 0);
  CHECK(body.state().servos_attached); // keep jaw PWM on sensor dropout
  CHECK(send(body, "arm", 5) == "ERR arm dock_gpio_missing_or_stale");
  read.dock.valid = true;
  read.dock.sample_seq = 2;
  read.dock.at_ms = 6;
  body.set_accessories(read);
  CHECK(send(body, "arm", 7) == "OK arm"); // manual explicit rearm
  body.tick(507); // 501ms since last physical expander read
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 508) == "ERR arm dock_gpio_missing_or_stale");
  read.dock.sample_seq = 3;
  read.dock.at_ms = 509;
  body.set_accessories(read);
  CHECK(send(body, "arm", 510) == "OK arm");
  read.dock.left_seated = true; // even one seat without powered PGOOD
  read.dock.sample_seq = 4;
  read.dock.at_ms = 511;
  body.set_accessories(read);
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 512) == "ERR arm dock_power_connected");
  read.dock.left_seated = false;
  read.dock.sample_seq = 5;
  read.dock.at_ms = 513;
  body.set_accessories(read); // both open + no PGOOD is an observed removal
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
  body.set_accessories(read);
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
    real_dock_power_good_and_two_seat_switches_force_body_disarm();
    installed_dock_i2c_loss_or_single_seat_stops_local_motors();
    dock_gpio_aux_sample_sequence_is_bounded_and_not_charging_proof();
    optional_sensor_inputs_never_arm_or_forge_boot_events();
    accessory_sensors_never_infer_grip_or_current_or_grant_arm();
    optional_max30102_raw_never_authorizes_motion_or_diagnosis();
    extra_three_ranging_channels_are_diagnostics_only();
    cap_petting_zones_are_optional_and_never_arm();
    touch_telemetry_never_grants_motion();
    raw_touch_trip_preempts_debounce_without_forging_a_tap();
    touch_is_local_human_stop_and_requires_fresh_arm();
    touch_gesture_counters_survive_slow_status_polling();
    five_range_status_reports_real_samples_not_a_permission();
    imu_identity_is_diagnostic_only();
    required_imu_is_a_local_freshness_interlock();
    std::cout << "PASS touch gestures, rollover and local stop interlock\\n";
    measured_local_calibration_is_atomic_and_never_arms();
    std::cout << "PASS USB calibration staged atomically with no arming\\n";
    recovery_is_local_and_not_an_arm();
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
