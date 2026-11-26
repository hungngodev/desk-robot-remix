#pragma once

#include <cstdint>
#include <optional>

namespace desk_robot {
enum class FacePanelMode { kAwake, kDim, kOff };

// Display-only policy. Never infer that HSM sleep means microphone consent
// or that continuous listening can safely be treated as ordinary idle.
class FaceIdlePower {
public:
    static constexpr uint64_t kDimAfterMs = 60000;
    static constexpr uint64_t kRetryMs = 1000;

    template <typename Apply>
    void Update(uint64_t now, bool can_rest, bool sleeping, Apply apply) {
        if (!can_rest || (idle_since_ && now < *idle_since_)) idle_since_.reset();
        if (can_rest && !idle_since_) idle_since_ = now;
        const auto mode = idle_since_ && now - *idle_since_ >= kDimAfterMs
            ? (sleeping ? FacePanelMode::kOff : FacePanelMode::kDim)
            : FacePanelMode::kAwake;
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
