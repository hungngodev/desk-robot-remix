#pragma once

#include <stdint.h>
#include <string.h>

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
  // Retire partial packets even when the UART is silent. Use the existing
  // radar freshness budget; a late suffix must not renew an old observation.
  void expire_partial(uint32_t now_ms, uint32_t max_age_ms) {
    if (position_ != 0 && now_ms - partial_started_ms_ > max_age_ms)
      position_ = 0;
  }

  bool consume_at(uint8_t byte, uint32_t now_ms, uint32_t max_age_ms) {
    expire_partial(now_ms, max_age_ms);
    if (position_ == 0) partial_started_ms_ = now_ms;
    return consume(byte);
  }

  bool consume(uint8_t byte) {
    static constexpr uint8_t kHeader[4] = {0xF4, 0xF3, 0xF2, 0xF1};
    // Retain candidate bytes until validated; on rejection slide by one
    // instead of discarding a possibly intact successor packet.
    frame_[position_++] = byte;
    bool accepted = false;
    while (position_ != 0) {
      const uint8_t prefix = position_ < 4 ? position_ : 4;
      if (memcmp(frame_, kHeader, prefix) != 0) {
        discard(1);
        continue;
      }
      if (position_ < 6) break;
      const uint16_t payload_len = read_le16(frame_ + 4);
      if ((payload_len != 13 && payload_len < 33) ||
          payload_len > sizeof(frame_) - 10 ||
          (position_ >= 7 && frame_[6] != (payload_len == 13 ? 0x02 : 0x01)) ||
          (position_ >= 8 && frame_[7] != 0xAA) ||
          (position_ >= 9 && frame_[8] > 0x03)) {
        discard(1);
        continue;
      }
      const uint16_t expected_ = payload_len + 10;
      if (position_ < expected_) break;
      const bool valid = valid_frame(frame_, expected_);
      // A truncated engineering report can borrow the tail of an intact
      // successor. If both interpretations share the footer, neither is
      // trustworthy. Discard both and wait for an unambiguous report.
      const bool unambiguous = valid && !has_competing_suffix(expected_);
      if (unambiguous) {
        // LD2410 basic target data occupies the same offsets in basic and
        // engineering packets. Distances are little-endian centimeters.
        const uint8_t target = frame_[8];
        completed_.presence = target != 0;
        completed_.moving_cm = read_le16(frame_ + 9);
        completed_.stationary_cm = read_le16(frame_ + 12);
        completed_.moving = (target & 0x01) != 0 &&
            completed_.moving_cm > 0 && frame_[11] > 0;
        completed_.stationary = (target & 0x02) != 0 &&
            completed_.stationary_cm > 0 && frame_[14] > 0;
      }
      if (unambiguous) accepted = true;
      // Keep a possible successor header after a malformed candidate.
      discard(valid ? expected_ : 1);
    }
    return accepted;
  }

  const RadarTargetSample& completed_sample() const { return completed_; }

 private:
  static uint16_t read_le16(const uint8_t* bytes) {
    return static_cast<uint16_t>(static_cast<unsigned>(bytes[0]) |
                                 (static_cast<unsigned>(bytes[1]) << 8));
  }

  static bool valid_frame(const uint8_t* bytes, uint16_t size) {
    static constexpr uint8_t kHeader[] = {0xF4, 0xF3, 0xF2, 0xF1};
    static constexpr uint8_t kFooter[] = {0xF8, 0xF7, 0xF6, 0xF5};
    if (size < 23 || memcmp(bytes, kHeader, sizeof(kHeader)) != 0) return false;
    const uint16_t payload = read_le16(bytes + 4);
    // Match the pinned decoder's basic and engineering layouts. Reject
    // reserved target states and validate both tail markers and footer.
    return payload == size - 10 &&
        ((bytes[6] == 0x02 && payload == 13) ||
         (bytes[6] == 0x01 && payload >= 33)) &&
        bytes[7] == 0xAA && bytes[8] <= 0x03 &&
        bytes[size - 6] == 0x55 && bytes[size - 5] == 0x00 &&
        memcmp(bytes + size - 4, kFooter, sizeof(kFooter)) == 0;
  }

  bool has_competing_suffix(uint16_t size) const {
    // Every candidate fits the same 64-byte buffer. A basic report is the
    // shortest possible competing frame (23 bytes).
    for (uint16_t start = 1; start + 23 <= size; ++start) {
      if (valid_frame(frame_ + start, size - start)) return true;
    }
    return false;
  }

  RadarTargetSample completed_;
  void discard(uint16_t count) {
    // Callers discard only a received prefix or a complete validated frame.
    position_ = static_cast<uint8_t>(position_ - count);
    memmove(frame_, frame_ + count, position_);
  }
  uint8_t frame_[64] = {};
  uint8_t position_ = 0;
  uint32_t partial_started_ms_ = 0;
};

}  // namespace desk_robot_room
