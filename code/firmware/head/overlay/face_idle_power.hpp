#pragma once

#include <cstdint>
#include <optional>

namespace desk_robot {
enum class FacePanelMode { kAwake, kSoftDim, kDim, kOff };

// Display-only policy. Never infer that HSM sleep means microphone consent
// or that continuous listening can safely be treated as ordinary idle.
class FaceIdlePower {
public:
    static constexpr uint64_t kDimAfterMs = 60000;
    static constexpr uint64_t kRetryMs = 1000;
    static constexpr uint64_t kFadeStepMs = 1000;

    template <typename Apply>
    void Update(uint64_t now, bool can_rest, bool sleeping, Apply apply) {
        if (!can_rest || (idle_since_ && now < *idle_since_)) idle_since_.reset();
        if (can_rest && !idle_since_) idle_since_ = now;
        auto mode = FacePanelMode::kAwake;
        if (idle_since_ && now - *idle_since_ >= kDimAfterMs) {
            // Advance only after a successfully displayed step has had time
            // to be seen. A stalled loop must not jump straight to darkness.
            mode = attempted_.value_or(FacePanelMode::kAwake);
            const bool settled = applied_ && now >= attempted_at_ &&
                now - attempted_at_ >= kFadeStepMs;
            if (mode == FacePanelMode::kAwake) mode = FacePanelMode::kSoftDim;
            else if (mode == FacePanelMode::kSoftDim && settled) mode = FacePanelMode::kDim;
            else if (mode == FacePanelMode::kDim && sleeping && settled) mode = FacePanelMode::kOff;
            else if (mode == FacePanelMode::kOff && !sleeping) mode = FacePanelMode::kDim;
        }
        if (applied_ && *applied_ == mode) return;
        if (attempted_ && *attempted_ == mode && now >= attempted_at_ &&
            now - attempted_at_ < kRetryMs) return;
        attempted_ = mode;
        attempted_at_ = now;
        // A failed multi-command write can leave the panel partially changed.
        // Invalidate even the previous successful mode and retry at a bounded rate.
        applied_.reset();
        if (apply(mode)) applied_ = mode;
    }

private:
    std::optional<uint64_t> idle_since_;
    std::optional<FacePanelMode> applied_;
    std::optional<FacePanelMode> attempted_;
    uint64_t attempted_at_ = 0;
};
}  // namespace desk_robot
