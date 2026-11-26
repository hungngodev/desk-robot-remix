#include "BodyControl.h"
#include "McpContactEvidence.h"

#include <cstdint>
#include <iostream>
#include <stdexcept>

#define CHECK(condition) do { if (!(condition)) throw std::runtime_error(#condition); } while (false)

namespace {
using desk_robot::BodyControl;
using desk_robot::McpContactEvidence;
using desk_robot::McpOptionalRaw;

McpOptionalRaw reading(std::uint32_t seq, std::uint32_t at,
                       bool reed, bool pir) {
  McpOptionalRaw raw{};
  raw.present = raw.valid = true;
  raw.sample_seq = seq;
  raw.at_ms = at;
  raw.reed_closed = reed;
  raw.pir_active = pir;
  return raw;
}

void poll(BodyControl& body, McpContactEvidence& evidence,
          const McpOptionalRaw& raw, std::uint32_t now,
          bool bumper = false) {
  std::uint8_t mask = 1U; // the direct bumper remains available every 25 ms
  bool reed = false, pir = false;
  if (evidence.observe(raw, now)) {
    mask |= 6U;
    reed = evidence.reed_closed();
    pir = evidence.pir_active();
  }
  // Production poll_optional passes the already-qualified GPIOB state.
  body.sample_optional_inputs(mask, bumper, reed, pir, true);
}

void duplicate_cached_gpio_never_fabricates_rising_event() {
  BodyControl body;
  McpContactEvidence evidence;
  const auto low = reading(10, 0, false, false);
  poll(body, evidence, low, 0);
  const auto high = reading(11, 84, true, true);
  for (std::uint32_t now : {84U, 109U, 134U, 159U})
    poll(body, evidence, high, now);
  CHECK(body.state().reed_events == 0U && body.state().pir_events == 0U);
  for (std::uint32_t now : {168U, 193U, 218U})
    poll(body, evidence, reading(12, 168, false, false), now);
  CHECK(body.state().reed_events == 0U && body.state().pir_events == 0U);
  CHECK(!body.state().reed_active && !body.state().pir_active);
}

void three_independent_gpio_conversions_emit_exactly_one_event() {
  BodyControl body;
  McpContactEvidence evidence;
  poll(body, evidence, reading(10, 0, false, false), 0);
  for (std::uint32_t now : {25U, 50U, 75U})
    poll(body, evidence, reading(10, 0, false, false), now);
  poll(body, evidence, reading(11, 84, true, true), 84);
  for (std::uint32_t now : {109U, 134U, 159U})
    poll(body, evidence, reading(11, 84, true, true), now);
  CHECK(body.state().reed_events == 0U);
  poll(body, evidence, reading(12, 168, true, true), 168);
  for (std::uint32_t now : {193U, 218U, 243U})
    poll(body, evidence, reading(12, 168, true, true), now);
  CHECK(body.state().pir_events == 0U);
  // The THIRD actual conversion is sufficient. Do not require two fake
  // new inputs from cached 25ms polls before announcing a valid edge.
  poll(body, evidence, reading(13, 252, true, true), 252);
  CHECK(body.state().reed_events == 1U && body.state().pir_events == 1U);
  poll(body, evidence, reading(13, 252, true, true), 277);
  poll(body, evidence, reading(13, 252, true, true), 302);
  CHECK(body.state().reed_events == 1U && body.state().pir_events == 1U);
  CHECK(body.state().reed_active && body.state().pir_active);
  for (std::uint32_t now : {336U, 361U, 386U, 411U})
    poll(body, evidence, reading(14, 336, true, true), now);
  CHECK(body.state().reed_events == 1U && body.state().pir_events == 1U);
}

void independent_contact_bounce_requires_three_consecutive_conversions() {
  McpContactEvidence evidence;
  std::uint32_t seq = 0, now = 0;
  const auto sample = [&](bool reed, bool pir, bool want_reed, bool want_pir) {
    CHECK(evidence.observe(reading(++seq, now, reed, pir), now));
    CHECK(evidence.reed_closed() == want_reed);
    CHECK(evidence.pir_active() == want_pir);
    now += 84U;
  };
  sample(false, false, false, false);
  // Two real high conversions are still insufficient, even when repeated.
  for (int i = 0; i < 3; ++i) {
    sample(true, true, false, false);
    sample(true, true, false, false);
    sample(false, false, false, false);
  }
  // Alternating channels must never contribute to each other's streak.
  sample(true, false, false, false);
  sample(false, true, false, false);
  sample(true, false, false, false);
  sample(false, true, false, false);
  // A real reed closure qualifies while the PIR continues to bounce.
  sample(true, true, false, false);
  sample(true, false, false, false);
  sample(true, true, true, false);
  // Two low conversions cannot clear the stable reed level. The PIR can
  // qualify independently during that release bounce.
  sample(false, true, true, false);
  sample(false, true, true, true);
  sample(true, false, true, true);
  // A genuine release clears each level only on its third conversion.
  sample(false, false, true, true);
  sample(false, false, true, false);
  sample(false, false, false, false);
}

void rapid_chatter_needs_acquisition_time_on_both_edges() {
  for (const std::uint32_t start : {0U, 0xfffffff0U}) {
    McpContactEvidence evidence;
    std::uint32_t seq = 0;
    const auto sample = [&](std::uint32_t offset, bool reed, bool pir,
                            bool want_reed, bool want_pir) {
      const auto at = start + offset;
      CHECK(evidence.observe(reading(++seq, at, reed, pir), at));
      CHECK(evidence.reed_closed() == want_reed);
      CHECK(evidence.pir_active() == want_pir);
    };
    sample(0, false, false, false, false);
    sample(1, true, true, false, false);
    sample(2, true, true, false, false);
    sample(3, true, true, false, false);
    sample(4, false, false, false, false);
    sample(10, true, false, false, false);
    sample(12, true, true, false, false);
    sample(59, true, true, false, false);
    sample(60, true, true, true, false);
    sample(62, true, true, true, true);
    sample(63, false, false, true, true);
    sample(64, false, false, true, true);
    sample(65, false, false, true, true);
    sample(66, true, true, true, true);
    sample(70, false, false, true, true);
    sample(72, false, false, true, true);
    sample(119, false, false, true, true);
    sample(120, false, false, false, false);
  }
}

void stale_replay_and_conflicting_cache_rebaseline() {
  BodyControl body;
  McpContactEvidence evidence;
  poll(body, evidence, reading(1, 0, false, false), 0);
  poll(body, evidence, reading(2, 84, true, true), 84);
  // The sequence is unchanged but its levels contradict the original read.
  poll(body, evidence, reading(2, 84, false, true), 109);
  CHECK(body.state().extra_mask == 1U);
  poll(body, evidence, reading(3, 168, true, true), 168);
  CHECK(body.state().extra_mask == 7U);
  CHECK(body.state().reed_active && body.state().pir_active);
  CHECK(body.state().reed_events == 0U && body.state().pir_events == 0U);
  // Old sequence cannot pass an ordering check even with a newer receipt.
  poll(body, evidence, reading(2, 193, true, true), 193);
  CHECK(body.state().extra_mask == 1U);
  poll(body, evidence, reading(4, 252, true, true), 252);
  CHECK(body.state().reed_events == 0U);
  poll(body, evidence, reading(4, 252, true, true), 503); // >250ms stale
  CHECK(body.state().extra_mask == 1U);
  poll(body, evidence, reading(5, 504, true, true), 504);
  CHECK(body.state().reed_events == 0U);
}

void acquisition_gaps_cannot_fabricate_edges() {
  for (const auto gap : {251U, 84U}) {
    BodyControl body;
    McpContactEvidence evidence;
    poll(body, evidence, reading(10, 0, false, false), 0);
    // A time gap or an unobserved conversion invalidates continuity even
    // when this poll receives a fresh high sample and no intervening poll.
    const auto seq = gap == 251U ? 11U : 12U;
    poll(body, evidence, reading(seq, gap, true, true), gap);
    CHECK(body.state().extra_mask == 1U);
    CHECK(body.state().reed_events == 0U && body.state().pir_events == 0U);
    poll(body, evidence, reading(seq, gap, true, true), gap + 25U);
    CHECK(body.state().extra_mask == 7U);
    CHECK(body.state().reed_active && body.state().pir_active);
    CHECK(body.state().reed_events == 0U && body.state().pir_events == 0U);
    for (std::uint32_t i = 1; i <= 3; ++i)
      poll(body, evidence, reading(seq + i, gap + i * 84U, false, false),
           gap + i * 84U);
    for (std::uint32_t i = 4; i <= 6; ++i)
      poll(body, evidence, reading(seq + i, gap + i * 84U, true, true),
           gap + i * 84U);
    CHECK(body.state().reed_events == 1U && body.state().pir_events == 1U);
  }
}

void genuine_uint32_wrap_and_bumper_are_preserved() {
  BodyControl body;
  McpContactEvidence evidence;
  poll(body, evidence, reading(0xfffffffeU, 0xffffffa0U, false, false),
       0xffffffa0U);
  poll(body, evidence, reading(0xffffffffU, 0xfffffff4U, true, false),
       0xfffffff4U, true);
  CHECK(body.state().bumper_raw);
  poll(body, evidence, reading(1U, 0x48U, true, false), 0x48U, true);
  CHECK(!body.state().reed_active);
  poll(body, evidence, reading(2U, 0x9cU, true, false), 0x9cU, true);
  poll(body, evidence, reading(2U, 0x9cU, true, false), 0xb5U, true);
  poll(body, evidence, reading(2U, 0x9cU, true, false), 0xceU, true);
  CHECK(body.state().reed_events == 1U);
  CHECK(body.state().bumper_raw);
  CHECK(!body.state().armed);
}
} // namespace

int main() {
  try {
    duplicate_cached_gpio_never_fabricates_rising_event();
    three_independent_gpio_conversions_emit_exactly_one_event();
    independent_contact_bounce_requires_three_consecutive_conversions();
    rapid_chatter_needs_acquisition_time_on_both_edges();
    stale_replay_and_conflicting_cache_rebaseline();
    acquisition_gaps_cannot_fabricate_edges();
    genuine_uint32_wrap_and_bumper_are_preserved();
    std::cout << "seven MCP GPIOB acquisition provenance tests passed\n";
    return 0;
  } catch (const std::exception& exc) {
    std::cerr << "FAIL " << exc.what() << '\n';
    return 1;
  }
}
