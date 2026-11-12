#pragma once

#include <algorithm>
#include <charconv>
#include <string>
#include <string_view>
#include <vector>

namespace desk_robot {
struct Command {
    std::string verb;
    std::vector<int> args;
    std::string wire;
};

inline bool Integer(std::string_view text, int& value) {
    if (text.empty() || text.front() == '+') return false;
    const auto [end, ec] = std::from_chars(text.data(), text.data() + text.size(), value);
    return ec == std::errc{} && end == text.data() + text.size();
}

inline bool ParseCommand(std::string_view line, bool operator_control, Command& result) {
    result = {};
    if (line.empty() || line.size() > 95 || line.front() == ' ' || line.back() == ' ') return false;
    for (unsigned char ch : line) if (ch < 32 || ch > 126) return false;
    std::vector<std::string_view> parts;
    for (size_t pos = 0; pos < line.size();) {
        size_t end = line.find(' ', pos);
        if (end == std::string_view::npos) end = line.size();
        if (end == pos) return false;
        parts.push_back(line.substr(pos, end - pos));
        pos = end + 1;
    }
    result.verb = std::string(parts[0]);
    for (size_t i = 1; i < parts.size(); ++i) {
        int n = 0;
        if (!Integer(parts[i], n)) return false;
        result.args.push_back(n);
    }
    const auto& v = result.verb;
    const auto& a = result.args;
    if (v == "drive") {
        if (a.size() != 2 && a.size() != 3) return false;
        if (a[0] < -100 || a[0] > 100 || a[1] < -100 || a[1] > 100) return false;
        if (a.size() == 3 && (a[2] < 1 || a[2] > 250)) return false;
    } else if (v == "lift" || v == "grip") {
        if (a.size() != 1 || a[0] < 60 || a[0] > 120) return false;
    } else if (v == "arm" || v == "disarm" || v == "keepalive") {
        if (!operator_control || !a.empty()) return false;
    } else if (v == "stop" || v == "status" || v == "aux" || v == "ir" || v == "ping") {
        if (!a.empty()) return false;
    } else return false;
    result.wire = std::string(line);
    return true;
}

inline std::string ExpectedAck(const Command& command) {
    const auto& a = command.args;
    std::string reply = "OK " + command.verb;
    if (command.verb == "drive") {
        reply += " left=" + std::to_string(std::clamp(a[0], -40, 40));
        reply += " right=" + std::to_string(std::clamp(a[1], -40, 40));
        reply += " ms=" + std::to_string(a.size() == 3 ? a[2] : 250);
    } else if (command.verb == "lift" || command.verb == "grip") {
        reply += " angle=" + std::to_string(a[0]);
    }
    return reply;
}

inline bool MatchingError(std::string_view reply, const Command& command) {
    const std::string prefix = "ERR " + command.verb + " ";
    return reply.starts_with(prefix) || reply == "ERR input line_too_long" ||
           reply == "ERR input invalid_ascii";
}
}  // namespace desk_robot
