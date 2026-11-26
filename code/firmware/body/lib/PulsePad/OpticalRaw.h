#pragma once
#include <cstdint>
#ifndef DESK_ROBOT_MAX30102_FIFO_IR_FIRST
#define DESK_ROBOT_MAX30102_FIFO_IR_FIRST 0
#endif
#if DESK_ROBOT_MAX30102_FIFO_IR_FIRST != 0 && DESK_ROBOT_MAX30102_FIFO_IR_FIRST != 1
#error MAX30102 FIFO channel order must be zero or one
#endif
namespace desk_robot {
// SparkFun MAX30105 driver / MAX30102 datasheet: FIFO red then IR, each 18 bits.
// Portable parsing used by the bounded WROOM bridge, not a heart-rate diagnosis.
// https://github.com/sparkfun/SparkFun_MAX3010x_Sensor_Library
inline std::uint32_t optical18(const std::uint8_t* bytes) {
  return ((static_cast<std::uint32_t>(bytes[0]) & 0x03U) << 16) |
         (static_cast<std::uint32_t>(bytes[1]) << 8) | bytes[2];
}
// Generic GY-MAX30102 PCB replacements can have reversed optical channel
// identity despite the same part ID. Do not assume a genuine IC changes FIFO
// order. Isolate each LED on the exact fitted PCB; requalify after every swap.
// Only the reversed FIFO lab profile may be selected on measured evidence.
// A compile flag or plausible raw value does not qualify paw interaction.
static_assert(DESK_ROBOT_MAX30102_FIFO_IR_FIRST == 0 ||
              DESK_ROBOT_MAX30102_FIFO_IR_FIRST == 1,
              "MAX30102 FIFO channel order must be zero or one");
constexpr bool kOpticalFifoIrFirst = DESK_ROBOT_MAX30102_FIFO_IR_FIRST == 1;
struct OpticalChannels {
  std::uint32_t red = 0;
  std::uint32_t ir = 0;
  constexpr OpticalChannels() = default;
  constexpr OpticalChannels(std::uint32_t red_raw, std::uint32_t ir_raw = 0)
      : red(red_raw), ir(ir_raw) {}
};
inline OpticalChannels decode_optical_channels(const std::uint8_t* bytes,
                                               bool ir_first) {
  const std::uint32_t first = optical18(bytes);
  const std::uint32_t second = optical18(bytes + 3);
  return ir_first ? OpticalChannels{second, first}
                  : OpticalChannels{first, second};
}
// Uniform transport fill is ambiguous even if the I2C read ACKed.
// Check raw bytes before decoding away the upper six bits of each channel.
inline bool optical_fifo_uniform_fault(const std::uint8_t* bytes) {
  const auto fill = bytes[0];
  if (fill != 0U && fill != 0xffU) return false;
  for (unsigned i = 1; i < 6; ++i)
    if (bytes[i] != fill) return false;
  return true;
}
// Reject the 18-bit ADC rail; a single zero channel remains legitimate.
// Preserve the portable decoder's raw units and channel ordering.
inline bool optical_channels_saturated(const OpticalChannels& channels) {
  return channels.red == 0x3ffffU || channels.ir == 0x3ffffU;
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
