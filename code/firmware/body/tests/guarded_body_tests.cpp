#include <cstdio>
#include "BodyControl.h"
#include "TouchDebounce.h"
#include "CliffGuard.h"
#include "ReplyTxQueue.h"
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

static void cold_boot_complete_unsafe_sweep_reports_real_fault() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  CHECK(guard.fault() == desk_robot::CliffFault::MissingSample);
  for (std::uint8_t lane = 0; lane < 5; ++lane)
    guard.sample(lane, lane == 2 ? 80 : lane < 4 ? 50 : 200, true, 100);
  CHECK(!guard.evaluate(100));
  CHECK(guard.fault() == desk_robot::CliffFault::FloorOutOfRange);
  CHECK(guard.fault_sensor() == 2);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  const auto status = send(body, "status", 100);
  CHECK(status.find("\"ready\":false") != std::string::npos);
  CHECK(status.find("\"fault\":\"floor_out_of_range\"") !=
        std::string::npos);
  CHECK(status.find("\"sensor\":2") != std::string::npos);
  CHECK(send(body, "arm", 100) == "ERR arm safety_interlock");
  // Fresh good samples never clear the first real fault without local rearm.
  fresh(guard, 101);
  CHECK(!guard.evaluate(101));
  CHECK(guard.fault() == desk_robot::CliffFault::FloorOutOfRange);
  CHECK(send(body, "arm", 101) == "ERR arm safety_interlock");
  CHECK(send(body, "rearm", 101) == "ERR rearm local_only");
  CHECK(send(body, "rearm", 101, true) == "OK rearm");
  CHECK(!body.state().armed);

  // After first successful rearm the ordinary first-fault-sticky policy wins.
  guard.sample(1, 80, true, 102);
  CHECK(!guard.evaluate(102));
  CHECK(guard.fault() == desk_robot::CliffFault::FloorOutOfRange);
  CHECK(guard.fault_sensor() == 1);
  guard.sample(2, 0, false, 103);
  CHECK(!guard.evaluate(103));
  CHECK(guard.fault() == desk_robot::CliffFault::FloorOutOfRange);
  CHECK(guard.fault_sensor() == 1);
  fresh(guard, 104);
  CHECK(!guard.evaluate(104));
  CHECK(send(body, "rearm", 104, true) == "OK rearm");
  CHECK(!body.state().armed);

  desk_robot::CliffGuard healthy_boot;
  CHECK(healthy_boot.configure(config()));
  fresh(healthy_boot, 10);
  CHECK(!healthy_boot.evaluate(10));
  CHECK(healthy_boot.fault() == desk_robot::CliffFault::MissingSample);
  CHECK(healthy_boot.try_rearm(10));
  CHECK(healthy_boot.evaluate(10));
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
  body.sample_touch_input(true, 100);
  CHECK(send(body, "rearm", 100, true) == "ERR rearm touch_active");
  CHECK(send(body, "arm", 100) == "ERR arm touch_active");
  body.sample_touch_input(false, 100);
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

// Contact before the deadline is an ordinary stop. At or after expiry
// the independent host timeout must remain USB-latched after release.
static void contact_cannot_hide_expired_host_lease() {
  for (const auto profile : {desk_robot::BodyProfile::StepperGuarded,
                             desk_robot::BodyProfile::DcGuarded}) {
    for (const std::uint32_t start : {10U, 0xffffff80U}) {
      for (const bool moving : {false, true}) {
        for (const int contact : {0, 1, 2}) {
          for (const bool expired : {false, true}) {
            desk_robot::CliffGuard guard;
            CHECK(guard.configure(config()));
            fresh(guard, start);
            desk_robot::BodyControl body(profile, &guard);
            CHECK(send(body, "rearm", start, true) == "OK rearm");
            CHECK(send(body, "arm", start) == "OK arm");
            if (moving)
              CHECK(send(body, "drive 20 20 250", start).find("OK drive") == 0);
            const std::uint32_t limit = moving ? 200U : 500U;
            for (std::uint32_t dt = 50; dt < limit; dt += 50) {
              fresh(guard, start + dt);
              body.tick(start + dt);
              CHECK(body.state().armed);
            }
            const std::uint32_t now = start + limit - (expired ? 0U : 1U);
            fresh(guard, now);
            if (contact == 0) {
              body.sample_touch_input(true, now);
              body.sample_touch_input(false, now + 1);
            } else if (contact == 1) {
              body.set_touch(true, now);
              body.set_touch(false, now + 1);
            } else {
              desk_robot::AccessoryReadings readings{};
              readings.dock.present = readings.dock.valid = true;
              readings.dock.left_seated = true;
              readings.dock.sample_seq = 1;
              readings.dock.at_ms = now;
              body.set_accessories(readings, now);
              readings.dock.left_seated = false;
              readings.dock.sample_seq = 2;
              readings.dock.at_ms = now + 1;
              body.set_accessories(readings, now + 1);
            }
            CHECK(!body.state().armed);
            CHECK(body.state().left == 0 && body.state().right == 0);
            CHECK(body.state().servos_attached);
            if (expired) {
              CHECK(send(body, "arm", now + 1) == "ERR arm command_timeout_latched");
              CHECK(send(body, "rearm", now + 1) == "ERR rearm local_only");
              CHECK(send(body, "rearm", now + 1, true) == "OK rearm");
              CHECK(!body.state().armed);
            }
            CHECK(send(body, "arm", now + 1) == "OK arm");
            CHECK(body.state().left == 0 && body.state().right == 0);
          }
        }
      }
    }
  }
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

static void guarded_directional_drive_rejects_unqualified_sweep() {
  // Only the five mounted floor/front lanes are presently qualified for
  // LOCAL motion policy; the three side/rear readings are diagnostics.
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 0);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  CHECK(send(body, "rearm", 0, true) == "OK rearm");
  CHECK(send(body, "arm", 0) == "OK arm");
  desk_robot::LineReceiver head;
  char reply[desk_robot::kReplyCapacity]{};
  for (char byte : std::string("drive -20 -20 100\n"))
    head.feed(byte, 1, body, reply, sizeof(reply));
  CHECK(std::string(reply) == "ERR drive directional_clearance_unqualified");
  CHECK(body.state().armed && body.state().servos_attached &&
        body.state().left == 0 && body.state().right == 0);
  for (const char* command : {
      "drive 20 -20 100", "drive -20 20 100", "drive 20 10 100",
      "drive 20 0 100", "drive 0 20 100"}) {
    CHECK(send(body, command, 2) ==
          "ERR drive directional_clearance_unqualified");
    CHECK(body.state().armed && body.state().left == 0 &&
          body.state().right == 0);
  }
  // Forward pulses remain bounded and intact; a later unsafe turn
  // immediately cancels an otherwise live forward command.
  CHECK(send(body, "drive 20 20 100", 3) ==
        "OK drive left=20 right=20 ms=100");
  CHECK(body.state().left == 20 && body.state().right == 20);
  CHECK(send(body, "drive 30 20 100", 4) ==
        "ERR drive directional_clearance_unqualified");
  CHECK(body.state().armed && body.state().servos_attached &&
        body.state().left == 0 && body.state().right == 0);
  CHECK(send(body, "drive 0 0 100", 5) ==
        "OK drive left=0 right=0 ms=100");
  CHECK(send(body, "stop", 6) == "OK stop");

  // A rejected command must not refresh the independent body watchdog.
  desk_robot::CliffGuard timeout_guard;
  CHECK(timeout_guard.configure(config()));
  fresh(timeout_guard, 0);
  desk_robot::BodyControl timeout(desk_robot::BodyProfile::StepperGuarded,
                                  &timeout_guard);
  CHECK(send(timeout, "rearm", 0, true) == "OK rearm");
  CHECK(send(timeout, "arm", 0) == "OK arm");
  // Real CliffGuard correctly latches a stalled optical sweep BEFORE its
  // first replacement sample. Maintain independent fresh acquisitions while
  // deliberately leaving the command watchdog without a keepalive.
  for (std::uint32_t at = 80; at <= 480; at += 80) {
    fresh(timeout_guard, at);
    timeout.tick(at);
    CHECK(timeout.state().armed);
  }
  fresh(timeout_guard, 490);
  CHECK(send(timeout, "drive 20 -20 100", 490) ==
        "ERR drive directional_clearance_unqualified");
  timeout.tick(501);
  CHECK(!timeout.state().armed && timeout.state().left == 0 &&
        timeout.state().right == 0);
  CHECK(send(timeout, "status", 501).find("command_timeout_latched") !=
        std::string::npos);
}

// Every local trip cancels the active pulse, not merely future ARM requests.
// Reverse/pivot clearance is not qualified: recovery must never move blindly.
static void local_trip_blocks_forward_and_reverse_replay() {
  using desk_robot::BodyProfile;
  for (const auto profile : {BodyProfile::StepperGuarded, BodyProfile::DcGuarded}) {
    // Four floor lanes, front obstacle, raw bumper and CPU cutoff notification.
    // A CPU cutoff notification is not a mechanical wheel-stall detector.
    for (std::uint8_t fault = 0; fault < 7; ++fault) {
      desk_robot::CliffGuard guard;
      CHECK(guard.configure(config()));
      fresh(guard, 10);
      desk_robot::BodyControl body(profile, &guard);
      CHECK(send(body, "rearm", 10, true) == "OK rearm");
      CHECK(send(body, "arm", 10) == "OK arm");
      CHECK(send(body, "drive 40 40 250", 10) ==
            "OK drive left=40 right=40 ms=250");
      CHECK(body.state().armed && body.state().left == 40 &&
            body.state().right == 40 && body.drive_remaining(10) == 250);
      if (fault < 5) {
        guard.sample(fault, fault < 4 ? 80 : 30, true, 11);
        // A queued drive arriving before the next scheduled tick must still
        // execute the local safety policy before processing the command.
        CHECK(send(body, "drive 40 40 250", 11) == "ERR drive disarmed");
      } else if (fault == 5) {
        body.sample_bumper_input(true);
      } else {
        body.motor_watchdog_trip();
      }
      CHECK(!body.state().armed && body.state().left == 0 &&
            body.state().right == 0 && body.drive_remaining(11) == 0);
      CHECK(body.state().servos_attached);

      if (fault < 5)
        CHECK(send(body, "rearm", 11, true) == "ERR rearm safety_interlock");
      else if (fault == 5)
        CHECK(send(body, "rearm", 11, true) == "ERR rearm bumper_active");
      const char* arm_error = fault < 5 ? "ERR arm safety_interlock" :
          fault == 5 ? "ERR arm bumper_latched" : "ERR arm motor_watchdog_latched";

      fresh(guard, 12);
      body.sample_bumper_input(false);
      // Both command authorities must obey the latch. Neither healthy sensor
      // recovery, STOP, keepalive nor another ARM may resurrect a drive lease.
      for (bool local : {false, true}) {
        CHECK(send(body, "stop", 12, local) == "OK stop");
        CHECK(send(body, "keepalive", 12, local) == "ERR keepalive disarmed");
        CHECK(send(body, "arm", 12, local) == arm_error);
        for (const char* command : {"drive 40 40 250", "drive -40 -40 250",
                                    "drive 40 -40 250"}) {
          CHECK(send(body, command, 12, local) == "ERR drive disarmed");
          CHECK(!body.state().armed && body.state().left == 0 &&
                body.state().right == 0 && body.drive_remaining(12) == 0);
        }
      }
      CHECK(send(body, "rearm", 12) == "ERR rearm local_only");
      CHECK(send(body, "rearm", 12, true) == "OK rearm");
      CHECK(!body.state().armed && body.drive_remaining(12) == 0);
      CHECK(send(body, "arm", 12) == "OK arm");
      CHECK(body.state().left == 0 && body.state().right == 0 &&
            body.drive_remaining(12) == 0);
      CHECK(send(body, "drive -40 -40 250", 12) ==
            "ERR drive directional_clearance_unqualified");
      CHECK(body.state().left == 0 && body.state().right == 0);
    }
  }
}

