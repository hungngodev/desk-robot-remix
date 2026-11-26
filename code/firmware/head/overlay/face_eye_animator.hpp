#pragma once

#include <cstdint>
#include "stackchan_behavior.hpp"
#include "face_eye_geometry.hpp"

// Small original, nonactuating OLED expression policy. Xiaozhi owns the status
// and transcript; Stackchan owns optional idle gaze. Pixels render only under
// the existing LVGL lock, never via the body motor or camera API.
namespace desk_robot {
struct EyeFrame {
    bool visible = false;
    bool closed = false;
    int8_t x = 0;
    int8_t y = 0;
    uint8_t lid_height = face_eye_geometry::kOpenHeight;
    uint8_t mouth_height = 0;
};

// Preserve an active gaze and blink while the independent mood aperture eases.
// A zero height leaves the stock glyph/gesture decision unchanged.
inline EyeFrame BlendMoodAperture(EyeFrame frame, uint8_t height) noexcept {
    if (height != 0) {
        frame.visible = true;
        frame.lid_height = height;
    }
    return frame;
}

namespace face_eye_detail {
// Integer smoothstep (3t^2 - 2t^3), rounded to the nearest pixel.
// A zero duration completes immediately; widen before scaling elapsed time.
inline int8_t EaseAxis(int8_t from, int8_t to, uint32_t elapsed,
                       uint32_t duration) noexcept {
    if (elapsed >= duration) return to;
    constexpr uint32_t scale = 256U;
    const uint32_t t = static_cast<uint32_t>(
        static_cast<uint64_t>(elapsed) * scale / duration);
    const uint32_t weight = (t * t * (3U * scale - 2U * t) + 32768U) / 65536U;
    const int delta = static_cast<int>(to) - from;
    const uint32_t distance = static_cast<uint32_t>(delta < 0 ? -delta : delta);
    const int step = static_cast<int>((distance * weight + scale / 2U) / scale);
    return static_cast<int8_t>(from + (delta < 0 ? -step : step));
}
}  // namespace face_eye_detail

class FaceEyeAnimator {
public:
    // Independent per-pet xorshift stream, as used by the existing HSM.
    // Zero must not be allowed to lock the generator into a constant cadence.
    void Seed(uint32_t seed) noexcept { rng_ = seed ? seed : 1U; }

    EyeFrame Step(uint32_t now_ms, stackchan::behavior::Motion motion, bool allowed,
                  bool priority_or_rest = false) {
        using stackchan::behavior::Motion;
        using face_eye_detail::EaseAxis;
        using namespace face_eye_geometry;
        if (priority_or_rest) started_ = false;
        if (!allowed || priority_or_rest) {
            // Transient voice/reconnect gates cancel a gesture without starving
            // the timer. Safety and sleep instead require a fresh wake interval.
            gaze_ = Motion::kNone;
            retarget_ = false;
            blink_active_ = false;
            return {};
        }
        if (!started_) {
            started_ = true;
            blink_at_ms_ = now_ms;
            next_blink_ms_ = NextBlinkDelay();
            blink_active_ = false;
        }
        if (gaze_ != Motion::kNone && now_ms - gaze_at_ms_ >= 1100U)
            gaze_ = Motion::kNone;
        UpdateGaze(now_ms, motion);
        const uint32_t gaze_age = now_ms - gaze_at_ms_;
        const uint32_t blink_phase = AdvanceBlink(now_ms);
        const bool blinking = blink_active_;
        if (gaze_ == Motion::kNone && !blinking) return {};
        EyeFrame frame;
        frame.visible = true;
        frame.closed = blinking && ((blink_phase >= 100U && blink_phase < 250U) ||
            (double_blink_ && blink_phase >= 600U && blink_phase < 750U));
        switch (gaze_) {
            case Motion::kLookLeft: frame.x = -kGazeExtent; break;
            case Motion::kLookRight: frame.x = kGazeExtent; break;
            case Motion::kLookUp: frame.y = -kGazeExtent; break;
            case Motion::kLookDown: frame.y = kGazeExtent; break;
            case Motion::kNod:
                frame.y = gaze_age <= 350U ? kGazeExtent :
                    EaseAxis(kGazeExtent, kNodReturn, gaze_age - 350U, 200U);
                break;
            case Motion::kShake:
                frame.x = gaze_age <= 350U ? -kGazeExtent :
                    EaseAxis(-kGazeExtent, kGazeExtent, gaze_age - 350U, 200U);
                break;
            default: break;
        }
        // Keep the initial quick saccade, then settle back to center within
        // the existing 1.1 s gesture window. Never delay a priority cancel.
        if (gaze_age >= 800U && gaze_ != Motion::kNone) {
            frame.x = EaseAxis(frame.x, 0, gaze_age - 800U, 300U);
            frame.y = EaseAxis(frame.y, 0, gaze_age - 800U, 300U);
        }
        if (retarget_ && gaze_ != Motion::kNone && gaze_age < kRetargetMs) {
            frame.x = EaseAxis(from_x_, frame.x, gaze_age, kRetargetMs);
            frame.y = EaseAxis(from_y_, frame.y, gaze_age, kRetargetMs);
        }
        last_x_ = frame.x;
        last_y_ = frame.y;
        return frame;
    }

private:
    static constexpr uint32_t kRetargetMs = 200U;

