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
    // Invalidation must reject old sightings without erasing diagnostic counts.
    desk_robot::DualIrEvidence invalidated;
    invalidated.accept(0, code, 100);
    invalidated.accept(1, code, 110);
    CHECK(invalidated.assess(120).same_code);
    invalidated.invalidate();
    result = invalidated.assess(120);
    CHECK(!result.left_fresh && !result.right_fresh && !result.same_code);
    CHECK(result.left_seq == 1 && result.right_seq == 1);
    invalidated.accept(0, code, 130);
    CHECK(!invalidated.assess(130).same_code);
    invalidated.accept(1, code, 140);
    CHECK(invalidated.assess(140).same_code);
    // IDF 4.4 has no receive timestamp. An unqualified poll cannot relabel
    // queued old RMT frames as fresh directional evidence.
    desk_robot::IrFrameQueueGate queue;
    CHECK(!queue.on_poll(100)); // first poll is a drain-only baseline
    CHECK(queue.finish(0, 1, true) && queue.finish(1, 1, true));
    CHECK(queue.on_poll(150)); // previous queues were observed empty
    CHECK(queue.finish(0, 1, true) && queue.finish(1, 1, true));
    // Two valid packets on one receiver have no source timestamps. They
    // cannot be treated as a single current bearing even when both decode.
    CHECK(queue.on_poll(200));
    CHECK(!queue.finish(0, 2, true));
    CHECK(queue.finish(1, 1, true));
    CHECK(queue.on_poll(250));
    CHECK(queue.finish(0, 1, true)); // a later isolated frame recovers
    CHECK(queue.finish(1, 0, true));
    CHECK(!queue.on_poll(400)); // old messages after a long stall are stale
    CHECK(queue.finish(0, 1, true) && queue.finish(1, 1, true));
    CHECK(queue.on_poll(450));
    CHECK(!queue.finish(0, 3, true)); // three packets mean ambiguous backlog
    CHECK(queue.finish(1, 1, true)); // other side's evidence must be discarded
    CHECK(queue.on_poll(500));
    CHECK(!queue.finish(0, 8, false)); // receive budget ran out
    CHECK(queue.draining(0));
    CHECK(!queue.finish(0, 2, true)); // merely draining is not a new sighting
    CHECK(!queue.draining(0));
    CHECK(queue.finish(0, 1, true)); // only a later batch can reacquire
    CHECK(!queue.draining(9));
    CHECK(!queue.finish(9, 1, true));
    queue.reset();
    CHECK(!queue.on_poll(0xfffffff0U));
    CHECK(queue.finish(0, 0, true) && queue.finish(1, 0, true));
    CHECK(queue.on_poll(0x00000022U)); // wrapping short interval is timely
    CHECK(queue.finish(0, 1, true) && queue.finish(1, 1, true));
    // Clock wrapping after both receivers captured real, independent bursts.
    desk_robot::DualIrEvidence wrapped;
    wrapped.accept(0, code, 0xfffffff0U);
    wrapped.accept(1, code, 0x00000012U);
    result = wrapped.assess(0x00000022U);
    CHECK(result.same_code);
    CHECK(result.left_age_ms == 50 && result.right_age_ms == 16);
    CHECK(!result.motor_authorized && !result.charging_authorized);
    // 100 independent classic NEC beacons, and 400 deterministic fault
    // mutations. This is protocol stress, NOT 100 physical robot iterations.
    for (unsigned seed = 0; seed != 100; ++seed) {
      const auto addr = static_cast<std::uint8_t>(seed);
      const auto command = static_cast<std::uint8_t>(seed * 37U);
      make_frame(frame, addr, command);
      const std::uint32_t expected =
          std::uint32_t(addr) |
          (std::uint32_t(static_cast<std::uint8_t>(~addr)) << 8) |
          (std::uint32_t(command) << 16) |
          (std::uint32_t(static_cast<std::uint8_t>(~command)) << 24);
      CHECK(desk_robot::decode_nec(frame, 34, code) && code == expected);
      frame[1 + seed % 32].mark_us = 40; // rejected glitch
      CHECK(!desk_robot::decode_nec(frame, 34, code));
      make_frame(frame, addr, command);
      frame[1 + seed % 32].space_us = 1100; // ambiguous one/zero
      CHECK(!desk_robot::decode_nec(frame, 34, code));
      make_frame(frame, addr, command);
      frame[0].mark_us = 250; // header never accepted by chance
      CHECK(!desk_robot::decode_nec(frame, 34, code));
      make_frame(frame, addr, command);
      frame[33].space_us = 560; // missing mandatory frame end idle
      CHECK(!desk_robot::decode_nec(frame, 34, code));
    }
    std::cout << "PASS 100 NEC codes, 400 corruptions, dual freshness and rollover\n";
  } catch (const std::exception& e) {
    std::cerr << "FAIL " << e.what() << "\n";
    return 1;
  }
  return 0;
}