// Exercise the same first-fault contract on the live drive state, not
// just the pure guard. Each case has exactly one faulty critical lane.
static void single_invalid_or_stale_lane_cancels_drive() {
  using desk_robot::BodyProfile;
  using desk_robot::CliffFault;
  for (const auto profile : {BodyProfile::StepperGuarded, BodyProfile::DcGuarded}) {
    for (std::uint8_t lane = 0; lane < desk_robot::kCliffSensorCount; ++lane) {
      for (const bool stale : {false, true}) {
        desk_robot::CliffGuard guard;
        CHECK(guard.configure(config()));
        fresh(guard, 100);
        desk_robot::BodyControl body(profile, &guard);
        CHECK(send(body, "rearm", 100, true) == "OK rearm");
        CHECK(send(body, "arm", 100) == "OK arm");
        CHECK(send(body, "drive 40 40 250", 100) ==
              "OK drive left=40 right=40 ms=250");
        const std::uint32_t trip = stale ? 200 : 101;
        if (stale) {
          // Only the chosen lane misses its freshness deadline. The
          // active drive lease and every peer lane are still healthy.
          for (std::uint8_t peer = 0; peer < desk_robot::kCliffSensorCount; ++peer)
            if (peer != lane) guard.sample(peer, peer < 4 ? 50 : 200, true, 199);
          body.tick(199);
          CHECK(body.state().armed && body.state().left == 40 &&
                body.state().right == 40 && body.drive_remaining(199) > 0);
        } else {
          // Plausible millimeters must not mask one invalid chip result.
          guard.sample(lane, lane < 4 ? 50 : 200, false, trip);
          CHECK(guard.fault() == CliffFault::InvalidSample);
        }
        body.tick(trip);
        CHECK(guard.fault() == (stale ? CliffFault::StaleSample :
                                      CliffFault::InvalidSample));
        CHECK(guard.fault_sensor() == lane);
        CHECK(!body.state().armed && body.state().left == 0 &&
              body.state().right == 0 && body.drive_remaining(trip) == 0);
        CHECK(body.state().servos_attached);
        CHECK(send(body, "rearm", trip, true) == "ERR rearm safety_interlock");
        // One actual replacement restores sensor health, not motion authority.
        const auto recovered = trip + 1;
        guard.sample(lane, lane < 4 ? 50 : 200, true, recovered);
        CHECK(guard.diagnostic(lane, recovered).valid);
        CHECK(send(body, "arm", recovered) == "ERR arm safety_interlock");
        CHECK(send(body, "keepalive", recovered) == "ERR keepalive disarmed");
        CHECK(send(body, "drive 40 40 250", recovered) == "ERR drive disarmed");
        CHECK(send(body, "rearm", recovered) == "ERR rearm local_only");
        CHECK(send(body, "rearm", recovered, true) == "OK rearm");
        CHECK(!body.state().armed && body.drive_remaining(recovered) == 0);
        CHECK(send(body, "arm", recovered) == "OK arm");
        CHECK(body.state().left == 0 && body.state().right == 0 &&
              body.drive_remaining(recovered) == 0);
      }
    }
  }
}

static void fault_holds_payload_and_requires_rearm() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 0);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  CHECK(send(body, "rearm", 0, true) == "OK rearm");
  CHECK(send(body, "arm", 0) == "OK arm");
  CHECK(send(body, "drive 40 40 250", 0) == "OK drive left=40 right=40 ms=250");
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
  // Stage a different calibration before a later arm and safety trip.
  for (int i = 0; i < 4; ++i)
    CHECK(send(body, "calfloor " + std::to_string(i) + " 41 60", 0, true) ==
          "OK calfloor channel=" + std::to_string(i));
  CHECK(send(body, "calfront 30 1000", 0, true) == "OK calfront");
  CHECK(send(body, "calfresh 100", 0, true) == "OK calfresh");
  CHECK(send(body, "arm", 1) == "ERR arm safety_interlock");
  fresh(guard, 2);
  CHECK(send(body, "rearm", 2) == "ERR rearm local_only");
  CHECK(send(body, "rearm", 2, true) == "OK rearm");
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 2) == "OK arm");
  CHECK(send(body, "calfloor 0 40 60", 3, true) ==
        "ERR calibration disarm_first");
  body.sample_touch_input(true, 3);
  CHECK(!body.state().armed && body.state().servos_attached);
  const auto held_grip = body.state().grip;
  CHECK(send(body, "calcommit", 3, true) == "ERR calibration disarm_first");
  CHECK(body.state().servos_attached && body.state().grip == held_grip);
  CHECK(guard.configuration().floor[0].min_mm == 40);
  CHECK(send(body, "disarm", 3) == "OK disarm");
  CHECK(!body.state().servos_attached);
  CHECK(send(body, "calcommit", 4, true) == "OK calcommit");
  CHECK(guard.configuration().floor[0].min_mm == 41);
  CHECK(!body.state().armed && !body.state().servos_attached);
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

static void optional_range_replay_preserves_newest_raw_evidence() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.sample_side_range(0, 120, true, 100);
  body.sample_side_range(0, 999, true, 100); // contradictory same-tick value
  CHECK(body.state().side_present[0] && !body.state().side_valid[0]);
  CHECK(body.state().side_mm[0] == 120 &&
        body.state().side_at_ms[0] == 100);
  CHECK(send(body, "status", 101).find(
      "\"side_ranges\":{") != std::string::npos);
  CHECK(send(body, "status", 101).find(
      "\"present_mask\":1,\"valid_mask\":0") != std::string::npos);
  body.sample_side_range(0, 121, true, 101);
  CHECK(body.state().side_valid[0] && body.state().side_mm[0] == 121);
  body.sample_side_range(0, 998, true, 100); // stale late completion
  CHECK(!body.state().side_valid[0] &&
        body.state().side_mm[0] == 121 &&
        body.state().side_at_ms[0] == 101);
  body.sample_side_range(0, 122, true, 102);
  CHECK(body.state().side_valid[0] && body.state().side_mm[0] == 122);

  body.sample_range_optics(5, 32, 128, true, 100);
  body.sample_range_optics(5, 65535, 65535, true, 100);
  CHECK(body.state().optical[5].present && !body.state().optical[5].valid);
  CHECK(body.state().optical[5].ambient_97 == 32 &&
        body.state().optical[5].signal_97 == 128 &&
        body.state().optical[5].at_ms == 100);
  CHECK(send(body, "optics", 101).find(
      "\"present_mask\":32,\"valid_mask\":0") != std::string::npos);
  body.sample_range_optics(5, 33, 129, true, 101);
  CHECK(body.state().optical[5].valid);
  body.sample_range_optics(5, 65535, 65535, true, 99);
  CHECK(!body.state().optical[5].valid &&
        body.state().optical[5].ambient_97 == 33 &&
        body.state().optical[5].signal_97 == 129 &&
        body.state().optical[5].at_ms == 101);
  body.sample_range_optics(5, 34, 130, true, 102);
  CHECK(body.state().optical[5].valid);

  // A real post-wrap conversion is forward, an old pre-wrap completion isn't.
  desk_robot::BodyControl wrapped(desk_robot::BodyProfile::DcPwm);
  wrapped.sample_side_range(2, 200, true, 0xfffffff0U);
  wrapped.sample_range_optics(7, 40, 100, true, 0xfffffff0U);
  wrapped.sample_side_range(2, 201, true, 5U);
  wrapped.sample_range_optics(7, 41, 101, true, 5U);
  CHECK(wrapped.state().side_valid[2] &&
        wrapped.state().side_mm[2] == 201);
  CHECK(wrapped.state().optical[7].valid &&
        wrapped.state().optical[7].ambient_97 == 41);
  wrapped.sample_side_range(2, 999, true, 0xfffffff5U);
  wrapped.sample_range_optics(7, 999, 999, true, 0xfffffff5U);
  CHECK(!wrapped.state().side_valid[2] &&
        wrapped.state().side_mm[2] == 201);
  CHECK(!wrapped.state().optical[7].valid &&
        wrapped.state().optical[7].ambient_97 == 41);
  wrapped.sample_side_range(2, 202, true, 6U);
  wrapped.sample_range_optics(7, 42, 102, true, 6U);
  CHECK(wrapped.state().side_valid[2] &&
        wrapped.state().optical[7].valid);
  CHECK(!body.state().armed && !wrapped.state().armed);
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

static void raw_touch_observations_restart_gesture_debounce() {
  desk_robot::TouchDebounce touch;
  CHECK(!touch.poll(true, 100));
  CHECK(!touch.poll(true, 125));
  touch.observe(false, 130);  // UART/output safety read between gesture polls
  CHECK(!touch.poll(true, 150));
  CHECK(!touch.stable());
  CHECK(!touch.poll(true, 175));
  CHECK(touch.poll(true, 200));
  CHECK(touch.stable());
  CHECK(!touch.poll(false, 225));
  CHECK(!touch.poll(false, 250));
  touch.observe(true, 255);  // interrupt a candidate release
  CHECK(!touch.poll(false, 275));
  CHECK(touch.stable());
  CHECK(!touch.poll(false, 300));
  CHECK(touch.poll(false, 325));
  CHECK(!touch.stable());
  desk_robot::TouchDebounce wrap;
  CHECK(!wrap.poll(true, 0xfffffff0U));
  CHECK(!wrap.poll(true, 9U));
  CHECK(wrap.poll(true, 34U));
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
  body.sample_touch_input(true, 20);  // one raw GPIO high, gesture state still false
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
  body.sample_touch_input(false, 160);  // one raw low still requires explicit arm
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
      "\"belly_seq\":0,\"belly_age_ms\":0,\"belly_valid\":false") !=
      std::string::npos);
  CHECK(force_source.find(
      "\"jaw_seq\":0,\"boot_id\":123456789,\"jaw_age_ms\":0,\"jaw_valid\":false,\"valid\":false") !=
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
  imu.at_ms = 101; // a distinct successful source conversion
  body.set_imu(imu);
  CHECK(send(body, "rearm", 101, true) == "OK rearm");
  CHECK(send(body, "arm", 101) == "OK arm");
  CHECK(send(body, "drive 20 20 200", 101).find("OK drive") == 0);
  imu.low_g_status_valid = false;  // intermittent I2C/clone failure
  imu.at_ms = 102;
  body.set_imu(imu);
  fresh(guard, 102);
  body.tick(102);
  CHECK(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0 && body.state().servos_attached);
  CHECK(send(body, "arm", 102) == "ERR arm imu_sensor_fault_latched");
  const auto status = send(body, "status", 102);
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
  imu.at_ms = 101;
  body.set_imu(imu);
  CHECK(send(body, "rearm", 101, true) == "OK rearm");
  CHECK(send(body, "arm", 101) == "OK arm");
  CHECK(send(body, "drive 20 20 200", 101).find("OK drive") == 0);
  CHECK(body.state().servos_attached);
  imu.accel[2] = 0;
  imu.at_ms = 102;
  body.set_imu(imu);
  fresh(guard, 102);
  body.tick(102);
  CHECK(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0 && body.state().servos_attached);
  CHECK(send(body, "arm", 102) == "ERR arm imu_sensor_fault_latched");
  CHECK(send(body, "status", 102).find("\"fault\":\"imu_sensor_fault_latched\"") != std::string::npos);
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
  reading.at_ms = 253; // only a new acquisition can repair invalid evidence
  body.set_imu(reading);
  CHECK(send(body, "arm", 253) == "ERR arm imu_sensor_fault_latched");
  CHECK(send(body, "status", 253).find(
      "\"fault\":\"imu_sensor_fault_latched\"") != std::string::npos);
  CHECK(send(body, "rearm", 253) == "ERR rearm local_only");
  CHECK(send(body, "rearm", 253, true) == "OK rearm");
  CHECK(send(body, "arm", 253) == "OK arm");
  CHECK(body.state().left == 0 && body.state().right == 0);
  // Unrecognized model cannot claim a valid raw sample.
  reading.model = desk_robot::BerryModel::Unknown;
  body.set_imu(reading);
  body.tick(253);
  CHECK(!body.state().armed);
}


