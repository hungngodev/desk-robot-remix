// Bounded causal USB connection epoch challenge, not authentication.
// Pure C++11 for Feather firmware and sanitizer host verification.
// No motor/charging control, dynamic allocation or sensor cache mutation.
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace desk_robot_room {
class UsbEpochSync {
 public:
  bool consume(uint8_t byte) {
    if (byte == '\n') {
      const bool complete = !overflow_ && used_ == 21
          && memcmp(request_, "SYNC ", 5) == 0
          && valid_lower_hex(request_ + 5);
      if (complete) {
        memcpy(token_, request_ + 5, 16);
        token_[16] = '\0';
      }
      used_ = 0;
      overflow_ = false;
      return complete;
    }
    if (overflow_) return false;
    if (used_ == sizeof(request_)) {
      overflow_ = true;
      return false;
    }
    request_[used_++] = static_cast<char>(byte);
    return false;
  }

  const char* token() const { return token_; }

 private:
  static bool valid_lower_hex(const char* candidate) {
    for (size_t i = 0; i < 16; ++i) {
      const char c = candidate[i];
      if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) {
        return false;
      }
    }
    return true;
  }
  char request_[21] = {};
  char token_[17] = {};
  uint8_t used_ = 0;
  bool overflow_ = false;
};
}  // namespace desk_robot_room
