#include "TerminalIr.h"
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <iostream>
#include <initializer_list>
#include <limits>
#include <stdexcept>
#include <string>

#define CHECK(x) do { if (!(x)) throw std::runtime_error(#x); } while (false)
namespace {
struct Packet {
  std::array<rmt_item32_t, 34> symbols{};
  std::size_t bytes = 34 * sizeof(rmt_item32_t);
};
struct Queue {
  std::deque<Packet> pending;
  unsigned reads = 0, returns = 0;
  bool borrowed = false, installed = false;
  unsigned arrivals_remaining = 0;
  bool next_arrival_noise = false;
};
Queue queues[2];
std::uint32_t now = 0, receive_cost = 0;
int failed_start = -1;
constexpr std::uint32_t kCode = 0xcb34ed12U;
Packet packet(bool corrupt = false, std::uint32_t code = kCode) {
  Packet p{};
  p.symbols[0] = {9000, 0, 4500, 1};
  for (unsigned bit = 0; bit != 32; ++bit)
    p.symbols[bit + 1] = {560, 0, (code & (std::uint32_t{1} << bit)) ? 1690U : 560U, 1};
  p.symbols[33] = {560, 0, 0, 0};
  if (corrupt) p.symbols[5].level0 = 1;
  return p;
}
Packet mixed_packet(bool noise) {
  if (!noise) return packet();
  Packet p{};
  p.symbols[0] = {180, 0, 300, 1};
  p.bytes = sizeof(rmt_item32_t);
  return p;
}
void push(unsigned side, unsigned count = 1, std::uint32_t code = kCode) {
  for (unsigned i = 0; i < count; ++i) queues[side].pending.push_back(packet(false, code));
}
void pair(std::uint32_t code = kCode) { push(0, 1, code); push(1, 1, code); }
void poll(desk_robot::TerminalIr& ir, std::uint32_t at) {
  now = at;
  ir.poll(at);
  for (const auto& q : queues) CHECK(!q.borrowed);
}
void check_unmatched(desk_robot::TerminalIr& ir) {
  auto e = ir.evidence(now);
  CHECK(!e.left_fresh && !e.right_fresh && !e.same_code);
  CHECK(e.code == 0 && e.left_code == 0 && e.right_code == 0);
  CHECK(!e.motor_authorized && !e.charging_authorized);
}
void check_matched(desk_robot::TerminalIr& ir, std::uint32_t expected_age) {
  auto e = ir.evidence(now);
  CHECK(e.left_fresh && e.right_fresh && e.same_code);
  CHECK(e.left_age_ms == expected_age && e.right_age_ms == expected_age);
  CHECK(e.code == kCode && e.left_code == kCode && e.right_code == kCode);
  CHECK(!e.motor_authorized && !e.charging_authorized);
}
void reset_fixture() {
  for (auto& q : queues) q = Queue{};
  now = receive_cost = 0;
  failed_start = -1;
}
// Simulate a producer adding alternating NEC and noise packets while the
// consumer returns each borrowed item. No OS thread or scheduling luck.
void check_mixed_arrivals(unsigned side, unsigned total, bool noise_first) {
  reset_fixture();
  desk_robot::TerminalIr ir;
  CHECK(ir.begin(36, 39));
  poll(ir, 100);
  pair(); poll(ir, 125); check_matched(ir, 25);
  const auto prior = ir.evidence(now);
  auto& q = queues[side];
  auto& other = queues[1 - side];
  const auto reads = q.reads;
  const auto returns = q.returns;
  const auto other_returns = other.returns;
  q.pending.push_back(mixed_packet(noise_first));
  q.arrivals_remaining = total - 1;
  q.next_arrival_noise = !noise_first;
  push(1 - side);
  poll(ir, 150); check_unmatched(ir);
  const unsigned drained = total < 8 ? total : 8;
  CHECK(q.returns - returns == drained);
  CHECK(q.reads - reads == (total < 8 ? total + 1 : 8));
  CHECK(q.pending.size() == total - drained && q.arrivals_remaining == 0);
  CHECK(other.returns - other_returns == 1 && other.pending.empty());
  CHECK(ir.evidence(now).left_seq == prior.left_seq);
  CHECK(ir.evidence(now).right_seq == prior.right_seq);
  if (total >= 8) {
    // A capped drain, even with zero queued items, did not observe empty.
    // Fresh-looking packets on either side must be discarded in quarantine.
    pair(); poll(ir, now + 25); check_unmatched(ir);
    CHECK(q.pending.empty() && other.pending.empty());
    CHECK(ir.evidence(now).left_seq == prior.left_seq);
    CHECK(ir.evidence(now).right_seq == prior.right_seq);
  }
  pair(); poll(ir, now + 25); check_matched(ir, 25);
  CHECK(ir.evidence(now).left_seq == prior.left_seq + 1);
  CHECK(ir.evidence(now).right_seq == prior.right_seq + 1);
  CHECK(!ir.begin(36, 36));
}
// Byte counts are supplied by the driver, not inferred from the backing array.
// Neither a partial symbol nor an oversized packet may refresh either side.
void check_packet_size_boundaries(unsigned side) {
  reset_fixture();
  desk_robot::TerminalIr ir;
  CHECK(ir.begin(36, 39));
  poll(ir, 100);
  pair(); poll(ir, 125); check_matched(ir, 25);
  constexpr std::size_t expected = 34 * sizeof(rmt_item32_t);
  for (const auto bytes : {std::size_t{0}, std::size_t{1}, expected - 1,
                           expected + 1, std::numeric_limits<std::size_t>::max()}) {
    const auto prior = ir.evidence(now);
    const auto left_returns = queues[0].returns;
    const auto right_returns = queues[1].returns;
    auto malformed = packet();
    malformed.bytes = bytes;
    queues[side].pending.push_back(malformed);
    push(1 - side);
    poll(ir, now + 25); check_unmatched(ir);
    CHECK(queues[0].returns == left_returns + 1);
    CHECK(queues[1].returns == right_returns + 1);
    CHECK(queues[0].pending.empty() && queues[1].pending.empty());
    CHECK(ir.evidence(now).left_seq == prior.left_seq);
    CHECK(ir.evidence(now).right_seq == prior.right_seq);
    pair(); poll(ir, now + 25); check_matched(ir, 25);
    CHECK(ir.evidence(now).left_seq == prior.left_seq + 1);
    CHECK(ir.evidence(now).right_seq == prior.right_seq + 1);
  }
  CHECK(!ir.begin(36, 36));
}
// Fresh, checksum-valid frames from different docks must revoke a previous
// agreement without losing the independently observed receiver diagnostics.
void check_mismatched_dock_ids(unsigned changed_side) {
  reset_fixture();
  desk_robot::TerminalIr ir;
  CHECK(ir.begin(36, 39));
  poll(ir, 100);
  pair(); poll(ir, 125); check_matched(ir, 25);
  const auto before = ir.evidence(now);
  constexpr std::uint32_t other_code = 0xca35ed12U;
  push(changed_side, 1, other_code);
  push(1 - changed_side);
  poll(ir, 150);
  const auto mixed = ir.evidence(now);
  CHECK(mixed.left_fresh && mixed.right_fresh && !mixed.same_code);
  CHECK(mixed.left_code == (changed_side == 0 ? other_code : kCode));
  CHECK(mixed.right_code == (changed_side == 1 ? other_code : kCode));
  CHECK(mixed.code == 0);
  CHECK(mixed.left_seq == before.left_seq + 1);
  CHECK(mixed.right_seq == before.right_seq + 1);
  CHECK(mixed.left_age_ms == 25 && mixed.right_age_ms == 25);
  CHECK(!mixed.motor_authorized && !mixed.charging_authorized);
  pair(); poll(ir, 175); check_matched(ir, 25);
  CHECK(ir.evidence(now).left_seq == mixed.left_seq + 1);
  CHECK(ir.evidence(now).right_seq == mixed.right_seq + 1);
  CHECK(!ir.begin(36, 36));
}
// Individually fresh, matching IDs are not necessarily a paired bearing.
// Include drain time in the later receiver's uncertainty, on either side.
void check_receipt_window_pair(unsigned first_side, unsigned separation) {
  reset_fixture();
  desk_robot::TerminalIr ir;
  CHECK(ir.begin(36, 39));
  poll(ir, 100);
  push(first_side); poll(ir, 180);
  const auto first = ir.evidence(now);
  CHECK(first.left_fresh == (first_side == 0));
  CHECK(first.right_fresh == (first_side == 1));
  CHECK(!first.same_code && first.code == 0);
  receive_cost = 1;
  push(1 - first_side); poll(ir, 100 + separation - 3);
  CHECK(now == 100 + separation); // three receives, including empty checks
  const auto result = ir.evidence(now);
  CHECK(result.left_fresh && result.right_fresh);
  CHECK(result.left_code == kCode && result.right_code == kCode);
  CHECK(result.left_seq == 1 && result.right_seq == 1);
  CHECK(result.left_age_ms == separation - (first_side == 0 ? 0U : 80U));
  CHECK(result.right_age_ms == separation - (first_side == 1 ? 0U : 80U));
  CHECK(result.same_code == (separation == 120));
  CHECK(result.code == (separation == 120 ? kCode : 0U));
  CHECK(!result.motor_authorized && !result.charging_authorized);
  CHECK(!ir.begin(36, 36));
}
// Emit the portable evidence fields for the Mac cross-layer host regression.
// The Python consumer supplies only the outer robot identity and qualification.
void emit_receipt(const desk_robot::IrPairEvidence& e) {
  std::cout << e.left_fresh << ' ' << e.right_fresh << ' ' << e.same_code << ' '
            << e.left_seq << ' ' << e.right_seq << ' '
            << e.left_age_ms << ' ' << e.right_age_ms << ' '
            << e.code << ' ' << e.left_code << ' ' << e.right_code << ' '
            << e.motor_authorized << ' ' << e.charging_authorized << '\n';
}
void emit_mac_receipts(std::uint32_t code, unsigned side) {
  reset_fixture();
  desk_robot::TerminalIr ir;
  CHECK(ir.begin(36, 39));
  poll(ir, 100);
  pair(code); poll(ir, 125);
  emit_receipt(ir.evidence(now));
  emit_receipt(desk_robot::age_ir_snapshot(ir.evidence(now), 175));
  emit_receipt(desk_robot::age_ir_snapshot(ir.evidence(now), 176));
  // An actual two-symbol NEC repeat cannot refresh either side's evidence.
  Packet repeat{};
  repeat.symbols[0] = {9000, 0, 2250, 1};
  repeat.symbols[1] = {560, 0, 0, 0};
  repeat.bytes = 2 * sizeof(rmt_item32_t);
  queues[side].pending.push_back(repeat);
  push(1 - side, 1, code); poll(ir, 150);
  emit_receipt(ir.evidence(now));
  pair(code); poll(ir, 175);
  emit_receipt(ir.evidence(now));
  // The eight-packet budget cannot prove the queue empty, even at exactly eight.
  push(side, 8, code); push(1 - side, 1, code); poll(ir, 200);
  emit_receipt(ir.evidence(now));
  pair(code); poll(ir, 225);
  emit_receipt(ir.evidence(now));
  pair(code); poll(ir, 250);
  emit_receipt(ir.evidence(now));
  CHECK(!ir.begin(36, 36));
}
} // namespace