static void imu_replay_and_rollover_are_local_motion_safety_evidence() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 100);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.require_imu_for_motion(true);
  body.set_imu_identity(4, 0x68, 0);
  desk_robot::BerryReading reading{};
  reading.model = desk_robot::BerryModel::Mpu6050;
  reading.valid = true;
  reading.low_g_status_valid = true;
  reading.accel[2] = 16384;
  reading.at_ms = 100;
  body.set_imu(reading);
  CHECK(send(body, "rearm", 100, true) == "OK rearm");
  CHECK(send(body, "arm", 100) == "OK arm");
  CHECK(send(body, "drive 20 20 200", 100).find("OK drive") == 0);
  body.set_imu(reading); // normal cached reading between real I2C polls
  fresh(guard, 101);
  body.tick(101);
  CHECK(body.state().armed && body.state().left == 20);
  reading.accel[0] = 900; // changed data under the same conversion identity
  body.set_imu(reading);
  CHECK(!body.state().armed && body.state().left == 0);
  CHECK(body.state().servos_attached); // never drop an already held object
  CHECK(!body.imu_fresh(101));
  const auto replay_status = send(body, "status", 101);
  CHECK(replay_status.find(
      "\"temp_valid\":false,\"low_g_valid\":false,\"low_g_irq\":false") !=
      std::string::npos);  // a rejected replay is not live physical MPU data
  CHECK(send(body, "arm", 101) == "ERR arm imu_sensor_fault_latched");
  CHECK(send(body, "rearm", 101, true) == "ERR rearm imu_missing_or_stale");
  reading.at_ms = 102; // genuine newer conversion
  body.set_imu(reading);
  fresh(guard, 102);
  CHECK(body.imu_fresh(102));
  const auto genuine_status = send(body, "status", 102);
  CHECK(genuine_status.find(
      "\"temp_valid\":true,\"low_g_valid\":true,\"low_g_irq\":false") !=
      std::string::npos);  // fresh source restores raw evidence, not wheel ARM
  CHECK(send(body, "arm", 102) == "ERR arm imu_sensor_fault_latched");
  CHECK(send(body, "rearm", 102, true) == "OK rearm");
  CHECK(send(body, "arm", 102) == "OK arm");
  CHECK(send(body, "drive 20 20 200", 102).find("OK drive") == 0);
  reading.at_ms = 101; // out-of-order sample, even if otherwise plausible
  body.set_imu(reading);
  CHECK(!body.state().armed && body.state().left == 0);
  CHECK(send(body, "arm", 103) == "ERR arm imu_sensor_fault_latched");
  reading.at_ms = 104;
  body.set_imu(reading);
  fresh(guard, 104);
  CHECK(send(body, "rearm", 104, true) == "OK rearm");
  CHECK(send(body, "arm", 104) == "OK arm");
  CHECK(body.state().left == 0); // no automatic old drive restart

  // millis() genuinely wraps after a new device conversion. Half-range
  // unsigned ordering accepts progress, but rejects a delayed old packet.
  desk_robot::BodyControl wrapped(desk_robot::BodyProfile::StepperGuarded);
  wrapped.require_imu_for_motion(true);
  wrapped.set_imu_identity(4, 0x68, 0);
  reading.at_ms = 0xfffffff9U;
  wrapped.set_imu(reading);
  CHECK(wrapped.imu_fresh(0xfffffffbU));
  reading.at_ms = 3U;
  wrapped.set_imu(reading);
  CHECK(wrapped.imu_fresh(3U));
  reading.at_ms = 0xfffffffaU; // pre-wrap packet arriving after wrap
  wrapped.set_imu(reading);
  CHECK(!wrapped.imu_fresh(4U));
  reading.at_ms = 5U;
  wrapped.set_imu(reading);
  CHECK(wrapped.imu_fresh(5U));
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


static void guarded_dc_dock_loss_latches_until_fresh_local_usb_rearm() {
  using desk_robot::BodyControl;
  using desk_robot::BodyProfile;
  // Three independent acquisition failures, not three replays of one run.
  for (int failure = 0; failure < 3; ++failure) {
    desk_robot::CliffGuard guard;
    CHECK(guard.configure(config()));
    fresh(guard, 100);
    BodyControl body(BodyProfile::DcGuarded, &guard);
    body.require_dock_monitor(true);
    desk_robot::AccessoryReadings readings{};
    auto& dock = readings.dock;
    dock.present = dock.valid = true;
    dock.sample_seq = 1;
    dock.at_ms = 100;
    body.set_accessories(readings, 100);
    CHECK(send(body, "rearm", 100, true) == "OK rearm");
    CHECK(send(body, "arm", 100) == "OK arm");
    CHECK(send(body, "drive 20 20 200", 101).find("OK drive") == 0);
    CHECK(body.state().armed && body.state().servos_attached);
    CHECK(body.state().left == 20 && body.state().right == 20);

    std::uint32_t lost_at = 102;
    if (failure == 0) {
      dock.valid = false;  // a failed GPIOA I2C transaction
      body.set_accessories(readings, lost_at);
    } else if (failure == 1) {
      dock.present = false;  // physical expander unplug or bus loss
      body.set_accessories(readings, lost_at);
    } else {
      lost_at = 601; // >500 ms after the last real independent read
      fresh(guard, lost_at);
      body.tick(lost_at);
    }
    CHECK(!body.state().armed && body.state().servos_attached);
    CHECK(body.state().left == 0 && body.state().right == 0);
    const auto stopped_status = send(body, "status", lost_at);
    // When the GPIOA timeout also expires cliff samples, the independently
    // latched cliff failure takes precedence in reported status. The dock
    // latch must nevertheless reject all remote ARM requests below.
    CHECK(stopped_status.find("\"ready\":false") != std::string::npos);
    if (failure == 2) {
      CHECK(stopped_status.find("\"fault\":\"stale_sample\"") !=
            std::string::npos);
    } else {
      CHECK(stopped_status.find("dock_monitor_latched") !=
            std::string::npos);
    }

    desk_robot::LineReceiver head, usb(true);
    auto request = [&](desk_robot::LineReceiver& receiver,
                       const char* line, std::uint32_t now_ms) {
      char response[desk_robot::kReplyCapacity]{};
      for (char c : std::string(line) + "\n") {
        receiver.feed(c, now_ms, body, response, sizeof(response));
      }
      return std::string(response);
    };
    CHECK(request(head, "arm", lost_at) == "ERR arm dock_monitor_latched");
    CHECK(request(head, "rearm", lost_at) == "ERR rearm local_only");

    // Replaying the last acknowledged, unseated GPIOA does not prove that
    // an expander has recovered after the failed acquisition.
    dock.present = dock.valid = true;
    body.set_accessories(readings, lost_at + 1);
    CHECK(request(head, "arm", lost_at + 1) ==
          "ERR arm dock_monitor_latched");
    if (failure == 2) {
      CHECK(request(usb, "rearm", lost_at + 1) ==
            "ERR rearm dock_gpio_missing_or_stale");
    } else {
      CHECK(request(usb, "rearm", lost_at + 1) ==
            "ERR rearm dock_monitor_no_new_sample");
    }
    CHECK(!body.state().armed);

    // Only a genuinely later, fresh, fully unseated GPIOA transaction plus
    // an explicit LOCAL USB action may authorize a NEW motion session.
    dock.sample_seq = 2;
    dock.at_ms = lost_at + 2;
    fresh(guard, lost_at + 2);
    body.set_accessories(readings, lost_at + 2);
    CHECK(send(body, "status", lost_at + 2).find("\"ready\":false") !=
          std::string::npos);
    CHECK(request(head, "arm", lost_at + 3) ==
          "ERR arm dock_monitor_latched");
    CHECK(request(usb, "rearm", lost_at + 3) == "OK rearm");
    CHECK(!body.state().armed && body.state().left == 0 &&
          body.state().right == 0 && body.state().servos_attached);
    CHECK(request(head, "arm", lost_at + 3) == "OK arm");
    CHECK(body.state().left == 0 && body.state().right == 0);
    CHECK(send(body, "disarm", lost_at + 4) == "OK disarm");
  }
}

static void repeated_dock_loss_retires_last_trusted_gpioa_acquisition() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 100);
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcGuarded, &guard);
  // Even an optional expander becomes compulsory once observed.
  desk_robot::AccessoryReadings readings{};
  readings.dock.present = readings.dock.valid = true;
  readings.dock.sample_seq = 10;
  readings.dock.at_ms = 100;
  body.set_accessories(readings, 100);
  CHECK(send(body, "rearm", 100, true) == "OK rearm");
  CHECK(send(body, "arm", 100) == "OK arm");
  CHECK(send(body, "drive 20 20 150", 100).find("OK drive") == 0);

  // Complete disappearance of the formerly installed expander is a fault
  // even without a separate profile-level require_dock_monitor flag.
  const desk_robot::AccessoryReadings missing{};
  body.set_accessories(missing, 101);
  CHECK(!body.state().armed && body.state().left == 0);
  CHECK(send(body, "arm", 101) == "ERR arm dock_monitor_latched");

  readings.dock.sample_seq = 11;
  readings.dock.at_ms = 102;
  body.set_accessories(readings, 102);
  // A second failure before USB recovery retires the newer acquisition.
  body.set_accessories(missing, 103);
  body.set_accessories(readings, 104);
  CHECK(send(body, "rearm", 104, true) ==
        "ERR rearm dock_monitor_no_new_sample");

  readings.dock.sample_seq = 12;
  readings.dock.at_ms = 105;
  body.set_accessories(readings, 105);
  fresh(guard, 105);
  CHECK(send(body, "rearm", 105, true) == "OK rearm");
  CHECK(send(body, "arm", 105) == "OK arm");
  CHECK(body.state().left == 0 && body.state().right == 0);
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
  sample.code = sample.left_code = sample.right_code = 0xcb34ed12U;
  body.set_terminal_ir(sample);
  const std::string data = send(body, "ir", 100);
  CHECK(data.find("\"match\":true") != std::string::npos);
  CHECK(data.find("\"left_seq\":9") != std::string::npos);
  CHECK(data.find("\"right_seq\":12") != std::string::npos);
  CHECK(data.find("\"left_code\":" + std::to_string(sample.code)) != std::string::npos);
  CHECK(data.find("\"right_code\":" + std::to_string(sample.code)) != std::string::npos);
  CHECK(data.find("\"motor_authorized\":false") != std::string::npos);
  CHECK(data.find("\"charging_authorized\":false") != std::string::npos);
  CHECK(!body.state().armed);
  CHECK(body.state().left == 0 && body.state().right == 0);
  CHECK(send(body, "ir 1", 101) == "ERR ir bad_arguments");
  // Even a matched NEC code is never a local calibration or arm permit.
  CHECK(send(body, "drive 20 20 100", 102) != "OK drive left=20 right=20 ms=100");
  sample.left_fresh = sample.same_code = false;
  sample.code = sample.left_code = 0;
  body.set_terminal_ir(sample);
  const auto single = send(body, "ir", 103);
  CHECK(single.find("\"match\":false") != std::string::npos);
  CHECK(single.find("\"left_code\":0") != std::string::npos);
  CHECK(single.find("\"right_code\":" + std::to_string(sample.right_code)) != std::string::npos);
}