    void UpdateGaze(uint32_t now_ms, stackchan::behavior::Motion motion) {
        using stackchan::behavior::Motion;
        switch (motion) {
            case Motion::kLookUp:
            case Motion::kLookDown:
            case Motion::kLookLeft:
            case Motion::kLookRight:
            case Motion::kNod:
            case Motion::kShake:
                // Blend from the last displayed gaze when a new gesture
                // interrupts an existing one. Repeated commands must not
                // keep restarting the same in-progress transition.
                if (motion == gaze_ && retarget_ &&
                    now_ms - gaze_at_ms_ < kRetargetMs) break;
                retarget_ = gaze_ != Motion::kNone;
                from_x_ = last_x_;
                from_y_ = last_y_;
                gaze_ = motion;
                gaze_at_ms_ = now_ms;
                break;
            case Motion::kLookFront:
                gaze_ = Motion::kNone;
                retarget_ = false;
                break;
            default:
                break;
        }
    }

    uint32_t AdvanceBlink(uint32_t now_ms) {
        const uint32_t blink_age = now_ms - blink_at_ms_;
        if (blink_age >= next_blink_ms_) {
            blink_at_ms_ = now_ms;
            next_blink_ms_ = NextBlinkDelay();
            double_blink_ = (Random() % 8U == 0U);
            blink_active_ = true;
        }
        const uint32_t blink_phase = now_ms - blink_at_ms_;
        if (blink_active_ && blink_phase >= (double_blink_ ? 850U : 350U))
            blink_active_ = false;
        return blink_phase;
    }

    uint32_t Random() noexcept {
        rng_ ^= rng_ << 13;
        rng_ ^= rng_ >> 17;
        rng_ ^= rng_ << 5;
        return rng_;
    }
    uint32_t NextBlinkDelay() noexcept { return 3000U + Random() % 3001U; }

    uint32_t rng_ = 1;
    bool started_ = false;
    bool blink_active_ = false;
    bool double_blink_ = false;
    bool retarget_ = false;
    int8_t from_x_ = 0;
    int8_t from_y_ = 0;
    int8_t last_x_ = 0;
    int8_t last_y_ = 0;
    uint32_t blink_at_ms_ = 0;
    uint32_t gaze_at_ms_ = 0;
    uint32_t next_blink_ms_ = 0;
    stackchan::behavior::Motion gaze_ = stackchan::behavior::Motion::kNone;
};
}  // namespace desk_robot
