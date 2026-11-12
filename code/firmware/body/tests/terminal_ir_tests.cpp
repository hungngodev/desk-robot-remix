#include <cstdint>
#include <iostream>
#include <stdexcept>
#include "NecBurst.h"

#define CHECK(x) do { if (!(x)) throw std::runtime_error(#x); } while (false)

static void make_frame(desk_robot::IrMarkSpace (&items)[34],
                       std::uint8_t addr, std::uint8_t command) {
  items[0] = {9000, 4500};
  const std::uint32_t raw =
      std::uint32_t(addr) |
      (std::uint32_t(static_cast<std::uint8_t>(~addr)) << 8) |
      (std::uint32_t(command) << 16) |
      (std::uint32_t(static_cast<std::uint8_t>(~command)) << 24);
  for (unsigned bit = 0; bit != 32; ++bit)
    items[bit + 1] = desk_robot::IrMarkSpace(
        560, static_cast<std::uint16_t>(
            (raw & (std::uint32_t(1) << bit)) ? 1690 : 560));
  items[33] = {560, 0};
}

int main() {
  try {
    desk_robot::IrMarkSpace frame[34]{};
    make_frame(frame, 0x12, 0x34);
    std::uint32_t code = 0;
    CHECK(desk_robot::decode_nec(frame, 34, code));
    CHECK(code == 0xcb34ed12U);
    CHECK(!desk_robot::decode_nec(frame, 33, code)); // no final NEC mark
    CHECK(code == 0);
    CHECK(!desk_robot::decode_nec(nullptr, 34, code));
    frame[0].space_us = 2250; // NEC repeat is not full fresh information
    CHECK(!desk_robot::decode_nec(frame, 34, code));
    make_frame(frame, 0x12, 0x34);
    frame[9].space_us = 1120; // ambiguous timing
    CHECK(!desk_robot::decode_nec(frame, 34, code));
    make_frame(frame, 0x12, 0x34);
    frame[33].mark_us = 0; // truncated trailing mark
    CHECK(!desk_robot::decode_nec(frame, 34, code));
    make_frame(frame, 0x12, 0x34);
    // Flip one bit in inverse command byte, proving full checksum validation.
    frame[25].space_us = 560;
    CHECK(!desk_robot::decode_nec(frame, 34, code));
    make_frame(frame, 0x12, 0x34);
    CHECK(desk_robot::decode_nec(frame, 34, code));

    desk_robot::DualIrEvidence pair;
    auto result = pair.assess(100);
    CHECK(!result.left_fresh && !result.right_fresh && !result.same_code);
    CHECK(!result.motor_authorized && !result.charging_authorized);
    pair.accept(0, code, 100);
    result = pair.assess(100);
    CHECK(result.left_fresh && !result.right_fresh && !result.same_code);
    pair.accept(1, code ^ 0x01000000U, 105);
    result = pair.assess(110);
    CHECK(result.left_fresh && result.right_fresh && !result.same_code);
    pair.accept(1, code, 120);
    result = pair.assess(121);
    CHECK(result.same_code && result.code == code);
    CHECK(result.left_seq == 1 && result.right_seq == 2);
    result = pair.assess(410);
    CHECK(!result.same_code && !result.left_fresh && !result.right_fresh);
    pair.accept(9, code, 420);  // invalid source is not registered
    result = pair.assess(420);
    CHECK(result.left_seq == 1 && result.right_seq == 2);
    // Clock wrapping after both receivers captured real, independent bursts.
    desk_robot::DualIrEvidence wrapped;
    wrapped.accept(0, code, 0xfffffff0U);
    wrapped.accept(1, code, 0x00000012U);
    result = wrapped.assess(0x00000022U);
    CHECK(result.same_code);
    CHECK(result.left_age_ms == 50 && result.right_age_ms == 16);
    CHECK(!result.motor_authorized && !result.charging_authorized);
    std::cout << "PASS independent full NEC frames, errors, freshness and rollover\n";
  } catch (const std::exception& e) {
    std::cerr << "FAIL " << e.what() << "\n";
    return 1;
  }
  return 0;
}
