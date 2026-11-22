#pragma once

#include <stdint.h>

namespace desk_robot_room {

// Only a complete validated LD2410 data packet may update acquisition time.
// The pinned driver's read() boolean also means "any UART byte was read".
// Keep a timestamp across invalid bytes and over uint32 millis rollover.
class RadarSampleClock {
 public:
  void observe(bool data_frame_complete, bool connected, uint32_t now_ms) {
    if (data_frame_complete && connected) {
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
