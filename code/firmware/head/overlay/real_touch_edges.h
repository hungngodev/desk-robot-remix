#pragma once
#include <array>
#include <cstddef>
#include <cstdint>

namespace desk_robot {
// Share the same bounded, reboot-safe edge interpretation across both sensor
// families. This is only an expression event; never a motion or force permit.
class RealTouchEdges {
public:
    // Reset only the sample baseline. Keep the counter watermark and retired
    // boot identities across UART failures so stale replies cannot replay touches.
    void Reset() { baselined_ = false; }

    bool AcceptBoot(std::uint32_t boot_id) {
        boot_accepted_ = false;
        // WROOM initializes its epoch as esp_random() | 1U. Zero is an
        // uninitialized or malformed report, never a new observed boot.
        // Invalidate the edge baseline but preserve the retired epoch fence.
        if (boot_id == 0U) {
            Reset();
            return false;
        }
        if (!boot_seen_) {
            boot_seen_ = true;
            active_boot_ = boot_id;
            Reset();
            return boot_accepted_ = true;
        }
        if (boot_id == active_boot_) return boot_accepted_ = true;
        for (std::size_t i = 0; i < retired_count_; ++i)
            if (retired_boot_ids_[i] == boot_id) return false;
        // Bounded UART transport has no legitimate multi-boot replay source.
        // Retain eight retired generations without dynamic memory.
        retired_boot_ids_[retired_next_] = active_boot_;
        retired_next_ = (retired_next_ + 1) % retired_boot_ids_.size();
        if (retired_count_ < retired_boot_ids_.size()) ++retired_count_;
        active_boot_ = boot_id;
        Reset();  // first post-reboot count may already be nonzero
        counter_seen_ = false;
        return boot_accepted_ = true;
    }

    int Observe(std::uint32_t counter, std::uint32_t cap = 3) {
        if (!boot_accepted_) return 0;
        if (!counter_seen_) {
            last_ = counter;
            counter_seen_ = true;
            baselined_ = true;
            return 0;
        }
        // Serial arithmetic accepts a small real rollover but rejects stale
        // replies and the ambiguous half-range without moving the watermark.
        const std::uint32_t delta = counter - last_;
        if (delta >= 0x80000000U) return 0;
        last_ = counter;
        if (!baselined_) {
            baselined_ = true;
            return 0;
        }
        return delta > 0 && delta <= cap ? static_cast<int>(delta) : 0;
    }

private:
    bool baselined_ = false;
    bool counter_seen_ = false;
    std::uint32_t last_ = 0;
    bool boot_seen_ = false;
    bool boot_accepted_ = false;
    std::uint32_t active_boot_ = 0;
    std::array<std::uint32_t, 8> retired_boot_ids_{};
    std::size_t retired_count_ = 0;
    std::size_t retired_next_ = 0;
};
} // namespace desk_robot
