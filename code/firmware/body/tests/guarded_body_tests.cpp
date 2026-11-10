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

static void touch_telemetry_never_grants_motion() {
  desk_robot::CliffGuard guard;
  desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded, &guard);
  CHECK(!body.state().armed && body.state().touch_count == 0);
  body.set_touch(true);
  body.set_touch(true);
  CHECK(body.state().touch_count == 1 && body.state().touch_active);
  CHECK(send(body, "status", 0).find("\"touch\":{\"active\":true,\"count\":1}") !=
        std::string::npos);
  CHECK(send(body, "arm", 0) == "ERR arm touch_active");
  body.set_touch(false);
  CHECK(!body.state().touch_active && body.state().touch_count == 1);
  body.set_touch(true);
  CHECK(body.state().touch_count == 2);
  CHECK(send(body, "status", 0).find("\"touch\":{\"active\":true,\"count\":2}") !=
        std::string::npos);
  CHECK(!body.state().armed);
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
    touch_telemetry_never_grants_motion();
    touch_is_local_human_stop_and_requires_fresh_arm();
    std::cout << "PASS physical touch stops motion locally without remote rearm\\n";
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
