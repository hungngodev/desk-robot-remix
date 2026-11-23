#include "BodyControl.h"

#include <cstdint>
#include <stdexcept>
#include <string>

namespace {
void check(bool condition) {
  if (!condition) throw std::runtime_error("pose read-only contract failed");
}

std::string request(desk_robot::BodyControl& body,
                    desk_robot::LineReceiver& receiver,
                    const std::string& line, std::uint32_t now_ms,
                    std::uint64_t sample_us) {
  char reply[desk_robot::kReplyCapacity]{};
  bool complete = false;
  for (char byte : line)
    if (receiver.feed(byte, now_ms, body, reply, sizeof(reply), sample_us))
      complete = true;
  check(complete);
  return reply;
}

void verify() {
  desk_robot::BodyControl body;
  desk_robot::LineReceiver head;
  check(request(body, head, "pose\r\n", 10, 100000) ==
        "ERR pose clock_or_sequence_unavailable");
  body.set_boot_epoch(42);
  const std::string expected =
      "{\"v\":1,\"body_boot\":42,\"origin\":0,\"seq\":1,"
      "\"sample_us\":100001,\"x_mm\":0,\"y_mm\":0,"
      "\"yaw_mrad\":0,\"quality\":\"unavailable\"}";
  const auto first = request(body, head, "pose\r\n", 10, 100001);
  check(first == expected);
  check(first.size() < 180);
  check(!body.state().armed && body.state().left == 0 && body.state().right == 0);
  check(request(body, head, "pose\r\n", 10, 100001) ==
        "ERR pose clock_or_sequence_unavailable");
  check(request(body, head, "pose\r\n", 11, 100000) ==
        "ERR pose clock_or_sequence_unavailable");
  check(request(body, head, "pose extra\r\n", 11, 100002) ==
        "ERR pose bad_arguments");
  check(request(body, head, "pose v=2\r\n", 11, 100002) ==
        "ERR pose bad_arguments");
  check(request(body, head, "pose\r\n", 11, 100002).find("\"seq\":2") !=
        std::string::npos);
  check(request(body, head, "arm\r\n", 12, 100003) == "OK arm");
  check(request(body, head, "drive 20 20 250\r\n", 13, 100004).find("OK drive") == 0);
  const auto left = body.state().left;
  const auto right = body.state().right;
  check(request(body, head, "pose\r\n", 14, 100005).find(
      "\"quality\":\"unavailable\"") != std::string::npos);
  check(body.state().armed && body.state().left == left &&
        body.state().right == right);
  // A pose request must NOT refresh the 500 ms remote control watchdog.
  check(request(body, head, "pose\r\n", 514, 600005).find(
      "\"quality\":\"unavailable\"") != std::string::npos);
  check(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0);
  check(request(body, head, "stop\r\n", 515, 600006) == "OK stop");
  body.set_boot_epoch(99);
  const auto reboot = request(body, head, "pose\r\n", 1, 8);
  check(reboot.find("\"body_boot\":99") != std::string::npos);
  check(reboot.find("\"seq\":1") != std::string::npos);
  check(reboot.find("\"sample_us\":8") != std::string::npos);
  // Invalid times never become a recent body observation.
  check(request(body, head, "pose\r\n", 2, 9007199254740992ULL) ==
        "ERR pose clock_or_sequence_unavailable");
  // Reassigning the SAME boot identity cannot reset its sequence fence.
  body.set_boot_epoch(99);
  check(request(body, head, "pose\r\n", 3, 9).find("\"seq\":2") !=
        std::string::npos);

}

// Heavy read-only polling and rejected UART input must not turn into either a
// remote-control keepalive or an apparent new measured wheel observation.
void verify_poll_flood_and_malformed_frames() {
  desk_robot::BodyControl body;
  desk_robot::LineReceiver receiver;
  body.set_boot_epoch(73);
  check(request(body, receiver, "arm\r\n", 10, 0) == "OK arm");
  check(request(body, receiver, "drive 15 -15 250\r\n", 11, 0)
            .find("OK drive") == 0);

  std::uint32_t sequence = 0;
  for (std::uint32_t now = 12; now <= 612; now += 24) {
    const auto response = request(
        body, receiver, "pose\r\n", now,
        static_cast<std::uint64_t>(now) * 1000ULL);
    check(response.find("\"seq\":" + std::to_string(++sequence) + ",") !=
          std::string::npos);
    check(response.find("\"origin\":0") != std::string::npos);
    check(response.find("\"quality\":\"unavailable\"") != std::string::npos);
    if (now >= 276)
      check(body.state().left == 0 && body.state().right == 0);
    if (now >= 516) check(!body.state().armed);
  }
  check(!body.state().armed);
  check(request(body, receiver, "pose v=2\r\n", 650, 650000) ==
        "ERR pose bad_arguments");
  check(request(body, receiver, "pose\rjunk\n", 650, 650000) ==
        "ERR input invalid_ascii");
  check(request(body, receiver,
                "pose" + std::string(desk_robot::kMaxLineLength + 1, 'x') +
                    "\r\n", 650, 650000) ==
        "ERR input line_too_long");
  const auto next = request(body, receiver, "pose\r\n", 650, 650000);
  check(next.find("\"seq\":" + std::to_string(sequence + 1) + ",") !=
        std::string::npos);
  check(next.find("\"quality\":\"unavailable\"") != std::string::npos);
  check(!body.state().armed && body.state().left == 0 &&
        body.state().right == 0);
}
}  // namespace

int main() {
  verify();
  verify_poll_flood_and_malformed_frames();
  return 0;
}