std::uint32_t millis() { return now; }
esp_err_t rmt_config(const rmt_config_t*) { return ESP_OK; }
esp_err_t rmt_driver_install(rmt_channel_t channel, std::size_t, int) {
  queues[channel].installed = true;
  return ESP_OK;
}
esp_err_t rmt_get_ringbuf_handle(rmt_channel_t channel, RingbufHandle_t* handle) {
  *handle = &queues[channel];
  return ESP_OK;
}
esp_err_t rmt_rx_start(rmt_channel_t channel, bool) {
  return static_cast<int>(channel) == failed_start ? 1 : ESP_OK;
}
esp_err_t rmt_rx_stop(rmt_channel_t) { return ESP_OK; }
esp_err_t rmt_driver_uninstall(rmt_channel_t channel) {
  auto& q = queues[channel];
  CHECK(!q.borrowed);
  q.installed = false;
  q.pending.clear();
  return ESP_OK;
}
Queue* late_arrival_target = nullptr;
bool late_arrival_armed = false;

void* xRingbufferReceive(RingbufHandle_t ring, std::size_t* size, TickType_t wait) {
  auto& q = *static_cast<Queue*>(ring);
  CHECK(wait == 0 && q.installed && !q.borrowed);
  ++q.reads;
  now += receive_cost;
  if (q.pending.empty()) return nullptr;
  q.borrowed = true;
  *size = q.pending.front().bytes;
  return q.pending.front().symbols.data();
}
void vRingbufferReturnItem(RingbufHandle_t ring, void* item) {
  auto& q = *static_cast<Queue*>(ring);
  CHECK(q.borrowed && !q.pending.empty());
  CHECK(item == q.pending.front().symbols.data());
  q.borrowed = false;
  q.pending.pop_front();
  ++q.returns;
  if (late_arrival_armed && &q != late_arrival_target) {
    late_arrival_armed = false;
    late_arrival_target->pending.push_back(packet());
  }
  if (q.arrivals_remaining != 0) {
    q.pending.push_back(mixed_packet(q.next_arrival_noise));
    q.next_arrival_noise = !q.next_arrival_noise;
    --q.arrivals_remaining;
  }
}