static void belly_adc_does_not_refresh_stale_jaw_sample() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.set_boot_epoch(123U);
  desk_robot::AccessoryReadings readings{};
  readings.force.present = readings.force.valid = true;
  readings.force.valid_mask = 3U;
  readings.force.adc[0] = 111;
  readings.force.adc[1] = 555;
  readings.force.belly_sample_seq = 2U;
  readings.force.belly_at_ms = 100U;
  readings.force.jaw_sample_seq = 4U;
  readings.force.jaw_at_ms = readings.force.at_ms = 100U;
  body.set_accessories(readings, 100U);
  const auto initial = send(body, "aux", 120U);
  CHECK(initial.find(
      "\"belly_seq\":2,\"belly_age_ms\":20,\"belly_valid\":true")
        != std::string::npos);
  CHECK(initial.find(
      "\"jaw_seq\":4,\"boot_id\":123,\"jaw_age_ms\":20,\"jaw_valid\":true,\"valid\":true")
        != std::string::npos);
  // Belly conversion advances to 700ms while jaw stays at 100ms (stale > 500ms).
  // Belly must remain independently valid while jaw and composite valid are false.
  readings.force.belly_sample_seq = 3U;
  readings.force.belly_at_ms = 700U;
  readings.force.at_ms = 700U;
  body.set_accessories(readings, 700U);
  const auto stale_jaw = send(body, "aux", 700U);
  CHECK(stale_jaw.find(
      "\"belly_seq\":3,\"belly_age_ms\":0,\"belly_valid\":true")
        != std::string::npos);
  CHECK(stale_jaw.find(
      "\"jaw_seq\":4,\"boot_id\":123,\"jaw_age_ms\":600,\"jaw_valid\":false,\"valid\":false")
        != std::string::npos);
  // Jaw advances to 701ms, recovering jaw and composite validity.
  readings.force.jaw_sample_seq = 5U;
  readings.force.jaw_at_ms = 701U;
  body.set_accessories(readings, 701U);
  const auto recovered_jaw = send(body, "aux", 702U);
  CHECK(recovered_jaw.find(
      "\"belly_seq\":3,\"belly_age_ms\":2,\"belly_valid\":true")
        != std::string::npos);
  CHECK(recovered_jaw.find(
      "\"jaw_seq\":5,\"boot_id\":123,\"jaw_age_ms\":1,\"jaw_valid\":true,\"valid\":true")
        != std::string::npos);
  // Electrical clipping on jaw invalidates jaw and composite valid, but belly remains valid.
  for (const int endpoint : {-32768, 32767}) {
    readings.force.adc[1] = static_cast<std::int16_t>(endpoint);
    readings.force.jaw_sample_seq += 1U;
    readings.force.jaw_at_ms = readings.force.at_ms = 703U;
    body.set_accessories(readings, 703U);
    const auto clipped = send(body, "aux", 704U);
    CHECK(clipped.find("\"belly_valid\":true") != std::string::npos);
    CHECK(clipped.find(
        "\"jaw_age_ms\":1,\"jaw_valid\":false,\"valid\":false,\"calibrated\":false")
          != std::string::npos);
    CHECK(clipped.find(std::string(",") + std::to_string(endpoint) + "]") !=
          std::string::npos);
  }
  // Conversely, clipping on belly invalidates belly and composite valid, while jaw remains valid.
  for (const int endpoint : {-32768, 32767}) {
    readings.force.adc[0] = static_cast<std::int16_t>(endpoint);
    readings.force.adc[1] = 555;
    if (endpoint == -32768) {
      // Restoring an earlier clipped jaw value needs a fresh channel-1
      // conversion rather than relabeling the last failed sample.
      ++readings.force.jaw_sample_seq;
      readings.force.jaw_at_ms = 705U;
    }
    readings.force.belly_sample_seq += 1U;
    readings.force.belly_at_ms = readings.force.at_ms = 705U;
    body.set_accessories(readings, 705U);
    const auto clipped_belly = send(body, "aux", 706U);
    CHECK(clipped_belly.find("\"belly_valid\":false") != std::string::npos);
    CHECK(clipped_belly.find("\"jaw_valid\":true,\"valid\":false") != std::string::npos);
    CHECK(clipped_belly.find(std::string("[") + std::to_string(endpoint) + ",") !=
          std::string::npos);
  }
  CHECK(!body.state().armed);
}

static void jaw_aux_and_motion_require_present_independent_channel() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  desk_robot::AccessoryReadings readings{};
  auto& f = readings.force;
  f.valid = true;
  f.valid_mask = 2U;
  f.adc[1] = 555;
  f.jaw_sample_seq = 1U;
  f.jaw_at_ms = 100U;
  const auto check = [&](std::uint32_t now, bool expected) {
    body.set_accessories(readings, now);
    CHECK(body.grip_feedback_fresh(now) == expected);
    const auto aux = send(body, "aux", now);
    CHECK(aux.find(expected ? "\"jaw_valid\":true" : "\"jaw_valid\":false") !=
          std::string::npos);
  };
  check(101U, false);  // Absent ADC, contradictory cached fields.
  f.present = true;
  f.valid_mask = 0U;
  check(102U, false);  // Composite validity is not channel evidence.
  f.valid_mask = 1U;
  check(103U, false);  // Belly alone cannot authorize a jaw.
  f.valid = false;
  f.valid_mask = 2U;
  ++f.jaw_sample_seq;
  f.jaw_at_ms = 104U;
  check(104U, true);   // Independent jaw remains usable without belly.
  f.valid = true;
  f.valid_mask = 0U;
  check(105U, false);
  f.valid_mask = 2U;
  check(106U, false);  // Cached conversion cannot restore lost validity.
  ++f.jaw_sample_seq;
  f.jaw_at_ms = 107U;
  check(107U, true);
}

static void belly_acquisition_identity_cannot_forge_contact() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.set_boot_epoch(123U);
  desk_robot::AccessoryReadings readings{};
  auto& f = readings.force;
  f.present = f.valid = true;
  f.valid_mask = 3U;
  f.adc[0] = 111;
  f.adc[1] = 555;
  f.belly_sample_seq = 10U;
  f.jaw_sample_seq = 1U;
  f.belly_at_ms = f.jaw_at_ms = f.at_ms = 100U;
  body.set_accessories(readings, 100U);
  CHECK(send(body, "aux", 101U).find("\"belly_valid\":true") !=
        std::string::npos);
  // Altered ADC under the same completed conversion cannot forge contact.
  f.adc[0] = 333;
  body.set_accessories(readings, 110U);
  const auto changed = send(body, "aux", 111U);
  CHECK(changed.find("\"belly_valid\":false") != std::string::npos);
  CHECK(changed.find("\"jaw_valid\":true,\"valid\":false") !=
        std::string::npos);
  f.adc[0] = 111;  // cached previously good value is not a recovery
  body.set_accessories(readings, 112U);
  CHECK(send(body, "aux", 113U).find("\"belly_valid\":false") !=
        std::string::npos);
  f.adc[0] = 444;
  f.belly_sample_seq = 11U;
  f.belly_at_ms = 114U;
  body.set_accessories(readings, 114U);
  CHECK(send(body, "aux", 115U).find("\"belly_valid\":true") !=
        std::string::npos);
  f.adc[0] = 555;
  f.belly_sample_seq = 10U;  // backwards sequence, newer timestamp
  f.belly_at_ms = 116U;
  body.set_accessories(readings, 116U);
  CHECK(send(body, "aux", 117U).find("\"belly_valid\":false") !=
        std::string::npos);
  f.adc[0] = 666;
  f.belly_sample_seq = 12U;
  f.belly_at_ms = 118U;
  body.set_accessories(readings, 118U);
  CHECK(send(body, "aux", 119U).find("\"belly_valid\":true") !=
        std::string::npos);

  // Sequence and hardware acquisition time can both legitimately wrap.
  desk_robot::BodyControl wrapped(desk_robot::BodyProfile::DcPwm);
  const std::uint32_t near_wrap = UINT32_MAX - 4U;
  f.adc[0] = 777;
  f.belly_sample_seq = UINT32_MAX;
  f.belly_at_ms = near_wrap;
  f.jaw_sample_seq = UINT32_MAX;
  f.jaw_at_ms = f.at_ms = near_wrap;
  wrapped.set_accessories(readings, near_wrap);
  CHECK(send(wrapped, "aux", near_wrap).find("\"belly_valid\":true") !=
        std::string::npos);
  f.belly_sample_seq = 1U;
  f.belly_at_ms = 4U;
  f.adc[0] = 888;
  wrapped.set_accessories(readings, 4U);
  CHECK(send(wrapped, "aux", 5U).find("\"belly_valid\":true") !=
        std::string::npos);
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
  // The forged timestamp freezes the old target; a newly acquired reading
  // does not revive that cancelled motion without a fresh grip command.
  CHECK(send(body, "grip 120", 281) == "OK grip angle=120");
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


static void jaw_acquisition_identity_prevents_forged_force_relief() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::DcPwm);
  body.require_grip_feedback(true);
  CHECK(body.configure_jaw_force_limits({60, 120, 1000, 1, 300}));
  CHECK(send(body, "arm", 100) == "OK arm");
  desk_robot::AccessoryReadings r{};
  r.force.present = r.force.valid = true;
  r.force.valid_mask = 2U;
  r.force.adc[1] = 1000;
  r.force.jaw_sample_seq = 10U;
  r.force.jaw_at_ms = r.force.at_ms = 100U;
  body.set_accessories(r, 100U);
  CHECK(send(body, "grip 120", 100) == "OK grip angle=120");
  body.tick(160);
  CHECK(body.state().grip == 93);

  // A cached reading is allowed. Altering its force value is not.
  body.set_accessories(r, 161U);
  CHECK(body.grip_feedback_fresh(161U));
  r.force.adc[1] = 900; // falsely claims less contact force
  body.set_accessories(r, 162U);
  CHECK(!body.grip_feedback_fresh(162U));
  CHECK(body.state().grip_target == 93);
  CHECK(body.state().armed && body.state().servos_attached);
  CHECK(send(body, "grip 120", 162) ==
        "ERR grip force_missing_or_stale");
  CHECK(send(body, "aux", 162).find(
      "\"jaw_valid\":false") != std::string::npos);
  r.force.adc[1] = 1000; // reverting cached data is not recovery
  body.set_accessories(r, 163U);
  CHECK(!body.grip_feedback_fresh(163U));

  r.force.jaw_sample_seq = 11U;
  r.force.jaw_at_ms = r.force.at_ms = 164U;
  body.set_accessories(r, 164U);
  CHECK(body.grip_feedback_fresh(164U));
  CHECK(body.state().grip_target == 93);
  CHECK(send(body, "grip 120", 164) == "OK grip angle=120");
  body.tick(200);
  CHECK(body.state().grip == 95);

  // Sequence-only and time-only changes are not completed conversions.
  r.force.jaw_sample_seq = 12U;
  body.set_accessories(r, 201U);
  CHECK(!body.grip_feedback_fresh(201U));
  CHECK(body.state().grip_target == 95);
  r.force.jaw_at_ms = r.force.at_ms = 202U;
  r.force.jaw_sample_seq = 11U;
  body.set_accessories(r, 202U);
  CHECK(!body.grip_feedback_fresh(202U));
  r.force.jaw_sample_seq = 12U;
  body.set_accessories(r, 203U);
  CHECK(body.grip_feedback_fresh(203U));
  CHECK(send(body, "grip 120", 203) == "OK grip angle=120");

  r.force.jaw_sample_seq = 11U; // backward acquisition
  r.force.jaw_at_ms = r.force.at_ms = 164U;
  body.set_accessories(r, 204U);
  CHECK(!body.grip_feedback_fresh(204U));
  CHECK(body.state().grip_target == body.state().grip);
  r.force.jaw_sample_seq = 13U;
  r.force.jaw_at_ms = r.force.at_ms = 205U;
  body.set_accessories(r, 205U);
  CHECK(body.grip_feedback_fresh(205U));

  // A real uint32 sequence and millis rollover is forward progress.
  desk_robot::BodyControl wrapped;
  r.force.jaw_sample_seq = 0xffffffffU;
  r.force.jaw_at_ms = 0xfffffff9U;
  wrapped.set_accessories(r, 0xfffffffbU);
  CHECK(wrapped.grip_feedback_fresh(0xfffffffbU));
  r.force.jaw_sample_seq = 1U;
  r.force.jaw_at_ms = 3U;
  wrapped.set_accessories(r, 3U);
  CHECK(wrapped.grip_feedback_fresh(3U));
  r.force.jaw_sample_seq = 0xffffffffU; // delayed pre-wrap replay
  r.force.jaw_at_ms = 0xfffffffaU;
  wrapped.set_accessories(r, 4U);
  CHECK(!wrapped.grip_feedback_fresh(4U));
  r.force.jaw_sample_seq = 2U;
  r.force.jaw_at_ms = 5U;
  wrapped.set_accessories(r, 5U);
  CHECK(wrapped.grip_feedback_fresh(5U));
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
  readings.force.valid_mask &= ~2U;
  body.set_accessories(readings, 121U);
  body.tick(140U);
  CHECK(body.state().grip == 89 && body.state().grip_target == 89);
  CHECK(body.state().armed && body.state().servos_attached);
  CHECK(send(body, "grip 60", 140U) == "ERR grip force_missing_or_stale");
  readings.force.valid = true;
  readings.force.valid_mask |= 2U;
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
  // Boundary check: delta == max_delta_adc - 1 (1299) admits closing; == max_delta_adc (1300) blocks.
  r.force.adc[1] = 1299;
  r.force.jaw_sample_seq = 5U;
  r.force.at_ms = r.force.jaw_at_ms = 241U;
  body.set_accessories(r, 241);
  CHECK(send(body, "grip 120", 241) == "OK grip angle=120");
  body.tick(260);
  CHECK(body.state().grip > 93);
  const int before_ceiling = body.state().grip;
  r.force.adc[1] = 1300;
  r.force.jaw_sample_seq = 6U;
  r.force.at_ms = r.force.jaw_at_ms = 261U;
  body.set_accessories(r, 261);
  body.tick(280);
  CHECK(body.state().grip == before_ceiling && body.state().grip_target == before_ceiling);
  CHECK(send(body, "grip 120", 280) == "ERR grip local_force_limit_or_reversal");
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


