#pragma once

#include <algorithm>
#include <atomic>
#include <charconv>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace desk_robot {
// Capability detection is diagnostic only; unknown versions never supply pose.
inline bool UnsupportedPoseWireVersion(double version) {
    return std::isfinite(version) && std::floor(version) == version &&
           version >= 0 && version <= 4294967295.0 && version != 1;
}

inline bool ContentLengthMatches(std::string_view field, std::size_t parsed) {
    if (field.empty()) return false;
    for (char c : field) if (c < '0' || c > '9') return false;
    std::size_t declared = 0;
    const auto [end, ec] = std::from_chars(field.data(), field.data() + field.size(), declared);
    return ec == std::errc{} && end == field.data() + field.size() && declared == parsed;
}

inline bool JsonWireBounded(std::string_view value) {
    // Bound parser recursion before allocating any cJSON nodes. Quoted braces
    // are data, not nesting; the parser still validates complete JSON syntax.
    unsigned depth = 0;
    bool quoted = false;
    bool escaped = false;
    for (char c : value) {
        if (c == '\0') return false;
        if (quoted) {
            if (escaped) escaped = false;
            else if (c == '\\') escaped = true;
            else if (c == '"') quoted = false;
        } else if (c == '"') quoted = true;
        else if (c == '{' || c == '[') {
            if (++depth > 12) return false;
        } else if (c == '}' || c == ']') {
            if (depth == 0) return false;
            --depth;
        }
    }
    return !quoted && depth == 0 && value.find("\\u0000") == std::string_view::npos;
}

// cJSON accepts duplicate names, while consumers may choose first or last.
// Check decoded object keys at every depth before using any field.
template <typename Node, typename IsObject>
bool JsonKeysUnique(const Node* node, IsObject is_object, unsigned depth = 0) {
    if (!node || depth > 12) return false;
    const bool object = is_object(node);
    for (const auto* item = node->child; item; item = item->next) {
        if (object) {
            if (!item->string) return false;
            for (const auto* other = item->next; other; other = other->next) {
                if (!other->string || std::string_view(item->string) == other->string)
                    return false;
            }
        }
        if (!JsonKeysUnique(item, is_object, depth + 1)) return false;
    }
    return true;
}

// Validate bytes BEFORE publishing a source identity or JPEG success receipt.
// These are the same bounded native JPEG framing requirements on both routes.
inline bool CompleteJpeg(const std::uint8_t* data, std::size_t size) {
    return data != nullptr && size >= 4 && size <= 512 * 1024 &&
           data[0] == 0xff && data[1] == 0xd8 &&
           data[size - 2] == 0xff && data[size - 1] == 0xd9;
}

// A pending urgent STOP/HALT preempts nonurgent UART traffic. This head
// scheduling cue never replaces the WROOM's independent motor safety latch.
class UrgentStopGate {
public:
    class Request {
    public:
        Request(UrgentStopGate& gate, bool urgent)
            : gate_(gate), urgent_(urgent),
              generation_(gate.generation_.load(std::memory_order_acquire)),
              blocked_at_entry_(gate.preempts(urgent)) {
            if (urgent_) {
                gate_.pending_.fetch_add(1, std::memory_order_acq_rel);
                gate_.generation_.fetch_add(1, std::memory_order_acq_rel);
            }
        }
        Request(const Request&) = delete;
        Request& operator=(const Request&) = delete;
        ~Request() {
            if (urgent_) gate_.pending_.fetch_sub(1, std::memory_order_acq_rel);
        }
        // A request queued before STOP/HALT stays canceled even after the
        // urgent transaction releases the UART and its pending count drops.
        bool preempted() const {
            return !urgent_ && (blocked_at_entry_ || gate_.preempts(false) ||
                generation_ != gate_.generation_.load(std::memory_order_acquire));
        }
    private:
        UrgentStopGate& gate_;
        bool urgent_;
        std::uint32_t generation_;
        bool blocked_at_entry_;
    };

    bool preempts(bool urgent) const {
        return !urgent && pending_.load(std::memory_order_acquire) != 0;
    }
private:
    std::atomic<unsigned> pending_{0};
    std::atomic<std::uint32_t> generation_{0};
};

// The WROOM status "none" is healthy only with an active AND ready local
// motion guard. A bench or legacy profile reporting "not_required" is not a
// safety-qualified robot and must not release the head's neutral fault face.
// This informs OLED state only; WROOM remains the sole motor safety owner.
inline bool BodySafetyUnhealthy(bool required, bool ready,
                                std::string_view fault) {
    return !required || !ready || fault != "none";
}

// Read-only OLED classification of the WROOM's latched dock contact stop.
// This is NOT proof of current seating, electrical charging or a motor permit.
// Other faults and any unready/missing safety profile retain the generic STOP.
inline bool BodyDockLockoutObserved(bool required, bool ready, bool armed,
                                    std::string_view fault) {
    return required && !ready && !armed &&
           fault == "dock_power_connected";
}

