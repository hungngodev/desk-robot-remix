#pragma once

#include <cstdint>
#include "stackchan_behavior.hpp"

// Small original, nonactuating OLED expression policy. Xiaozhi owns the status
// and transcript; Stackchan owns optional idle gaze. Pixels render only under
// the existing LVGL lock, never via the body motor or camera API.
namespace desk_robot {
struct EyeFrame {
    bool visible = false;
    bool closed = false;
    int8_t x = 0;
    int8_t y = 0;
};

class FaceEyeAnimator {
public:
    // The same pet identity seed used by Stackchan also offsets idle blink
    // phases so several freshly booted pets do not share one fixed cadence.
    // This never changes the bounded 4.3 to 6.6 second blink interval.
    void Seed(uint32_t seed) noexcept { seed_ = seed; }

    EyeFrame Step(uint32_t now_ms, stackchan::behavior::Motion motion, bool allowed) {
        using stackchan::behavior::Motion;
        if (!allowed) {
            // A transient voice/reconnect or fault gate cancels the current
            // gesture, but must not restart the idle blink clock indefinitely.
            // The next allowed frame may start a new blink, never replay one.
            gaze_ = Motion::kNone;
            blink_active_ = false;
            return {};
        }
        if (!started_) {
            started_ = true;
            blink_at_ms_ = now_ms;
            next_blink_ms_ = 4300U + ((seed_ + 300U) % 2300U);
            blink_active_ = false;
        }
        switch (motion) {
            case Motion::kLookUp:
            case Motion::kLookDown:
            case Motion::kLookLeft:
            case Motion::kLookRight:
            case Motion::kNod:
            case Motion::kShake:
                gaze_ = motion;
                gaze_at_ms_ = now_ms;
                break;
            case Motion::kLookFront:
                gaze_ = Motion::kNone;
                break;
            default:
                break;
        }
        const uint32_t gaze_age = now_ms - gaze_at_ms_;
        if (gaze_ != Motion::kNone && gaze_age >= 1100U)
            gaze_ = Motion::kNone;
        const uint32_t blink_age = now_ms - blink_at_ms_;
        if (blink_age >= next_blink_ms_) {
            blink_at_ms_ = now_ms;
            next_blink_ms_ = 4300U + ((seed_ + blink_cycle_ * 733U) % 2300U);
            ++blink_cycle_;
            blink_active_ = true;
        }
        const uint32_t blink_phase = now_ms - blink_at_ms_;
        if (blink_active_ && blink_phase >= 350U) blink_active_ = false;
        const bool blinking = blink_active_;
        if (gaze_ == Motion::kNone && !blinking) return {};
        EyeFrame frame;
        frame.visible = true;
        frame.closed = blinking && blink_phase >= 100U && blink_phase < 250U;
        switch (gaze_) {
            case Motion::kLookLeft: frame.x = -3; break;
            case Motion::kLookRight: frame.x = 3; break;
            case Motion::kLookUp: frame.y = -3; break;
            case Motion::kLookDown: frame.y = 3; break;
            case Motion::kNod:
                frame.y = gaze_age <= 350U ? 3 : EaseAxis(3, -2, gaze_age - 350U, 200U);
                break;
            case Motion::kShake:
                frame.x = gaze_age <= 350U ? -3 : EaseAxis(-3, 3, gaze_age - 350U, 200U);
                break;
            default: break;
        }
        // Keep the initial quick saccade, then settle back to center within
        // the existing 1.1 s gesture window. Never delay a priority cancel.
        if (gaze_age >= 800U && gaze_ != Motion::kNone) {
            frame.x = EaseAxis(frame.x, 0, gaze_age - 800U, 300U);
            frame.y = EaseAxis(frame.y, 0, gaze_age - 800U, 300U);
        }
        return frame;
    }

private:
    // Integer smoothstep (3t^2 - 2t^3), rounded to the nearest pixel.
    // Only the 200/300 ms phases call this helper; clamp before multiplying.
    static int8_t EaseAxis(int8_t from, int8_t to, uint32_t elapsed,
                           uint32_t duration) noexcept {
        if (elapsed >= duration) return to;
        constexpr uint32_t scale = 256U;
        const uint32_t t = elapsed * scale / duration;
        const uint32_t weight = (t * t * (3U * scale - 2U * t) + 32768U) / 65536U;
        const int delta = static_cast<int>(to) - from;
        const uint32_t distance = static_cast<uint32_t>(delta < 0 ? -delta : delta);
        const int step = static_cast<int>((distance * weight + scale / 2U) / scale);
        return static_cast<int8_t>(from + (delta < 0 ? -step : step));
    }

    uint32_t seed_ = 0;
    bool started_ = false;
    bool blink_active_ = false;
    uint32_t blink_at_ms_ = 0;
    uint32_t gaze_at_ms_ = 0;
    uint32_t next_blink_ms_ = 4600;
    uint32_t blink_cycle_ = 0;
    stackchan::behavior::Motion gaze_ = stackchan::behavior::Motion::kNone;
};
}  // namespace desk_robot
