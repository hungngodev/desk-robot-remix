#include "OpticalRaw.h"
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
    const auto datasheet = desk_robot::decode_optical_channels(two_led_fifo, false);
    const auto reversed = desk_robot::decode_optical_channels(two_led_fifo, true);
    CHECK(datasheet.red == 0x1234U && datasheet.ir == 0x12345U);
    CHECK(reversed.red == datasheet.ir && reversed.ir == datasheet.red);
    const desk_robot::OpticalRaw unknown{};
    CHECK(!unknown.present && !unknown.valid && unknown.ir == 0);
    CHECK(unknown.sample_seq == 0U); // boot cannot mimic a fresh touch
    std::cout << "PASS bounded MAX30102 red/IR raw decoder\n";
  } catch (const std::exception& e) {
    std::cerr << "FAIL " << e.what() << "\n";
    return 1;
  }
}