// A pure cosmetic one-shot, not a sensor HSM, speech or motor authority.
// This mailbox carries the Mac's already validated decision to the local
// OLED owner and expires if the face task stalls or Xiaozhi owns the screen.
enum class CosmeticMood : std::uint8_t {
    kNone = 0, kNeutral, kHappy, kThinking, kSurprised,
};

inline CosmeticMood ParseCosmeticMood(std::string_view event) {
    if (event == "mood:neutral") return CosmeticMood::kNeutral;
    if (event == "mood:happy") return CosmeticMood::kHappy;
    if (event == "mood:thinking") return CosmeticMood::kThinking;
    if (event == "mood:surprised") return CosmeticMood::kSurprised;
    return CosmeticMood::kNone;
}

class CosmeticMoodCue {
public:
    void offer(CosmeticMood mood, std::uint32_t now_ms) {
        if (mood < CosmeticMood::kNeutral || mood > CosmeticMood::kSurprised) return;
        // Four moods fit in three bits. Store the remaining 29 bits as
        // eight-millisecond ticks, so the modulus EXACTLY matches the full
        // uint32_t millisecond clock wrap. The old 100 ms division did not:
        // it discarded a fresh cue when uptime crossed 49.7 days.
        constexpr std::uint32_t kShift = 3U;
        const std::uint32_t tick = now_ms >> kShift;
        pending_.store((tick << kShift) | static_cast<std::uint32_t>(mood),
                       std::memory_order_release);
    }
    CosmeticMood take(std::uint32_t now_ms) {
        const std::uint32_t receipt = pending_.exchange(
            0U, std::memory_order_acq_rel);
        if (receipt == 0U) return CosmeticMood::kNone;
        constexpr std::uint32_t kShift = 3U;
        constexpr std::uint32_t kTickMask = (1U << 29U) - 1U;
        const auto age_ticks = ((now_ms >> kShift) -
            (receipt >> kShift)) & kTickMask;
        if (age_ticks > 125U) return CosmeticMood::kNone;  // ~1 s TTL
        switch (receipt & ((1U << kShift) - 1U)) {
            case 1: return CosmeticMood::kNeutral;
            case 2: return CosmeticMood::kHappy;
            case 3: return CosmeticMood::kThinking;
            case 4: return CosmeticMood::kSurprised;
            default: return CosmeticMood::kNone;
        }
    }
private:
    std::atomic<std::uint32_t> pending_{0U};
};

// A person detection is not permission for indefinite future OLED
// animation. Keep one bounded, rollover safe, latest-only visual cue.
class TimedPersonCue {
public:
    void offer(std::uint32_t now_ms) {
        // One event bit and 31 two-millisecond ticks preserve the full
        // uint32_t uptime wrap without needing another clock or task.
        pending_.store((now_ms & ~1U) | 1U, std::memory_order_release);
    }
    bool take(std::uint32_t now_ms) {
        const auto receipt = pending_.exchange(
            0U, std::memory_order_acq_rel);
        if ((receipt & 1U) == 0U) return false;
        const auto age_ticks = ((now_ms >> 1U) -
            (receipt >> 1U)) & 0x7fffffffU;
        return age_ticks <= 500U;
    }
private:
    std::atomic<std::uint32_t> pending_{0U};
};

// Only commands that may renew body control authority have a queue deadline.
// STOP/HALT must always remain admissible; telemetry never renews the lease.
inline bool ControlQueueFresh(std::string_view verb, std::int64_t admitted_us,
                              std::int64_t now_us) {
    if (verb != "arm" && verb != "drive" && verb != "lift" &&
        verb != "grip" && verb != "keepalive") return true;
    // Match the WROOM's stricter active wheel host-silence window, rather
    // than the longer UART read timeout or 500 ms idle watchdog.
    constexpr std::int64_t kMaxQueueUs = 200000;
    return admitted_us >= 0 && now_us >= admitted_us &&
           now_us - admitted_us < kMaxQueueUs;
}

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
    // Delay clearing output until input is no longer needed: line may alias
    // result.wire or result.verb. Every rejected parse still clears stale state.
    const auto reject = [&result]() { result = {}; return false; };
    if (line.empty() || line.size() > 95 || line.front() == ' ' || line.back() == ' ') return reject();
    for (const char raw : line) {
        const auto ch = static_cast<unsigned char>(raw);
        if (ch < 32U || ch > 126U) return reject();
    }
    std::vector<std::string_view> parts;
    for (size_t pos = 0; pos < line.size();) {
        size_t end = line.find(' ', pos);
        if (end == std::string_view::npos) end = line.size();
        if (end == pos) return reject();
        parts.push_back(line.substr(pos, end - pos));
        pos = end + 1;
    }
    Command parsed;
    parsed.verb = std::string(parts[0]);
    for (size_t i = 1; i < parts.size(); ++i) {
        int n = 0;
        if (!Integer(parts[i], n)) return reject();
        parsed.args.push_back(n);
    }
    const auto& v = parsed.verb;
    const auto& a = parsed.args;
    if (v == "drive") {
        if (a.size() != 2 && a.size() != 3) return reject();
        if (a[0] < -100 || a[0] > 100 || a[1] < -100 || a[1] > 100) return reject();
        if (a.size() == 3 && (a[2] < 1 || a[2] > 250)) return reject();
    } else if (v == "lift" || v == "grip") {
        if (a.size() != 1 || a[0] < 60 || a[0] > 120) return reject();
    } else if (v == "arm" || v == "disarm" || v == "keepalive") {
        if (!operator_control || !a.empty()) return reject();
    } else if (v == "stop" || v == "halt" || v == "status" || v == "aux" || v == "ir" || v == "optics" || v == "pose" || v == "ping") {
        if (!a.empty()) return reject();
    } else return reject();
    parsed.wire = std::string(line);
    result = std::move(parsed);
    return true;
}

