#pragma once

#include <cstdint>
#include <limits>

// I2S acceptance is not acoustic playback. A write that returns after STOP
// cannot qualify a newer AEC capture as having current speaker activity.
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
    }

    void RecordAccepted(uint64_t started_generation, int accepted) noexcept {
        if (accepted <= 0 || started_generation != generation_) return;
        const auto amount = static_cast<uint64_t>(accepted);
        const auto limit = std::numeric_limits<uint64_t>::max();
        frames_ = amount > limit - frames_ ? limit : frames_ + amount;
    }

    Snapshot SnapshotNow() const noexcept { return {generation_, frames_}; }

    bool AdvancedSince(Snapshot start) const noexcept {
        return generation_ == start.generation && frames_ > start.frames;
    }

private:
    uint64_t generation_ = 0;
    uint64_t frames_ = 0;
};
}  // namespace desk_robot
