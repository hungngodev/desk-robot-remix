#pragma once
#include <cstdint>

namespace desk_robot {
// MCP23017 BANK=0, DS20001952C tables 3-3 and 3-4. No motor authority.
// A verified configuration mismatch is sticky until explicit initialization.
class McpPortDirectionLock {
 public:
  void expect_haptic_output() { expected_b_ = 0xFB; }
  bool faulted() const { return faulted_; }

  template <typename Read, typename Write>
  bool verify(Read read, Write write, bool optional_configured) {
    if (!faulted_) {
      std::uint8_t a = 0, b = 0, pull_a = 0, pull_b = 0;
      if (!read(0x00, a) || !read(0x01, b) || !read(0x0C, pull_a) ||
          (optional_configured && !read(0x0D, pull_b))) return false;
      if (a == 0xFF && b == expected_b_ && pull_a == 0x0F &&
          (!optional_configured || pull_b == 0x01)) return true;
      faulted_ = true;
    }
    if (!reset_verified_) reset_verified_ = reset_outputs(read, write);
    return false;
  }

 private:
  template <typename Read, typename Write>
  static bool reset_outputs(Read read, Write write) {
    // Independently attempt both ports even when the first write fails.
    const bool wrote_a = write(0x00, 0xFF);
    const bool wrote_b = write(0x01, 0xFF);
    std::uint8_t a = 0, b = 0, latch = 0xFF;
    const bool safe_a = wrote_a && read(0x00, a) && a == 0xFF;
    const bool safe_b = wrote_b && read(0x01, b) && b == 0xFF;
    // Never change the latch of an unverified output configuration.
    const bool low = safe_b && write(0x15, 0x00) &&
                     read(0x15, latch) && latch == 0x00;
    return safe_a && safe_b && low;
  }

  std::uint8_t expected_b_ = 0xFF;
  bool faulted_ = false;
  bool reset_verified_ = false;
};
} // namespace desk_robot
