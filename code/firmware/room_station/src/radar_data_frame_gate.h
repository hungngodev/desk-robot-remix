#pragma once

#include <stdint.h>

namespace desk_robot_room {

// Observe the same LD2410C UART bytes handed to the pinned ld2410 v0.2.2
// decoder, but count only complete validated *data* frames. Its read() return
// value also means "received any byte", so cannot timestamp a measurement.
// Keep the basic target fields from that same complete packet. They are
// radar observations only, never identity or motion authority.
struct RadarTargetSample {
  bool presence = false;
  bool stationary = false;
  bool moving = false;
  uint16_t stationary_cm = 0;
  uint16_t moving_cm = 0;
};

class RadarDataFrameGate {
 public:
  bool consume(uint8_t byte) {
    static constexpr uint8_t kHeader[4] = {0xF4, 0xF3, 0xF2, 0xF1};
    static constexpr uint8_t kFooter[4] = {0xF8, 0xF7, 0xF6, 0xF5};
    if (position_ < 4) {
      if (byte == kHeader[position_]) {
        frame_[position_++] = byte;
      } else {
        // Reuse an overlapping first byte rather than losing the next frame.
        position_ = byte == kHeader[0] ? 1 : 0;
        if (position_ != 0) frame_[0] = byte;
      }
      return false;
    }

    frame_[position_++] = byte;
    if (position_ < 6) return false;
    if (position_ == 6) {
      const uint16_t payload_len = static_cast<uint16_t>(frame_[4]) |
          (static_cast<uint16_t>(frame_[5]) << 8);
      // Basic target payload is 13 bytes; longer engineering data fits 64.
      if (payload_len < 13 || payload_len > sizeof(frame_) - 10) {
        reset();
      } else {
        expected_ = payload_len + 10;
      }
      return false;
    }
    if (position_ < expected_) return false;

    const uint16_t payload_len = expected_ - 10;
    const bool valid = (frame_[6] == 0x01 || frame_[6] == 0x02) &&
        frame_[7] == 0xAA &&
        frame_[payload_len + 4] == 0x55 &&
        frame_[payload_len + 5] == 0x00 &&
        frame_[expected_ - 4] == kFooter[0] &&
        frame_[expected_ - 3] == kFooter[1] &&
        frame_[expected_ - 2] == kFooter[2] &&
        frame_[expected_ - 1] == kFooter[3];
    if (valid) {
      // LD2410 basic target data occupies the same offsets in basic and
      // engineering packets. Distances are little-endian centimeters.
      const uint8_t target = frame_[8];
      completed_.presence = target != 0;
      completed_.moving_cm = static_cast<uint16_t>(frame_[9]) |
          (static_cast<uint16_t>(frame_[10]) << 8);
      completed_.stationary_cm = static_cast<uint16_t>(frame_[12]) |
          (static_cast<uint16_t>(frame_[13]) << 8);
      completed_.moving = (target & 0x01) != 0 &&
          completed_.moving_cm > 0 && frame_[11] > 0;
      completed_.stationary = (target & 0x02) != 0 &&
          completed_.stationary_cm > 0 && frame_[14] > 0;
    }
    reset();
    return valid;
  }

  const RadarTargetSample& completed_sample() const { return completed_; }

 private:
  RadarTargetSample completed_;
  void reset() {
    position_ = 0;
    expected_ = 0;
  }
  uint8_t frame_[64] = {};
  uint8_t position_ = 0;
  uint16_t expected_ = 0;
};

}  // namespace desk_robot_room
