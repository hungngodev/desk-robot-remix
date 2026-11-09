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

static void local_only_real_ranges_and_persistable_calibration() {
  desk_robot::CliffGuard guard;
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  const std::string values = "calibrate 40 60 40 60 40 60 40 60 30 1000 100";
  CHECK(send(body, values, 0) == "ERR calibrate local_only");
  CHECK(!guard.configured());
  CHECK(send(body, "calclear", 0) == "ERR calclear local_only");
  CHECK(send(body, "calibrate 40 60 40", 0, true) ==
        "ERR calibrate bad_arguments");
  CHECK(send(body, "calibrate 20 10 40 60 40 60 40 60 30 1000 100",
             0, true) == "ERR calibrate invalid_intervals");
  CHECK(!guard.configured());
  CHECK(send(body, values, 0, true) == "OK calibrate");
  CHECK(guard.configured());
  CHECK(guard.configuration().floor[0].min_mm == 40);
  CHECK(guard.configuration().front_max_mm == 1000);
  CHECK(send(body, "arm", 0) == "ERR arm safety_interlock");
  for (std::uint8_t sensor = 0; sensor < desk_robot::kCliffSensorCount; ++sensor) {
    guard.sample(sensor, sensor < 4 ? 50 : 200, true, 3);
  }
  const auto diag = send(body, "ranges", 3);
  CHECK(diag.find("\"ranges_mm\":[50,50,50,50,200]") != std::string::npos);
  CHECK(diag.find("\"valid_mask\":31") != std::string::npos);
  CHECK(send(body, "rearm", 3, true) == "OK rearm");
  CHECK(send(body, "arm", 3) == "OK arm");
  CHECK(send(body, values, 4, true) == "ERR calibrate disarm_first");
  CHECK(send(body, "calclear", 4, true) == "ERR calclear disarm_first");
  CHECK(send(body, "disarm", 4) == "OK disarm");
  CHECK(send(body, "calclear", 4, true) == "OK calclear");
  CHECK(!guard.configured());
  CHECK(send(body, "rearm", 4, true) == "ERR rearm safety_interlock");
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
    std::cout << "PASS guarded profile cannot arm without a guard\n";
    recovery_is_local_and_not_an_arm();
    std::cout << "PASS only local recovery can clear a healthy fault latch\n";
    receiver_recovery_authority_is_not_shared();
    std::cout << "PASS head receiver cannot borrow USB recovery authority\n";
    fault_holds_payload_and_requires_rearm();
    std::cout << "PASS fault holds payload and requires explicit rearm\n";
    local_only_real_ranges_and_persistable_calibration();
    std::cout << "PASS only local measured calibration enables guarded sensor recovery\\n";
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