int main(int argc, char** argv) {
  try {
    if (argc == 2 && std::string(argv[1]) == "--emit-mac-receipts") {
      for (auto code : {0xce31ed12U, 0xcd32ed12U, 0xcc33ed12U,
                        0xcb34ed12U, 0xca35ed12U}) {
        emit_mac_receipts(code, 0);
        emit_mac_receipts(code, 1);
      }
      return EXIT_SUCCESS;
    }
    reset_fixture();
    desk_robot::TerminalIr ir;
    CHECK(ir.begin(36, 39));
    pair(); poll(ir, 100); check_unmatched(ir); // startup only drains
    pair(); poll(ir, 200); check_matched(ir, 100); // inclusive gap
    const auto seq = ir.evidence(now).left_seq;
    pair(); poll(ir, 301); check_unmatched(ir); // 101 ms stall -> quarantine
    CHECK(ir.evidence(now).left_seq == seq);
    pair(); poll(ir, 302); check_unmatched(ir); // quarantine drain-only poll
    CHECK(ir.evidence(now).left_seq == seq);
    pair(); poll(ir, 326); check_matched(ir, 24);
    // Saturate the left queue. Exactly eight items must be returned, not
    // an unbounded drain. Opposite valid evidence cannot revive the pair.
    const unsigned before = queues[0].returns;
    const unsigned reads = queues[0].reads;
    push(0, 10); push(1); poll(ir, 351); check_unmatched(ir);
    CHECK(queues[0].returns - before == 8 && queues[0].reads - reads == 8);
    CHECK(queues[0].pending.size() == 2);
    push(1); poll(ir, 376); check_unmatched(ir); // quarantine drain
    CHECK(queues[0].pending.empty());
    pair(); poll(ir, 401); check_matched(ir, 25);
    // Even exactly eight queued items are not an observed empty queue.
    push(0, 8); push(1); poll(ir, 426); check_unmatched(ir);
    CHECK(queues[0].pending.empty());
    pair(); poll(ir, 451); check_unmatched(ir); // still drain-only
    pair(); poll(ir, 476); check_matched(ir, 25);
    // Multiple valid frames, malformed size and corrupt polarity each
    // discard both receivers' evidence and return every borrowed item.
    push(0); push(1, 2); poll(ir, 501); check_unmatched(ir);
    pair(); poll(ir, 526); check_matched(ir, 25);
    push(0); auto short_packet = packet(); short_packet.bytes -= 4;
    queues[1].pending.push_back(short_packet);
    poll(ir, 551); check_unmatched(ir);
    pair(); poll(ir, 576); check_matched(ir, 25);
    queues[0].pending.push_back(packet(true)); push(1);
    poll(ir, 601); check_unmatched(ir);
    pair(); poll(ir, 626); check_matched(ir, 25);
    // The start-to-start gap alone is insufficient if the drain took time.
    receive_cost = 20;
    pair(); poll(ir, 651); check_unmatched(ir); // 25 + 4 calls * 20 = 105
    receive_cost = 0;
    poll(ir, 752); check_unmatched(ir); // 101 ms from start -> stays quarantined
    poll(ir, 753); check_unmatched(ir); // timely drain clears quarantine
    pair(); poll(ir, 777); check_matched(ir, 24);
    pair(); poll(ir, 777); check_unmatched(ir); // same tick cannot refresh
    // Failed reinitialization revokes both readings and releases resources.
    failed_start = 1;
    CHECK(!ir.begin(36, 39)); check_unmatched(ir);
    CHECK(!queues[0].installed && !queues[1].installed);
    const auto read_count = queues[0].reads;
    poll(ir, 800); CHECK(queues[0].reads == read_count);
    failed_start = -1;
    CHECK(ir.begin(36, 39));
    pair(); poll(ir, 825); check_unmatched(ir); // no pre-reset evidence survives
    pair(); poll(ir, 850); check_matched(ir, 25);
    // The same drain bound applies to the right receiver.
    const auto right_before = queues[1].returns;
    push(0); push(1, 9); poll(ir, 875); check_unmatched(ir);
    CHECK(queues[1].returns - right_before == 8);
    CHECK(queues[1].pending.size() == 1);
    poll(ir, 900); check_unmatched(ir);
    pair(); poll(ir, 925); check_matched(ir, 25);
    // A long drain can exceed the receipt window even though the next
    // start-to-start gap is timely. Require another drain-only poll.
    const auto before_stall = ir.evidence(now);
    receive_cost = 20;
    pair(); poll(ir, 950); check_unmatched(ir);
    CHECK(now == 1030);
    receive_cost = 0;
    pair(); poll(ir, 1031); check_unmatched(ir);
    CHECK(ir.evidence(now).left_seq == before_stall.left_seq);
    CHECK(ir.evidence(now).right_seq == before_stall.right_seq);
    // The two directions must independently reacquire after quarantine.
    push(0); poll(ir, 1056);
    auto left_only = ir.evidence(now);
    CHECK(left_only.left_fresh && !left_only.right_fresh && !left_only.same_code);
    CHECK(left_only.left_seq == before_stall.left_seq + 1);
    CHECK(left_only.right_seq == before_stall.right_seq);
    CHECK(left_only.code == 0 && left_only.left_code == kCode && left_only.right_code == 0);
    push(1); poll(ir, 1081);
    auto recovered = ir.evidence(now);
    CHECK(recovered.same_code && recovered.left_age_ms == 50 && recovered.right_age_ms == 25);
    CHECK(recovered.left_seq == left_only.left_seq);
    CHECK(recovered.right_seq == left_only.right_seq + 1);
    CHECK(!recovered.motor_authorized && !recovered.charging_authorized);
    // Repeated saturation on either side must not advance either sequence.
    for (unsigned side = 0; side != 2; ++side) {
      const auto before_overflow = ir.evidence(now);
      push(side, 17); push(1 - side);
      for (unsigned batch = 0; batch != 3; ++batch) {
        poll(ir, now + 25); check_unmatched(ir);
        CHECK(ir.evidence(now).left_seq == before_overflow.left_seq);
        CHECK(ir.evidence(now).right_seq == before_overflow.right_seq);
        if (batch != 2) push(1 - side);
      }
      push(1 - side); poll(ir, now + 25);
      const auto first = ir.evidence(now);
      CHECK(!first.same_code && first.left_fresh == (side == 1));
      CHECK(first.right_fresh == (side == 0));
      push(side); poll(ir, now + 25);
      CHECK(ir.evidence(now).same_code);
    }
    // An ambiguous batch can also overrun its receipt window. The next
    // timely poll must drain both receivers before either can reacquire.
    for (unsigned side = 0; side != 2; ++side) {
      const auto before_ambiguous = ir.evidence(now);
      receive_cost = 16;
      push(side, 2); push(1 - side);
      const auto start = now + 25U;
      poll(ir, start); check_unmatched(ir);
      CHECK(now == start + 80U); // 25 + five receives * 16 = 105 ms
      receive_cost = 0;
      pair(); poll(ir, now + 1U); check_unmatched(ir);
      CHECK(ir.evidence(now).left_seq == before_ambiguous.left_seq);
      CHECK(ir.evidence(now).right_seq == before_ambiguous.right_seq);
      pair(); poll(ir, now + 25U); check_matched(ir, 25);
    }
    // Tear down before isolating a second receiver history for rollover.
    CHECK(!ir.begin(36, 36));
    CHECK(!queues[0].installed && !queues[1].installed);
    for (unsigned side = 0; side != 2; ++side) {
      check_packet_size_boundaries(side);
      check_mismatched_dock_ids(side);
      check_receipt_window_pair(side, 120);
      check_receipt_window_pair(side, 121);
      for (unsigned total : {2U, 7U, 8U, 9U}) {
        check_mixed_arrivals(side, total, false);
        check_mixed_arrivals(side, total, true);
      }
    }
    // Late-start poll (>100 ms gap): if a frame arrives in side 0 after side 0
    // was observed empty while side 1 is still draining, quarantine must hold
    // through another complete drain before an independent pair refreshes.
    reset_fixture();
    desk_robot::TerminalIr late;
    CHECK(late.begin(36, 39));
    poll(late, 100);
    pair();
    poll(late, 125);
    check_matched(late, 25);
    const auto before_late_start = late.evidence(now);
    late_arrival_target = &queues[0];
    late_arrival_armed = true;
    push(1);
    poll(late, now + 150U);
    if (late.evidence(now).left_fresh || late.evidence(now).right_fresh || late.evidence(now).same_code)
      throw std::runtime_error("late_start step1 unmatched");
    CHECK(!late_arrival_armed);
    CHECK(queues[0].pending.size() == 1);
    CHECK(late.evidence(now).left_seq == before_late_start.left_seq);
    CHECK(late.evidence(now).right_seq == before_late_start.right_seq);
    push(1);
    poll(late, now + 25U);
    if (late.evidence(now).left_fresh || late.evidence(now).right_fresh || late.evidence(now).same_code)
      throw std::runtime_error("late_start step2 drain unmatched");
    CHECK(queues[0].pending.empty() && queues[1].pending.empty());
    CHECK(late.evidence(now).left_seq == before_late_start.left_seq);
    CHECK(late.evidence(now).right_seq == before_late_start.right_seq);
    pair();
    poll(late, now + 25U);
    const auto rec = late.evidence(now);
    if (!rec.left_fresh || !rec.right_fresh || !rec.same_code)
      throw std::runtime_error("late_start step3 match failed: lf=" + std::to_string(rec.left_fresh) + " rf=" + std::to_string(rec.right_fresh) + " sc=" + std::to_string(rec.same_code));
    CHECK(rec.left_age_ms == 25 && rec.right_age_ms == 25);
    CHECK(rec.left_seq == before_late_start.left_seq + 1);
    CHECK(rec.right_seq == before_late_start.right_seq + 1);
    CHECK(!rec.motor_authorized && !rec.charging_authorized);
    reset_fixture();
    desk_robot::TerminalIr wrap;
    CHECK(wrap.begin(36, 39));
    poll(wrap, 0xfffffff0U); check_unmatched(wrap);
    pair(); poll(wrap, 0x12U); check_matched(wrap, 34);
    now = 0xb8U; check_matched(wrap, 200);
    now = 0xb9U; check_unmatched(wrap);
    std::cout << "PASS production RMT poll: queue cap, mixed arrivals, quarantine, "
                 "gap, drain cost, rollover, reset\n";
  } catch (const std::exception& e) {
    std::cerr << "FAIL " << e.what() << '\n';
    return EXIT_FAILURE;
  }
  return EXIT_SUCCESS;
}
