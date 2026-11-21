#pragma once

#include <cstdint>

namespace desk_robot {

// Preserve first-priority floor/forward sampling cadence while adding optional
// left/right/rear ToF channels. No I2C, GPIO or motion authority in this class.
class RangeScanOrder {
 public:
  explicit RangeScanOrder(bool full_eight) : full_eight_(full_eight) {}

  std::uint8_t next() {
    if (critical_index_ < 5) return critical_index_++;
    critical_index_ = 0;
    if (!full_eight_) return critical_index_++;
    const std::uint8_t channel = static_cast<std::uint8_t>(5 + extra_index_);
    extra_index_ = static_cast<std::uint8_t>((extra_index_ + 1) % 3);
    return channel;
  }

  void reset() {
    critical_index_ = 0;
    extra_index_ = 0;
  }

 private:
  const bool full_eight_;
  std::uint8_t critical_index_ = 0;
  std::uint8_t extra_index_ = 0;
};

}  // namespace desk_robot
