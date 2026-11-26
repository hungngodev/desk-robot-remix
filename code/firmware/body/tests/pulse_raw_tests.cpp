#include "OpticalRaw.h"

constexpr desk_robot::OpticalChannels cold_channels;
static_assert(cold_channels.red == 0 && cold_channels.ir == 0, "FIFO evidence must start empty");
#include <iostream>
#include <stdexcept>
#define CHECK(x) do { if (!(x)) throw std::runtime_error(#x); } while (false)
int main() {
  try {
    const std::uint8_t zero[3] = {0,0,0};
    const std::uint8_t max[3] = {0xff,0xff,0xff};
    const std::uint8_t example[3] = {0x01,0x23,0x45};
    CHECK(desk_robot::optical18(zero) == 0);
    CHECK(desk_robot::optical18(max) == 262143U);
    CHECK(desk_robot::optical18(example) == 0x12345U);
    const std::uint8_t two_led_fifo[6] = {0x00, 0x12, 0x34, 0x01, 0x23, 0x45};
    // All six bytes must agree; a single zero channel is not a bus fill.
    for (std::uint8_t fill : {std::uint8_t(0), std::uint8_t(0xff)}) {
      std::uint8_t frame[6] = {fill, fill, fill, fill, fill, fill};
      CHECK(desk_robot::optical_fifo_uniform_fault(frame));
      for (unsigned i = 0; i < 6; ++i) {
        frame[i] ^= 1U;
        CHECK(!desk_robot::optical_fifo_uniform_fault(frame));
        frame[i] ^= 1U;
      }
    }
    CHECK(!desk_robot::optical_fifo_uniform_fault(two_led_fifo));
    const auto datasheet = desk_robot::decode_optical_channels(two_led_fifo, false);
    const auto reversed = desk_robot::decode_optical_channels(two_led_fifo, true);
    CHECK(datasheet.red == 0x1234U && datasheet.ir == 0x12345U);
    CHECK(reversed.red == datasheet.ir && reversed.ir == datasheet.red);
    CHECK(!desk_robot::optical_channels_saturated({0U, 0U}));
    CHECK(!desk_robot::optical_channels_saturated({262142U, 262142U}));
    CHECK(desk_robot::optical_channels_saturated({262143U, 0U}));
    CHECK(desk_robot::optical_channels_saturated({0U, 262143U}));
    // Both channels can clip in the same FIFO record; reject either or both.
    const std::uint8_t both_clipped[6] = {0x03, 0xff, 0xff, 0x03, 0xff, 0xff};
    for (bool ir_first : {false, true}) {
      const auto channels = desk_robot::decode_optical_channels(both_clipped, ir_first);
      CHECK(channels.red == 262143U && channels.ir == 262143U);
      CHECK(desk_robot::optical_channels_saturated(channels));
    }
    // Exercise every 18-bit ADC code in both channels. Upper six bits are
    // outside the ADC payload; vary them independently of the sample values.
    // This is a decoder test, not a measurement of conversion or UART jitter.
    for (std::uint32_t red = 0; red <= 262143U; ++red) {
      const std::uint32_t ir = 262143U - red;
      const std::uint8_t frame[6] = {
          static_cast<std::uint8_t>(red / 65536U + 4U * (red % 64U)),
          static_cast<std::uint8_t>(red / 256U % 256U),
          static_cast<std::uint8_t>(red % 256U),
          static_cast<std::uint8_t>(ir / 65536U + 4U * (ir % 64U)),
          static_cast<std::uint8_t>(ir / 256U % 256U),
          static_cast<std::uint8_t>(ir % 256U)};
      const auto normal = desk_robot::decode_optical_channels(frame, false);
      const auto swapped = desk_robot::decode_optical_channels(frame, true);
      CHECK(normal.red == red && normal.ir == ir);
      CHECK(swapped.red == ir && swapped.ir == red);
      const bool clipped = red == 262143U || ir == 262143U;
      CHECK(desk_robot::optical_channels_saturated(normal) == clipped);
      CHECK(desk_robot::optical_channels_saturated(swapped) == clipped);
    }
    // Four consecutive records fit the driver's 24-byte read bound. Adjacent
    // records must not bleed into the channel pair at each six-byte offset.
    const std::uint8_t burst[24] = {
        0x00, 0x00, 0x01, 0x03, 0xff, 0xfe,
        0x01, 0x00, 0x00, 0x02, 0x00, 0x01,
        0x03, 0xff, 0xff, 0x00, 0x00, 0x00,
        0x00, 0xff, 0xff, 0x02, 0xff, 0xff};
    const std::uint32_t reds[4] = {1U, 65536U, 262143U, 65535U};
    const std::uint32_t irs[4] = {262142U, 131073U, 0U, 196607U};
    for (unsigned i = 0; i < 4; ++i) {
      const auto normal = desk_robot::decode_optical_channels(burst + 6 * i, false);
      const auto swapped = desk_robot::decode_optical_channels(burst + 6 * i, true);
      CHECK(normal.red == reds[i] && normal.ir == irs[i]);
      CHECK(swapped.red == irs[i] && swapped.ir == reds[i]);
      CHECK(desk_robot::optical_channels_saturated(normal) == (i == 2));
    }
    const desk_robot::OpticalRaw unknown{};
    CHECK(!unknown.present && !unknown.valid && unknown.ir == 0);
    CHECK(unknown.sample_seq == 0U); // boot cannot mimic a fresh touch
    std::cout << "PASS bounded MAX30102 red/IR raw decoder\n";
  } catch (const std::exception& e) {
    std::cerr << "FAIL " << e.what() << "\n";
    return 1;
  }
}