static void stale_range_veto_survives_saturated_uart() {
  struct Serial {
    int free = 0;
    std::string sent;
    int availableForWrite() const { return free; }
    std::size_t write(const std::uint8_t* data, std::size_t count) {
      CHECK(count <= static_cast<std::size_t>(free));
      sent.append(reinterpret_cast<const char*>(data), count);
      free -= static_cast<int>(count);
      return count;
    }
  };
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 100);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  CHECK(send(body, "rearm", 100, true) == "OK rearm");
  CHECK(send(body, "arm", 100) == "OK arm");
  char reply[desk_robot::kReplyCapacity]{};
  const char drive[] = "drive 40 40 250";
  body.execute(drive, sizeof(drive) - 1, 199, reply, sizeof(reply));
  CHECK(std::string(reply) == "OK drive left=40 right=40 ms=250");
  CHECK(body.state().armed && body.state().left == 40);
  const auto status = send(body, "status", 199);
  desk_robot::ReplyTxQueue<2 * (desk_robot::kReplyCapacity + 2)> head, usb;
  Serial head_serial, usb_serial;
  for (int i = 0; i < 16; ++i) {
    head.enqueue_line(status.c_str());
    usb.enqueue_line(status.c_str());
  }
  CHECK(head.dropped() > 0 && usb.dropped() > 0);
  head_serial.free = 7;
  CHECK(head.drain(head_serial) == 7);
  CHECK(head.drain(head_serial) == 0 && usb.drain(usb_serial) == 0);

  // The final output checkpoint must stop independently of both UARTs.
  body.tick(200);
  body.veto_unapplied_motion_ack(reply, sizeof(reply));
  CHECK(std::string(reply) == "ERR drive safety_interlock");
  CHECK(!body.state().armed && body.state().left == 0 && body.state().right == 0);
  CHECK(body.state().servos_attached);
  CHECK(guard.fault() == desk_robot::CliffFault::StaleSample);
  body.sample_bumper_input(true);
  guard.bus_fault();
  CHECK(guard.fault() == desk_robot::CliffFault::StaleSample);
  CHECK(head.enqueue_priority_line(send(body, "stop", 200).c_str()));
  CHECK(usb.enqueue_priority_line(send(body, "halt", 200).c_str()));
  CHECK(head.drain(head_serial) == 0 && usb.drain(usb_serial) == 0);
  for (int i = 0; i < 256 && (head.pending() || usb.pending()); ++i) {
    head_serial.free = usb_serial.free = 32;
    CHECK(head.drain(head_serial) <= 32 && usb.drain(usb_serial) <= 32);
  }
  CHECK(head.pending() == 0 && usb.pending() == 0);
  const auto prefix = status + "\r\nOK stop\r\n";
  CHECK(head_serial.sent.compare(0, prefix.size(), prefix) == 0);
  CHECK(usb_serial.sent.compare(0, 9, "OK halt\r\n") == 0);
  body.sample_bumper_input(false);
  fresh(guard, 201);
  CHECK(send(body, "rearm", 201) == "ERR rearm local_only");
  const auto recovered = send(body, "rearm", 201, true);
  CHECK(recovered == "OK rearm");
  std::snprintf(reply, sizeof(reply), "%s", recovered.c_str());
  body.veto_unapplied_motion_ack(reply, sizeof(reply));
  CHECK(std::string(reply) == "OK rearm" && !body.state().armed);
  body.tick(301);
  body.veto_unapplied_motion_ack(reply, sizeof(reply));
  CHECK(std::string(reply) == "ERR rearm safety_interlock");
}

static void jaw_expiry_during_output_vetoes_accepted_target() {
  for (const std::uint32_t start : {100U, 0xffffff05U}) {
    desk_robot::CliffGuard guard;
    CHECK(guard.configure(config()));
    fresh(guard, start);
    desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
    body.require_grip_feedback(true);
    CHECK(body.configure_jaw_force_limits({60, 120, 1000, 1, 300}));
    desk_robot::AccessoryReadings r{};
    r.force.present = r.force.valid = true;
    r.force.valid_mask = 2U;
    r.force.adc[1] = 1000;
    r.force.jaw_sample_seq = 1U;
    r.force.at_ms = r.force.jaw_at_ms = start;
    body.set_accessories(r, start);
    CHECK(send(body, "rearm", start, true) == "OK rearm");
    CHECK(send(body, "arm", start) == "OK arm");
    // Keep independent floor evidence fresh while allowing jaw feedback
    // to reach its own 500 ms freshness boundary.
    for (std::uint32_t delta = 90U; delta < 499U; delta += 90U)
      fresh(guard, start + delta);
    fresh(guard, start + 499U);
    char reply[128]{};
    const char command[] = "grip 120";
    body.execute(command, sizeof(command) - 1, start + 499U, reply, sizeof(reply));
    CHECK(std::string(reply) == "OK grip angle=120");
    body.veto_unapplied_motion_ack(reply, sizeof(reply));
    CHECK(std::string(reply) == "OK grip angle=120");
    body.tick(start + 500U);
    CHECK(body.state().armed && body.state().servos_attached);
    CHECK(guard.fault() == desk_robot::CliffFault::None);
    CHECK(body.state().grip_target == body.state().grip);
    CHECK(body.state().grip_target != 120);
    body.veto_unapplied_motion_ack(reply, sizeof(reply));
    CHECK(std::string(reply) == "ERR grip safety_interlock");
    // Other valid targets and inert replies are not rewritten.
    std::snprintf(reply, sizeof(reply), "OK lift angle=%d", body.state().lift_target);
    const std::string lift_reply(reply);
    body.veto_unapplied_motion_ack(reply, sizeof(reply));
    CHECK(std::string(reply) == lift_reply);
    std::snprintf(reply, sizeof(reply), "OK halt");
    body.veto_unapplied_motion_ack(reply, sizeof(reply));
    CHECK(std::string(reply) == "OK halt");
  }
}

void output_fault_vetoes_all_motion_acknowledgments() {
  using desk_robot::MotionAckVeto;
  const char* acks[] = {"OK arm", "OK rearm", "OK keepalive",
                       "OK drive 20 20 100", "OK lift 90", "OK grip 90"};
  const char* commands[] = {"arm", "rearm", "keepalive", "drive", "lift", "grip"};
  for (auto fault : {MotionAckVeto::BumperActive, MotionAckVeto::MotorWatchdogLatched,
                     MotionAckVeto::TouchActive, MotionAckVeto::SafetyInterlock}) {
    const std::string reason = fault == MotionAckVeto::BumperActive ? "bumper_active" :
        fault == MotionAckVeto::TouchActive ? "touch_active" :
        fault == MotionAckVeto::MotorWatchdogLatched ? "motor_watchdog_latched" :
        "safety_interlock";
    for (std::size_t i = 0; i < 6; ++i) {
      char reply[128]{};
      std::snprintf(reply, sizeof(reply), "%s", acks[i]);
      desk_robot::veto_motion_ack(reply, sizeof(reply), fault);
      CHECK(std::string(reply) == std::string("ERR ") + commands[i] + " " + reason);
    }
    for (const char* ack : {"OK stop", "OK halt", "OK disarm", "OK ping",
                            "ERR drive disarmed", "{\"armed\":false}"}) {
      char reply[128]{};
      std::snprintf(reply, sizeof(reply), "%s", ack);
      desk_robot::veto_motion_ack(reply, sizeof(reply), fault);
      CHECK(std::string(reply) == ack);
    }
    char incomplete[] = {'O', 'K'};
    desk_robot::veto_motion_ack(incomplete, sizeof(incomplete), fault);
    CHECK(incomplete[0] == 'O' && incomplete[1] == 'K');
    desk_robot::veto_motion_ack(nullptr, 0, fault);
  }
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

static void raw_bumper_bounce_resets_both_edge_classifiers() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 0);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.sample_optional_inputs(1U, false, false, false);
  CHECK(send(body, "rearm", 0, true) == "OK rearm");
  CHECK(send(body, "arm", 0) == "OK arm");
  CHECK(send(body, "drive 30 30 250", 0).find("OK drive") == 0);
  body.sample_bumper_input(true);
  CHECK(!body.state().armed && body.state().left == 0 && body.state().right == 0);
  CHECK(body.state().servos_attached);
  // Three classifier calls seeing HIGH are not consecutive if the fast
  // safety sampler observed a LOW transition between each pair.
  for (int i = 0; i < 3; ++i) {
    body.sample_optional_inputs(1U, true, false, false);
    CHECK(body.state().bumper_events == 0 && !body.state().bumper_active);
    body.sample_bumper_input(false);
    body.sample_bumper_input(true);
  }
  // Fast repeated HIGH reads alone never advance the event classifier.
  for (int i = 0; i < 20; ++i) body.sample_bumper_input(true);
  CHECK(body.state().bumper_events == 0);
  for (int i = 0; i < 3; ++i) {
    body.sample_optional_inputs(1U, true, false, false);
    CHECK(body.state().bumper_events == (i == 2 ? 1U : 0U));
  }
  // A momentary NC closure must not count toward stable release either.
  for (int i = 0; i < 3; ++i) {
    body.sample_optional_inputs(1U, false, false, false);
    CHECK(body.state().bumper_active);
    body.sample_bumper_input(true);
    body.sample_bumper_input(false);
  }
  for (int i = 0; i < 3; ++i) {
    body.sample_optional_inputs(1U, false, false, false);
    CHECK(body.state().bumper_active == (i < 2));
  }
  CHECK(body.state().bumper_events == 1);
  CHECK(send(body, "arm", 20) == "ERR arm bumper_latched");
  CHECK(send(body, "rearm", 20) == "ERR rearm local_only");
  CHECK(send(body, "rearm", 20, true) == "OK rearm");
  CHECK(!body.state().armed && body.state().left == 0 && body.state().right == 0);
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

