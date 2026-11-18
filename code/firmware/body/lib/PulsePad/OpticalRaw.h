#pragma once
#include <cstdint>
namespace desk_robot {
// SparkFun MAX30105 driver / MAX30102 datasheet: FIFO red then IR, each 18 bits.
// Portable parsing used by the bounded WROOM bridge, not a heart-rate diagnosis.
// https://github.com/sparkfun/SparkFun_MAX3010x_Sensor_Library
inline std::uint32_t optical18(const std::uint8_t* bytes) {
  return ((static_cast<std::uint32_t>(bytes[0]) & 0x03U) << 16) |
         (static_cast<std::uint32_t>(bytes[1]) << 8) | bytes[2];
}
struct OpticalRaw {
  bool present = false;
  bool valid = false;
  std::uint8_t part_id = 0;
  std::uint32_t red = 0;
  std::uint32_t ir = 0;
  std::uint32_t at_ms = 0;
  // Increment only when a genuinely new, bounded FIFO read succeeds.
  std::uint32_t sample_seq = 0;
};
} // namespace desk_robot
