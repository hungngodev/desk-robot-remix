#pragma once

#include <cstdint>
#include <string_view>

namespace desk_robot {
// A short cosmetic aperture bridge between the existing discrete OLED glyphs.
// Zero means no overlay: the stock Xiaozhi expression remains authoritative.
class FaceMoodMorph {
public:
    static constexpr uint32_t kDurationMs = 300;

    uint8_t Step(uint32_t now, std::string_view mood, bool allowed) noexcept {
        const uint8_t next = Aperture(mood);
        if (!allowed || next == 0) {
            known_ = false;
            active_ = false;
            return 0;
        }
        if (!known_) {
            known_ = true;
            target_ = next;
            return 0;
        }
        if (next != target_) {
            from_ = active_ ? Sample(now) : target_;
            target_ = next;
            started_ = now;
            active_ = from_ != target_;
        }
        if (!active_) return 0;
        if (now - started_ >= kDurationMs) {
            active_ = false;
            return 0;
        }
        return Sample(now);
    }

private:
    static uint8_t Aperture(std::string_view mood) noexcept {
        if (mood == "happy") return 8;
        if (mood == "surprised") return 14;
        if (mood == "sleepy") return 2;
        if (mood == "neutral") return 10;
        if (mood == "thinking") return 9;
        if (mood == "sad") return 6;
        if (mood == "angry") return 5;
        return 0;
    }

    uint8_t Sample(uint32_t now) const noexcept {
        const uint32_t age = now - started_;
        if (age >= kDurationMs) return target_;
        // Integer smoothstep, bounded to 300 ms before multiplication.
        const uint32_t t = age * 256U / kDurationMs;
        const uint32_t w = (t * t * (768U - 2U * t) + 32768U) / 65536U;
        return static_cast<uint8_t>((from_ * (256U - w) + target_ * w + 128U) / 256U);
    }

    bool known_ = false;
    bool active_ = false;
    uint8_t from_ = 0;
    uint8_t target_ = 0;
    uint32_t started_ = 0;
};
}  // namespace desk_robot