inline std::string ExpectedAck(const Command& command) {
    const auto& a = command.args;
    std::string reply = "OK " + command.verb;
    if (command.verb == "drive") {
        if (a.size() != 2 && a.size() != 3) return {};
        reply += " left=" + std::to_string(std::clamp(a[0], -40, 40));
        reply += " right=" + std::to_string(std::clamp(a[1], -40, 40));
        reply += " ms=" + std::to_string(a.size() == 3 ? a[2] : 250);
    } else if (command.verb == "lift" || command.verb == "grip") {
        if (a.size() != 1) return {};
        reply += " angle=" + std::to_string(a[0]);
    }
    return reply;
}

inline bool MatchingError(std::string_view reply, const Command& command) {
    const std::string prefix = "ERR " + command.verb + " ";
    return reply.substr(0, prefix.size()) == prefix || reply == "ERR input line_too_long" ||
           reply == "ERR input invalid_ascii" || reply == "ERR input bad_checksum" ||
           reply == "ERR input unframed";
}

inline std::uint8_t UartCrc8(std::string_view data) {
    std::uint8_t crc = 0x00U;
    for (const char raw : data) {
        crc ^= static_cast<unsigned char>(raw);
        for (int bit = 0; bit < 8; ++bit) {
            const unsigned shifted = static_cast<unsigned>(crc) << 1U;
            crc = (crc & 0x80U) != 0U
                ? static_cast<std::uint8_t>(shifted ^ 0x07U)
                : static_cast<std::uint8_t>(shifted);
        }
    }
    return crc;
}

inline std::string FormatIntegrityFrame(std::uint32_t tx_id, std::string_view payload) {
    if (tx_id == 0U || payload.empty()) return {};
    static constexpr char kHex[] = "0123456789ABCDEF";
    std::string out = "@" + std::to_string(tx_id) + ":";
    out.append(payload);
    const std::uint8_t crc = UartCrc8(out);
    out.push_back('*');
    out.push_back(kHex[(crc >> 4) & 0x0FU]);
    out.push_back(kHex[crc & 0x0FU]);
    return out;
}

inline bool ParseIntegrityFrame(std::string_view line, std::uint32_t& tx_id,
                                std::string_view& payload) {
    tx_id = 0U;
    payload = {};
    if (line.size() < 7U || line.front() != '@') return false;
    const auto colon = line.find(':', 1);
    if (colon == std::string_view::npos || colon <= 1U) return false;
    const auto id_view = line.substr(1, colon - 1U);
    if (id_view.front() < '1' || id_view.front() > '9') return false;
    std::uint32_t parsed_id = 0U;
    const auto [end, ec] = std::from_chars(
        id_view.data(), id_view.data() + id_view.size(), parsed_id);
    if (ec != std::errc{} || end != id_view.data() + id_view.size() || parsed_id == 0U)
        return false;
    const auto star = line.size() - 3U;
    if (star <= colon + 1U || line[star] != '*') return false;
    const auto hex_val = [](char c) -> int {
        if (c >= '0' && c <= '9') return c - '0';
        if (c >= 'A' && c <= 'F') return 10 + (c - 'A');
        if (c >= 'a' && c <= 'f') return 10 + (c - 'a');
        return -1;
    };
    const int hi = hex_val(line[star + 1U]);
    const int lo = hex_val(line[star + 2U]);
    if (hi < 0 || lo < 0) return false;
    const std::uint8_t expected = UartCrc8(line.substr(0, star));
    if (static_cast<std::uint8_t>((hi << 4) | lo) != expected) return false;
    tx_id = parsed_id;
    payload = line.substr(colon + 1U, star - (colon + 1U));
    return !payload.empty();
}
}  // namespace desk_robot