// A cliff/bumper/CPU fault cannot be cleared at a voltage too low to arm.
static void low_voltage_cannot_clear_unrelated_recovery_latches() {
  using desk_robot::BodyProfile;
  for (const auto profile : {BodyProfile::StepperGuarded, BodyProfile::DcGuarded}) {
    for (bool required : {false, true}) {
      desk_robot::CliffGuard guard;
      CHECK(guard.configure(config()));
      fresh(guard, 100);
      desk_robot::BodyControl body(profile, &guard);
      body.require_fuel_monitor(required);
      desk_robot::AccessoryReadings readings{};
      auto& fuel = readings.gauge;
      fuel.fuel_present = fuel.fuel_valid = true;
      fuel.fuel_sample_seq = 1;
      fuel.fuel_at_ms = 100;
      fuel.cell_mv = 3350;
      body.set_accessories(readings, 100);
      CHECK(send(body, "rearm", 100, true) == "OK rearm");
      CHECK(send(body, "arm", 100) == "OK arm");
      CHECK(send(body, "drive 30 30 250", 100).find("OK drive") == 0);
      guard.sample(0, 80, true, 101);
      body.tick(101);
      body.sample_bumper_input(true);
      body.sample_bumper_input(false);
      body.motor_watchdog_trip();
      fresh(guard, 102);
      fuel.fuel_sample_seq = 2;
      fuel.fuel_at_ms = 102;
      fuel.cell_mv = 3250;
      body.set_accessories(readings, 102);
      CHECK(send(body, "rearm", 102, true) == "ERR rearm battery_unsafe_or_stale");
      CHECK(!guard.evaluate(102) && !body.state().armed);
      CHECK(body.state().left == 0 && body.state().right == 0);
      fuel.fuel_sample_seq = 3;
      fuel.fuel_at_ms = 103;
      fuel.cell_mv = 3350;
      body.set_accessories(readings, 103);
      CHECK(send(body, "arm", 103) != "OK arm");
      CHECK(send(body, "drive 30 30 250", 103) == "ERR drive disarmed");
      CHECK(send(body, "rearm", 103) == "ERR rearm local_only");
      CHECK(send(body, "rearm", 103, true) == "OK rearm");
      CHECK(!body.state().armed && body.state().servos_attached);
      CHECK(send(body, "arm", 103) == "OK arm");
      CHECK(body.state().left == 0 && body.state().right == 0);
      CHECK(body.drive_remaining(103) == 0);
    }
  }
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
  CHECK(send(body, "rearm", 100, true) == "ERR rearm battery_unsafe_or_stale");
  CHECK(!guard.evaluate(100));
  CHECK(!body.state().armed);
  // Raising voltage does not retroactively authorize recovery.
  CHECK(send(body, "arm", 100) == "ERR arm safety_interlock");
  CHECK(send(body, "status", 100).find("\"ready\":false") !=
        std::string::npos);
  CHECK(send(body, "status", 100).find("\"fault\":\"missing_sample\"") !=
        std::string::npos);

  readings.gauge.fuel_sample_seq = 2;
  readings.gauge.fuel_at_ms = 101;
  readings.gauge.cell_mv = 3350;
  body.set_accessories(readings, 101);
  CHECK(send(body, "arm", 101) == "ERR arm safety_interlock");
  CHECK(send(body, "rearm", 101) == "ERR rearm local_only");
  CHECK(send(body, "rearm", 101, true) == "OK rearm");
  CHECK(send(body, "status", 101).find("\"ready\":true") !=
        std::string::npos);
  CHECK(send(body, "arm", 101) == "OK arm");
  // Once boot recovery is authorized, the stricter ARM threshold still
  // applies independently of the lower emergency trip voltage.
  readings.gauge.fuel_sample_seq = 3;
  readings.gauge.fuel_at_ms = 102;
  readings.gauge.cell_mv = 3250;
  body.set_accessories(readings, 102);
  CHECK(send(body, "status", 102).find("\"ready\":false") != std::string::npos);
  CHECK(send(body, "status", 102).find("\"fault\":\"battery_low\"") !=
        std::string::npos);
  CHECK(send(body, "arm", 102) == "ERR arm battery_low");
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
  // Even when voltage is below the ordinary 3300 mV arm threshold,
  // the operator must see the persistent fault and USB-only recovery.
  CHECK(send(body, "status", 2).find(
      "\"fault\":\"battery_low_latched\"") != std::string::npos);
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



static void optional_gauge_low_latch_requires_trusted_recovery() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 100);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  desk_robot::AccessoryReadings readings{};
  readings.gauge.fuel_present = readings.gauge.fuel_valid = true;
  readings.gauge.cell_mv = 3800;
  readings.gauge.soc_centi = 5000;
  readings.gauge.fuel_sample_seq = 10;
  readings.gauge.fuel_at_ms = 100;
  body.set_accessories(readings, 100);
  CHECK(send(body, "rearm", 100, true) == "OK rearm");
  CHECK(send(body, "arm", 100) == "OK arm");
  CHECK(send(body, "drive 30 30 150", 100).find("OK drive") == 0);

  // A suspicious low value must still stop wheels, but zeroed identity
  // must not permit rearm using the preceding cached high-voltage read.
  auto low = readings;
  low.gauge.fuel_present = false;
  low.gauge.cell_mv = 0;
  low.gauge.fuel_sample_seq = 0;
  low.gauge.fuel_at_ms = 0;
  body.set_accessories(low, 101);
  CHECK(!body.state().armed && body.state().left == 0);
  CHECK(send(body, "arm", 101) == "ERR arm battery_low_latched");
  body.set_accessories(readings, 102);
  CHECK(send(body, "rearm", 102, true) ==
        "ERR rearm battery_unsafe_or_stale");

  readings.gauge.fuel_sample_seq = 11;
  readings.gauge.fuel_at_ms = 103;
  body.set_accessories(readings, 103);
  readings.gauge.soc_centi = 6000; // altered identity, not a new conversion
  body.set_accessories(readings, 104);
  CHECK(!body.fuel_monitor_fresh(104));
  CHECK(send(body, "rearm", 104, true) ==
        "ERR rearm battery_unsafe_or_stale");

  readings.gauge.fuel_sample_seq = 12;
  readings.gauge.fuel_at_ms = 105;
  body.set_accessories(readings, 105);
  fresh(guard, 105);
  CHECK(send(body, "rearm", 105, true) == "OK rearm");
  CHECK(send(body, "arm", 105) == "OK arm");
  CHECK(body.state().left == 0 && body.state().right == 0);
}

static void fuel_voltage_replay_cannot_rearm_or_restore_drive() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 100);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.require_fuel_monitor(true);
  desk_robot::AccessoryReadings readings{};
  readings.gauge.fuel_present = readings.gauge.fuel_valid = true;
  readings.gauge.fuel_sample_seq = 10;
  readings.gauge.fuel_at_ms = 100;
  readings.gauge.cell_mv = 3250; // below the new ARM minimum
  readings.gauge.soc_centi = 5000;
  body.set_accessories(readings, 100);
  CHECK(send(body, "rearm", 100, true) == "ERR rearm battery_unsafe_or_stale");
  CHECK(send(body, "arm", 100) == "ERR arm safety_interlock");
  CHECK(!guard.evaluate(100) && !body.state().armed);

  // A second caller must not relabel the same conversion as 3.8 V.
  readings.gauge.cell_mv = 3800;
  body.set_accessories(readings, 101);
  CHECK(!body.fuel_monitor_fresh(101));
  // The original optical boot latch remains the primary status fault.
  // The independent fuel latch must still reject ARM and local rearm.
  CHECK(send(body, "status", 101).find(
      "\"fault\":\"missing_sample\"") != std::string::npos);
  CHECK(send(body, "status", 101).find("\"ready\":false") != std::string::npos);
  CHECK(send(body, "arm", 101) == "ERR arm fuel_monitor_latched");
  CHECK(send(body, "rearm", 101, true) ==
        "ERR rearm fuel_monitor_missing_or_stale");

  // Only a genuinely newer conversion and local USB rearm restore motion.
  readings.gauge.fuel_sample_seq = 11;
  readings.gauge.fuel_at_ms = 102;
  body.set_accessories(readings, 102);
  CHECK(body.fuel_monitor_fresh(102));
  CHECK(send(body, "arm", 102) == "ERR arm fuel_monitor_latched");
  CHECK(send(body, "rearm", 102, true) == "OK rearm");
  CHECK(send(body, "arm", 102) == "OK arm");
  CHECK(send(body, "drive 30 30 150", 102).find("OK drive") == 0);
  body.set_accessories(readings, 103); // identical cached frame is permitted
  CHECK(body.state().armed && body.state().left == 30);

  readings.gauge.soc_centi = 6000; // same identity, contradictory SOC
  body.set_accessories(readings, 104);
  CHECK(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0 && body.state().servos_attached);
  CHECK(send(body, "arm", 104) == "ERR arm fuel_monitor_latched");
  readings.gauge.fuel_sample_seq = 10; // older, even if it looks plausible
  readings.gauge.fuel_at_ms = 100;
  body.set_accessories(readings, 105);
  CHECK(!body.fuel_monitor_fresh(105));
  readings.gauge.fuel_sample_seq = 12;
  readings.gauge.fuel_at_ms = 106;
  body.set_accessories(readings, 106);
  fresh(guard, 106);
  CHECK(send(body, "rearm", 106, true) == "OK rearm");
  CHECK(send(body, "arm", 106) == "OK arm");
  CHECK(body.state().left == 0 && body.state().right == 0);

  // The producer explicitly skips sequence zero on wrap. Both sequence
  // and millis wrap must preserve forward ordering, not old replays.
  desk_robot::BodyControl wrapped;
  wrapped.require_fuel_monitor(true);
  readings.gauge.fuel_sample_seq = 0xffffffffU;
  readings.gauge.fuel_at_ms = 0xfffffff9U;
  wrapped.set_accessories(readings, 0xfffffffbU);
  CHECK(wrapped.fuel_monitor_fresh(0xfffffffbU));
  readings.gauge.fuel_sample_seq = 1U;
  readings.gauge.fuel_at_ms = 3U;
  wrapped.set_accessories(readings, 3U);
  CHECK(wrapped.fuel_monitor_fresh(3U));
  readings.gauge.fuel_sample_seq = 0xffffffffU;
  readings.gauge.fuel_at_ms = 0xfffffffaU;
  wrapped.set_accessories(readings, 4U);
  CHECK(!wrapped.fuel_monitor_fresh(4U));
  readings.gauge.fuel_sample_seq = 2U;
  readings.gauge.fuel_at_ms = 5U;
  wrapped.set_accessories(readings, 5U);
  CHECK(wrapped.fuel_monitor_fresh(5U));
}

static void invalid_fuel_identity_cannot_rearm_from_cached_conversion() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 100);
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.require_fuel_monitor(true);
  desk_robot::AccessoryReadings readings{};
  readings.gauge.fuel_present = readings.gauge.fuel_valid = true;
  readings.gauge.cell_mv = 3800;
  readings.gauge.soc_centi = 5000;
  readings.gauge.fuel_sample_seq = 10;
  readings.gauge.fuel_at_ms = 100;
  body.set_accessories(readings, 100);
  CHECK(send(body, "rearm", 100, true) == "OK rearm");
  CHECK(send(body, "arm", 100) == "OK arm");
  CHECK(send(body, "drive 30 30 150", 100).find("OK drive") == 0);

  // An invalid identity must not move the fault recovery threshold back
  // to zero, even if the previously accepted cache is subsequently restored.
  auto invalid = readings;
  invalid.gauge.fuel_valid = false;
  invalid.gauge.fuel_sample_seq = 0;
  invalid.gauge.fuel_at_ms = 0;
  body.set_accessories(invalid, 101);
  CHECK(!body.state().armed && body.state().left == 0);
  body.set_accessories(readings, 102);
  CHECK(send(body, "rearm", 102, true) ==
        "ERR rearm fuel_monitor_no_new_sample");

  // A real new conversion followed by a second loss before local rearm
  // must advance the recovery threshold too, not reuse that conversion.
  readings.gauge.fuel_sample_seq = 11;
  readings.gauge.fuel_at_ms = 103;
  body.set_accessories(readings, 103);
  body.set_accessories(invalid, 104);
  body.set_accessories(readings, 105);
  CHECK(send(body, "rearm", 105, true) ==
        "ERR rearm fuel_monitor_no_new_sample");

  readings.gauge.fuel_sample_seq = 12;
  readings.gauge.fuel_at_ms = 106;
  body.set_accessories(readings, 106);
  fresh(guard, 106);
  CHECK(send(body, "rearm", 106, true) == "OK rearm");
  CHECK(send(body, "arm", 106) == "OK arm");
  CHECK(body.state().left == 0 && body.state().right == 0);
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
  dc.sample_touch_input(true, 1);
  dc.tick(1);
  CHECK(dc.state().left == 0 && dc.state().right == 0 && !dc.state().armed);
  CHECK(send(dc, "arm", 2) == "ERR arm touch_active");
  dc.sample_touch_input(false, 3);
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
  body.sample_touch_input(true, 1);
  CHECK(send(body, "status", 1).find("\"ready\":false") != std::string::npos);
  CHECK(send(body, "status", 1).find("\"fault\":\"touch_active\"") !=
        std::string::npos);
  CHECK(send(body, "arm", 1) == "ERR arm touch_active");
  body.sample_touch_input(false, 1);

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
  body.sample_touch_input(true, 4);
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

