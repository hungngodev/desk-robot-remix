#pragma once

#include <algorithm>
#include <cstdint>

namespace desk_robot {
// Cosmetic digital I2S acceptance only, not a playback acknowledgement.
struct SpeechLevel {
    constexpr SpeechLevel(uint16_t mean = 0, bool is_fresh = false) noexcept
        : mean_abs(mean), fresh(is_fresh) {}

    uint16_t mean_abs;
    bool fresh;
};

// All methods are called under the codec's existing reference mutex.
class SpeechLevelWindow {
public:
    void Publish(uint64_t sum, int samples, int64_t now_us) noexcept {
        if (samples <= 0 || now_us < 0) return;
        level_ = static_cast<uint16_t>(std::min<uint64_t>(32768, sum / static_cast<uint64_t>(samples)));
        at_us_ = now_us;
    }

    SpeechLevel Read(int64_t now_us) const noexcept {
        if (at_us_ < 0 || now_us < at_us_ || now_us - at_us_ > 200000) return {};
        return {level_, true};
    }

    void Reset() noexcept { at_us_ = -1; level_ = 0; }

private:
    int64_t at_us_ = -1;
    uint16_t level_ = 0;
};

// The OLED task samples at 100 ms. A closed mouth is one pixel; zero hides
// it immediately on priority/voice exit. Limit each visible step to two pixels.
class FaceMouthAnimator {
public:
    static constexpr int kMaxHeight = 7;

    uint8_t Step(SpeechLevel level, bool allowed) noexcept {
        if (!allowed || !level.fresh) {
            height_ = 1;
            return allowed ? 1 : 0;
        }
        constexpr int floor = 256;
        constexpr int full = 8192;
        const int amplitude = std::min(full, std::max(floor, static_cast<int>(level.mean_abs)));
        const int target = 1 + (amplitude - floor) * (kMaxHeight - 1) / (full - floor);
        height_ += std::min(2, std::max(-2, target - height_));
        return static_cast<uint8_t>(height_);
    }

private:
    int height_ = 1;
};
}  // namespace desk_robot
