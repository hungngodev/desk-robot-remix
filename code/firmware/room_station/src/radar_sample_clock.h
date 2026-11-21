#pragma once

#include <stdint.h>

namespace desk_robot_room {

// The pinned ld2410 library exposes only a 100 ms isConnected() freshness
// window, not its private valid-packet timestamp. Record the latest local UART
// activity that still coincides with that validated connection window. This is
// a conservative transport observation timestamp, never person identity.
class RadarSampleClock {
 public:
  void observe(bool uart_activity, bool connected, uint32_t now_ms) {
    if (uart_activity && connected) {
      sample_ms_ = now_ms;
      has_sample_ = true;
    }
  }

  bool has_sample() const { return has_sample_; }
  uint32_t sample_ms() const { return sample_ms_; }

 private:
  bool has_sample_ = false;
  uint32_t sample_ms_ = 0;
};

}  // namespace desk_robot_room
