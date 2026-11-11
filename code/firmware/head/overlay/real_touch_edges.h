#pragma once
#include <cstdint>

namespace desk_robot {
// Share the same bounded, reboot-safe edge interpretation across both sensor
// families. This is only an expression event; never a motion or force permit.
class RealTouchEdges {
public:
    void Reset() { baselined_ = false; last_ = 0; }

    int Observe(std::uint32_t counter, std::uint32_t cap = 3) {
        if (!baselined_ || counter < last_) {
            last_ = counter;
            baselined_ = true;
            return 0;
        }
        const std::uint32_t delta = counter - last_;
        last_ = counter;
        return delta > 0 && delta <= cap ? static_cast<int>(delta) : 0;
    }

private:
    bool baselined_ = false;
    std::uint32_t last_ = 0;
};
} // namespace desk_robot
