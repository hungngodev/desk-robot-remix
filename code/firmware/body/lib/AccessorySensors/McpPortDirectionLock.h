#pragma once
#include <cstdint>

namespace desk_robot {
// MCP23017 BANK=0, DS20001952C tables 3-3 and 3-4. No motor authority.
// A verified configuration mismatch is sticky until explicit initialization.
class McpPortDirectionLock {
 public:
  void expect_haptic_output() {
    if (expected_b_ != 0xFB) {
      expected_b_ = 0xFB;
      verified_ = false; // proof of the old direction is no longer current
    }
  }
  bool faulted() const { return faulted_; }
  bool verified() const { return verified_; }

  template <typename Read, typename Write>
  bool verify(Read read, Write write, bool optional_configured) {
    verified_ = false;
    if (!faulted_) {
      const auto result = check_registers(read, optional_configured);
      if (result == Check::Unavailable) return false;
      if (result == Check::Verified) {
        verified_ = true;
        return true;
      }
      faulted_ = true;
    }
    // A verified reset is not a permanent electrical guarantee. Recheck
    // both directions and the inactive latch on every faulted poll.
    if (reset_verified_) {
      std::uint8_t a = 0, b = 0, latch = 0xFF;
      reset_verified_ = read(0x00, a) && a == 0xFF &&
                        read(0x01, b) && b == 0xFF &&
                        read(0x15, latch) && latch == 0;
    }
    if (!reset_verified_) reset_verified_ = reset_outputs(read, write);
    return false;
  }

 private:
  enum class Check { Verified, Unavailable, Mismatch };

  template <typename Read>
  Check check_registers(Read read, bool optional_configured) const {
    const std::uint8_t registers[] = {0x00, 0x01, 0x0C, 0x0D};
    const std::uint8_t expected[] = {0xFF, expected_b_, 0x0F, 0x01};
    const unsigned count = optional_configured ? 4U : 3U;
    for (unsigned i = 0; i < count; ++i) {
      std::uint8_t actual = 0;
      if (!read(registers[i], actual)) return Check::Unavailable;
      // Do not let a later read failure hide an already observed mismatch.
      if (actual != expected[i]) return Check::Mismatch;
    }
    return Check::Verified;
  }

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
  bool verified_ = false;
  bool faulted_ = false;
  bool reset_verified_ = false;
};
} // namespace desk_robot