static void range_diagnostics_do_not_revive_after_full_millis_wrap() {
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded);
  body.sample_range_optics(0, 291, 17767, true, 60);
  body.sample_range_optics(5, 32, 1024, true, 60);
  body.sample_side_range(0, 125, true, 60);
  body.tick(259);
  CHECK(body.state().optical[0].valid);
  body.tick(260);
  CHECK(!body.state().optical[0].valid);
  body.tick(410);
  CHECK(body.state().optical[5].valid && body.state().side_valid[0]);
  body.tick(411);
  CHECK(!body.state().optical[5].valid && !body.state().side_valid[0]);
  body.tick(0x7fffffffU);
  body.tick(0xfffffff0U);
  body.tick(61);
  CHECK(send(body, "optics", 61).find(
      "\"present_mask\":33,\"valid_mask\":0") != std::string::npos);
  CHECK(send(body, "status", 61).find(
      "\"present_mask\":1,\"valid_mask\":0,\"motion_certified\":false") != std::string::npos);
  CHECK(body.state().optical[5].ambient_97 == 32);
  CHECK(body.state().side_mm[0] == 125);
  body.sample_range_optics(5, 33, 1025, true, 62);
  body.sample_side_range(0, 126, true, 62);
  CHECK(body.state().optical[5].valid && body.state().side_valid[0]);
  CHECK(!body.state().armed);
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

static void mpu_static_attitude_fails_closed_and_needs_usb_recovery() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 100);
  CHECK(guard.try_rearm(100));
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.require_imu_for_motion(true);
  body.require_imu_attitude_guard(true);
  body.set_imu_identity(4, 0x68, 0);
  desk_robot::BerryReading imu{};
  imu.model = desk_robot::BerryModel::Mpu6050;
  imu.valid = true;
  imu.low_g_status_valid = true;
  imu.accel[2] = 16384;
  imu.at_ms = 100;
  body.set_imu(imu);
  CHECK(send(body, "arm", 100) == "ERR arm imu_attitude_unqualified");
  CHECK(!body.configure_imu_attitude_limits({{0, 0, 16384}, 1000, 12000, 20000}));
  CHECK(body.configure_imu_attitude_limits({{0, 0, 16384}, 800, 12000, 20000}));
  CHECK(!body.configure_imu_attitude_limits({{0, 0, 16384}, 800, 12000, 20000}));
  imu.at_ms = 150;
  body.set_imu(imu);
  imu.at_ms = 200;
  body.set_imu(imu);
  fresh(guard, 200);
  CHECK(send(body, "rearm", 200, true) == "OK rearm");
  CHECK(send(body, "arm", 200) == "OK arm");
  CHECK(send(body, "drive 20 20 200", 200).find("OK drive") == 0);

  // A single tilt-shaped impulse followed by a recovered upright frame
  // cannot falsely latch a healthy motor session.
  imu.accel[0] = 14000;
  imu.accel[2] = 8000;
  imu.at_ms = 250;
  body.set_imu(imu);
  fresh(guard, 250);
  body.tick(250);
  CHECK(body.state().armed);
  imu.accel[0] = 3000;
  imu.accel[2] = 16100;
  imu.at_ms = 300;
  body.set_imu(imu);
  fresh(guard, 300);
  body.tick(300);
  CHECK(body.state().armed);

  // Tilted and accelerated inside the configured norm envelope: the old
  // baseline-squared projection check incorrectly accepted this vector
  // (15100/16384 > 0.8), while its true cosine is < 0.8.
  // No MPU low-g interrupt is present.
  imu.accel[0] = 12500;
  imu.accel[2] = 15100;
  imu.at_ms = 350;
  body.set_imu(imu);
  fresh(guard, 350);
  CHECK(body.state().armed);
  imu.at_ms = 400;
  body.set_imu(imu);
  fresh(guard, 400);
  CHECK(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0 && body.state().servos_attached);
  CHECK(send(body, "status", 400).find(
      "\"fault\":\"imu_attitude_latched\"") != std::string::npos);
  CHECK(send(body, "arm", 400) == "ERR arm imu_attitude_latched");
  CHECK(send(body, "rearm", 400, true) == "ERR rearm imu_attitude_not_upright");

  // Putdown with healthy samples is not automatic motion authority.
  imu.accel[0] = 0;
  imu.accel[2] = 16384;
  imu.at_ms = 450;
  body.set_imu(imu);
  fresh(guard, 450);
  CHECK(send(body, "rearm", 450, true) == "ERR rearm imu_attitude_not_upright");
  imu.at_ms = 500;
  body.set_imu(imu);
  fresh(guard, 500);
  CHECK(send(body, "arm", 500) == "ERR arm imu_attitude_latched");
  CHECK(send(body, "rearm", 500) == "ERR rearm local_only");
  // Independent dock seating arrives while attitude is still latched.
  // A fresh putdown must not hide the dock power lockout.
  desk_robot::AccessoryReadings contact{};
  contact.dock.present = contact.dock.valid = true;
  contact.dock.left_seated = true;
  contact.dock.sample_seq = 1;
  contact.dock.at_ms = 500;
  body.set_accessories(contact, 500);
  CHECK(send(body, "status", 500).find(
      "\"fault\":\"dock_power_connected\"") != std::string::npos);
  CHECK(send(body, "rearm", 500, true) == "ERR rearm dock_power_connected");
  contact.dock.left_seated = false;
  contact.dock.sample_seq = 2; // distinct unseated GPIO conversion
  contact.dock.at_ms = 501;
  body.set_accessories(contact, 501);
  fresh(guard, 501);
  CHECK(!body.state().armed && body.state().left == 0);
  CHECK(send(body, "rearm", 501, true) == "OK rearm");
  CHECK(send(body, "arm", 501) == "OK arm");
  CHECK(body.state().left == 0 && body.state().right == 0);

  // Same timestamp with contradictory axes is a replay, not a new permit.
  imu.accel[1] = 300;
  body.set_imu(imu);
  fresh(guard, 501);
  body.tick(501);
  CHECK(!body.state().armed);
  CHECK(send(body, "arm", 501) == "ERR arm imu_sensor_fault_latched");

  // Prior upright evidence cannot survive the contradictory conversion.
  // Two distinct fresh, healthy samples after the fault are required.
  imu.accel[1] = 0;
  imu.at_ms = 550;
  body.set_imu(imu);
  fresh(guard, 550);
  CHECK(send(body, "rearm", 550, true) == "ERR rearm imu_attitude_not_upright");
  imu.at_ms = 600;
  body.set_imu(imu);
  fresh(guard, 600);
  CHECK(send(body, "rearm", 600, true) == "OK rearm");

  // A new valid sample after the freshness window cannot inherit old
  // upright credit, even when no intervening tick observed the outage.
  imu.at_ms = 850;
  body.set_imu(imu);
  fresh(guard, 850);
  CHECK(send(body, "rearm", 850, true) == "ERR rearm imu_attitude_not_upright");
  imu.at_ms = 900;
  body.set_imu(imu);
  fresh(guard, 900);
  CHECK(send(body, "rearm", 900, true) == "OK rearm");
  CHECK(!body.state().armed && body.state().left == 0 && body.state().right == 0);
}




static void guarded_lift_never_replays_missed_servo_steps_in_one_pwm_write() {
  auto cfg = config();
  cfg.freshness_ms = 200U; // a valid allowed window longer than the slow loop
  for (const auto profile : {
      desk_robot::BodyProfile::StepperGuarded,
      desk_robot::BodyProfile::DcGuarded}) {
    desk_robot::CliffGuard guard;
    CHECK(guard.configure(cfg));
    fresh(guard, 100);
    CHECK(guard.try_rearm(100));
    desk_robot::BodyControl body(profile, &guard);
    body.require_lift_travel_limits(true);
    CHECK(body.configure_lift_travel_limits({80, 110}));
    CHECK(send(body, "arm", 100) == "OK arm");
    CHECK(send(body, "lift 110", 100) == "OK lift angle=110");

    // All five critical ToF samples are still <200ms old, and the 500ms
    // watchdog has not expired. Old code issued 8 degrees immediately.
    body.tick(260);
    CHECK(body.state().armed && body.state().servos_attached);
    CHECK(body.state().lift == 91 && body.state().lift_target == 110);
    body.tick(260); // multiple same-ms loop invocations cannot catch up
    body.tick(261);
    body.tick(279);
    CHECK(body.state().lift == 91);
    body.tick(280);
    CHECK(body.state().lift == 92);

    // The physical guard retains independent authority when later stale.
    body.tick(301);
    CHECK(!body.state().armed);
    CHECK(body.state().lift == body.state().lift_target);
    CHECK(body.state().servos_attached); // hold a possible payload
  }

  // The same bounded movement must survive the WROOM millis() rollover.
  desk_robot::CliffGuard wrapped_guard;
  CHECK(wrapped_guard.configure(cfg));
  constexpr std::uint32_t before_wrap = 0xfffffff0U;
  fresh(wrapped_guard, before_wrap);
  CHECK(wrapped_guard.try_rearm(before_wrap));
  desk_robot::BodyControl wrapped(
      desk_robot::BodyProfile::StepperGuarded, &wrapped_guard);
  wrapped.require_lift_travel_limits(true);
  CHECK(wrapped.configure_lift_travel_limits({80, 110}));
  CHECK(send(wrapped, "arm", before_wrap) == "OK arm");
  CHECK(send(wrapped, "lift 110", before_wrap) == "OK lift angle=110");
  wrapped.tick(0x40U); // 80ms elapsed across wrap: no 4-degree burst
  CHECK(wrapped.state().lift == 91 && wrapped.state().armed);
  wrapped.tick(0x41U);
  CHECK(wrapped.state().lift == 91);
  wrapped.tick(0x54U);
  CHECK(wrapped.state().lift == 92);
}

static void full_profile_lift_requires_measured_startup_and_travel() {
  desk_robot::CliffGuard guard;
  CHECK(guard.configure(config()));
  fresh(guard, 100);
  CHECK(guard.try_rearm(100));
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  body.require_lift_travel_limits(true);
  CHECK(send(body, "status", 100).find("\"ready\":false") !=
        std::string::npos);
  CHECK(send(body, "status", 100).find(
      "\"fault\":\"lift_limits_unqualified\"") != std::string::npos);
  CHECK(send(body, "arm", 100) == "ERR arm lift_limits_unqualified");
  CHECK(!body.state().armed && !body.state().servos_attached);
  CHECK(!body.configure_lift_travel_limits({0, 120}));
  CHECK(!body.configure_lift_travel_limits({60, 121}));
  CHECK(!body.configure_lift_travel_limits({100, 90}));
  CHECK(!body.configure_lift_travel_limits({95, 110})); // excludes startup 90
  CHECK(!body.configure_lift_travel_limits({90, 90}));
  // These are synthetic host test values, NOT a physical qualification.
  CHECK(body.configure_lift_travel_limits({80, 110}));
  CHECK(!body.configure_lift_travel_limits({60, 120}));
  CHECK(send(body, "status", 100).find("\"ready\":true") !=
        std::string::npos);
  CHECK(send(body, "arm", 100) == "OK arm");
  CHECK(body.state().servos_attached && body.state().lift == 90);
  CHECK(send(body, "lift 79", 100) ==
        "ERR lift outside_measured_endstops");
  CHECK(send(body, "lift 111", 100) ==
        "ERR lift outside_measured_endstops");
  CHECK(body.state().lift_target == 90);
  CHECK(send(body, "lift 110", 100) == "OK lift angle=110");
  body.tick(120);
  CHECK(body.state().lift == 91 && body.state().lift_target == 110);
  CHECK(send(body, "stop", 121) == "OK stop");
  CHECK(body.state().lift == 91 && body.state().lift_target == 91);
  CHECK(body.state().servos_attached);
  CHECK(!body.configure_lift_travel_limits({80, 120}));
  CHECK(send(body, "disarm", 122) == "OK disarm");
  CHECK(!body.state().servos_attached);
  CHECK(!body.configure_lift_travel_limits({80, 120}));

  // DC guarded profile has the same two-servo attachment veto.
  desk_robot::CliffGuard dc_guard;
  CHECK(dc_guard.configure(config()));
  fresh(dc_guard, 200);
  CHECK(dc_guard.try_rearm(200));
  desk_robot::BodyControl dc(desk_robot::BodyProfile::DcGuarded, &dc_guard);
  dc.require_lift_travel_limits(true);
  CHECK(send(dc, "arm", 200) == "ERR arm lift_limits_unqualified");
  CHECK(!dc.state().servos_attached);
  CHECK(dc.configure_lift_travel_limits({80, 100}));
  CHECK(send(dc, "arm", 200) == "OK arm");
  CHECK(send(dc, "lift 101", 200) ==
        "ERR lift outside_measured_endstops");
}

