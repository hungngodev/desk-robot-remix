#pragma once
#include <cstdint>

namespace desk_robot {
// TCA9548A permits multi-channel writes; this shared bus must never do so.
constexpr bool mux_mask_allowed(std::uint8_t mask) {
  return (mask & (mask - 1U)) == 0U;
}

struct MuxWriteResult {
  bool wrote;
  bool acknowledged;
  bool ok() const { return wrote && acknowledged; }
};

template <typename WireType>
MuxWriteResult write_mux_mask(WireType& wire, std::uint8_t address,
                              std::uint8_t mask) {
  if (!mux_mask_allowed(mask)) return {false, false};
  wire.beginTransmission(address);
  const bool wrote = wire.write(mask) == 1;
  // STOP activates the channel and must also terminate a short write.
  const bool acknowledged = wire.endTransmission(true) == 0;
  return {wrote, acknowledged};
}
}  // namespace desk_robot
