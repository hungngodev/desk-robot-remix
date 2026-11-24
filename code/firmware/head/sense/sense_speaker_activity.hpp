#pragma once

#include <cstdint>
#include <limits>

// I2S acceptance is not acoustic playback. A write that returns after STOP
// cannot qualify a newer AEC capture, nor can a write accepted after the
// final microphone sample backfill activity in an already completed window.
namespace desk_robot {
class SenseSpeakerActivity {
public:
    struct Snapshot {
        uint64_t generation = 0;
        uint64_t frames = 0;
    };

    uint64_t generation() const noexcept { return generation_; }

    void Reset() noexcept {
        ++generation_;
        frames_ = 0;
        window_active_ = false;
        first_window_accept_us_ = 0;
        last_window_accept_us_ = 0;
        window_minimum_us_ = 0;
    }

    void RecordAccepted(uint64_t started_generation, int accepted,
                        int64_t recorded_us) noexcept {
        if (accepted <= 0 || started_generation != generation_) return;
        const auto amount = static_cast<uint64_t>(accepted);
        const auto limit = std::numeric_limits<uint64_t>::max();
        frames_ = amount > limit - frames_ ? limit : frames_ + amount;
        // Keep the first qualifying acceptance for the end-time fence.
        // The latest is needed only until the first retained MIC callback
        // establishes the actual recording start rather than START time.
        if (window_active_ && recorded_us > 0 &&
            recorded_us >= window_minimum_us_) {
            last_window_accept_us_ = recorded_us;
            if (first_window_accept_us_ == 0)
                first_window_accept_us_ = recorded_us;
        }
    }

    Snapshot SnapshotNow() const noexcept { return {generation_, frames_}; }

    Snapshot BeginWindow() noexcept {
        window_start_ = SnapshotNow();
        window_active_ = true;
        first_window_accept_us_ = 0;
        last_window_accept_us_ = 0;
        window_minimum_us_ = 0;
        return window_start_;
    }

    // A microphone callback can overlap authorization and be discarded.
    // At the first retained callback, remove earlier digital accepts. The
    // latest accept is sufficient here: later callbacks have not yet
    // completed the four-second recording, and subsequent accepts retain
    // the first qualifying time for the existing endpoint fence.
    void FenceWindowStart(Snapshot start, int64_t first_sample_us) noexcept {
        if (!window_active_ || generation_ != start.generation ||
            window_start_.generation != start.generation ||
            window_start_.frames != start.frames ||
            first_sample_us <= 0 || window_minimum_us_ != 0) return;
        window_minimum_us_ = first_sample_us;
        if (first_window_accept_us_ < first_sample_us) {
            first_window_accept_us_ = last_window_accept_us_ >= first_sample_us
                ? last_window_accept_us_ : 0;
        }
    }

    bool AdvancedSince(Snapshot start, int64_t capture_end_us) const noexcept {
        return window_active_ && generation_ == start.generation &&
               window_start_.generation == start.generation &&
               window_start_.frames == start.frames &&
               frames_ > start.frames && first_window_accept_us_ > 0 &&
               first_window_accept_us_ <= capture_end_us;
    }

private:
    uint64_t generation_ = 0;
    uint64_t frames_ = 0;
    Snapshot window_start_{};
    int64_t first_window_accept_us_ = 0;
    int64_t last_window_accept_us_ = 0;
    int64_t window_minimum_us_ = 0;
    bool window_active_ = false;
};
}  // namespace desk_robot
