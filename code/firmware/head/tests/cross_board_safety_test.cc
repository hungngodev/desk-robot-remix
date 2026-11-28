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
             std::uint64_t sample_us, std::uint32_t pose_seq) {
    for (const auto verb : {"status", "aux", "ir", "optics", "pose", "ping"}) {
        const auto reply = head_command(body, head, verb, false, now, sample_us);
        assert(!reply.empty());
        assert(reply.find("OK drive") != 0 && reply.find("OK arm") != 0);
        if (std::string(verb) == "pose") {
            // Polling must produce a fresh unavailable pose, not an error,
            // stale receipt or navigation authority.
            assert(reply == "{\"v\":1,\"body_boot\":42,\"origin\":0,\"seq\":" +
                   std::to_string(pose_seq) + ",\"sample_us\":" +
                   std::to_string(sample_us) + ",\"x_mm\":0,\"y_mm\":0,"
                   "\"yaw_mrad\":0,\"quality\":\"unavailable\"}");
        }
    }
}

void verify_urgent_stop(BodyControl& body, LineReceiver& head, LineReceiver& usb,
                        CliffGuard& guard, std::uint32_t now) {
    fresh(guard, now);
    assert(frame(body, usb, "rearm\r\n", now) == "OK rearm");
    assert(head_command(body, head, "arm", true, now) == "OK arm");
    assert(head_command(body, head, "drive 20 20 250", true, now) ==
           "OK drive left=20 right=20 ms=250");
    UrgentStopGate gate;
    UrgentStopGate::Request queued(gate, false);
    assert(!queued.preempted());
    {
        UrgentStopGate::Request urgent(gate, true);
        assert(!urgent.preempted());
        assert(queued.preempted());
        assert(head_command(body, head, "stop", false, now + 1) == "OK stop");
        assert(body.state().armed);
        assert(body.state().left == 0 && body.state().right == 0);
        assert(body.drive_remaining(now + 1) == 0);
    }
    assert(queued.preempted());
    UrgentStopGate::Request new_request(gate, false);
    assert(!new_request.preempted());
    assert(head_command(body, head, "drive 20 20 250", true, now + 2) ==
           "OK drive left=20 right=20 ms=250");
    {
        UrgentStopGate::Request urgent(gate, true);
        assert(new_request.preempted());
        assert(head_command(body, head, "halt", false, now + 3) == "OK halt");
    }
    assert(new_request.preempted());
    assert(!body.state().armed && body.state().left == 0 && body.state().right == 0);
    assert(head_command(body, head, "drive 20 20 250", true, now + 4) ==
           "ERR drive disarmed");
}

void verify_dock_contact(BodyControl& body, LineReceiver& head, CliffGuard& guard,
                         std::uint32_t now) {
    body.require_dock_monitor(true);
    AccessoryReadings readings{};
    readings.dock.present = readings.dock.valid = true;
    readings.dock.sample_seq = 1;
    readings.dock.at_ms = now;
    fresh(guard, now);
    body.set_accessories(readings, now);
    for (const auto contact : {&DockPinRaw::left_seated, &DockPinRaw::right_seated,
                               &DockPinRaw::input_good}) {
        assert(head_command(body, head, "arm", true, now) == "OK arm");
        assert(head_command(body, head, "drive 20 20 250", true, now) ==
               "OK drive left=20 right=20 ms=250");
        readings.dock.*contact = true;
        readings.dock.at_ms = ++now;
        ++readings.dock.sample_seq;
        fresh(guard, now);
        body.set_accessories(readings, now);
        assert(!body.state().armed && body.state().left == 0 && body.state().right == 0);
        assert(body.drive_remaining(now) == 0);
        const auto status = head_command(body, head, "status", false, now);
        assert(status.find("\"safety\":{\"required\":true,\"ready\":false,"
                           "\"fault\":\"dock_power_connected\"") != std::string::npos);
        assert(head_command(body, head, "arm", true, now) == "ERR arm dock_power_connected");
        assert(head_command(body, head, "drive 20 20 250", true, now) == "ERR drive disarmed");
        readings.dock.*contact = false;
        readings.dock.at_ms = ++now;
        ++readings.dock.sample_seq;
        fresh(guard, now);
        body.set_accessories(readings, now);
        assert(!body.state().armed && body.drive_remaining(now) == 0);
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
        observe(body, head, now, 1000000ULL + elapsed * 1000ULL, elapsed);
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
        observe(body, head, now, 2000000ULL + elapsed * 1000ULL, 200U + elapsed);
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
    verify_urgent_stop(body, head, usb, guard, now + 1);
    verify_dock_contact(body, head, guard, now + 10);
}

void verify_framed_integrity_cross_board(BodyProfile profile) {
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
    fresh(guard, 5000U);
    BodyControl body(profile, &guard);
    body.set_boot_epoch(42);
    LineReceiver usb(true);
    LineReceiver head(false, true);
    assert(frame(body, usb, "rearm\r\n", 5000U) == "OK rearm");
    std::uint32_t tx_id = 100U;
    auto send_framed = [&](const std::string& text, bool operator_ctrl, std::uint32_t now) {
        Command cmd;
        assert(ParseCommand(text, operator_ctrl, cmd));
        const std::string wire = FormatIntegrityFrame(tx_id, cmd.wire) + "\r\n";
        char reply[kReplyCapacity]{};
        unsigned completed = 0;
        for (char c : wire) {
            if (head.feed(c, now, body, reply, sizeof(reply), now * 1000ULL)) ++completed;
        }
        assert(completed == 1);
        assert(head.last_tx_id() == tx_id);
        assert(head.wrap_reply(reply, sizeof(reply)));
        std::uint32_t rx_id = 0U;
        std::string_view inner;
        assert(ParseIntegrityFrame(reply, rx_id, inner) && rx_id == tx_id);
        ++tx_id;
        return std::string(inner);
    };
    assert(send_framed("arm", true, 5001U) == "OK arm");
    assert(send_framed("drive 20 20 250", true, 5002U) == "OK drive left=20 right=20 ms=250");
    assert(body.state().left == 20 && body.state().right == 20);
    // Corrupted checksum frame rejected without renewing drive lease.
    std::string bad = FormatIntegrityFrame(tx_id++, "drive 10 10 250");
    bad[bad.find("10")] = '3';
    assert(frame(body, head, bad + "\r\n", 5010U) == "ERR input bad_checksum");
    assert(body.state().left == 20);
    assert(send_framed("stop", false, 5020U) == "OK stop");
    assert(body.state().left == 0 && body.state().right == 0);
}
}  // namespace

int main() {
    for (auto profile : {desk_robot::BodyProfile::StepperGuarded,
                         desk_robot::BodyProfile::DcGuarded}) {
        verify(profile, 1000U);
        verify(profile, 0xffffff80U);
        verify_framed_integrity_cross_board(profile);
    }
}
