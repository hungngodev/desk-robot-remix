#include <cassert>
#include <cstdint>
#include <string>
#include <vector>

#include "BodyControl.h"
#include "CliffGuard.h"
#include "robot_protocol.h"

namespace {
using namespace desk_robot;

std::string frame(BodyControl& body, LineReceiver& receiver,
                  const std::string& bytes, std::uint32_t now,
                  std::uint64_t sample_us = 0) {
    char reply[kReplyCapacity]{};
    unsigned completed = 0;
    for (const char byte : bytes) {
        if (receiver.feed(byte, now, body, reply, sizeof(reply), sample_us))
            ++completed;
    }
    assert(completed == 1);
    return reply;
}

std::string head_command(BodyControl& body, LineReceiver& head,
                         const std::string& text, bool operator_control,
                         std::uint32_t now, std::uint64_t sample_us = 0) {
    Command command;
    assert(ParseCommand(text, operator_control, command));
    return frame(body, head, command.wire + "\r\n", now, sample_us);
}

void fresh(CliffGuard& guard, std::uint32_t now) {
    for (std::uint8_t lane = 0; lane < 5; ++lane)
        guard.sample(lane, lane < 4 ? 50 : 200, true, now);
}

void observe(BodyControl& body, LineReceiver& head, std::uint32_t now,
             std::uint64_t sample_us) {
    for (const auto verb : {"status", "aux", "ir", "optics", "pose", "ping"}) {
        const auto reply = head_command(body, head, verb, false, now, sample_us);
        assert(!reply.empty());
        assert(reply.find("OK drive") != 0 && reply.find("OK arm") != 0);
    }
}

void verify(BodyProfile profile, std::uint32_t start) {
    CliffConfig config;
    config.calibrated = true;
    config.freshness_ms = 100;
    config.front_obstacle_mm = 30;
    config.front_max_mm = 1000;
    for (auto& interval : config.floor) {
        interval.min_mm = 40;
        interval.max_mm = 60;
    }
    CliffGuard guard;
    assert(guard.configure(config));
    BodyControl body(profile, &guard);
    body.set_boot_epoch(42);
    LineReceiver head;
    LineReceiver usb(true);
    fresh(guard, start);
    assert(frame(body, head, "rearm\r\n", start) == "ERR rearm local_only");
    assert(frame(body, usb, "rearm\r\n", start) == "OK rearm");
    assert(head_command(body, head, "arm", true, start) == "OK arm");
    assert(head_command(body, head, "drive 20 20 250", true, start) ==
           "OK drive left=20 right=20 ms=250");

    for (std::uint32_t elapsed = 1; elapsed <= 200; ++elapsed) {
        const auto now = start + elapsed;
        fresh(guard, now);
        observe(body, head, now, 1000000ULL + elapsed * 1000ULL);
        if (elapsed < 200) {
            assert(body.state().armed && body.state().left == 20);
            assert(body.watchdog_remaining(now) == 200 - elapsed);
            assert(body.drive_remaining(now) == 250 - elapsed);
        }
        if (elapsed == 100) {
            const std::vector<std::string> malformed = {
                "drive 20 20 251", "drive 2147483648 20",
                "drive 20 20 250 junk", "status\rdrive 20 20",
                "drive 20 20 250\rkeepalive", std::string("drive 20 20\0", 12),
            };
            for (const auto& input : malformed) {
                Command parsed;
                assert(!ParseCommand(input, true, parsed));
                assert(frame(body, head, input + "\r\n", now).find("ERR ") == 0);
                assert(body.watchdog_remaining(now) == 100);
                assert(body.drive_remaining(now) == 150);
            }
        }
    }
    auto now = start + 200;
    assert(!body.state().armed && body.state().left == 0 && body.state().right == 0);
    assert(body.watchdog_remaining(now) == 0 && body.drive_remaining(now) == 0);
    Command rejected;
    assert(!ParseCommand("rearm", true, rejected));
    assert(!ParseCommand("rearm", false, rejected));
    assert(frame(body, head, "rearm\r\n", now) == "ERR rearm local_only");
    assert(frame(body, head, "calabort\r\n", now) == "ERR calibration local_usb_only");
    assert(head_command(body, head, "keepalive", true, now) == "ERR keepalive disarmed");
    assert(head_command(body, head, "arm", true, now) == "ERR arm command_timeout_latched");
    assert(head_command(body, head, "drive 20 20 250", true, now) == "ERR drive disarmed");

    // A newer local USB recovery plus a new ARM is required. An explicit
    // keepalive may renew the host lease, but not the original drive permit.
    now = start + 201;
    fresh(guard, now);
    assert(frame(body, usb, "rearm\r\n", now) == "OK rearm");
    assert(!body.state().armed && body.drive_remaining(now) == 0);
    assert(head_command(body, head, "arm", true, now) == "OK arm");
    assert(head_command(body, head, "drive 20 20 250", true, now) ==
           "OK drive left=20 right=20 ms=250");
    for (std::uint32_t elapsed = 1; elapsed <= 600; ++elapsed) {
        now = start + 201 + elapsed;
        fresh(guard, now);
        observe(body, head, now, 2000000ULL + elapsed * 1000ULL);
        if (elapsed == 100)
            assert(head_command(body, head, "keepalive", true, now) == "OK keepalive");
        if (elapsed < 250) {
            assert(body.state().armed && body.state().left == 20);
            assert(body.drive_remaining(now) == 250 - elapsed);
        } else {
            assert(body.state().left == 0 && body.state().right == 0);
            assert(body.drive_remaining(now) == 0);
            assert(body.state().armed == (elapsed < 600));
            assert(body.watchdog_remaining(now) == 600 - elapsed);
        }
    }
    assert(head_command(body, head, "arm", true, now) == "ERR arm command_timeout_latched");
    assert(frame(body, head, "rearm\r\n", now) == "ERR rearm local_only");
}
}  // namespace

int main() {
    for (auto profile : {desk_robot::BodyProfile::StepperGuarded,
                         desk_robot::BodyProfile::DcGuarded}) {
        verify(profile, 1000U);
        verify(profile, 0xffffff80U);
    }
}
