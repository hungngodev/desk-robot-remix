#pragma once
#include <cstddef>
#include <cstdint>

namespace desk_robot {
// Portable and bounded decoder for one complete 38 kHz demodulated NEC burst.
// Timing/reference: Espressif esp-idf v4.4 RMT IR protocols and Vishay TSOP382.
// Input is MARK LOW, SPACE HIGH (TSOP active low), in microseconds.
// A repeat-only NEC frame, a truncated frame, or a non-inverted checksum
// is NOT a fresh sighting. The result NEVER authorizes a motor or charger.
struct IrMarkSpace {
  std::uint16_t mark_us;
  std::uint16_t space_us;
  IrMarkSpace(std::uint16_t mark = 0, std::uint16_t space = 0)
      : mark_us(mark), space_us(space) {}
};
inline bool ir_between(std::uint16_t v, unsigned lo, unsigned hi) {
  return v >= lo && v <= hi;
}
inline bool decode_nec(const IrMarkSpace* items, std::size_t count,
                       std::uint32_t& code) {
  code = 0;
  // Real NEC contains a final 560us mark after 32 data bits.
  // Espressif's reference decoder receives 34 RMT symbols, not 33.
  if (!items || count != 34 ||
      !ir_between(items[0].mark_us, 7200, 10800) ||
      !ir_between(items[0].space_us, 3600, 5400) ||
      !ir_between(items[33].mark_us, 350, 850) ||
      items[33].space_us != 0) return false;
  std::uint32_t bits = 0;
  for (unsigned i = 0; i < 32; ++i) {
    const IrMarkSpace p = items[i + 1];
    if (!ir_between(p.mark_us, 350, 850)) return false;
    const bool zero = ir_between(p.space_us, 350, 850);
    const bool one = ir_between(p.space_us, 1300, 2100);
    if (zero == one) return false;
    if (one) bits |= (std::uint32_t(1) << i);
  }
  const std::uint8_t address = static_cast<std::uint8_t>(bits);
  const std::uint8_t address_inverse = static_cast<std::uint8_t>(bits >> 8);
  const std::uint8_t command = static_cast<std::uint8_t>(bits >> 16);
  const std::uint8_t command_inverse = static_cast<std::uint8_t>(bits >> 24);
  // Strict classic NEC. Extended NEC and arbitrary remotes are rejected
  // until an actual, verified dock beacon protocol has been selected.
  if (static_cast<std::uint8_t>(address ^ address_inverse) != 0xff ||
      static_cast<std::uint8_t>(command ^ command_inverse) != 0xff)
    return false;
  code = bits;
  return true;
}

struct IrSideEvidence {
  std::uint32_t code = 0;
  std::uint32_t seq = 0;       // accepted complete frames, not HTTP queries
  std::uint32_t at_ms = 0;     // WROOM receive/poll time, NOT exposure time
  bool valid = false;
};
struct IrPairEvidence {
  bool left_fresh = false, right_fresh = false, same_code = false;
  std::uint32_t left_seq = 0, right_seq = 0;
  std::uint32_t left_age_ms = 0, right_age_ms = 0;
  std::uint32_t code = 0;
  bool motor_authorized = false;
  bool charging_authorized = false;
};

// IDF 4.4 RMT ringbuffers have no source-time timestamp. An observation
// may be marked fresh only if the previous poll drained the queue completely,
// this poll was on time, and this poll did not encounter an excessive backlog.
// Discard an entire ambiguous batch, then require a later independent burst.
class IrFrameQueueGate {
 public:
  void reset() {
    started_ = false;
    last_ms_ = 0;
    draining_[0] = draining_[1] = false;
  }
  bool on_poll(std::uint32_t now_ms) {
    // Unsigned subtraction handles the normal millis 32-bit wraparound.
    const std::uint32_t elapsed = now_ms - last_ms_;
    // A second poll in the same millisecond cannot establish a new
    // independently completed NEC burst; reject untimestamped backlog.
    const bool timely = started_ && elapsed != 0U && elapsed <= 100U;
    started_ = true;
    last_ms_ = now_ms;
    return timely;
  }
  bool draining(unsigned side) const {
    return side < 2 && draining_[side];
  }
  bool finish(unsigned side, unsigned packets, bool queue_emptied,
              bool decoded_packet = true) {
    if (side > 1) return false;
    // Multiple queued frames have no individual receive timestamps. Even two
    // valid NEC packets may be old or from competing beacons; require exactly
    // one packet for a directional observation, or an empty drained queue.
    const bool acceptable = !draining_[side] && queue_emptied && packets <= 1 &&
                            (packets == 0 || decoded_packet);
    // An exhausted packet budget is never silently considered an empty queue.
    draining_[side] = !queue_emptied;
    return acceptable;
  }
 private:
  bool started_ = false;
  std::uint32_t last_ms_ = 0;
  bool draining_[2] = {false, false};
};

class DualIrEvidence {
 public:
  // Drop all previously accepted sightings after a receive backlog or poll stall.
  // Keep acquisition watermarks as well as sequence counters: quarantine
  // must not allow old frames to be replayed as fresh sightings.
  void invalidate() {
    for (auto& side : sides_) {
      side.code = 0;
      side.valid = false;
    }
  }
  // Called only after an actual valid independent RMT frame for that side.
  void accept(unsigned side, std::uint32_t code, std::uint32_t now_ms) {
    // An impossible receiver index is a corrupt observation, not a reason
    // to keep a previously valid paired docking bearing alive.
    if (side > 1) {
      invalidate();
      return;
    }
    if (static_cast<std::uint8_t>(code ^ (code >> 8)) != 0xff ||
        static_cast<std::uint8_t>((code >> 16) ^ (code >> 24)) != 0xff) {
      // A corrupt observation from either receiver revokes the old pair.
      // Keeping an older valid side would allow stale bearing reuse.
      invalidate();
      return;
    }
    IrSideEvidence& s = sides_[side];
    // Reject duplicate or regressed receive times even if a future caller
    // bypasses the queue gate. Unsigned half-range ordering permits wrap.
    const std::uint32_t elapsed = now_ms - s.at_ms;
    if (s.seq != 0U && (elapsed == 0U || elapsed >= 0x80000000U)) {
      invalidate();
      return;
    }
    s.code = code;
    s.at_ms = now_ms;
    s.valid = true;
    ++s.seq;
    if (s.seq == 0) ++s.seq;
  }
  IrPairEvidence assess(std::uint32_t now_ms) const {
    IrPairEvidence out{};
    const auto& left = sides_[0];
    const auto& right = sides_[1];
    out.left_seq = left.seq;
    out.right_seq = right.seq;
    out.left_age_ms = left.valid ? now_ms - left.at_ms : 0xffffffffU;
    out.right_age_ms = right.valid ? now_ms - right.at_ms : 0xffffffffU;
    out.left_fresh = left.valid && out.left_age_ms <= 200U;
    out.right_fresh = right.valid && out.right_age_ms <= 200U;
    // A 200 ms time window does not itself prove a bearing. Different
    // receivers must actually observe the SAME checksum-valid beacon.
    // Ages are both relative to the SAME clock, so this difference is
    // correct even when the 32-bit millis counter rolls over.
    const std::uint32_t separation =
        out.left_age_ms >= out.right_age_ms
            ? out.left_age_ms - out.right_age_ms
            : out.right_age_ms - out.left_age_ms;
    out.same_code = out.left_fresh && out.right_fresh &&
                    separation <= 120U && left.code == right.code;
    if (out.same_code) out.code = left.code;
    return out;
  }
 private:
  IrSideEvidence sides_[2]{};
};
} // namespace desk_robot