static void guarded_startup_never_attaches_unmeasured_jaw_pwm() {
  for (int which = 0; which < 2; ++which) {
    desk_robot::CliffGuard guard;
    CHECK(guard.configure(config()));
    fresh(guard, 10);
    const auto profile = which == 0
        ? desk_robot::BodyProfile::StepperGuarded
        : desk_robot::BodyProfile::DcGuarded;
    desk_robot::BodyControl body(profile, &guard);
    body.require_grip_feedback(true);
    CHECK(send(body, "rearm", 10, true) == "OK rearm");
    const auto status = send(body, "status", 10);
    CHECK(status.find("\"ready\":false") != std::string::npos);
    CHECK(status.find("\"fault\":\"jaw_limits_unqualified\"") !=
          std::string::npos);
    CHECK(send(body, "arm", 10) == "ERR arm jaw_limits_unqualified");
    CHECK(!body.state().armed && !body.state().servos_attached &&
          body.state().left == 0 && body.state().right == 0);
    // The fixed startup target 90 lies inside these measured endpoints.
    // Firmware configuration is not a substitute for actual rig trials.
    CHECK(body.configure_jaw_force_limits({60, 120, 1000, 1, 300}));
    fresh(guard, 11);
    CHECK(send(body, "status", 11).find("\"ready\":true") !=
          std::string::npos);
    CHECK(send(body, "arm", 11) == "OK arm");
    CHECK(body.state().armed && body.state().servos_attached);
    CHECK(send(body, "stop", 12) == "OK stop");
    CHECK(body.state().servos_attached); // preserve confirmed holding PWM
    CHECK(send(body, "disarm", 13) == "OK disarm");
    CHECK(!body.state().servos_attached);
  }
}


static void combined_cliff_attitude_watchdog_and_uart_backpressure() {
  using desk_robot::BodyProfile;
  for (const auto profile : {BodyProfile::StepperGuarded, BodyProfile::DcGuarded}) {
    for (const std::uint32_t start : {100U, 0xffffffd0U}) {
      for (const bool watchdog_first : {false, true}) {
        desk_robot::CliffGuard guard;
        CHECK(guard.configure(config()));
        fresh(guard, start - 50U);
        desk_robot::BodyControl body(profile, &guard);
        body.require_imu_for_motion(true);
        body.require_imu_attitude_guard(true);
        body.set_imu_identity(4, 0x68, 0);
        CHECK(body.configure_imu_attitude_limits({{0, 0, 16384}, 800, 12000, 20000}));
        desk_robot::BerryReading imu{};
        imu.model = desk_robot::BerryModel::Mpu6050;
        imu.valid = imu.low_g_status_valid = true;
        imu.accel[2] = 16384;
        imu.at_ms = start - 50U;
        body.set_imu(imu);
        imu.at_ms = start;
        body.set_imu(imu);
        fresh(guard, start);
        CHECK(send(body, "rearm", start, true) == "OK rearm");
        CHECK(send(body, "arm", start) == "OK arm");
        const char drive[] = "drive 40 40 250";
        char ack[desk_robot::kReplyCapacity]{};
        body.execute(drive, sizeof(drive) - 1, start, ack, sizeof(ack));
        CHECK(std::string(ack) == "OK drive left=40 right=40 ms=250");
        CHECK(body.state().left == 40 && body.drive_remaining(start) == 250);

        // Fill both transmit queues using real query replies from both command
        // authorities; no bytes are drained while the independent trips occur.
        desk_robot::ReplyTxQueue<2 * (desk_robot::kReplyCapacity + 2)> head_tx, usb_tx;
        desk_robot::LineReceiver head, usb(true);
        char reply[desk_robot::kReplyCapacity]{};
        for (int i = 0; i < 16; ++i) {
          for (char c : std::string("status\n"))
            head.feed(c, start + 1U, body, reply, sizeof(reply));
          head_tx.enqueue_line(reply);
          for (char c : std::string("status\n"))
            usb.feed(c, start + 1U, body, reply, sizeof(reply));
          usb_tx.enqueue_line(reply);
        }
        CHECK(head_tx.dropped() > 0 && usb_tx.dropped() > 0);
        CHECK(body.state().armed && body.state().left == 40);

        imu.accel[0] = 14000;
        imu.accel[2] = 8000;
        imu.at_ms = start + 50U;
        body.set_imu(imu);
        fresh(guard, start + 50U);
        body.tick(start + 50U);
        CHECK(body.state().armed); // one impulse alone must not trip attitude
        const auto trip = start + 100U;
        guard.sample(2, 80, true, trip);
        if (watchdog_first) body.motor_watchdog_trip();
        imu.at_ms = trip;
        body.set_imu(imu);
        if (!watchdog_first) body.motor_watchdog_trip();
        body.tick(trip);
        body.veto_unapplied_motion_ack(ack, sizeof(ack));
        CHECK(std::string(ack) == "ERR drive safety_interlock");
        CHECK(guard.fault() == desk_robot::CliffFault::FloorOutOfRange);
        CHECK(guard.fault_sensor() == 2);
        CHECK(!body.state().armed && body.state().left == 0 &&
              body.state().right == 0 && body.drive_remaining(trip) == 0);
        CHECK(body.state().servos_attached);
        CHECK(body.state().lift_target == body.state().lift &&
              body.state().grip_target == body.state().grip);

        // Restoring the IMU first must not clear the still unsafe cliff.
        CHECK(send(body, "rearm", trip, true) == "ERR rearm imu_attitude_not_upright");
        imu.accel[0] = 0;
        imu.accel[2] = 16384;
        for (const std::uint32_t delta : {150U, 200U}) {
          const auto now = start + delta;
          imu.at_ms = now;
          body.set_imu(imu);
          for (std::uint8_t lane = 0; lane < 5; ++lane)
            guard.sample(lane, lane == 2 ? 80 : lane < 4 ? 50 : 200, true, now);
          CHECK(send(body, "rearm", now, true) ==
                (delta == 150U ? "ERR rearm imu_attitude_not_upright" :
                                 "ERR rearm safety_interlock"));
          CHECK(guard.fault() == desk_robot::CliffFault::FloorOutOfRange);
          CHECK(!body.state().armed && body.drive_remaining(now) == 0);
        }

        const auto recovery = start + 201U;
        fresh(guard, recovery);
        body.sample_touch_input(true, recovery);
        CHECK(send(body, "rearm", recovery, true) == "ERR rearm touch_active");
        body.sample_touch_input(false, recovery + 1U);
        for (char c : std::string("rearm\n"))
          head.feed(c, recovery + 1U, body, reply, sizeof(reply));
        CHECK(std::string(reply) == "ERR rearm local_only");
        CHECK(head_tx.enqueue_priority_line(send(body, "stop", recovery + 1U).c_str()));
        CHECK(usb_tx.enqueue_priority_line(send(body, "halt", recovery + 1U).c_str()));
        CHECK(send(body, "arm", recovery + 1U) == "ERR arm imu_attitude_latched");
        CHECK(send(body, "keepalive", recovery + 1U) == "ERR keepalive disarmed");
        CHECK(send(body, drive, recovery + 1U) == "ERR drive disarmed");
        CHECK(guard.fault() == desk_robot::CliffFault::FloorOutOfRange);
        for (char c : std::string("rearm\n"))
          usb.feed(c, recovery + 1U, body, reply, sizeof(reply));
        CHECK(std::string(reply) == "OK rearm");
        CHECK(!body.state().armed && body.drive_remaining(recovery + 1U) == 0);
        CHECK(send(body, "arm", recovery + 1U) == "OK arm");
        CHECK(body.state().left == 0 && body.state().right == 0);
      }
    }
  }
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
    guarded_dc_dock_loss_latches_until_fresh_local_usb_rearm();
    repeated_dock_loss_retires_last_trusted_gpioa_acquisition();
    complete_robot_requires_boot_installed_and_fresh_dock_expander();
    dock_gpio_aux_sample_sequence_is_bounded_and_not_charging_proof();
    belly_adc_does_not_refresh_stale_jaw_sample();
    jaw_aux_and_motion_require_present_independent_channel();
    belly_acquisition_identity_cannot_forge_contact();
    physical_gripper_stops_ramping_when_adc_is_not_trustworthy();
    gripper_jaw_consumes_at_most_four_degrees_per_adc_conversion();
    jaw_acquisition_identity_prevents_forged_force_relief();
    jaw_force_ceiling_is_local_and_direction_aware();
    optional_nfc_and_fresh_ambient_fit_existing_bounded_aux_contract();
    dual_ir_evidence_never_authorizes_body_motion_or_charging();
    output_fault_vetoes_all_motion_acknowledgments();
    jaw_expiry_during_output_vetoes_accepted_target();
    stale_range_veto_survives_saturated_uart();
    combined_cliff_attitude_watchdog_and_uart_backpressure();
    raw_bumper_trip_preempts_debounce_and_preserves_payload();
    raw_bumper_bounce_resets_both_edge_classifiers();
    accessory_reconnect_does_not_invent_petting_events();
    optional_sensor_inputs_never_arm_or_forge_boot_events();
    battery_readiness_matches_stricter_arm_voltage();
    low_voltage_cannot_clear_unrelated_recovery_latches();
    battery_undervoltage_rejects_arm_and_stops_motion();
    optional_gauge_low_latch_requires_trusted_recovery();
    invalid_fuel_identity_cannot_rearm_from_cached_conversion();
    required_fuel_gauge_loss_stops_and_requires_local_rearm();
    fuel_voltage_replay_cannot_rearm_or_restore_drive();
    accessory_sensors_never_infer_grip_or_current_or_grant_arm();
    independent_pack_sensor_freshness_never_crosses_devices();
    optional_max30102_raw_never_authorizes_motion_or_diagnosis();
    extra_three_ranging_channels_are_diagnostics_only();
    eight_lane_optical_words_are_read_only_and_expire();
    range_diagnostics_do_not_revive_after_full_millis_wrap();
    side_range_validity_clears_on_shared_bus_fault_without_fake_samples();
    optional_range_replay_preserves_newest_raw_evidence();
    cap_petting_zones_are_optional_and_never_arm();
    raw_touch_observations_restart_gesture_debounce();
    touch_telemetry_never_grants_motion();
    raw_touch_trip_preempts_debounce_without_forging_a_tap();
    touch_is_local_human_stop_and_requires_fresh_arm();
    touch_gesture_counters_survive_slow_status_polling();
    five_range_status_reports_real_samples_not_a_permission();
    imu_identity_is_diagnostic_only();
    required_imu_is_a_local_freshness_interlock();
    zero_acceleration_mpu_does_not_authorize_motion();
    mpu_native_low_g_irq_vetoes_local_wheels();
    mpu_static_attitude_fails_closed_and_needs_usb_recovery();
    guarded_startup_never_attaches_unmeasured_jaw_pwm();
    full_profile_lift_requires_measured_startup_and_travel();
    guarded_lift_never_replays_missed_servo_steps_in_one_pwm_write();
    imu_replay_and_rollover_are_local_motion_safety_evidence();
    missing_mpu_interrupt_status_cannot_authorize_wheels();
    imu_status_preserves_physical_conversion_and_boot_identity();
    std::cout << "PASS touch gestures, rollover and local stop interlock\\n";
    measured_local_calibration_is_atomic_and_never_arms();
    std::cout << "PASS USB calibration staged atomically with no arming\\n";
    cold_boot_complete_unsafe_sweep_reports_real_fault();
    unqualified_stepper_cutoff_never_claims_motion_ready();
    cpu_heartbeat_fault_is_sticky_and_holds_gripper();
    std::cout << "PASS CPU heartbeat fault latches drive and holds gripper\n";
    recovery_is_local_and_not_an_arm();
    usb_rearm_refuses_unsafe_physical_interlocks();
    std::cout << "PASS only local recovery can clear a healthy fault latch\n";
    contact_cannot_hide_expired_host_lease();
    receiver_recovery_authority_is_not_shared();
    std::cout << "PASS head receiver cannot borrow USB recovery authority\n";
    guarded_directional_drive_rejects_unqualified_sweep();
    std::cout << "PASS guarded reverse and turns need calibrated swept space\n";
    local_trip_blocks_forward_and_reverse_replay();
    single_invalid_or_stale_lane_cancels_drive();
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
