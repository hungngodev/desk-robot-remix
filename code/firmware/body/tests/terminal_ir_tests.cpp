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
    // The evidence owner must not trust raw codes from future RMT callers.
    // Invalid complement bytes must never refresh freshness or sequence.
    pair.accept(0, 0U, 99);
    pair.accept(1, code ^ 0x01000000U, 99);
    result = pair.assess(100);
    CHECK(!result.left_fresh && !result.right_fresh && !result.same_code);
    CHECK(result.left_seq == 0 && result.right_seq == 0);
    CHECK(!result.motor_authorized && !result.charging_authorized);
    pair.accept(0, code, 100);
    result = pair.assess(100);
    CHECK(result.left_fresh && !result.right_fresh && !result.same_code);
    pair.accept(1, code ^ 0x01010000U, 105); // distinct but checksum-valid NEC command
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
    // A corrupt receiver identity must revoke both old sightings. Otherwise
    // a future RMT caller could preserve a stale terminal dock bearing.
    desk_robot::DualIrEvidence invalid_side;
    invalid_side.accept(0, code, 100);
    invalid_side.accept(1, code, 110);
    CHECK(invalid_side.assess(115).same_code);
    invalid_side.accept(2, code, 116);
    result = invalid_side.assess(116);
    CHECK(!result.left_fresh && !result.right_fresh && !result.same_code);
    CHECK(result.left_seq == 1 && result.right_seq == 1);
    CHECK(!result.motor_authorized && !result.charging_authorized);
    invalid_side.accept(0, code, 120);
    CHECK(!invalid_side.assess(120).same_code);
    invalid_side.accept(1, code, 125);
    CHECK(invalid_side.assess(125).same_code);
    invalid_side.accept(0xffffffffU, code, 130);
    result = invalid_side.assess(130);
    CHECK(!result.same_code && !result.left_fresh && !result.right_fresh);
    CHECK(result.left_seq == 2 && result.right_seq == 2);
    CHECK(!result.motor_authorized && !result.charging_authorized);
    // A caller bypassing the queue gate must not replay a same-tick or
    // older receiver frame to refresh previously qualified dock evidence.
    desk_robot::DualIrEvidence replay;
    replay.accept(0, code, 100);
    replay.accept(1, code, 110);
    CHECK(replay.assess(110).same_code);
    replay.accept(0, code, 100);
    result = replay.assess(110);
    CHECK(!result.same_code && !result.left_fresh && !result.right_fresh);
    CHECK(result.left_seq == 1 && result.right_seq == 1);
    CHECK(!result.motor_authorized && !result.charging_authorized);
    replay.accept(0, code, 120);
    replay.accept(1, code, 125);
    CHECK(replay.assess(125).same_code);
    replay.accept(1, code, 124);
    CHECK(!replay.assess(125).same_code);
    // Valid monotonic timestamps across the 32-bit clock wrap still work.
    desk_robot::DualIrEvidence replay_wrap;
    replay_wrap.accept(0, code, 0xfffffff0U);
    replay_wrap.accept(1, code, 0xfffffff1U);
    replay_wrap.accept(0, code, 0x00000012U);
    replay_wrap.accept(1, code, 0x00000013U);
    CHECK(replay_wrap.assess(0x00000022U).same_code);
    CHECK(replay_wrap.assess(0x00000022U).left_seq == 2);
    CHECK(replay_wrap.assess(0x00000022U).right_seq == 2);
    // Invalidation must reject old sightings without erasing diagnostic counts.
    desk_robot::DualIrEvidence invalidated;
    invalidated.accept(0, code, 100);
    invalidated.accept(1, code, 110);
    CHECK(invalidated.assess(120).same_code);
    invalidated.invalidate();
    result = invalidated.assess(120);
    CHECK(!result.left_fresh && !result.right_fresh && !result.same_code);
    CHECK(result.left_seq == 1 && result.right_seq == 1);
    // Quarantine invalidates the bearing, not the acquisition watermark.
    invalidated.accept(0, code, 100);
    invalidated.accept(1, code, 110);
    result = invalidated.assess(120);
    CHECK(!result.same_code && !result.left_fresh && !result.right_fresh);
    CHECK(result.left_seq == 1 && result.right_seq == 1);
    invalidated.accept(0, code, 99);
    invalidated.accept(1, code, 109);
    result = invalidated.assess(120);
    CHECK(!result.same_code && result.left_seq == 1 && result.right_seq == 1);
    desk_robot::DualIrEvidence quarantine_wrap;
    quarantine_wrap.accept(0, code, 0xfffffff0U);
    quarantine_wrap.accept(1, code, 0xfffffff1U);
    quarantine_wrap.invalidate();
    quarantine_wrap.accept(0, code, 0xfffffff0U);
    quarantine_wrap.accept(1, code, 0xfffffff1U);
    CHECK(!quarantine_wrap.assess(0x10U).same_code);
    quarantine_wrap.accept(0, code, 0x12U);
    quarantine_wrap.accept(1, code, 0x13U);
    result = quarantine_wrap.assess(0x14U);
    CHECK(result.same_code && result.left_seq == 2 && result.right_seq == 2);
    CHECK(!result.motor_authorized && !result.charging_authorized);
    invalidated.accept(0, code, 130);
    CHECK(!invalidated.assess(130).same_code);
    invalidated.accept(1, code, 140);
    CHECK(invalidated.assess(140).same_code);
    // A future caller bypassing the RMT queue gate must not preserve a
    // previous bearing when it supplies a checksum-invalid raw observation.
    invalidated.accept(1, code ^ 0x01000000U, 145);
    result = invalidated.assess(145);
    CHECK(!result.left_fresh && !result.right_fresh && !result.same_code);
    CHECK(result.left_seq == 2 && result.right_seq == 2);
    CHECK(!result.motor_authorized && !result.charging_authorized);
    invalidated.accept(0, code, 150);
    CHECK(!invalidated.assess(150).same_code);
    invalidated.accept(1, code, 155);
    CHECK(invalidated.assess(155).same_code);
    // A corrupt left observation must revoke both sides as well.
    invalidated.accept(0, code ^ 0x00000100U, 160);
    CHECK(!invalidated.assess(160).same_code);
    CHECK(!invalidated.assess(160).left_fresh);
    CHECK(!invalidated.assess(160).right_fresh);
    // Reproduce the actual poll owner's fail-closed composition: a single
    // corrupt right receiver packet revokes a previously valid pair, even
    // when the left receiver simultaneously reports a valid new NEC burst.
    // Recovery requires two independent subsequent clean observations.
    desk_robot::DualIrEvidence integrated;
    desk_robot::IrFrameQueueGate integrated_gate;
    CHECK(!integrated_gate.on_poll(100));
    CHECK(integrated_gate.finish(0, 0, true));
    CHECK(integrated_gate.finish(1, 0, true));
    CHECK(integrated_gate.on_poll(125));
    CHECK(integrated_gate.finish(0, 1, true, true));
    CHECK(integrated_gate.finish(1, 1, true, true));
    integrated.accept(0, code, 125);
    integrated.accept(1, code, 125);
    CHECK(integrated.assess(125).same_code);
    CHECK(integrated_gate.on_poll(150));
    const bool clean_left = integrated_gate.finish(0, 1, true, true);
    const bool corrupt_right = integrated_gate.finish(1, 1, true, false);
    CHECK(clean_left && !corrupt_right);
    if (!(clean_left && corrupt_right)) integrated.invalidate();
    CHECK(!integrated.assess(150).same_code);
    CHECK(!integrated.assess(150).motor_authorized);
    CHECK(!integrated.assess(150).charging_authorized);
    CHECK(integrated_gate.on_poll(175));
    CHECK(integrated_gate.finish(0, 1, true, true));
    CHECK(integrated_gate.finish(1, 0, true));
    integrated.accept(0, code, 175);
    CHECK(!integrated.assess(175).same_code);
    CHECK(integrated_gate.on_poll(200));
    CHECK(integrated_gate.finish(0, 0, true));
    CHECK(integrated_gate.finish(1, 1, true, true));
    integrated.accept(1, code, 200);
    CHECK(integrated.assess(200).same_code);
    CHECK(!integrated.assess(200).motor_authorized);
    CHECK(!integrated.assess(200).charging_authorized);
    // IDF 4.4 has no receive timestamp. An unqualified poll cannot relabel
    // queued old RMT frames as fresh directional evidence.
    desk_robot::IrFrameQueueGate queue;
    CHECK(!queue.on_poll(100)); // first poll is a drain-only baseline
    CHECK(queue.finish(0, 1, true) && queue.finish(1, 1, true));
    // A second poll with the same millis value cannot contain a newly
    // completed 34-symbol NEC burst. It must not refresh a previous bearing.
    CHECK(!queue.on_poll(100));
    CHECK(queue.finish(0, 1, true, true));
    CHECK(queue.finish(1, 1, true, true));
    CHECK(queue.on_poll(150)); // previous queues were observed empty
    CHECK(queue.finish(0, 1, true) && queue.finish(1, 1, true));
    // Two valid packets on one receiver have no source timestamps. They
    // cannot be treated as a single current bearing even when both decode.
    CHECK(queue.on_poll(200));
    CHECK(!queue.finish(0, 2, true));
    CHECK(queue.finish(1, 1, true));
    CHECK(queue.on_poll(250));
    CHECK(queue.finish(0, 1, true)); // a later isolated frame recovers
    // A single malformed/noisy frame must revoke the previous pair, not
    // leave its old same-code bearing usable alongside a newer other side.
    CHECK(queue.on_poll(275));
    CHECK(!queue.finish(0, 1, true, false)); // checksum/polarity/size failure
    CHECK(queue.finish(1, 1, true, true));
    CHECK(queue.on_poll(300));
    CHECK(!queue.finish(0, 1, true, false)); // repeated invalid frame
    CHECK(queue.finish(1, 0, true, false)); // empty side is not a failure
    CHECK(queue.on_poll(325));
    CHECK(queue.finish(0, 1, true, true)); // later valid frame reacquires
    CHECK(queue.finish(1, 1, true, true));
    CHECK(queue.finish(1, 0, true));
    CHECK(!queue.on_poll(426)); // 101ms after last poll exceeds 100ms freshness fence
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
    // The second receiver must reject an untimestamped double burst too.
    // A valid opposite-side packet cannot make that ambiguous batch safe.
    CHECK(queue.on_poll(525));
    CHECK(queue.finish(0, 1, true, true));
    CHECK(!queue.finish(1, 2, true, true));
    CHECK(queue.on_poll(550));
    CHECK(queue.finish(1, 1, true, true)); // isolated recovery only
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
    // Generic classic NEC decoding is useful for protocol stress but is
    // not sufficient for dock evidence. All five configured senders are
    // accepted; unrelated remotes cannot advance or preserve a bearing.
    for (unsigned id = 1; id <= 5; ++id) {
      make_frame(frame, 0x12, static_cast<std::uint8_t>(0x30 + id));
      std::uint32_t dock_code = 0;
      CHECK(desk_robot::decode_nec(frame, 34, dock_code));
      desk_robot::DualIrEvidence dock;
      dock.accept(0, dock_code, 100);
      dock.accept(1, dock_code, 105);
      const auto reading = dock.assess(105);
      CHECK(reading.same_code && reading.code == dock_code);
      CHECK(!reading.motor_authorized && !reading.charging_authorized);
    }
    const std::uint8_t other_addresses[] = {0x13, 0x12, 0x12};
    const std::uint8_t other_commands[] = {0x34, 0x30, 0x36};
    for (unsigned i = 0; i < 3; ++i) {
      make_frame(frame, other_addresses[i], other_commands[i]);
      std::uint32_t other = 0;
      CHECK(desk_robot::decode_nec(frame, 34, other));
      desk_robot::DualIrEvidence dock;
      dock.accept(0, other, 100);
      CHECK(!dock.assess(100).left_fresh);
      CHECK(dock.assess(100).left_seq == 0);
      dock.accept(0, code, 110);
      dock.accept(1, code, 115);
      CHECK(dock.assess(115).same_code);
      dock.accept(1, other, 120);
      const auto rejected = dock.assess(120);
      CHECK(!rejected.left_fresh && !rejected.right_fresh &&
            !rejected.same_code && rejected.code == 0);
      CHECK(rejected.left_seq == 1 && rejected.right_seq == 1);
      CHECK(!rejected.motor_authorized && !rejected.charging_authorized);
      dock.accept(0, code, 110);
      CHECK(!dock.assess(121).left_fresh);
      dock.accept(0, code, 130);
      dock.accept(1, code, 135);
      CHECK(dock.assess(135).same_code);
    }
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
