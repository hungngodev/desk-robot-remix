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
// The MAX30102 datasheet specifies RED then IR, but generic carrier builds
// can present inverted LED/FIFO channel wiring. Keep both interpretations
// explicit; the selected PCB must be optically tested before interpreting
// either channel as a qualified paw measurement.
struct OpticalChannels {
  std::uint32_t red;
  std::uint32_t ir;
};
inline OpticalChannels decode_optical_channels(const std::uint8_t* bytes,
                                               bool ir_first) {
  const std::uint32_t first = optical18(bytes);
  const std::uint32_t second = optical18(bytes + 3);
  return ir_first ? OpticalChannels{second, first}
                  : OpticalChannels{first, second};
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
