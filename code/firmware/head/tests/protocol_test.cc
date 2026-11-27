#include <cassert>
#include <limits>
#include <string>
#include <vector>
#include "robot_protocol.h"
#include "real_touch_edges.h"
using namespace desk_robot;

// Minimal decoded cJSON-shaped nodes; the same templated validator is
// called by the bridge after actual cJSON parsing.
struct JsonNode {
    const char* string = nullptr;
    JsonNode* child = nullptr;
    JsonNode* next = nullptr;
    bool object = false;
};

int main() {
    const auto is_object = [](const JsonNode* node) { return node->object; };
    JsonNode second{"ready"};
    JsonNode first{"ready", nullptr, &second};
    JsonNode safety{"safety", &first, nullptr, true};
    JsonNode root{nullptr, &safety, nullptr, true};
    assert(!JsonKeysUnique(&root, is_object));
    second.string = "fault";
    assert(JsonKeysUnique(&root, is_object));
    second.string = nullptr;
    assert(!JsonKeysUnique(&root, is_object));
    second.string = "ready";
    JsonNode array{nullptr, &safety};
    assert(!JsonKeysUnique(&array, is_object));
    second.string = "READY";
    assert(JsonKeysUnique(&array, is_object));
    JsonNode distinct{"other", &second, nullptr, true};
    safety.next = &distinct;
    first.next = nullptr;
    second.string = "ready";
    assert(JsonKeysUnique(&root, is_object)); // same name in different objects
    assert(!JsonKeysUnique(static_cast<const JsonNode*>(nullptr), is_object));

    assert(ContentLengthMatches("0", 0));
    assert(ContentLengthMatches("0160", 160));
    assert(ContentLengthMatches("160", 160));
    assert(!ContentLengthMatches("", 0));
    assert(!ContentLengthMatches("160", 159));
    assert(!ContentLengthMatches("4294967296", 0));
    assert(!ContentLengthMatches("4294967456", 160));
    assert(!ContentLengthMatches("18446744073709551616", 0));
    assert(ContentLengthMatches(std::to_string(std::numeric_limits<std::size_t>::max()),
                                std::numeric_limits<std::size_t>::max()));
    for (const auto field : {"-1", "+1", " 1", "1 ", "1,1", "1\t", "1x"})
        assert(!ContentLengthMatches(field, 1));
    assert(!ContentLengthMatches(std::string_view("1\0", 2), 1));
    assert(JsonWireBounded(R"({"command":"stop"})"));
    assert(JsonWireBounded(R"({"event":"[{{{\"}}}}"})"));
    assert(JsonWireBounded(std::string(12, '[') + std::string(12, ']')));
    assert(!JsonWireBounded(std::string(13, '[') + std::string(13, ']')));
    assert(!JsonWireBounded(R"({"command":"stop\u0000"})"));
    assert(!JsonWireBounded(std::string_view("{}\0", 3)));
    assert(!JsonWireBounded("}"));
    assert(!JsonWireBounded("{\""));
    for (unsigned seed = 0; seed < 100000; ++seed) {
        auto field = std::to_string(seed);
        assert(ContentLengthMatches(field, seed));
        assert(!ContentLengthMatches(field, seed + 1));
        assert(!ContentLengthMatches(field + ",0", seed));
    }

    std::uint8_t jpeg[] = {0xff, 0xd8, 0x11, 0x22, 0xff, 0xd9};
    assert(CompleteJpeg(jpeg, sizeof(jpeg)));
    assert(!CompleteJpeg(nullptr, sizeof(jpeg)));
    assert(!CompleteJpeg(jpeg, 3));
    // Use fully backed spans on both sides of the framing limit.
    constexpr std::size_t kJpegLimit = 512 * 1024;
    std::vector<std::uint8_t> limit_jpeg(kJpegLimit + 1, 0);
    limit_jpeg[0] = 0xff;
    limit_jpeg[1] = 0xd8;
    limit_jpeg[kJpegLimit - 2] = 0xff;
    limit_jpeg[kJpegLimit - 1] = 0xd9;
    assert(CompleteJpeg(limit_jpeg.data(), kJpegLimit));
    limit_jpeg[kJpegLimit - 1] = 0xff;
    limit_jpeg[kJpegLimit] = 0xd9;
    assert(!CompleteJpeg(limit_jpeg.data(), kJpegLimit + 1));
    const std::uint8_t minimum_jpeg[] = {0xff, 0xd8, 0xff, 0xd9};
    for (std::size_t length = 0; length < sizeof(minimum_jpeg); ++length)
        assert(!CompleteJpeg(minimum_jpeg, length));
    assert(CompleteJpeg(minimum_jpeg, sizeof(minimum_jpeg)));
    jpeg[0] = 0x11;
    assert(!CompleteJpeg(jpeg, sizeof(jpeg)));
    jpeg[0] = 0xff;
    jpeg[5] = 0x00;
    assert(!CompleteJpeg(jpeg, sizeof(jpeg)));

    RealTouchEdges head;
    assert(head.Observe(10) == 0); // no boot identity, no edges
    assert(head.Observe(11) == 0);
    assert(!head.AcceptBoot(0));
    assert(head.AcceptBoot(101));
    assert(head.Observe(10) == 0); // first read is baseline
    assert(head.Observe(11) == 1);
    assert(head.Observe(11) == 0);
    assert(head.Observe(12) == 1);
    assert(head.Observe(0) == 0); // stale counter, not a reboot
    assert(head.Observe(1) == 0);
    assert(head.Observe(13) == 1);
    assert(head.Observe(99) == 0); // huge jump cannot forge touch
    head.Reset();
    assert(head.Observe(8) == 0); // stale data cannot reset watermark
    assert(head.AcceptBoot(101));
    assert(head.Observe(100) == 0); // reconnect rebaselines
    assert(head.Observe(101) == 1);
    assert(head.AcceptBoot(103));
    assert(head.Observe(8) == 0); // first sample of new boot
    assert(!head.AcceptBoot(101)); // old generation cannot replay
    assert(head.AcceptBoot(103));
    assert(head.Observe(9) == 1);
    RealTouchEdges cap;
    assert(cap.AcceptBoot(201));
    assert(cap.Observe(4294967295U) == 0);
    assert(cap.Observe(0) == 1); // real one-step counter rollover
    assert(cap.Observe(3) == 3);
    assert(cap.Observe(0x80000003U) == 0); // ambiguous half-range
    assert(cap.Observe(4) == 1);

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

    // A queued ARM/drive/keepalive must not become eligible after a
    // completed HALT merely because the urgent request count reaches zero.
    {
        UrgentStopGate::Request queued(gate, false);
        assert(!queued.preempted());
        {
            UrgentStopGate::Request halt(gate, true);
            assert(queued.preempted());
            assert(!halt.preempted());
            UrgentStopGate::Request during(gate, false);
            assert(during.preempted());
            {
                UrgentStopGate::Request stop(gate, true);
                assert(!stop.preempted());
            }
            assert(during.preempted());
        }
        assert(queued.preempted());
        assert(!gate.preempts(false));
        UrgentStopGate::Request fresh(gate, false);
        assert(!fresh.preempted());
    }
    // Requests survive ordinary telemetry scheduling but never a STOP epoch.
    for (unsigned i = 0; i < 1000; ++i) {
        UrgentStopGate::Request queued(gate, false);
        { UrgentStopGate::Request stop(gate, true); }
        assert(queued.preempted());
    }

    for (const auto verb : {"arm", "drive", "lift", "grip", "keepalive"}) {
        assert(ControlQueueFresh(verb, 100000, 100000));
        assert(ControlQueueFresh(verb, 100000, 299999));
        assert(!ControlQueueFresh(verb, 100000, 300000));
        assert(!ControlQueueFresh(verb, 100000, 450000));
        assert(!ControlQueueFresh(verb, 100000, 99999));
        assert(!ControlQueueFresh(verb, -1, std::numeric_limits<std::int64_t>::max()));
        assert(!ControlQueueFresh(verb, 0, std::numeric_limits<std::int64_t>::max()));
        const auto latest = std::numeric_limits<std::int64_t>::max();
        const auto earliest = std::numeric_limits<std::int64_t>::min();
        assert(ControlQueueFresh(verb, latest, latest));
        assert(ControlQueueFresh(verb, latest - 199999, latest));
        assert(!ControlQueueFresh(verb, latest - 200000, latest));
        assert(!ControlQueueFresh(verb, earliest, latest));
        assert(!ControlQueueFresh(verb, latest, earliest));
    }
    for (const auto verb : {"stop", "halt", "disarm", "status", "pose", "ir",
                            "optics", "aux", "ping"}) {
        assert(ControlQueueFresh(verb, 100000, 900000));
    }

    // ACK formatting must reject incomplete or surplus argument vectors even
    // when a caller constructs Command directly rather than using ParseCommand.
    assert(ExpectedAck(Command{"drive", {}, ""}).empty());
    assert(ExpectedAck(Command{"drive", {1}, ""}).empty());
    assert(ExpectedAck(Command{"drive", {1, 2, 3, 4}, ""}).empty());
    for (const auto verb : {"lift", "grip"}) {
        assert(ExpectedAck(Command{verb, {}, ""}).empty());
        assert(ExpectedAck(Command{verb, {60, 61}, ""}).empty());
        assert(ExpectedAck(Command{verb, {60}, ""}) ==
               std::string("OK ") + verb + " angle=60");
    }
    assert(ExpectedAck(Command{"drive", {100, -100}, ""}) ==
           "OK drive left=40 right=-40 ms=250");
    assert(ExpectedAck(Command{"drive", {1, 2, 3}, ""}) ==
           "OK drive left=1 right=2 ms=3");
    std::uint8_t bounded_jpeg[] = {0xff, 0xd8, 0x00, 0x11, 0xff, 0xd9};
    for (std::size_t length = 0; length < sizeof(bounded_jpeg); ++length)
        assert(!CompleteJpeg(bounded_jpeg, length));
    assert(CompleteJpeg(bounded_jpeg, sizeof(bounded_jpeg)));

    // An input view may refer to the output command's own storage.
    // Keep both short and heap-backed input alive until parsing finishes.
    {
        Command c;
        const std::string wire = std::string("drive ") + std::string(87, '0') + " 0";
        assert(ParseCommand(wire, true, c));
        assert(ParseCommand(c.wire, true, c));
        assert(c.wire == wire && c.args == std::vector<int>({0, 0}));
        assert(ParseCommand("stop", false, c));
        assert(ParseCommand(c.verb, false, c));
        assert(c.wire == "stop" && c.args.empty());
        c = {"stale", {1}, "drive 1 1 251"};
        assert(!ParseCommand(c.wire, true, c));
        assert(c.verb.empty() && c.args.empty() && c.wire.empty());
        c = {"stale", {1}, "arm"};
        assert(!ParseCommand(c.wire, false, c));
        assert(c.verb.empty() && c.args.empty() && c.wire.empty());
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
    assert(ParseCommand("pose", false, c));
    assert(c.verb == "pose");
    assert(!ParseCommand("pose 0", false, c));
    assert(!ParseCommand("pose raw", true, c));
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
        assert(c.verb.empty() && c.args.empty() && c.wire.empty());
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
    // A syntactically valid command at the byte limit distinguishes the
    // length guard from rejection of an unknown verb or invalid argument.
    const auto command_at_limit = std::string("drive ") + std::string(87, '0') + " 0";
    assert(command_at_limit.size() == 95);
    assert(ParseCommand(command_at_limit, true, c));
    assert(c.wire == command_at_limit && c.args == std::vector<int>({0, 0}));
    const auto command_over_limit = std::string("drive ") + std::string(88, '0') + " 0";
    assert(command_over_limit.size() == 96);
    assert(!ParseCommand(command_over_limit, true, c));
    assert(c.verb.empty() && c.args.empty() && c.wire.empty());
    // Mutation corpus for the real command parser. Exercise accepted near-misses
    // as well as invalid bytes; uniformly random data rarely reaches a verb.
    const std::string seeds[] = {"drive 100 -100 250", "drive -100 100",
        "drive 0 0 1", "lift 60", "grip 120", "arm", "disarm", "keepalive",
        "stop", "halt", "status", "aux", "ir", "optics", "pose", "ping",
        "rearm", "calcommit", "drive 2147483648 0", "drive -2147483649 0",
        "drive 0 0 0", "drive 0 0 251", "drive +1 0", "grip 59", "lift 121"};
    const auto check_mutation = [](const std::string& input) {
        for (bool op : {false, true}) {
            Command parsed{"poison", {999}, "stale"};
            if (!ParseCommand(input, op, parsed)) {
                assert(parsed.verb.empty() && parsed.args.empty() && parsed.wire.empty());
                continue;
            }
            assert(parsed.wire == input && input.size() <= 95);
            for (unsigned char ch : input) assert(ch >= 32 && ch <= 126);
            const auto& verb = parsed.verb;
            const auto& args = parsed.args;
            assert(verb != "rearm" && verb != "calcommit");
            if (!op) assert(verb != "arm" && verb != "disarm" && verb != "keepalive");
            // Compare the entire receipt, not just its verb prefix: a wrong
            // wheel, duration or angle is not the requested action.
            std::string expected = "OK " + verb;
            if (verb == "drive") {
                assert(args.size() == 2 || args.size() == 3);
                assert(args[0] >= -100 && args[0] <= 100);
                assert(args[1] >= -100 && args[1] <= 100);
                if (args.size() == 3) assert(args[2] >= 1 && args[2] <= 250);
                const auto bounded = [](int wheel) {
                    return wheel < -40 ? -40 : (wheel > 40 ? 40 : wheel);
                };
                expected += " left=" + std::to_string(bounded(args[0])) +
                            " right=" + std::to_string(bounded(args[1])) +
                            " ms=" + std::to_string(args.size() == 3 ? args[2] : 250);
            } else if (verb == "lift" || verb == "grip") {
                assert(args.size() == 1 && args[0] >= 60 && args[0] <= 120);
                expected += " angle=" + std::to_string(args[0]);
            } else {
                assert(args.empty());
                assert(verb == "arm" || verb == "disarm" || verb == "keepalive" ||
                       verb == "stop" || verb == "halt" || verb == "status" ||
                       verb == "aux" || verb == "ir" || verb == "optics" ||
                       verb == "pose" || verb == "ping");
            }
            assert(ExpectedAck(parsed) == expected);
        }
    };
    for (const auto& seed : seeds) {
        check_mutation(seed);
        for (std::size_t i = 0; i <= seed.size(); ++i) {
            for (int byte = 0; byte < 256; ++byte) {
                auto mutated = seed;
                mutated.insert(i, 1, static_cast<char>(byte));
                check_mutation(mutated);
                if (i < seed.size()) {
                    mutated = seed;
                    mutated[i] = static_cast<char>(byte);
                    check_mutation(mutated);
                }
            }
        }
    }
    for (int value = 0; value < 256; ++value) {
        if (value >= 32 && value <= 126) continue;
        assert(!ParseCommand(std::string("stop") + static_cast<char>(value), true, c));
    }
}
