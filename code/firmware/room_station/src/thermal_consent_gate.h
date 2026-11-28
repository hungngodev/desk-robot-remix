// Bounded runtime opt-in gate for optional room AMG8833 thermal scanning.
// Pure C++11 for Feather firmware and sanitizer host verification.
// Acquisition defaults OFF even in ROOM_AMG_FITTED=1 builds and revokes
// any active scan immediately upon consent withdrawal.
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace desk_robot_room {
class ThermalConsentGate {
 public:
  bool allowed() const { return allowed_; }

  bool take_revoked() {
    const bool was_revoked = revoked_;
    revoked_ = false;
    return was_revoked;
  }

  void set_allowed(bool grant) {
    if (!grant && allowed_) revoked_ = true;
    allowed_ = grant;
  }

  bool consume(uint8_t byte) {
    if (byte == '\r') return false;
    if (byte == '\n') {
      const bool enable = !overflow_ && used_ == 14 &&
          memcmp(line_, "AMG_CONSENT ON", 14) == 0;
      const bool disable = !overflow_ && used_ == 15 &&
          memcmp(line_, "AMG_CONSENT OFF", 15) == 0;
      used_ = 0;
      overflow_ = false;
      if (enable) {
        set_allowed(true);
        return true;
      }
      if (disable) {
        set_allowed(false);
        return true;
      }
      return false;
    }
    if (overflow_) return false;
    if (used_ == sizeof(line_)) {
      overflow_ = true;
      return false;
    }
    line_[used_++] = static_cast<char>(byte);
    return false;
  }

 private:
  bool allowed_ = false;
  bool revoked_ = false;
  char line_[16] = {};
  uint8_t used_ = 0;
  bool overflow_ = false;
};
}  // namespace desk_robot_room
