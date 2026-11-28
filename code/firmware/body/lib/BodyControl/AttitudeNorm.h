#pragma once

#include <cstdint>

namespace desk_robot {

// Floor square root of a 64-bit squared norm. Exactly 32 base-four digits
// are processed, independent of the input; no sensor-dependent polling.
inline std::uint32_t attitude_norm_root(std::uint64_t value) noexcept {
  std::uint64_t root = 0;
  std::uint64_t bit = std::uint64_t{1} << 62;
  for (unsigned digit = 0; digit < 32; ++digit, bit >>= 2) {
    if (value >= root + bit) {
      value -= root + bit;
      root = (root >> 1) + bit;
    } else {
      root >>= 1;
    }
  }
  return static_cast<std::uint32_t>(root);
}

}  // namespace desk_robot
