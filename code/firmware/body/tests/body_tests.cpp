#include "BodyControl.h"
#include "CliffGuard.h"

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

using desk_robot::BodyControl;
using desk_robot::LineReceiver;

namespace {

#define CHECK(expression)                                                        \
  do {                                                                          \
    if (!(expression))                                                          \
      throw std::runtime_error(std::string(__FILE__) + ":" +                      \
                               std::to_string(__LINE__) + ": " #expression);    \
  } while (false)

std::string send(BodyControl& body, const std::string& line, std::uint32_t now) {
  char reply[desk_robot::kReplyCapacity]{};
  body.execute(line.data(), line.size(), now, reply, sizeof(reply));
  return reply;
}

std::vector<std::string> frame(BodyControl& body, LineReceiver& receiver,
                               const std::string& bytes, std::uint32_t now) {
  std::vector<std::string> replies;
  char reply[desk_robot::kReplyCapacity]{};
  for (char byte : bytes)
    if (receiver.feed(byte, now, body, reply, sizeof(reply))) replies.emplace_back(reply);
  return replies;
}

void disarmed_boot() {
  BodyControl body;
  CHECK(!body.state().armed);
  CHECK(!body.state().servos_attached);
  CHECK(body.state().left == 0 && body.state().right == 0);
  for (const char* command : {"drive 10 10", "lift 120", "grip 60", "keepalive"})
    CHECK(send(body, command, 100).find("disarmed") != std::string::npos);
  CHECK(!body.state().servos_attached);
  CHECK(send(body, "stop", 100) == "OK stop");
  CHECK(!body.state().armed);
}

void arm_clears_old_motion() {
  BodyControl body;
  CHECK(send(body, "arm", 10) == "OK arm");
  CHECK(body.state().servos_attached);
  send(body, "drive 20 -20", 10);
  send(body, "lift 120", 10);
  body.tick(110);
  const int position = body.state().lift;
  CHECK(position == 95);
  send(body, "arm", 110);
  CHECK(body.state().left == 0 && body.state().right == 0);
  CHECK(body.state().lift_target == position);
  body.tick(310);
  CHECK(body.state().lift == position);
}

void drive_limits() {
  BodyControl body;
  send(body, "arm", 0);
  CHECK(send(body, "drive 100 -100 250", 0) == "OK drive left=40 right=-40 ms=250");
  CHECK(body.state().left == 40 && body.state().right == -40);
  CHECK(send(body, "drive -12 8 1", 0) == "OK drive left=-12 right=8 ms=1");
  CHECK(body.state().left == -12 && body.state().right == 8);
  send(body, "drive 0 0", 0);
  CHECK(body.state().left == 0 && body.state().right == 0);
}

void drive_duration() {
  BodyControl body;
  send(body, "arm", 0);
  send(body, "drive 20 20", 10);
  body.tick(259);
  CHECK(body.state().left == 20);
  CHECK(body.drive_remaining(259) == 1);
  body.tick(260);
  CHECK(body.state().left == 0 && body.state().right == 0);
  CHECK(body.state().armed);
  send(body, "drive 20 20 1", 260);
  body.tick(261);
  CHECK(body.state().left == 0);
}

void keepalive_does_not_extend_drive() {
  BodyControl body;
  send(body, "arm", 0);
  send(body, "drive 20 20 150", 0);
  CHECK(send(body, "keepalive", 149) == "OK keepalive");
  body.tick(150);
  CHECK(body.state().left == 0);
  CHECK(body.watchdog_remaining(150) == 499);
  body.tick(649);
  CHECK(!body.state().armed);
}

void invalid_does_not_renew() {
  BodyControl body;
  send(body, "arm", 0);
  CHECK(send(body, "keepalive extra", 400).find("ERR") == 0);
  CHECK(send(body, "drive 20 20 251", 499).find("ERR") == 0);
  body.tick(500);
  CHECK(!body.state().armed);
  CHECK(send(body, "drive 20 20", 500) == "ERR drive disarmed");
}

void rejected_grip_does_not_renew_watchdog() {
  BodyControl body;
  body.require_grip_feedback(true);
  CHECK(send(body, "arm", 0) == "OK arm");
  // Parsed but rejected by the actual jaw feedback gate, not the parser.
  CHECK(send(body, "grip 60", 499) == "ERR grip force_missing_or_stale");
  CHECK(body.watchdog_remaining(499) == 1);
  body.tick(500);
  CHECK(!body.state().armed);
  CHECK(send(body, "grip 60", 500) == "ERR grip disarmed");

  BodyControl accepted;
  accepted.require_grip_feedback(true);
  CHECK(send(accepted, "arm", 0) == "OK arm");
  CHECK(send(accepted, "keepalive", 499) == "OK keepalive");
  CHECK(accepted.watchdog_remaining(499) == 500);
  accepted.tick(500);
  CHECK(accepted.state().armed);
  accepted.tick(999);
  CHECK(!accepted.state().armed);
}

void queries_do_not_renew() {
  BodyControl body;
  send(body, "arm", 0);
  CHECK(send(body, "ping", 300) == "OK ping");
  CHECK(send(body, "status", 499).find("\"watchdog_ms\":1") != std::string::npos);
  CHECK(send(body, "status", 500).find("\"armed\":false") != std::string::npos);
  CHECK(!body.state().armed);
}

void smooth_servos() {
  BodyControl body;
  send(body, "arm", 0);
  CHECK(send(body, "lift 120", 0) == "OK lift angle=120");
  CHECK(send(body, "grip 60", 0) == "OK grip angle=60");
  CHECK(body.state().lift == 90 && body.state().grip == 90);
  body.tick(19);
  CHECK(body.state().lift == 90);
  body.tick(20);
  CHECK(body.state().lift == 91 && body.state().grip == 89);
  body.tick(200);
  CHECK(body.state().lift == 100 && body.state().grip == 80);
  CHECK(body.state().lift >= 60 && body.state().lift <= 120);
}

void keepalive_extends_servo_lease() {
  BodyControl body;
  send(body, "arm", 0);
  send(body, "lift 120", 0);
  send(body, "grip 60", 0);
  send(body, "keepalive", 400);
  body.tick(600);
  CHECK(body.state().lift == 120 && body.state().grip == 60);
  CHECK(body.state().armed);
  body.tick(899);
  CHECK(body.state().armed);
  body.tick(900);
  CHECK(!body.state().armed);
}

void stop_freezes_servos() {
  BodyControl body;
  send(body, "arm", 0);
  send(body, "lift 120", 0);
  send(body, "drive 20 20", 0);
  CHECK(send(body, "stop", 100) == "OK stop");
  CHECK(body.state().left == 0 && body.state().right == 0);
  CHECK(body.state().lift == 95 && body.state().lift_target == 95);
  body.tick(400);
  CHECK(body.state().lift == 95);
  CHECK(body.state().armed && body.state().servos_attached);
  CHECK(send(body, "stop", 400) == "OK stop");
}

void explicit_disarm_detaches() {
  BodyControl body;
  send(body, "arm", 0);
  send(body, "grip 60", 0);
  CHECK(send(body, "disarm", 100) == "OK disarm");
  CHECK(!body.state().armed && !body.state().servos_attached);
  CHECK(body.state().grip == 85 && body.state().grip_target == 85);
  body.tick(1000);
  CHECK(body.state().grip == 85);
  send(body, "arm", 1000);
  body.tick(1100);
  CHECK(body.state().grip == 85);
}

void watchdog_holds_servos() {
  BodyControl body;
  send(body, "arm", 0);
  send(body, "lift 120", 0);
  send(body, "grip 60", 0);
  body.tick(499);
  const int lift = body.state().lift;
  const int grip = body.state().grip;
  body.tick(500);
  CHECK(!body.state().armed);
  CHECK(body.state().servos_attached);
  CHECK(body.state().lift == lift && body.state().grip == grip);
  CHECK(body.state().lift_target == lift && body.state().grip_target == grip);
  body.tick(800);
  CHECK(body.state().lift == lift && body.state().grip == grip);
  CHECK(send(body, "keepalive", 800) == "ERR keepalive disarmed");
  send(body, "arm", 800);
  body.tick(900);
  CHECK(body.state().lift == lift && body.state().grip == grip);
  send(body, "disarm", 900);
  CHECK(!body.state().servos_attached);
}

void rollover_timers() {
  BodyControl body;
  const std::uint32_t start = std::numeric_limits<std::uint32_t>::max() - 99;
  send(body, "arm", start);
  send(body, "drive 30 30 250", start);
  send(body, "lift 120", start);
  body.tick(start + 100U);
  CHECK(body.state().left == 30 && body.state().lift == 95);
  body.tick(start + 249U);
  CHECK(body.state().left == 30 && body.drive_remaining(start + 249U) == 1);
  body.tick(start + 250U);
  CHECK(body.state().left == 0 && body.state().armed);
  body.tick(start + 499U);
  CHECK(body.state().armed && body.watchdog_remaining(start + 499U) == 1);
  body.tick(start + 500U);
  CHECK(!body.state().armed && body.state().servos_attached);
}

void strict_integer_parser() {
  BodyControl body;
  send(body, "arm", 0);
  for (const char* value : {"NaN", "nan", "inf", "-inf", "1.0", "1e2", "--1",
                            "-", "+1", "99999999999999999999999999", "0x10", "12x"}) {
    CHECK(send(body, std::string("drive ") + value + " 10", 0).find("ERR") == 0);
    CHECK(send(body, std::string("lift ") + value, 0).find("ERR") == 0);
    CHECK(body.state().left == 0 && body.state().lift_target == 90);
  }
}

void malformed_atomicity() {
  BodyControl body;
  send(body, "arm", 0);
  send(body, "drive 12 -8 250", 0);
  for (const char* command : {"drive 10 20 251", "drive 101 20", "drive 0 -101",
                             "drive 0 0 0", "drive 0 0 -1", "drive 0 0 1 extra",
                             "drive 0", "drive", "drive 10 10 20 30 40",
                             "lift 59", "grip 121", "grip 60 extra", "arm extra",
                             "disarm extra", "stop extra", "motor 0 fwd 255",
                             "forward 100", "DRIVE 10 10", "", "   "}) {
    CHECK(send(body, command, 0).find("ERR") == 0);
    CHECK(body.state().left == 12 && body.state().right == -8);
    CHECK(body.state().lift_target == 90 && body.state().grip_target == 90);
  }
}

void overlong_frame_recovery() {
  BodyControl body;
  LineReceiver receiver;
  auto replies = frame(body, receiver, std::string(100, 'x') + "arm\r\n", 0);
  CHECK(replies.size() == 1 && replies[0] == "ERR input line_too_long");
  CHECK(!body.state().armed);
  replies = frame(body, receiver, "arm\r\n", 0);
  CHECK(replies.size() == 1 && replies[0] == "OK arm");
  send(body, "disarm", 0);
  CHECK(frame(body, receiver, "ping" + std::string(91, ' ') + "\n", 0)[0] == "OK ping");
  CHECK(frame(body, receiver, "arm" + std::string(93, ' ') + "\n", 0)[0] ==
        "ERR input line_too_long");
  CHECK(!body.state().armed);
}

void framing() {
  BodyControl body;
  LineReceiver receiver;
  CHECK(frame(body, receiver, "arm\r", 0).empty());
  CHECK(!body.state().armed);
  CHECK(frame(body, receiver, "\n", 0)[0] == "OK arm");
  CHECK(frame(body, receiver, "disarm\n", 0)[0] == "OK disarm");
  for (const std::string& bytes : {std::string("ar\rm\n"), std::string("arm\r\r\n"),
                                  std::string("arm\0\n", 5), std::string("arm\x80\n", 5),
                                  std::string("arm\t\n")}) {
    auto replies = frame(body, receiver, bytes, 0);
    CHECK(replies.size() == 1 && replies[0] == "ERR input invalid_ascii");
    CHECK(!body.state().armed);
  }
  CHECK(frame(body, receiver, "arm\nstop\nstatus\n", 0).size() == 3);
}

void serial_idle_frame_timeout() {
  BodyControl body;
  LineReceiver local_usb(true);
  // A prior operator's incomplete prefix must never turn the next
  // independent "arm" into a privileged local USB "rearm" command.
  CHECK(frame(body, local_usb, "re", 100).empty());
  const auto stale = frame(body, local_usb, "arm\n", 100 + desk_robot::kWatchdogMs);
  CHECK(stale.size() == 1 && stale[0] == "ERR input interbyte_timeout");
  CHECK(!body.state().armed);
  CHECK(frame(body, local_usb, "arm\n", 601)[0] == "OK arm");
  CHECK(frame(body, local_usb, "disarm\n", 601)[0] == "OK disarm");

  // Both a continued command within the budget and an ordinary new line
  // remain valid, preserving normal UART fragmentation behavior.
  LineReceiver remote;
  CHECK(frame(body, remote, "ar", 1000).empty());
  CHECK(frame(body, remote, "m\n", 1000 + desk_robot::kWatchdogMs - 1)[0] ==
        "OK arm");
  CHECK(frame(body, remote, "disarm\n", 1500)[0] == "OK disarm");

  // CR before LF is still part of the unfinished frame; the timeout
  // cannot authorize a command merely because LF arrives much later.
  CHECK(frame(body, remote, "arm\r", 1600).empty());
  CHECK(frame(body, remote, "\n", 1600 + desk_robot::kWatchdogMs)[0] ==
        "ERR input interbyte_timeout");
  CHECK(!body.state().armed);

  // The serial acquisition clock is uint32 and legitimately wraps.
  const std::uint32_t before_wrap = UINT32_MAX - 15U;
  CHECK(frame(body, remote, "ar", before_wrap).empty());
  CHECK(frame(body, remote, "m\n", before_wrap + desk_robot::kWatchdogMs)[0] ==
        "ERR input interbyte_timeout");
  CHECK(frame(body, remote, "arm\n", before_wrap + desk_robot::kWatchdogMs)[0] ==
        "OK arm");
}

void independent_receivers() {
  BodyControl body;
  LineReceiver usb;
  LineReceiver head;
  frame(body, usb, "ar", 0);
  CHECK(frame(body, head, "m\n", 0)[0] == "ERR input unknown_command");
  CHECK(!body.state().armed);
  CHECK(frame(body, usb, "m\n", 0)[0] == "OK arm");
}

void status_honesty() {
  BodyControl body;
  send(body, "arm", 0);
  send(body, "lift 120", 0);
  const auto status = send(body, "status", 100);
  CHECK(status.front() == '{' && status.back() == '}');
  CHECK(status.find("\"lift\":95") != std::string::npos);
  CHECK(status.find("\"lift_target\":120") != std::string::npos);
  CHECK(status.find("\"position_source\":\"commanded\"") != std::string::npos);
  CHECK(status.find("\"watchdog_ms\":400") != std::string::npos);
  const auto after = send(body, "status", 500);
  CHECK(after.find("\"armed\":false") != std::string::npos);
  CHECK(after.find("\"attached\":true") != std::string::npos);
}

void guarded_head_timeout_cannot_rearm_from_reconnected_uart() {
  desk_robot::CliffConfig calibration{};
  calibration.calibrated = true;
  calibration.freshness_ms = 100;
  calibration.front_obstacle_mm = 30;
  calibration.front_max_mm = 1000;
  for (auto& floor : calibration.floor) {
    floor.min_mm = 40;
    floor.max_mm = 60;
  }
  for (const auto profile : {
           desk_robot::BodyProfile::StepperGuarded,
           desk_robot::BodyProfile::DcGuarded,
       }) {
    desk_robot::CliffGuard guard;
    CHECK(guard.configure(calibration));
    auto refresh = [&](std::uint32_t now) {
      for (std::uint8_t i = 0; i < 5; ++i)
        guard.sample(i, i < 4 ? 50 : 200, true, now);
    };
    refresh(0);
    BodyControl body(profile, &guard);
    auto usb = [&](const std::string& line, std::uint32_t now) {
      char reply[desk_robot::kReplyCapacity]{};
      body.execute(line.data(), line.size(), now, reply, sizeof(reply), true);
      return std::string(reply);
    };
    CHECK(usb("rearm", 0) == "OK rearm");
    CHECK(send(body, "arm", 0) == "OK arm");
    CHECK(send(body, "drive 20 20 250", 0) ==
          "OK drive left=20 right=20 ms=250");
    for (std::uint32_t now = 50; now <= 500; now += 50) {
      refresh(now); // The cliff guard does not expire first.
      body.tick(now);
      if (now == 200)
        CHECK(body.state().armed && body.state().left == 20);
    }
    CHECK(!body.state().armed);
    CHECK(body.state().left == 0 && body.state().right == 0);
    const auto status = send(body, "status", 500);
    CHECK(status.find("\"fault\":\"command_timeout_latched\"") !=
          std::string::npos);
    CHECK(status.find("\"ready\":false") != std::string::npos);

    // Head bytes are real framed commands; they cannot borrow local USB
    // rearm authority merely because the bus and floor are now healthy.
    LineReceiver remote;
    refresh(501);
    const auto replies = frame(
        body, remote, "arm\ndrive 20 20 100\n", 501);
    CHECK(replies.size() == 2);
    CHECK(replies[0] == "ERR arm command_timeout_latched");
    CHECK(replies[1] == "ERR drive disarmed");
    CHECK(send(body, "arm", 501) == "ERR arm command_timeout_latched");
    CHECK(send(body, "rearm", 501) == "ERR rearm local_only");

    refresh(502);
    CHECK(usb("rearm", 502) == "OK rearm");
    CHECK(!body.state().armed);
    CHECK(body.state().left == 0 && body.state().right == 0);
    CHECK(send(body, "arm", 502) == "OK arm");
    CHECK(body.state().left == 0);
    CHECK(send(body, "drive 20 20 100", 502) ==
          "OK drive left=20 right=20 ms=100");
  }
}

void deterministic_stream_stress() {
  BodyControl body;
  LineReceiver receiver;
  std::uint32_t random = 0xCAFE1234;
  char reply[desk_robot::kReplyCapacity]{};
  for (std::uint32_t now = 0; now < 100000; ++now) {
    if (now % 1000 == 0) send(body, "arm", now);
    random = random * 1664525U + 1013904223U;
    receiver.feed(static_cast<char>(random >> 24), now, body, reply, sizeof(reply));
    const auto& state = body.state();
    CHECK(state.left >= -40 && state.left <= 40);
    CHECK(state.right >= -40 && state.right <= 40);
    CHECK(state.lift >= 60 && state.lift <= 120);
    CHECK(state.grip >= 60 && state.grip <= 120);
    if (!state.armed) CHECK(state.left == 0 && state.right == 0);
  }
}

}  // namespace

int main(int argc, char** argv) {
  using Test = std::pair<const char*, void (*)()>;
  const std::vector<Test> tests = {
      {"disarmed_boot", disarmed_boot}, {"arm_clears_old_motion", arm_clears_old_motion},
      {"drive_limits", drive_limits}, {"drive_duration", drive_duration},
      {"keepalive_does_not_extend_drive", keepalive_does_not_extend_drive},
      {"invalid_does_not_renew", invalid_does_not_renew},
      {"rejected_grip_does_not_renew_watchdog", rejected_grip_does_not_renew_watchdog},
      {"queries_do_not_renew", queries_do_not_renew}, {"smooth_servos", smooth_servos},
      {"keepalive_extends_servo_lease", keepalive_extends_servo_lease},
      {"stop_freezes_servos", stop_freezes_servos},
      {"explicit_disarm_detaches", explicit_disarm_detaches},
      {"watchdog_holds_servos", watchdog_holds_servos},
      {"rollover_timers", rollover_timers}, {"strict_integer_parser", strict_integer_parser},
      {"malformed_atomicity", malformed_atomicity},
      {"overlong_frame_recovery", overlong_frame_recovery}, {"framing", framing},
      {"serial_idle_frame_timeout", serial_idle_frame_timeout},
      {"independent_receivers", independent_receivers}, {"status_honesty", status_honesty},
      {"guarded_head_timeout_cannot_rearm_from_reconnected_uart",
       guarded_head_timeout_cannot_rearm_from_reconnected_uart},
      {"deterministic_stream_stress", deterministic_stream_stress}};
  int ran = 0;
  for (const auto& test : tests) {
    if (argc > 1 && std::strcmp(argv[1], test.first) != 0) continue;
    try {
      test.second();
      ++ran;
      std::cout << "PASS " << test.first << '\n';
    } catch (const std::exception& error) {
      std::cerr << "FAIL " << test.first << ": " << error.what() << '\n';
      return EXIT_FAILURE;
    }
  }
  if (ran == 0) {
    std::cerr << "Unknown test name\n";
    return EXIT_FAILURE;
  }
  return EXIT_SUCCESS;
}
