#include "BodyControl.h"
#include "BodyCommandParser.h"
#include "AttitudeNorm.h"
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

void attitude_norm_root_boundaries() {
  using desk_robot::attitude_norm_root;
  CHECK(attitude_norm_root(0) == 0);
  CHECK(attitude_norm_root(1) == 1);
  for (const std::uint64_t n : {2ULL, 16384ULL, 32768ULL, 56755ULL, 0xffffffffULL}) {
    const auto square = n * n;
    CHECK(attitude_norm_root(square - 1) == n - 1);
    CHECK(attitude_norm_root(square) == n);
    CHECK(attitude_norm_root(square + 1) == n);
  }
  CHECK(attitude_norm_root(std::numeric_limits<std::uint64_t>::max()) == 0xffffffffU);
  std::uint64_t sample = 0x123456789abcdef0ULL;
  for (unsigned i = 0; i < 10000; ++i) {
    sample = sample * 6364136223846793005ULL + 1;
    const std::uint64_t root = attitude_norm_root(sample);
    CHECK(root * root <= sample);
    CHECK(root == 0xffffffffULL || (root + 1) * (root + 1) > sample);
  }
}

void optional_inputs_preserve_raw_stop_and_event_history() {
  BodyControl body;
  body.sample_optional_inputs(7, false, true, false);
  CHECK(body.state().reed_active && body.state().reed_events == 0);
  body.sample_optional_inputs(5, false, false, false, true);
  CHECK(!body.state().reed_active && body.state().reed_events == 0);
  body.sample_optional_inputs(7, false, true, false, true);
  CHECK(body.state().reed_active && body.state().reed_events == 0);
  body.sample_optional_inputs(7, false, false, false, true);
  CHECK(!body.state().reed_active);
  body.sample_optional_inputs(7, false, true, false, true);
  body.sample_optional_inputs(7, false, true, false, true);
  CHECK(body.state().reed_events == 1);
  body.sample_optional_inputs(7, false, true, true);
  body.sample_optional_inputs(7, false, true, true);
  CHECK(!body.state().pir_active && body.state().pir_events == 0);
  body.sample_optional_inputs(7, false, true, true);
  CHECK(body.state().pir_active && body.state().pir_events == 1);
  CHECK(send(body, "arm", 10) == "OK arm");
  CHECK(send(body, "drive 20 20", 10).find("OK drive") == 0);
  body.sample_optional_inputs(7, true, true, true, true);
  CHECK(body.state().bumper_raw && !body.state().armed);
  CHECK(body.state().left == 0 && body.state().right == 0);
  CHECK(!body.state().bumper_active && body.state().bumper_events == 0);
  CHECK(body.state().reed_events == 1 && body.state().pir_events == 1);
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

void overlapping_drive_replaces_pending_pulse() {
  for (const std::uint32_t start : {0U, std::numeric_limits<std::uint32_t>::max() - 49U}) {
    BodyControl body;
    CHECK(send(body, "arm", start) == "OK arm");
    for (const std::uint32_t offset : {0U, 25U, 50U, 75U}) {
      CHECK(send(body, "drive 20 20 250", start + offset) ==
            "OK drive left=20 right=20 ms=250");
      CHECK(body.drive_remaining(start + offset) == 250);
    }
    CHECK(send(body, "keepalive", start + 175U) == "OK keepalive");
    body.tick(start + 324U);
    CHECK(body.state().left == 20 && body.state().right == 20);
    CHECK(body.drive_remaining(start + 324U) == 1);
    body.tick(start + 325U);
    CHECK(body.state().armed);
    CHECK(body.state().left == 0 && body.state().right == 0);
    CHECK(body.drive_remaining(start + 325U) == 0);

    CHECK(send(body, "drive 20 20 250", start + 330U) ==
          "OK drive left=20 right=20 ms=250");
    CHECK(send(body, "drive 10 10 1", start + 380U) ==
          "OK drive left=10 right=10 ms=1");
    CHECK(body.drive_remaining(start + 380U) == 1);
    body.tick(start + 381U);
    CHECK(body.state().left == 0 && body.state().right == 0);
    CHECK(body.drive_remaining(start + 381U) == 0);
  }
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

void tokenizer_failure_contract() {
  using desk_robot::body_command::tokenize;
  char buffer[96]{};
  char* tokens[5]{};
  std::size_t count = 99;
  auto expect_error = [&](const char* line, std::size_t size, const char* expected) {
    count = 99;
    const auto* error = tokenize(line, size, buffer, tokens, count);
    CHECK(error && std::strcmp(error, expected) == 0);
    CHECK(count == 0);
  };
  expect_error(nullptr, 0, "ERR input empty");
  expect_error(nullptr, 1, "ERR input invalid_buffer");
  expect_error(nullptr, 96, "ERR input line_too_long");
  expect_error("a b c d e f", 11, "ERR input trailing_tokens");
  expect_error("stop\0extra", 10, "ERR input invalid_ascii");
  expect_error(" \t", 2, "ERR input invalid_ascii");
  std::string too_long(96, ' ');
  expect_error(too_long.data(), too_long.size(), "ERR input line_too_long");
  std::string max_line = "ping" + std::string(91, ' ');
  CHECK(!tokenize(max_line.data(), max_line.size(), buffer, tokens, count));
  CHECK(count == 1 && std::strcmp(tokens[0], "ping") == 0);
  CHECK(!tokenize("a b c d e", 9, buffer, tokens, count));
  CHECK(count == 5 && std::strcmp(tokens[4], "e") == 0);
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
  CHECK(send(body, "  drive 12 -8 250  ", 0) == "OK drive left=12 right=-8 ms=250");
  CHECK(send(body, "ping" + std::string(91, ' '), 0) == "OK ping");
  const std::pair<std::string, const char*> wire_errors[] = {
      {std::string(96, ' '), "ERR input line_too_long"},
      {std::string(96, '\0'), "ERR input line_too_long"},
      {std::string("stop\0", 5), "ERR input invalid_ascii"},
      {"stop\t", "ERR input invalid_ascii"},
      {"drive 1 2 3 4", "ERR drive bad_arguments"},
      {"drive 1 2 3 4 5", "ERR input trailing_tokens"},
      {"   ", "ERR input empty"},
  };
  for (const auto& item : wire_errors) {
    CHECK(send(body, item.first, 0) == item.second);
    CHECK(body.state().left == 12 && body.state().right == -8);
    CHECK(body.state().armed);
  }
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

// Exercise every forbidden byte at every position in an otherwise valid
// command. The parser and the actual serial receiver must both reject it,
// without extending an existing control lease or changing actuator targets.
void exhaustive_malformed_drive() {
  BodyControl body;
  LineReceiver receiver;
  CHECK(send(body, "arm", 0) == "OK arm");
  CHECK(send(body, "drive 12 -8 250", 0) == "OK drive left=12 right=-8 ms=250");
  auto unchanged = [&]() {
    CHECK(body.state().armed);
    CHECK(body.state().left == 12 && body.state().right == -8);
    CHECK(body.state().lift_target == 90 && body.state().grip_target == 90);
    CHECK(body.drive_remaining(1) == 249);
    CHECK(body.watchdog_remaining(1) == 499);
  };
  const std::string valid = "drive 12 -8 250";
  for (unsigned byte = 0; byte < 256; ++byte) {
    if (byte >= 32 && byte <= 126) continue;
    for (std::size_t pos = 0; pos <= valid.size(); ++pos) {
      auto malformed = valid;
      malformed.insert(pos, 1, static_cast<char>(byte));
      CHECK(send(body, malformed, 1) == "ERR input invalid_ascii");
      unchanged();
      // LF is a frame delimiter; CR immediately before LF is legal.
      if (byte == 10 || (byte == 13 && pos == valid.size())) continue;
      const auto replies = frame(body, receiver, malformed + "\n", 1);
      CHECK(replies.size() == 1 && replies[0] == "ERR input invalid_ascii");
      unchanged();
    }
  }
  for (const char* value : {"NaN", "nan", "Inf", "-inf", "1e2", "1.0",
                            "+1", "2147483648", "-2147483649"}) {
    const std::string invalid(value);
    for (const auto& command : {"drive " + invalid + " 8 250",
                                "drive 12 " + invalid + " 250",
                                "drive 12 8 " + invalid,
                                "lift " + invalid, "grip " + invalid}) {
      CHECK(send(body, command, 1).find("ERR") == 0);
      const auto replies = frame(body, receiver, command + "\n", 1);
      CHECK(replies.size() == 1 && replies[0].find("ERR") == 0);
      unchanged();
    }
  }
  // Small output buffers must return an explicit error, not partial JSON
  // that could be mistaken for a complete sensor observation.
  for (const char* command : {"status", "aux", "ir", "optics"}) {
    char storage[66];
    std::memset(storage, 'X', sizeof(storage));
    body.execute(command, std::strlen(command), 1, storage + 1, 64);
    CHECK(storage[0] == 'X' && storage[65] == 'X');
    CHECK(std::memchr(storage + 1, '\0', 64) != nullptr);
    CHECK(std::string(storage + 1) == std::string("ERR ") + command +
          " response_too_long");
    std::memset(storage, 'X', sizeof(storage));
    body.execute(command, std::strlen(command), 1, storage + 1, 1);
    CHECK(storage[0] == 'X' && storage[1] == '\0' && storage[2] == 'X');
    unchanged();
  }
  char short_reply[9];
  std::memset(short_reply, 'X', sizeof(short_reply));
  body.execute("ping", 4, 1, short_reply, 8);
  CHECK(std::string(short_reply) == "OK ping" && short_reply[8] == 'X');
  body.execute("ping", 4, 1, short_reply, 7);
  CHECK(short_reply[0] == '\0' && short_reply[8] == 'X');
  CHECK(frame(body, receiver, "ping\n", 1).at(0) == "OK ping");
  unchanged();
  body.tick(250);
  CHECK(body.state().left == 0 && body.state().right == 0);
  body.tick(500);
  CHECK(!body.state().armed);
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

void serial_fragmented_boundaries() {
  BodyControl body;
  LineReceiver receiver;
  std::uint32_t now = 0;
  const auto expect_frame = [&](const std::string& bytes, const char* expected) {
    char reply[desk_robot::kReplyCapacity] = "pending";
    for (std::size_t i = 0; i < bytes.size(); ++i) {
      const bool completed = receiver.feed(bytes[i], now++, body, reply, sizeof(reply));
      CHECK(completed == (i + 1 == bytes.size()));
      if (!completed) CHECK(std::strcmp(reply, "pending") == 0);
    }
    CHECK(std::strcmp(reply, expected) == 0);
    CHECK(!body.state().armed);
  };
  const auto max_line = "ping" + std::string(desk_robot::kMaxLineLength - 4, ' ');
  // Reuse the same receiver throughout: every LF must clear all framing state.
  expect_frame(max_line + "\r\n", "OK ping");
  expect_frame(max_line + " \r\n", "ERR input line_too_long");
  expect_frame("ping\n", "OK ping");
  expect_frame(max_line + "\n", "OK ping");
  expect_frame(std::string(2 * desk_robot::kMaxLineLength, ' ') + "ping\n",
               "ERR input line_too_long");
  expect_frame("\r\n", "ERR input empty");
  expect_frame("ping\r\n", "OK ping");
  expect_frame(std::string("pi\0ng\n", 6), "ERR input invalid_ascii");
  expect_frame(std::string("ping\0\r\n", 7), "ERR input invalid_ascii");
  expect_frame("ping\n", "OK ping");
  expect_frame("ping\r\r\n", "ERR input invalid_ascii");
  expect_frame("\n", "ERR input empty");
  expect_frame("ping\r\n", "OK ping");
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
  serial_fragmented_boundaries();
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

void serial_total_frame_timeout() {
  for (const std::uint32_t start : {100U, UINT32_MAX - 250U}) {
    BodyControl body;
    LineReceiver remote;
    LineReceiver local_usb(true);
    // Every adjacent gap is below the idle limit, but the whole command
    // crosses it. No stale ARM or privileged local REARM may execute.
    CHECK(frame(body, remote, "a", start).empty());
    CHECK(frame(body, remote, "r", start + 300U).empty());
    CHECK(frame(body, remote, "m\n", start + 500U)[0] ==
          "ERR input frame_timeout");
    CHECK(!body.state().armed && !body.state().servos_attached);
    CHECK(frame(body, local_usb, "re", start + 501U).empty());
    CHECK(frame(body, local_usb, "ar", start + 801U).empty());
    CHECK(frame(body, local_usb, "m\r", start + 1000U).empty());
    CHECK(frame(body, local_usb, "\n", start + 1001U)[0] ==
          "ERR input frame_timeout");
    CHECK(!body.state().armed && !body.state().servos_attached);
    // Discard through the newline, not the next independent valid command.
    CHECK(frame(body, remote, "ar", start + 1002U).empty());
    CHECK(frame(body, remote, "m\n", start + 1501U)[0] == "OK arm");
    CHECK(frame(body, remote, "disarm\n", start + 1501U)[0] == "OK disarm");
  }
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
    CHECK(body.watchdog_remaining(0) == 200);
    for (const std::uint32_t now : {50U, 100U, 150U, 199U}) {
      refresh(now); // The cliff guard does not expire first.
      body.tick(now);
      CHECK(body.state().armed && body.state().left == 20);
    }
    CHECK(body.watchdog_remaining(199) == 1);
    CHECK(send(body, "status", 199).find("\"watchdog_ms\":1") !=
          std::string::npos);
    refresh(200);
    // A late keepalive cannot restore expired motion or avoid the latch.
    CHECK(send(body, "keepalive", 200) == "ERR keepalive disarmed");
    CHECK(!body.state().armed && body.state().servos_attached);
    CHECK(body.state().left == 0 && body.state().right == 0);
    for (std::uint32_t now = 250; now <= 500; now += 50) {
      refresh(now);
      body.tick(now);
      CHECK(!body.state().armed);
    }
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
    CHECK(send(body, "drive 20 20 250", 502) ==
          "OK drive left=20 right=20 ms=250");
    for (const std::uint32_t now : {552U, 602U, 652U, 702U, 751U}) {
      refresh(now);
      if (now == 602U)
        CHECK(send(body, "keepalive", now) == "OK keepalive");
      body.tick(now);
      CHECK(body.state().armed && body.state().left == 20);
    }
    refresh(752);
    body.tick(752); // original drive duration expires, not extended by keepalive
    CHECK(body.state().armed && body.state().left == 0 &&
          body.state().right == 0);
    CHECK(body.watchdog_remaining(752) == 350);
  }
}

// Exercise the actual guarded controller, not an invented linear docking
// enum. Dock GPIO is only a motion veto; CHG is not proof of charging.
// Enumerate all three-event suffixes from boot, idle, moving, docked and
// CPU-fault prefixes, independently checking authority and actuator state.
void guarded_transition_sequences() {
  enum Event {
    Arm, Drive, Stop, Halt, Disarm, LeftSeat, RightSeat, InputGood,
    ChargeIndicated, Undock, CpuFault, LocalRearm, RemoteRearm,
    UnknownCommand, EventCount
  };
  desk_robot::CliffConfig calibration{};
  calibration.calibrated = true;
  calibration.freshness_ms = 100;
  calibration.front_obstacle_mm = 30;
  calibration.front_max_mm = 1000;
  for (auto& floor : calibration.floor) {
    floor.min_mm = 40;
    floor.max_mm = 60;
  }
  for (const auto profile : {desk_robot::BodyProfile::StepperGuarded,
                             desk_robot::BodyProfile::DcGuarded}) {
    for (int prefix = 0; prefix < 5; ++prefix) {
      for (int a = 0; a < EventCount; ++a) {
        for (int b = 0; b < EventCount; ++b) {
          for (int c = 0; c < EventCount; ++c) {
            desk_robot::CliffGuard guard;
            CHECK(guard.configure(calibration));
            BodyControl body(profile, &guard);
            body.require_dock_monitor(true);
            LineReceiver local(true), remote(false);
            std::uint32_t now = 0;
            bool armed = false, attached = false, moving = false;
            bool latched = true;  // initial cliff sweep requires local rearm
            unsigned dock_pins = 0;
            auto apply = [&](Event event) {
              ++now;
              if (event == LeftSeat) dock_pins = 1U;
              if (event == RightSeat) dock_pins = 2U;
              if (event == InputGood) dock_pins = 4U;
              if (event == ChargeIndicated) dock_pins = 8U;
              if (event == Undock) dock_pins = 0U;
              for (std::uint8_t i = 0; i < 5; ++i)
                guard.sample(i, i < 4 ? 50 : 200, true, now);
              desk_robot::AccessoryReadings readings{};
              readings.dock.present = readings.dock.valid = true;
              readings.dock.sample_seq = readings.dock.at_ms = now;
              readings.dock.left_seated = (dock_pins & 1U) != 0;
              readings.dock.right_seated = (dock_pins & 2U) != 0;
              readings.dock.input_good = (dock_pins & 4U) != 0;
              readings.dock.charge_indicated = (dock_pins & 8U) != 0;
              body.set_accessories(readings, now);
              if (dock_pins != 0) armed = moving = false;
              switch (event) {
                case Arm: {
                  const bool allowed = !latched && dock_pins == 0;
                  CHECK((send(body, "arm", now) == "OK arm") == allowed);
                  if (allowed) {
                    armed = attached = true;
                    moving = false;
                  }
                  break;
                }
                case Drive:
                  CHECK((send(body, "drive 20 20 250", now) ==
                         "OK drive left=20 right=20 ms=250") == armed);
                  moving = armed;
                  break;
                case Stop:
                  CHECK(send(body, "stop", now) == "OK stop");
                  moving = false;
                  break;
                case Halt:
                  CHECK(send(body, "halt", now) == "OK halt");
                  armed = moving = false;
                  break;
                case Disarm:
                  CHECK(send(body, "disarm", now) == "OK disarm");
                  armed = attached = moving = false;
                  break;
                case CpuFault:
                  body.motor_watchdog_trip();
                  armed = moving = false;
                  latched = true;
                  break;
                case LocalRearm: {
                  const auto replies = frame(body, local, "rearm\n", now);
                  CHECK(replies.size() == 1);
                  CHECK((replies[0] == "OK rearm") == (dock_pins == 0));
                  armed = moving = false;
                  if (dock_pins == 0) latched = false;
                  break;
                }
                case RemoteRearm: {
                  const auto replies = frame(body, remote, "rearm\n", now);
                  CHECK(replies.size() == 1);
                  CHECK(replies[0] == "ERR rearm local_only");
                  break;
                }
                case UnknownCommand:
                  CHECK(send(body, "charging", now) ==
                        "ERR input unknown_command");
                  break;
                case LeftSeat:
                case RightSeat:
                case InputGood:
                case ChargeIndicated:
                case Undock:
                  break;
                case EventCount:
                  CHECK(false);
                  break;
              }
              body.tick(now);
              const auto& state = body.state();
              CHECK(state.armed == armed);
              CHECK(state.servos_attached == attached);
              CHECK(state.left == (moving ? 20 : 0));
              CHECK(state.right == (moving ? 20 : 0));
              if (!armed) {
                CHECK(body.watchdog_remaining(now) == 0);
                CHECK(body.drive_remaining(now) == 0);
                CHECK(state.lift_target == state.lift);
                CHECK(state.grip_target == state.grip);
              }
              if (dock_pins != 0 || latched) CHECK(!armed && !moving);
            };
            try {
              if (prefix != 0) { apply(LocalRearm); apply(Arm); }
              if (prefix >= 2) apply(Drive);
              if (prefix == 3) apply(LeftSeat);
              if (prefix == 4) apply(CpuFault);
              apply(static_cast<Event>(a));
              apply(static_cast<Event>(b));
              apply(static_cast<Event>(c));
            } catch (const std::exception& error) {
              throw std::runtime_error(
                  std::string(error.what()) + " profile=" +
                  std::to_string(static_cast<int>(profile)) +
                  " prefix=" + std::to_string(prefix) +
                  " events=" + std::to_string(a) + "," +
                  std::to_string(b) + "," + std::to_string(c));
            }
          }
        }
      }
    }
  }
}

// Independent watchdog, optical and bumper trips must compose. A reset
// reconstructs both owners and UART parsers; persisted calibration is not
// a persisted permit. The fixture deliberately does not simulate hardware.
void guarded_reboot_fault_matrix() {
  using desk_robot::BodyProfile;
  desk_robot::CliffConfig calibration{};
  calibration.calibrated = true;
  calibration.freshness_ms = 100;
  calibration.front_obstacle_mm = 30;
  calibration.front_max_mm = 1000;
  for (auto& floor : calibration.floor) {
    floor.min_mm = 40;
    floor.max_mm = 60;
  }
  auto refresh = [](desk_robot::CliffGuard& guard, std::uint32_t now,
                    std::uint8_t count = 5) {
    for (std::uint8_t lane = 0; lane < count; ++lane)
      guard.sample(lane, lane < 4 ? 50 : 200, true, now);
  };
  auto stopped = [](const BodyControl& body, std::uint32_t now) {
    const auto& state = body.state();
    CHECK(!state.armed && state.left == 0 && state.right == 0);
    CHECK(body.drive_remaining(now) == 0 && body.watchdog_remaining(now) == 0);
    CHECK(state.lift_target == state.lift && state.grip_target == state.grip);
  };
  auto reject_replay = [&](BodyControl& body, LineReceiver& remote,
                           std::uint32_t now) {
    auto replies = frame(body, remote, "arm\ndrive 20 20 250\nkeepalive\nrearm\n", now);
    CHECK(replies.size() == 4);
    CHECK(replies[0].find("ERR arm ") == 0);
    CHECK(replies[1] == "ERR drive disarmed");
    CHECK(replies[2] == "ERR keepalive disarmed");
    CHECK(replies[3] == "ERR rearm local_only");
    stopped(body, now);
  };
  for (const auto profile : {BodyProfile::StepperGuarded, BodyProfile::DcGuarded}) {
    auto check_reboot = [&]() {
      desk_robot::CliffGuard reset_guard;
      CHECK(reset_guard.configure(calibration));
      BodyControl reset(profile, &reset_guard);
      LineReceiver remote, local(true);
      stopped(reset, 0);
      CHECK(!reset.state().servos_attached);
      reject_replay(reset, remote, 0);
      CHECK(frame(reset, local, "rearm\n", 0).at(0) == "ERR rearm safety_interlock");
      refresh(reset_guard, 1, 4); // missing forward lane
      CHECK(frame(reset, local, "rearm\n", 1).at(0) == "ERR rearm safety_interlock");
      refresh(reset_guard, 2);
      reject_replay(reset, remote, 2);
      CHECK(frame(reset, local, "rearm\n", 2).at(0) == "OK rearm");
      stopped(reset, 2);
      CHECK(!reset.state().servos_attached);
      CHECK(send(reset, "drive 20 20 250", 2) == "ERR drive disarmed");
      CHECK(send(reset, "arm", 2) == "OK arm");
      CHECK(reset.state().left == 0 && reset.state().right == 0);
    };
    for (const std::uint32_t start : {10U, std::numeric_limits<std::uint32_t>::max() - 100U}) {
      for (bool moving : {false, true}) {
        // Bits: head-link deadline, cliff, bumper, independent CPU cutoff.
        for (unsigned mask = 1; mask < 16; ++mask) {
          for (bool reverse_order : {false, true}) {
            desk_robot::CliffGuard guard;
            CHECK(guard.configure(calibration));
            refresh(guard, start);
            BodyControl body(profile, &guard);
            LineReceiver remote, local(true);
            CHECK(frame(body, local, "rearm\n", start).at(0) == "OK rearm");
            CHECK(send(body, "arm", start) == "OK arm");
            CHECK(send(body, "lift 120", start) == "OK lift angle=120");
            CHECK(send(body, "grip 60", start) == "OK grip angle=60");
            if (moving)
              CHECK(send(body, "drive 20 20 250", start).find("OK drive") == 0);
            auto now = start;
            if (mask & 1U) {
              const auto limit = moving ? 200U : 500U;
              for (unsigned elapsed = 50; elapsed < limit; elapsed += 50) {
                refresh(guard, start + elapsed);
                body.tick(start + elapsed);
                CHECK(body.state().armed);
              }
              now = start + limit;
              refresh(guard, now);
              // A valid frame at the exact deadline cannot renew the old lease.
              CHECK(frame(body, remote, "keepalive\n", now).at(0) ==
                    "ERR keepalive disarmed");
              stopped(body, now);
            }
            ++now;
            const auto lane = static_cast<std::uint8_t>(mask % 5);
            auto cliff = [&]() {
              if (mask & 2U) guard.sample(lane, lane < 4 ? 80 : 30, true, now);
            };
            auto bumper = [&]() {
              if (mask & 4U) {
                body.sample_bumper_input(true);
                body.sample_bumper_input(false);
                body.sample_bumper_input(true);
              }
            };
            auto cpu = [&]() { if (mask & 8U) body.motor_watchdog_trip(); };
            if (reverse_order) { cpu(); bumper(); cliff(); }
            else { cliff(); bumper(); cpu(); }
            body.tick(now);
            stopped(body, now);
            CHECK(body.state().servos_attached);
            reject_replay(body, remote, now);
            check_reboot(); // reset while the previous session was latched
            if (mask & 6U)
              CHECK(frame(body, local, "rearm\n", now).at(0).find("ERR rearm ") == 0);
            if (mask & 4U) {
              body.sample_bumper_input(false);
              body.sample_bumper_input(true); // contact bounce, no event debounce
              CHECK(frame(body, local, "rearm\n", now).at(0) == "ERR rearm bumper_active");
              body.sample_bumper_input(false);
            }
            if (mask & 2U) {
              // A putdown may replace the bad range but cannot replace a
              // complete, fresh safety sweep or the local operator decision.
              now += 100U;
              refresh(guard, now, 4);
              CHECK(frame(body, local, "rearm\n", now).at(0) ==
                    "ERR rearm safety_interlock");
            }
            refresh(guard, ++now);
            reject_replay(body, remote, now);
            CHECK(send(body, "stop", now) == "OK stop");
            CHECK(send(body, "halt", now) == "OK halt");
            if (reverse_order) {
              CHECK(send(body, "disarm", now) == "OK disarm");
              CHECK(!body.state().servos_attached);
            }
            reject_replay(body, remote, now);
            CHECK(frame(body, local, "rearm\n", now).at(0) == "OK rearm");
            stopped(body, now);
            CHECK(send(body, "drive 20 20 250", now) == "ERR drive disarmed");
            CHECK(send(body, "arm", now) == "OK arm");
            CHECK(body.state().left == 0 && body.state().right == 0);
            CHECK(send(body, "drive 20 20 250", now).find("OK drive") == 0);
            check_reboot(); // reset during a newly authorized drive
          }
        }
      }
    }
  }
}

void deterministic_stream_stress() {
  exhaustive_malformed_drive();
  guarded_transition_sequences();
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
      {"attitude_norm_root_boundaries", attitude_norm_root_boundaries},
      {"optional_inputs_preserve_raw_stop_and_event_history",
       optional_inputs_preserve_raw_stop_and_event_history},
      {"disarmed_boot", disarmed_boot}, {"arm_clears_old_motion", arm_clears_old_motion},
      {"drive_limits", drive_limits}, {"drive_duration", drive_duration},
      {"overlapping_drive_replaces_pending_pulse", overlapping_drive_replaces_pending_pulse},
      {"keepalive_does_not_extend_drive", keepalive_does_not_extend_drive},
      {"invalid_does_not_renew", invalid_does_not_renew},
      {"rejected_grip_does_not_renew_watchdog", rejected_grip_does_not_renew_watchdog},
      {"queries_do_not_renew", queries_do_not_renew}, {"smooth_servos", smooth_servos},
      {"keepalive_extends_servo_lease", keepalive_extends_servo_lease},
      {"stop_freezes_servos", stop_freezes_servos},
      {"explicit_disarm_detaches", explicit_disarm_detaches},
      {"watchdog_holds_servos", watchdog_holds_servos},
      {"rollover_timers", rollover_timers}, {"strict_integer_parser", strict_integer_parser},
      {"tokenizer_failure_contract", tokenizer_failure_contract},
      {"malformed_atomicity", malformed_atomicity},
      {"overlong_frame_recovery", overlong_frame_recovery}, {"framing", framing},
      {"serial_idle_frame_timeout", serial_idle_frame_timeout},
      {"serial_total_frame_timeout", serial_total_frame_timeout},
      {"independent_receivers", independent_receivers}, {"status_honesty", status_honesty},
      {"guarded_head_timeout_cannot_rearm_from_reconnected_uart",
       guarded_head_timeout_cannot_rearm_from_reconnected_uart},
      {"guarded_transition_sequences", guarded_transition_sequences},
      {"guarded_reboot_fault_matrix", guarded_reboot_fault_matrix},
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
