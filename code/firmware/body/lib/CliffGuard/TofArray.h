#pragma once

#include <Arduino.h>
#include <VL53L0X.h>
#include <Wire.h>

#include "CliffGuard.h"

namespace desk_robot {

// The WROOM owns all local safety ranging. Pololu VL53L0X driver is reused;
// the adapter only selects the existing TCA9548A channel and checks freshness.
// Channels 0..3 are floor corners, channel 4 is the forward obstacle.
// This variant requires a physically qualified standoff (normally 40-60 mm
// candidate). The smaller VL6180X is not wire compatible with this driver.
class TofArray {
 public:
  bool begin(TwoWire& bus, int reset_pin, CliffGuard& guard);
  // Nonblocking readiness probe, then one bounded range read per invocation.
  // Each call may observe only the selected mux port, never two at address 0x29.
  void poll(std::uint32_t now_ms);
  bool ready() const { return ready_; }
  std::uint8_t active_channel() const { return next_channel_; }

 private:
  static constexpr std::uint8_t kMuxAddress = 0x70;
  static constexpr std::uint8_t kRangerAddress = 0x29;
  static constexpr std::uint8_t kChannels = kCliffSensorCount;
  TwoWire* bus_ = nullptr;
  CliffGuard* guard_ = nullptr;
  VL53L0X sensors_[kChannels];
  bool ready_ = false;
  std::uint8_t next_channel_ = 0;
  std::uint32_t last_read_ms_[kChannels]{};
  bool sample_seen_[kChannels]{};

  bool select(std::uint8_t channel);
  void failure();
};

}  // namespace desk_robot
