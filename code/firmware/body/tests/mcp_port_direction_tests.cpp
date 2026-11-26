#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include "McpPortDirectionLock.h"

#define CHECK(x) do { if (!(x)) throw std::runtime_error(#x); } while (false)

struct Registers {
  std::array<std::uint8_t, 0x16> values{};
  int fail_read = -1, fail_write = -1, ignore_write = -1;
  unsigned writes = 0, latch_writes = 0;
  Registers() {
    values[0x00] = values[0x01] = 0xFF;
    values[0x0C] = 0x0F;
    values[0x0D] = 0x01;
  }
  bool verify(desk_robot::McpPortDirectionLock& lock, bool optional = true) {
    return lock.verify([this](std::uint8_t reg, std::uint8_t& value) {
      if (reg == fail_read) return false;
      value = values.at(reg);
      return true;
    }, [this](std::uint8_t reg, std::uint8_t value) {
      ++writes;
      if (reg == 0x15) ++latch_writes;
      if (reg == fail_write) return false;
      if (reg != ignore_write) values.at(reg) = value;
      return true;
    }, optional);
  }
};

static void check_every_direction_bit() {
  for (const bool haptic : {false, true}) {
    for (unsigned port = 0; port < 2; ++port) {
      for (unsigned bit = 0; bit < 8; ++bit) {
        Registers regs;
        desk_robot::McpPortDirectionLock lock;
        if (haptic) {
          lock.expect_haptic_output();
          regs.values[1] = 0xFB;
        }
        CHECK(regs.verify(lock) && lock.verified());
        CHECK(regs.writes == 0);
        regs.values[port] ^= static_cast<std::uint8_t>(1U << bit);
        regs.values[0x15] = 0x04;
        CHECK(!regs.verify(lock) && lock.faulted() && !lock.verified());
        CHECK(regs.values[0] == 0xFF && regs.values[1] == 0xFF);
        CHECK(regs.values[0x15] == 0 && regs.latch_writes == 1);
        const auto writes = regs.writes;
        CHECK(!regs.verify(lock));
        CHECK(regs.writes == writes); // verified reset cannot rearm
      }
    }
  }
}

static void check_reset_and_transport_faults() {
  for (const unsigned reg : {0x0CU, 0x0DU}) {
    Registers regs;
    desk_robot::McpPortDirectionLock lock;
    regs.values[reg] = 0;
    CHECK(!regs.verify(lock) && lock.faulted());
  }
  Registers missing_optional;
  desk_robot::McpPortDirectionLock dock_only;
  missing_optional.fail_read = 0x0D;
  CHECK(missing_optional.verify(dock_only, false));
  CHECK(!missing_optional.verify(dock_only) && !dock_only.faulted());
  CHECK(!dock_only.verified());
  missing_optional.fail_read = -1;
  CHECK(missing_optional.verify(dock_only));

  // A known unsafe GPA direction cannot be downgraded to a transient
  // read failure just because the next register is unavailable.
  Registers mixed;
  desk_robot::McpPortDirectionLock mixed_lock;
  CHECK(mixed.verify(mixed_lock) && mixed_lock.verified());
  mixed.values[0] = 0xFE;
  mixed.fail_read = 1;
  CHECK(!mixed.verify(mixed_lock) && mixed_lock.faulted());
  CHECK(!mixed_lock.verified() && mixed.latch_writes == 0);
  mixed.fail_read = -1;
  CHECK(!mixed.verify(mixed_lock) && !mixed_lock.verified());
  CHECK(mixed.values[0] == 0xFF && mixed.values[1] == 0xFF);
  CHECK(mixed.latch_writes == 1);

  Registers regs;
  desk_robot::McpPortDirectionLock lock;
  lock.expect_haptic_output();
  regs.values[1] = 0xF9; // unexpected GPB1 output, GPB2 still output
  regs.values[0x15] = 0x04;
  regs.ignore_write = 1;
  CHECK(!regs.verify(lock) && lock.faulted());
  CHECK(regs.latch_writes == 0 && regs.values[0x15] == 0x04);
  regs.ignore_write = -1;
  regs.fail_write = 0;
  CHECK(!regs.verify(lock));
  CHECK(regs.values[1] == 0xFF && regs.values[0x15] == 0);
  regs.fail_write = -1;
  CHECK(!regs.verify(lock));
  const auto writes = regs.writes;
  CHECK(!regs.verify(lock) && regs.writes == writes);
}

int main() {
  try {
    check_every_direction_bit();
    check_reset_and_transport_faults();
    std::cout << "PASS MCP23017 direction lock and verified reset\n";
  } catch (const std::exception& error) {
    std::cerr << "FAIL " << error.what() << '\n';
    return 1;
  }
}
