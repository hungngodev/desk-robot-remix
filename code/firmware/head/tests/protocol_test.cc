#include <cassert>
#include <string>
#include "robot_protocol.h"
using namespace desk_robot;
int main() {
    Command c;
    assert(ParseCommand("drive 100 -100 250", false, c));
    assert(ExpectedAck(c) == "OK drive left=40 right=-40 ms=250");
    assert(ExpectedAck(c) != "OK drive left=40 right=-40 ms=150");
    assert(ParseCommand("drive 0 0", false, c));
    assert(ExpectedAck(c) == "OK drive left=0 right=0 ms=250");
    assert(ParseCommand("aux", false, c));
    assert(c.verb == "aux");
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
