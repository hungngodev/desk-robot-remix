#include <cassert>
#include <string>
#include "robot_protocol.h"
#include "real_touch_edges.h"
using namespace desk_robot;
int main() {
    std::uint8_t jpeg[] = {0xff, 0xd8, 0x11, 0x22, 0xff, 0xd9};
    assert(CompleteJpeg(jpeg, sizeof(jpeg)));
    assert(!CompleteJpeg(nullptr, sizeof(jpeg)));
    assert(!CompleteJpeg(jpeg, 3));
    assert(!CompleteJpeg(jpeg, 512 * 1024 + 1));
    jpeg[0] = 0x11;
    assert(!CompleteJpeg(jpeg, sizeof(jpeg)));
    jpeg[0] = 0xff;
    jpeg[5] = 0x00;
    assert(!CompleteJpeg(jpeg, sizeof(jpeg)));

    RealTouchEdges head;
    assert(head.Observe(10) == 0); // first read is baseline
    assert(head.Observe(11) == 1);
    assert(head.Observe(11) == 0);
    assert(head.Observe(12) == 1);
    assert(head.Observe(0) == 0); // unplug, reset or reboot
    assert(head.Observe(1) == 1);
    assert(head.Observe(99) == 0); // huge jump cannot forge touch
    head.Reset();
    assert(head.Observe(8) == 0);
    RealTouchEdges cap;
    assert(cap.Observe(4294967295U) == 0);
    assert(cap.Observe(0) == 0); // wrap never fabricates a contact
    assert(cap.Observe(3) == 3);

    // OLED expressions require a genuinely active and ready local WROOM
    // guard. A legacy "not_required" profile or an unready calibration may
    // still provide sensors, but neither can advertise a healthy body.
    assert(!BodySafetyUnhealthy(true, true, "none"));
    assert(BodySafetyUnhealthy(false, true, "not_required"));
    assert(BodySafetyUnhealthy(false, false, "none"));
    assert(BodySafetyUnhealthy(true, false, "none"));
    assert(BodySafetyUnhealthy(true, true, "cliff"));
    assert(BodySafetyUnhealthy(true, true, ""));
    assert(BodySafetyUnhealthy(true, false, "not_required"));
    // A genuine WROOM dock interlock is still unhealthy and motor stopped.
    // Only a known, disarmed, required, not-ready local status may get a
    // truthful dock-lock label. Any stale/malformed status reverts to STOP.
    assert(BodySafetyUnhealthy(true, false, "dock_power_connected"));
    assert(BodyDockLockoutObserved(true, false, false, "dock_power_connected"));
    assert(!BodyDockLockoutObserved(true, true, false, "dock_power_connected"));
    assert(!BodyDockLockoutObserved(false, false, false, "dock_power_connected"));
    assert(!BodyDockLockoutObserved(true, false, true, "dock_power_connected"));
    assert(!BodyDockLockoutObserved(true, false, false, "dock_monitor_latched"));
    assert(!BodyDockLockoutObserved(true, false, false, "cliff"));
    assert(!BodyDockLockoutObserved(true, false, false, "none"));
    assert(!BodyDockLockoutObserved(true, false, false, ""));

    // Cosmetic cues are latest only, time bounded, and never motor commands.
    CosmeticMoodCue mood;
    assert(ParseCosmeticMood("mood:thinking") == CosmeticMood::kThinking);
    assert(ParseCosmeticMood("mood:surprised") == CosmeticMood::kSurprised);
    assert(ParseCosmeticMood("mood:move") == CosmeticMood::kNone);
    assert(ParseCosmeticMood("arm") == CosmeticMood::kNone);
    mood.offer(CosmeticMood::kHappy, 1000);
    mood.offer(CosmeticMood::kThinking, 1010);
    assert(mood.take(1100) == CosmeticMood::kThinking);
    assert(mood.take(1101) == CosmeticMood::kNone);
    mood.offer(CosmeticMood::kSurprised, 1000);
    assert(mood.take(2200) == CosmeticMood::kNone); // stale > 1s
    mood.offer(CosmeticMood::kNeutral, 0xffffff00U);
    assert(mood.take(0xffffff64U) == CosmeticMood::kNeutral); // uptime wrap
    mood.offer(CosmeticMood::kHappy, 200);
    assert(mood.take(200) == CosmeticMood::kHappy);
    // True UINT32 millisecond wrap, not merely a value near the rollover.
    // The former 24-bit /100 clock jumped by millions of ticks here.
    mood.offer(CosmeticMood::kThinking, 0xfffffff0U);
    assert(mood.take(100U) == CosmeticMood::kThinking);
    mood.offer(CosmeticMood::kSurprised, 0xfffffff0U);
    assert(mood.take(1050U) == CosmeticMood::kNone);
    // One pending receipt may not be replayed twice after a wrap.
    mood.offer(CosmeticMood::kNeutral, 0xffffffffU);
    assert(mood.take(0U) == CosmeticMood::kNeutral);
    assert(mood.take(1U) == CosmeticMood::kNone);

    // Face processing cannot replay an aged person observation after stalls
    // or when the uint32_t millisecond timer wraps.
    TimedPersonCue person;
    assert(!person.take(0));
    person.offer(1100);
    assert(person.take(1200));
    assert(!person.take(1201));
    person.offer(1100);
    assert(!person.take(2105));
    person.offer(0xfffffffeU);
    assert(person.take(4U));
    person.offer(0xfffffffeU);
    assert(!person.take(1100U));

    // Urgent requests must win over telemetry without fabricating ACKs.
    UrgentStopGate gate;
    assert(!gate.preempts(false));
    {
        UrgentStopGate::Request read(gate, false);
        assert(!gate.preempts(false));
        {
            UrgentStopGate::Request stop(gate, true);
            assert(gate.preempts(false));
            assert(!gate.preempts(true));
            {
                UrgentStopGate::Request halt(gate, true);
                assert(gate.preempts(false));
            }
            assert(gate.preempts(false));
        }
        assert(!gate.preempts(false));
    }

    Command c;
    assert(ParseCommand("drive 100 -100 250", false, c));
    assert(ExpectedAck(c) == "OK drive left=40 right=-40 ms=250");
    assert(ExpectedAck(c) != "OK drive left=40 right=-40 ms=150");
    assert(ParseCommand("drive 0 0", false, c));
    assert(ExpectedAck(c) == "OK drive left=0 right=0 ms=250");
    assert(ParseCommand("aux", false, c));
    assert(c.verb == "aux");
    assert(ParseCommand("ir", false, c));
    assert(c.verb == "ir");
    assert(ParseCommand("optics", false, c));
    assert(c.verb == "optics");
    assert(!ParseCommand("optics 1", false, c));
    assert(!ParseCommand("optics nonsense", true, c));
    assert(!ParseCommand("ir 1", false, c));
    assert(!ParseCommand("aux 1", false, c));
    assert(!ParseCommand("aux urgent", true, c));
    assert(ParseCommand("grip 60", false, c));
    assert(ExpectedAck(c) == "OK grip angle=60");
    assert(MatchingError("ERR grip disarmed", c));
    assert(!MatchingError("ERR drive disarmed", c));
    assert(!MatchingError("ERR gripper disarmed", c));
    for (const std::string bad : {"", "drive", "drive 1 1 0", "drive 1 1 251", "drive 101 1 1", "drive 1 -101", "drive 1 1 1 junk", "drive 1.0 1", "drive nan 1", "drive +1 1", "drive 1  1", " drive 1 1", "drive 1 1 ", "grip 59", "lift 121", "stop junk", "status\r", "ping\n", "drive 9999999999999999 0", "arm now", "forward 100"}) {
        assert(!ParseCommand(bad, true, c));
    }
    for (const auto verb : {"arm", "disarm", "keepalive"}) {
        assert(!ParseCommand(verb, false, c));
        assert(ParseCommand(verb, true, c));
        assert(ExpectedAck(c) == std::string("OK ") + verb);
    }
    // Guard fault recovery is a body-local USB action, never a bridge command,
    // even when the caller has ordinary head/operator movement authority.
    assert(!ParseCommand("rearm", true, c));
    assert(!ParseCommand("rearm", false, c));
    assert(!ParseCommand(std::string(96, 'x'), true, c));
    for (int value = 0; value < 256; ++value) {
        if (value >= 32 && value <= 126) continue;
        assert(!ParseCommand(std::string("stop") + static_cast<char>(value), true, c));
    }
}
