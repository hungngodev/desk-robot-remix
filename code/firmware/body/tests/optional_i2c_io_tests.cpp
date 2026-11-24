#include <cstdint>
#include <iostream>
#include <stdexcept>
#include "Wire.h"
#include "AccessorySensors.h"
#include "PulsePad.h"
#include "ExpansionTouch.h"
TwoWire Wire;
#define CHECK(x) do { if (!(x)) throw std::runtime_error(#x); } while (false)
int main() {
  try {
    desk_robot::AccessorySensors accessories;
    desk_robot::PulsePad pulse;
    desk_robot::ExpansionTouch touch;
    const bool accessories_initialized = accessories.begin(Wire);
    if (!accessories_initialized) {
      std::cerr << "ACCESSORY_INIT_FAILURE last_addr=" << unsigned(Wire.current_address)
                << " muxA=" << unsigned(Wire.ranges)
                << " muxB=" << unsigned(Wire.extras)
                << " transactions=" << Wire.transactions
                << " outbound_bytes=" << Wire.outbound.size() << '\n';
    }
    CHECK(accessories_initialized);
    CHECK(desk_robot::next_nonzero_sensor_sequence(0U) == 1U);
    CHECK(desk_robot::next_nonzero_sensor_sequence(0xfffffffeU) == 0xffffffffU);
    CHECK(desk_robot::next_nonzero_sensor_sequence(0xffffffffU) == 1U);
    CHECK(desk_robot::ads1115_completed_for_channel(0xC383U, 0U));
    CHECK(desk_robot::ads1115_completed_for_channel(0xD383U, 1U));
    CHECK(!desk_robot::ads1115_completed_for_channel(0x4383U, 0U)); // OS busy
    CHECK(!desk_robot::ads1115_completed_for_channel(0x5383U, 1U)); // OS busy
    CHECK(!desk_robot::ads1115_completed_for_channel(0xD383U, 0U)); // wrong mux
    CHECK(!desk_robot::ads1115_completed_for_channel(0xC383U, 2U)); // no lane 2
    CHECK(pulse.begin(Wire));
    CHECK(touch.begin(Wire));
    CHECK(Wire.ranges == 0 && Wire.extras == 0);
    // Common generic CAP1188 address 0x29 works on isolated 0x71 lane 0,
    // without requiring a special 0x28 resistor-strap carrier.
    TwoWire generic_touch_wire;
    generic_touch_wire.cap_uses_0x29 = true;
    generic_touch_wire.cap_config = 0xF8; // unrelated bits + disabled filters
    generic_touch_wire.cap_config2 = 0x45; // RF disabled; preserve unrelated bits
    generic_touch_wire.cap_recal_config = 0x7F;
    generic_touch_wire.cap_noise_threshold = 0x03;
    desk_robot::ExpansionTouch generic_touch;
    CHECK(generic_touch.begin(generic_touch_wire));
    CHECK(generic_touch.verified());
    // Upstream multi-electrode init is now adopted on the isolated mux.
    CHECK(generic_touch_wire.cap_multi_touch_block == 0);
    CHECK(Wire.cap_config == 0x00); // strapped 0x28 also enables noise gate
    CHECK(generic_touch_wire.cap_config == 0xC0);
    CHECK(generic_touch_wire.cap_config2 == 0x41);
    TwoWire ignored_multi_wire;
    ignored_multi_wire.ignore_cap_multi_touch_write = true;
    desk_robot::ExpansionTouch ignored_multi;
    CHECK(!ignored_multi.begin(ignored_multi_wire));
    CHECK(!ignored_multi.verified());
    CHECK(ignored_multi_wire.ranges == 0 && ignored_multi_wire.extras == 0);
    CHECK(generic_touch_wire.cap_recal_config == 0x0A);
    CHECK(generic_touch_wire.cap_noise_threshold == 0x01);
    for (const bool ignored : {false, true}) {
      TwoWire failed_config_wire;
      failed_config_wire.fail_cap_config_write = !ignored;
      failed_config_wire.ignore_cap_config_write = ignored;
      desk_robot::ExpansionTouch failed_config;
      CHECK(!failed_config.begin(failed_config_wire));
      CHECK(!failed_config.verified());
      CHECK(failed_config_wire.ranges == 0 && failed_config_wire.extras == 0);
      std::uint8_t untouched = 0x5A;
      CHECK(!failed_config.poll(100, untouched));
      CHECK(untouched == 0x5A);
    }
    std::uint8_t generic_zones = 0;
    CHECK(generic_touch.poll(100, generic_zones));
    CHECK(generic_zones == 0xA5);
    CHECK(generic_touch_wire.cap_main_control == 0);
    CHECK(generic_touch_wire.cap_interrupt_clears == 1);
    // Release creates an interrupt even when no electrode is touched.
    // Clear MAIN.INT and preserve unrelated control bits on a zero mask.
    generic_touch_wire.cap_touch_bits = 0;
    generic_touch_wire.cap_main_control = 0x81;
    CHECK(generic_touch.poll(200, generic_zones));
    CHECK(generic_zones == 0U);
    CHECK(generic_touch_wire.cap_main_control == 0x80);
    CHECK(generic_touch_wire.cap_interrupt_clears == 2);
    CHECK(generic_touch_wire.ranges == 0 && generic_touch_wire.extras == 0);
    // Failed release acknowledgement is not a valid reported release.
    TwoWire release_clear_wire;
    release_clear_wire.cap_touch_bits = 0;
    release_clear_wire.cap_main_control = 0x81;
    desk_robot::ExpansionTouch release_clear;
    CHECK(release_clear.begin(release_clear_wire));
    release_clear_wire.fail_cap_clear_write = true;
    std::uint8_t release_zones = 0xA5;
    CHECK(!release_clear.poll(100, release_zones));
    CHECK(release_zones == 0xA5);
    CHECK(!release_clear.verified());
    CHECK(release_clear_wire.ranges == 0 && release_clear_wire.extras == 0);
    CHECK(!release_clear_wire.unsafe_parallel_mux);
    // A lost MAIN.INT write must not publish the cached contact zone.
    TwoWire failed_clear_wire;
    desk_robot::ExpansionTouch failed_clear;
    CHECK(failed_clear.begin(failed_clear_wire));
    failed_clear_wire.fail_cap_clear_write = true;
    std::uint8_t unchanged = 0x5a;
    CHECK(!failed_clear.poll(100, unchanged));
    CHECK(!failed_clear.verified());
    CHECK(unchanged == 0x5a);
    CHECK(failed_clear_wire.ranges == 0 && failed_clear_wire.extras == 0);
    CHECK(!failed_clear_wire.unsafe_parallel_mux);
    CHECK(generic_touch_wire.ranges == 0 && generic_touch_wire.extras == 0);
    CHECK(!generic_touch_wire.unsafe_parallel_mux);
    // An ACK is not proof that the safety mux actually disabled its 0x29
    // sensor. Even when the CAP chip is also at 0x29, the optional path
    // must refuse to open its 0x71 branch until the 0x70 readback is zero.
    TwoWire stuck_range_touch_wire;
    stuck_range_touch_wire.ranges = 1;
    stuck_range_touch_wire.range_mux_stuck = true;
    desk_robot::ExpansionTouch stuck_range_touch;
    CHECK(!stuck_range_touch.begin(stuck_range_touch_wire));
    CHECK(!stuck_range_touch.verified());
    CHECK(stuck_range_touch_wire.ranges == 1);
    CHECK(stuck_range_touch_wire.extras == 0);
    CHECK(!stuck_range_touch_wire.unsafe_parallel_mux);
    // A multiplexer can ACK a write but return the wrong control byte.
    // Do not trust ID/status reads from an unverified selected branch.
    TwoWire bad_range_readback;
    bad_range_readback.range_mux_bad_readback = true;
    desk_robot::ExpansionTouch bad_range_touch;
    CHECK(!bad_range_touch.begin(bad_range_readback));
    CHECK(!bad_range_touch.verified());
    CHECK(bad_range_readback.extras == 0);
    TwoWire stuck_extra_touch_wire;
    stuck_extra_touch_wire.optional_mux_stuck = true;
    desk_robot::ExpansionTouch stuck_extra_touch;
    CHECK(!stuck_extra_touch.begin(stuck_extra_touch_wire));
    CHECK(!stuck_extra_touch.verified());
    CHECK(stuck_extra_touch_wire.extras == 0);
    // A failed CAP1188 register-address write must still terminate the
    // attempted I2C transaction, without accepting a cached touch sample.
    TwoWire cap_failed_write_wire;
    desk_robot::ExpansionTouch cap_failed_write;
    CHECK(cap_failed_write.begin(cap_failed_write_wire));
    const auto before_cap_ends = cap_failed_write_wire.cap_register_end_calls;
    const auto before_cap_requests = cap_failed_write_wire.cap_register_requests;
    cap_failed_write_wire.fail_cap_register_write = true;
    std::uint8_t failed_zones = 0x5A;
    CHECK(!cap_failed_write.poll(100, failed_zones));
    CHECK(cap_failed_write_wire.cap_register_end_calls == before_cap_ends + 1);
    CHECK(cap_failed_write_wire.cap_failed_write_stops == 1);
    CHECK(cap_failed_write_wire.cap_register_requests == before_cap_requests);
    CHECK(failed_zones == 0x5A);
    CHECK(!cap_failed_write.verified());
    CHECK(cap_failed_write_wire.ranges == 0);
    CHECK(cap_failed_write_wire.extras == 0);
    CHECK(!cap_failed_write_wire.unsafe_parallel_mux);
    // Corrupted high bits in a FIFO pointer must not be silently masked
    // into a plausible fresh touch sample. The 0x71 lane closes on error.
    for (const int reg : {0, 1, 2}) {
      TwoWire bad_pointer_wire;
      desk_robot::PulsePad bad_pointer;
      CHECK(bad_pointer.begin(bad_pointer_wire));
      if (reg == 0) bad_pointer_wire.pulse_fifo_write_pointer = 0x84;
      if (reg == 1) bad_pointer_wire.pulse_fifo_read_pointer = 0x80;
      if (reg == 2) bad_pointer_wire.pulse_fifo_overflow = 0x80;
      CHECK(!bad_pointer.poll(0));
      CHECK(!bad_pointer.sample().valid);
      CHECK(bad_pointer.sample().sample_seq == 0U);
      CHECK(bad_pointer_wire.ranges == 0 && bad_pointer_wire.extras == 0);
    }
    // A delayed WROOM poll must not convert old MAX30102 FIFO backlog
    // into a newly timestamped petting event. Discard >4 pending samples.
    TwoWire stale_pulse_wire;
    stale_pulse_wire.pulse_fifo_write_pointer = 9;
    desk_robot::PulsePad stale_pulse;
    CHECK(stale_pulse.begin(stale_pulse_wire));
    CHECK(!stale_pulse.poll(0));
    CHECK(!stale_pulse.sample().valid);
    CHECK(stale_pulse.sample().sample_seq == 0U);
    CHECK(stale_pulse_wire.pulse_fifo_read_pointer == 9);
    CHECK(stale_pulse_wire.ranges == 0 && stale_pulse_wire.extras == 0);
    // Two fresh samples after the flush can qualify a new interaction.
    stale_pulse_wire.pulse_fifo_write_pointer = 11;
    CHECK(stale_pulse.poll(100));
    CHECK(stale_pulse.sample().valid);
    CHECK(stale_pulse.sample().sample_seq == 1U);
    // The actual FIFO decoder, not just the portable helper, must honor
    // the qualified carrier channel-order compile-time selection.
#if DESK_ROBOT_MAX30102_FIFO_IR_FIRST
    CHECK(stale_pulse.sample().red == 5001U);
    CHECK(stale_pulse.sample().ir == 1001U);
#else
    CHECK(stale_pulse.sample().red == 1001U);
    CHECK(stale_pulse.sample().ir == 5001U);
#endif
    CHECK(stale_pulse_wire.pulse_fifo_read_pointer == 11);
    CHECK(stale_pulse_wire.ranges == 0 && stale_pulse_wire.extras == 0);
    // No new conversion must not increment the source sequence.
    CHECK(!stale_pulse.poll(200));
    CHECK(!stale_pulse.sample().valid); // FIFO empty: no fresh paw event
    CHECK(stale_pulse.sample().sample_seq == 1U);
    // Setup can stall before the first poll, when the FIFO has no timestamps.
    // A short, non-overflowed initial backlog is still old evidence.
    TwoWire startup_pulse_wire;
    desk_robot::PulsePad startup_pulse;
    fake_arduino_millis() = 1000U;
    CHECK(startup_pulse.begin(startup_pulse_wire));
    startup_pulse_wire.pulse_fifo_write_pointer = 2;
    CHECK(!startup_pulse.poll(1500));
    CHECK(!startup_pulse.sample().valid);
    CHECK(startup_pulse.sample().sample_seq == 0U);
    CHECK(startup_pulse_wire.pulse_fifo_read_pointer == 2U);
    CHECK(startup_pulse_wire.ranges == 0 && startup_pulse_wire.extras == 0);
    startup_pulse_wire.pulse_fifo_write_pointer = 3;
    CHECK(startup_pulse.poll(1570));
    CHECK(startup_pulse.sample().valid);
    CHECK(startup_pulse.sample().sample_seq == 1U);
    CHECK(startup_pulse.sample().at_ms == 1570U);
    // Initial acquisition across normal uint32 rollover remains valid.
    TwoWire wrap_pulse_wire;
    desk_robot::PulsePad wrap_pulse;
    fake_arduino_millis() = 0xfffffff0U;
    CHECK(wrap_pulse.begin(wrap_pulse_wire));
    CHECK(wrap_pulse.poll(0x20U));
    CHECK(wrap_pulse.sample().sample_seq == 1U);
    fake_arduino_millis() = 0U;
    // A long delay is ambiguous even with just two queued FIFO records and
    // no overflow. Old paw contact must not gain a new source timestamp.
    TwoWire delayed_pulse_wire;
    desk_robot::PulsePad delayed_pulse;
    CHECK(delayed_pulse.begin(delayed_pulse_wire));
    CHECK(delayed_pulse.poll(0));
    const auto before_gap_seq = delayed_pulse.sample().sample_seq;
    CHECK(before_gap_seq == 1U);
    delayed_pulse_wire.pulse_fifo_write_pointer = 6;
    CHECK(!delayed_pulse.poll(500));
    CHECK(!delayed_pulse.sample().valid);
    CHECK(delayed_pulse.sample().sample_seq == before_gap_seq);
    CHECK(delayed_pulse_wire.pulse_fifo_read_pointer == 6);
    CHECK(delayed_pulse_wire.pulse_fifo_overflow == 0);
    CHECK(delayed_pulse_wire.ranges == 0 && delayed_pulse_wire.extras == 0);
    // A subsequent independently acquired conversion restores raw contact.
    delayed_pulse_wire.pulse_fifo_write_pointer = 7;
    CHECK(delayed_pulse.poll(570));
    CHECK(delayed_pulse.sample().valid);
    CHECK(delayed_pulse.sample().sample_seq == before_gap_seq + 1);
    CHECK(delayed_pulse_wire.pulse_fifo_read_pointer == 7);
    CHECK(delayed_pulse_wire.ranges == 0 && delayed_pulse_wire.extras == 0);
    // A completely full MAX30102 FIFO can have matching write/read
    // pointers. Its independent overflow counter must still block old
    // optical evidence and recover only after a genuinely new conversion.
    TwoWire overflow_pulse_wire;
    desk_robot::PulsePad overflow_pulse;
    CHECK(overflow_pulse.begin(overflow_pulse_wire));
    overflow_pulse_wire.pulse_fifo_write_pointer = 0;
    overflow_pulse_wire.pulse_fifo_overflow = 7;
    CHECK(!overflow_pulse.poll(0));
    CHECK(!overflow_pulse.sample().valid);
    CHECK(overflow_pulse.sample().sample_seq == 0U);
    CHECK(overflow_pulse_wire.pulse_fifo_read_pointer == 0);
    CHECK(overflow_pulse_wire.pulse_fifo_overflow == 0);
    overflow_pulse_wire.pulse_fifo_write_pointer = 2;
    CHECK(overflow_pulse.poll(100));
    CHECK(overflow_pulse.sample().valid);
    CHECK(overflow_pulse.sample().sample_seq == 1U);
    CHECK(overflow_pulse_wire.pulse_fifo_read_pointer == 2);
    CHECK(overflow_pulse_wire.ranges == 0 && overflow_pulse_wire.extras == 0);
    // A failed FIFO read may have already consumed one record in silicon.
    // Remaining pre-failure frames have unknown capture time and must not
    // be reissued later as a freshly touched paw.
    TwoWire interrupted_fifo_wire;
    desk_robot::PulsePad interrupted_fifo;
    CHECK(interrupted_fifo.begin(interrupted_fifo_wire));
    CHECK(interrupted_fifo.poll(0));
    const auto observed_seq = interrupted_fifo.sample().sample_seq;
    CHECK(observed_seq == 1U);
    interrupted_fifo_wire.pulse_fifo_write_pointer = 7;
    interrupted_fifo_wire.fail_pulse_fifo_read_once = true;
    CHECK(!interrupted_fifo.poll(100));
    CHECK(!interrupted_fifo.sample().valid);
    CHECK(interrupted_fifo.sample().sample_seq == observed_seq);
    CHECK(interrupted_fifo_wire.pulse_fifo_read_pointer == 5U);
    CHECK(interrupted_fifo_wire.ranges == 0 &&
          interrupted_fifo_wire.extras == 0);
    CHECK(!interrupted_fifo.poll(200)); // discard two ambiguous old records
    CHECK(!interrupted_fifo.sample().valid);
    CHECK(interrupted_fifo.sample().sample_seq == observed_seq);
    CHECK(interrupted_fifo_wire.pulse_fifo_read_pointer == 7U);
    interrupted_fifo_wire.pulse_fifo_write_pointer = 8;
    CHECK(interrupted_fifo.poll(300)); // only a subsequent conversion counts
    CHECK(interrupted_fifo.sample().valid);
    CHECK(interrupted_fifo.sample().sample_seq == observed_seq + 1U);
    CHECK(interrupted_fifo_wire.ranges == 0 &&
          interrupted_fifo_wire.extras == 0);
    // A rejected MAX30102 register write/read must still finish the Wire
    // transaction and must invalidate an old optical sample.
    TwoWire pulse_write_fault_wire;
    desk_robot::PulsePad pulse_write_fault;
    CHECK(pulse_write_fault.begin(pulse_write_fault_wire));
    CHECK(pulse_write_fault.poll(0));
    CHECK(pulse_write_fault.sample().valid);
    const auto pulse_end_before =
        pulse_write_fault_wire.pulse_terminated_transmissions;
    pulse_write_fault_wire.fail_pulse_register_write = true;
    CHECK(!pulse_write_fault.poll(100));
    CHECK(!pulse_write_fault.sample().valid);
    CHECK(pulse_write_fault_wire.failed_pulse_writes > 0);
    CHECK(pulse_write_fault_wire.pulse_terminated_transmissions -
          pulse_end_before >= pulse_write_fault_wire.failed_pulse_writes);
    CHECK(pulse_write_fault_wire.ranges == 0 &&
          pulse_write_fault_wire.extras == 0);
    // MAX30102 shares the same optional lane. It must enforce the same
    // verified 0x70 quiescence and 0x71 isolation as CAP1188.
    TwoWire stuck_range_pulse_wire;
    stuck_range_pulse_wire.ranges = 1;
    stuck_range_pulse_wire.range_mux_stuck = true;
    desk_robot::PulsePad stuck_range_pulse;
    CHECK(!stuck_range_pulse.begin(stuck_range_pulse_wire));
    CHECK(stuck_range_pulse_wire.extras == 0);
    CHECK(!stuck_range_pulse_wire.unsafe_parallel_mux);
    TwoWire bad_range_pulse_wire;
    bad_range_pulse_wire.range_mux_bad_readback = true;
    desk_robot::PulsePad bad_range_pulse;
    CHECK(!bad_range_pulse.begin(bad_range_pulse_wire));
    CHECK(bad_range_pulse_wire.extras == 0);
    TwoWire stuck_extra_pulse_wire;
    stuck_extra_pulse_wire.optional_mux_stuck = true;
    desk_robot::PulsePad stuck_extra_pulse;
    CHECK(!stuck_extra_pulse.begin(stuck_extra_pulse_wire));
    CHECK(stuck_extra_pulse_wire.extras == 0);
    TwoWire late_bad_mux_pulse_wire;
    desk_robot::PulsePad late_bad_mux_pulse;
    CHECK(late_bad_mux_pulse.begin(late_bad_mux_pulse_wire));
    CHECK(late_bad_mux_pulse.poll(0));
    CHECK(late_bad_mux_pulse.sample().valid);
    late_bad_mux_pulse_wire.range_mux_bad_readback = true;
    CHECK(!late_bad_mux_pulse.poll(100));
    CHECK(!late_bad_mux_pulse.sample().valid);
    CHECK(late_bad_mux_pulse_wire.extras == 0);
    std::uint8_t bits = 0;
    for (std::uint32_t now_ms = 0; now_ms < 1600; now_ms += 12) {
      accessories.poll(now_ms);
      pulse.poll(now_ms);
      touch.poll(now_ms, bits);
      CHECK(Wire.ranges == 0 && Wire.extras == 0);
      CHECK(!Wire.unsafe_parallel_mux);
    }
    // Rejected I2C register writes must still finish the attempted Wire
    // transaction. Otherwise an incomplete MCP23017 GPIOA read may leave
    // the bus active and a stale charger seat status falsely usable.
    TwoWire rejected_mcp_wire;
    desk_robot::AccessorySensors rejected_mcp;
    CHECK(rejected_mcp.begin(rejected_mcp_wire));
    for (std::uint32_t ms = 0; ms < 720; ms += 12)
      rejected_mcp.poll(ms);
    CHECK(rejected_mcp.readings().dock.valid);
    const auto old_seq = rejected_mcp.readings().dock.sample_seq;
    const auto old_mcp_ends = rejected_mcp_wire.mcp_terminated_transmissions;
    rejected_mcp_wire.fail_mcp_register_write = true;
    for (std::uint32_t ms = 720; ms < 1600; ms += 12)
      rejected_mcp.poll(ms);
    CHECK(rejected_mcp_wire.failed_mcp_writes > 0);
    CHECK(rejected_mcp_wire.mcp_terminated_transmissions - old_mcp_ends >=
          rejected_mcp_wire.failed_mcp_writes);
    CHECK(!rejected_mcp.readings().dock.valid);
    CHECK(rejected_mcp.readings().dock.sample_seq == old_seq);
    CHECK(rejected_mcp_wire.ranges == 0 && rejected_mcp_wire.extras == 0);
    rejected_mcp_wire.fail_mcp_register_write = false;
    for (std::uint32_t ms = 1608; ms < 2200; ms += 12)
      rejected_mcp.poll(ms);
    CHECK(rejected_mcp.readings().dock.valid);
    CHECK(rejected_mcp.readings().dock.sample_seq > old_seq);
        // A busy ADS1115 must not turn a cached old register into new jaw data.
    const auto prior_jaw_seq = accessories.readings().force.jaw_sample_seq;
    const auto prior_jaw_at_ms = accessories.readings().force.jaw_at_ms;
    CHECK(prior_jaw_seq > 0U);
    CHECK(prior_jaw_at_ms > 0U); // genuinely completed channel 1 conversion
    Wire.ads_conversion_ready = false;
    for (std::uint32_t ms = 1608; ms < 3200; ms += 12)
      accessories.poll(ms);
    CHECK(accessories.readings().force.jaw_sample_seq == prior_jaw_seq);
    CHECK(accessories.readings().force.jaw_at_ms == prior_jaw_at_ms);
    CHECK(!accessories.readings().force.valid);
    Wire.ads_conversion_ready = true;
    for (std::uint32_t ms = 3204; ms < 4700; ms += 12)
      accessories.poll(ms);
    CHECK(accessories.readings().force.valid);
    CHECK(accessories.readings().force.jaw_sample_seq > prior_jaw_seq);
    CHECK(accessories.readings().force.jaw_at_ms > prior_jaw_at_ms);
    CHECK(bits == 0xA5);
    CHECK(pulse.sample().present);
    // The FIFO has been drained by the repeated polls above. The last
    // optical bytes remain diagnostic history, NOT new live paw contact.
    CHECK(!pulse.sample().valid);
#if DESK_ROBOT_MAX30102_FIFO_IR_FIRST
    CHECK(pulse.sample().red == 5003U);
    CHECK(pulse.sample().ir == 1003U);
#else
    CHECK(pulse.sample().red == 1003U);
    CHECK(pulse.sample().ir == 5003U);
#endif
    CHECK(pulse.sample().sample_seq > 0U);
    const auto& read = accessories.readings();
    for (unsigned i = 0; i < 3; ++i) {
      CHECK(read.angle[i].present);
      CHECK(read.angle[i].valid);
      CHECK(read.angle[i].angle == 2000);
      CHECK(read.angle[i].magnet_status == 0x20);
      CHECK(read.angle[i].sample_seq > 0U);
    }
    CHECK(read.proximity.present && read.proximity.valid);
    CHECK(read.proximity.raw == 42);
    CHECK(read.climate.present && read.climate.valid);
    CHECK(read.climate.temp_centi > 0);
    CHECK(read.climate.humidity_centi > 0);
    CHECK(read.climate.sample_seq > 0U); // only CRC-valid conversions count
    CHECK(read.force.present && read.force.valid && read.force.valid_mask == 3);
    CHECK(read.force.adc[0] == 1024);
    CHECK(read.force.adc[1] == -292);
    // A completed ADS1115 single shot is not new force evidence after a
    // stalled WROOM safety loop. In this scan order, lane 2 starts jaw
    // conversion at 516ms; the next visit after a pause is too late to
    // safely associate that old ADC register with the new receipt time.
    TwoWire stalled_ads_wire;
    desk_robot::AccessorySensors stalled_ads;
    CHECK(stalled_ads.begin(stalled_ads_wire));
    for (std::uint32_t ms = 0; ms <= 516; ms += 12)
      stalled_ads.poll(ms);
    CHECK(stalled_ads_wire.ads_config_high == 0xD3U);
    const auto jaw_seq_before_pause =
        stalled_ads.readings().force.jaw_sample_seq;
    const auto jaw_stamp_before_pause =
        stalled_ads.readings().force.jaw_at_ms;
    CHECK(jaw_seq_before_pause > 0U);
    CHECK(stalled_ads.readings().force.valid_mask == 3U);
    // During the gap the physical single-shot conversion finished long
    // ago; OS=1 is not a fresh acquisition after this scheduling stall.
    for (std::uint32_t ms = 1716; ms <= 1788; ms += 12)
      stalled_ads.poll(ms);
    CHECK(stalled_ads.readings().force.jaw_sample_seq ==
          jaw_seq_before_pause);
    CHECK(stalled_ads.readings().force.jaw_at_ms ==
          jaw_stamp_before_pause);
    CHECK((stalled_ads.readings().force.valid_mask & 2U) == 0U);
    CHECK(!stalled_ads.readings().force.valid);
    // Explicitly start another ADC single shot and wait for completion.
    // Old data may become valid ONLY after that later actual conversion.
    for (std::uint32_t ms = 1800; ms <= 1968; ms += 12)
      stalled_ads.poll(ms);
    CHECK(stalled_ads.readings().force.jaw_sample_seq >
          jaw_seq_before_pause);
    CHECK(stalled_ads.readings().force.jaw_at_ms >
          jaw_stamp_before_pause);
    CHECK((stalled_ads.readings().force.valid_mask & 2U) != 0U);
    CHECK(stalled_ads.readings().force.valid);
    // Like the ADS1115 above, an unread SHT41 single-shot result is not a
    // fresh climate observation after a long WROOM scheduling stall. Lane 3
    // starts a conversion at 696 ms; the next lane-3 visit after the gap must
    // discard that old result without advancing its acquisition identity.
    TwoWire stalled_sht_wire;
    desk_robot::AccessorySensors stalled_sht;
    CHECK(stalled_sht.begin(stalled_sht_wire));
    for (std::uint32_t ms = 0; ms <= 696; ms += 12)
      stalled_sht.poll(ms);
    const auto climate_seq_before_pause =
        stalled_sht.readings().climate.sample_seq;
    const auto climate_stamp_before_pause =
        stalled_sht.readings().climate.at_ms;
    CHECK(climate_seq_before_pause > 0U);
    CHECK(climate_stamp_before_pause > 0U);
    CHECK(stalled_sht.readings().climate.valid);
    for (std::uint32_t ms = 1692; ms <= 1764; ms += 12)
      stalled_sht.poll(ms);
    CHECK(stalled_sht.readings().climate.sample_seq ==
          climate_seq_before_pause);
    CHECK(stalled_sht.readings().climate.at_ms ==
          climate_stamp_before_pause);
    CHECK(!stalled_sht.readings().climate.valid);
    // A later lane-3 visit issues a new single-shot command; only its later
    // CRC-valid result may restore freshness and advance the sequence.
    for (std::uint32_t ms = 1776; ms <= 1932; ms += 12)
      stalled_sht.poll(ms);
    CHECK(stalled_sht.readings().climate.valid);
    CHECK(stalled_sht.readings().climate.sample_seq >
          climate_seq_before_pause);
    CHECK(stalled_sht.readings().climate.at_ms >
          climate_stamp_before_pause);
    // Retire a pending SHT41 conversion on a shared mux fault, even
    // when recovery occurs before the normal 200 ms age deadline.
    TwoWire climate_fault_wire;
    desk_robot::AccessorySensors climate_fault;
    CHECK(climate_fault.begin(climate_fault_wire));
    for (std::uint32_t ms = 0; ms <= 696; ms += 12)
      climate_fault.poll(ms);
    const auto pre_fault_climate = climate_fault.readings().climate;
    CHECK(pre_fault_climate.valid && pre_fault_climate.sample_seq > 0U);
    climate_fault_wire.optional_mux_stuck = true;
    climate_fault_wire.extras = 0;
    climate_fault.poll(708);
    CHECK(!climate_fault.readings().climate.valid);
    climate_fault_wire.optional_mux_stuck = false;
    // Lane 3 at 780 must start a new conversion, not read the one
    // launched at 696, before the mux fault.
    for (std::uint32_t ms = 720; ms <= 780; ms += 12)
      climate_fault.poll(ms);
    CHECK(!climate_fault.readings().climate.valid);
    CHECK(climate_fault.readings().climate.sample_seq ==
          pre_fault_climate.sample_seq);
    CHECK(climate_fault.readings().climate.at_ms ==
          pre_fault_climate.at_ms);
    for (std::uint32_t ms = 792; ms <= 864; ms += 12)
      climate_fault.poll(ms);
    CHECK(climate_fault.readings().climate.valid);
    CHECK(climate_fault.readings().climate.sample_seq ==
          pre_fault_climate.sample_seq + 1U);
    CHECK(climate_fault.readings().climate.at_ms == 864U);
    CHECK(!climate_fault_wire.unsafe_parallel_mux);
    CHECK(climate_fault_wire.ranges == 0 && climate_fault_wire.extras == 0);
    // A shared mux failure invalidates BOTH ADS1115 channels, not only
    // the aggregate flag. One recovered conversion cannot reuse the old pair.
    TwoWire force_fault_wire;
    desk_robot::AccessorySensors force_fault;
    CHECK(force_fault.begin(force_fault_wire));
    for (std::uint32_t ms = 0; ms < 2400; ms += 12)
      force_fault.poll(ms);
    CHECK(force_fault.readings().force.valid_mask == 3U);
    force_fault_wire.optional_mux_stuck = true;
    force_fault_wire.extras = 0;
    force_fault.poll(2400);
    CHECK(!force_fault.readings().force.valid);
    CHECK(force_fault.readings().force.valid_mask == 0U);
    force_fault_wire.optional_mux_stuck = false;
    bool saw_partial = false;
    for (std::uint32_t ms = 2412; ms < 4000; ms += 12) {
      force_fault.poll(ms);
      const auto& recovered = force_fault.readings().force;
      if (recovered.valid_mask == 1U || recovered.valid_mask == 2U) {
        CHECK(!recovered.valid);
        saw_partial = true;
        break;
      }
    }
    CHECK(saw_partial);
    // A failed ADS1115 conversion-config write must retire the previous
    // complete force pair even though both I2C mux controls still work.
    TwoWire config_fault_wire;
    desk_robot::AccessorySensors config_fault;
    CHECK(config_fault.begin(config_fault_wire));
    for (std::uint32_t ms = 0; ms < 2400; ms += 12)
      config_fault.poll(ms);
    CHECK(config_fault.readings().force.valid);
    CHECK(config_fault.readings().force.valid_mask == 3U);
    config_fault_wire.fail_ads_config_write = true;
    std::uint32_t resume_ms = 0;
    bool saw_write_failure = false;
    for (std::uint32_t ms = 2400; ms < 3600; ms += 12) {
      const auto prior_seq = config_fault.readings().force.jaw_sample_seq;
      config_fault.poll(ms);
      if (config_fault_wire.rejected_ads_config_writes == 0U) continue;
      CHECK(!config_fault.readings().force.valid);
      CHECK(config_fault.readings().force.valid_mask == 0U);
      CHECK(config_fault.readings().force.jaw_sample_seq == prior_seq);
      CHECK(!config_fault_wire.unsafe_parallel_mux);
      saw_write_failure = true;
      resume_ms = ms + 12;
      break;
    }
    CHECK(saw_write_failure);
    config_fault_wire.fail_ads_config_write = false;
    bool reacquired_one = false, reacquired_pair = false;
    for (std::uint32_t ms = resume_ms; ms < resume_ms + 2400; ms += 12) {
      config_fault.poll(ms);
      const auto& force = config_fault.readings().force;
      if (force.valid_mask == 1U || force.valid_mask == 2U) {
        CHECK(!force.valid);
        reacquired_one = true;
      }
      if (force.valid_mask == 3U) {
        CHECK(reacquired_one);
        CHECK(force.valid);
        reacquired_pair = true;
        break;
      }
    }
    CHECK(reacquired_one && reacquired_pair);
    CHECK(config_fault_wire.ranges == 0 && config_fault_wire.extras == 0);
    CHECK(read.gauge.fuel_present && read.gauge.fuel_valid);
    CHECK(read.gauge.cell_mv == 3600);
    CHECK(read.gauge.soc_centi == 5000);
    CHECK(read.gauge.monitor_present && read.gauge.monitor_valid);
    CHECK(read.gauge.bus_mv == 5120);
    CHECK(read.gauge.shunt_uv == 40);
    CHECK(read.gauge.monitor_sample_seq > 0U);
    CHECK(read.gauge.fuel_sample_seq > 0U);
    CHECK(read.gauge.fuel_at_ms <= read.gauge.at_ms);
    CHECK(read.gauge.monitor_at_ms <= read.gauge.at_ms);
#if defined(DESK_ROBOT_PACK_SHUNT_MOHM) && DESK_ROBOT_PACK_SHUNT_MOHM == 5
    CHECK(read.gauge.pack_current_valid);
    CHECK(read.gauge.pack_current_ma == 8); // 40uV / 5mOhm = +8mA
#else
    CHECK(!read.gauge.pack_current_valid);
    CHECK(read.gauge.pack_current_ma == 0);
#endif
    CHECK(read.dock.present && read.dock.valid);
    CHECK(read.dock.sample_seq == Wire.dock_gpio_reads);
    CHECK(read.dock.sample_seq >= 2);
    const auto sampled = read.dock.sample_seq;
    Wire.fail_dock_gpio = true;
    for (std::uint32_t ms = 1608; ms < 2000; ms += 12) {
      accessories.poll(ms);
      CHECK(!Wire.unsafe_parallel_mux);
    }
    CHECK(!read.dock.valid);
    CHECK(read.dock.sample_seq == sampled);
    Wire.fail_dock_gpio = false;
    for (std::uint32_t ms = 2004; ms < 2420; ms += 12) {
      accessories.poll(ms);
      CHECK(!Wire.unsafe_parallel_mux);
    }
    CHECK(read.dock.valid);
    CHECK(read.dock.sample_seq > sampled);
    CHECK(read.dock.sample_seq == Wire.dock_gpio_reads);
    // Genuine framed PN532 state transitions share the OPTIONAL mux slot.
    // The MCU still updates MCP23017 seat evidence before each NFC action.
    TwoWire nfc_wire;
    nfc_wire.nfc_connected = true;
    nfc_wire.nfc_tag_present = true;
    desk_robot::AccessorySensors nfc_accessories;
    CHECK(nfc_accessories.begin(nfc_wire));
    for (std::uint32_t ms = 0; ms < 2600; ms += 12) {
      nfc_accessories.poll(ms);
      CHECK(!nfc_wire.unsafe_parallel_mux);
      CHECK(nfc_wire.ranges == 0 && nfc_wire.extras == 0);
    }
    const auto& nfc = nfc_accessories.readings().nfc;
    CHECK(nfc.present && nfc.valid && nfc.tag_visible);
    CHECK(nfc.tag_events == 1U && nfc.tag_token != 0U);
    CHECK(nfc.scan_seq > 1U);
    CHECK(nfc_wire.dock_gpio_reads > 0);
    nfc_wire.nfc_tag_present = false;
    for (std::uint32_t ms = 2604; ms < 4200; ms += 12) {
      nfc_accessories.poll(ms);
      CHECK(!nfc_wire.unsafe_parallel_mux);
    }
    CHECK(nfc.valid && !nfc.tag_visible && nfc.tag_events == 1U);
    nfc_wire.nfc_tag_present = true;
    for (std::uint32_t ms = 4200; ms < 6100; ms += 12) {
      nfc_accessories.poll(ms);
      CHECK(!nfc_wire.unsafe_parallel_mux);
    }
    CHECK(nfc.valid && nfc.tag_visible && nfc.tag_events == 2U);
    CHECK(nfc_wire.dock_gpio_reads > 0);
    const unsigned previous_scans = nfc_wire.nfc_scans;
    nfc_wire.fail_dock_gpio = true;
    for (std::uint32_t ms = 6108; ms < 6800; ms += 12) {
      nfc_accessories.poll(ms);
      CHECK(!nfc_wire.unsafe_parallel_mux);
    }
    CHECK(!nfc_accessories.readings().dock.valid);
    CHECK(!nfc_accessories.readings().nfc.valid);
    CHECK(nfc_wire.nfc_scans == previous_scans);
    // Script one *actual PN532 ScanAck* corruption through the production
    // AccessorySensors poller, not just the portable NfcRaw state helper.
    // The UID stays continuously present on the fake antenna.
    TwoWire recovery_wire;
    recovery_wire.nfc_connected = true;
    recovery_wire.nfc_tag_present = true;
    desk_robot::AccessorySensors recovery;
    CHECK(recovery.begin(recovery_wire));
    for (std::uint32_t ms = 0; ms < 2600; ms += 12)
      recovery.poll(ms);
    const auto initial = recovery.readings().nfc;
    CHECK(initial.valid && initial.tag_visible && initial.tag_events == 1U);
    recovery_wire.nfc_corrupt_scan_ack_once = true;
    bool saw_bad_ack = false;
    for (std::uint32_t ms = 2604; ms < 5500; ms += 12) {
      recovery.poll(ms);
      const auto& current = recovery.readings().nfc;
      if (recovery_wire.nfc_corrupt_scan_acks == 1 && !saw_bad_ack) {
        CHECK(!current.valid && !current.present);
        CHECK(current.tag_visible && current.tag_token == initial.tag_token);
        CHECK(current.tag_events == initial.tag_events);
        CHECK(current.scan_seq == initial.scan_seq);
        saw_bad_ack = true;
      }
      CHECK(!recovery_wire.unsafe_parallel_mux);
      CHECK(recovery_wire.ranges == 0 && recovery_wire.extras == 0);
    }
    const auto& recovered = recovery.readings().nfc;
    CHECK(saw_bad_ack && recovery_wire.nfc_corrupt_scan_acks == 1U);
    CHECK(recovered.valid && recovered.tag_visible);
    CHECK(recovered.tag_token == initial.tag_token);
    CHECK(recovered.tag_events == initial.tag_events);
    CHECK(recovered.scan_seq > initial.scan_seq);
    // A complete absent frame is the first permitted edge reset.
    recovery_wire.nfc_tag_present = false;
    for (std::uint32_t ms = 5508; ms < 7400; ms += 12)
      recovery.poll(ms);
    CHECK(recovered.valid && !recovered.tag_visible);
    CHECK(recovered.tag_events == initial.tag_events);
    recovery_wire.nfc_tag_present = true;
    for (std::uint32_t ms = 7404; ms < 9400; ms += 12)
      recovery.poll(ms);
    CHECK(recovered.valid && recovered.tag_visible);
    CHECK(recovered.tag_events == initial.tag_events + 1U);
    CHECK(recovery_wire.ranges == 0 && recovery_wire.extras == 0);
    // A separate GPIOB read can host slow reed/PIR while GPIOA continues
    // owning the compulsory independent dock stop/PGOOD evidence.
    TwoWire optional_wire;
    optional_wire.optional_gpioB = 0x09; // B3 HIGH healthy, reed open, PIR idle
    desk_robot::AccessorySensors optional_accessories;
    CHECK(optional_accessories.begin(optional_wire));
    for (std::uint32_t ms = 0; ms < 2800; ms += 12) {
      optional_accessories.poll(ms);
      CHECK(!optional_wire.unsafe_parallel_mux);
    }
    const auto& slow = optional_accessories.readings().optional_inputs;
    CHECK(slow.present && slow.valid && slow.sample_seq >= 2U);
    CHECK(optional_wire.optional_gpio_reads == slow.sample_seq);
    CHECK(!slow.reed_closed && !slow.pir_active);
    CHECK(!slow.driver_fault_active);  // genuine B3 HIGH
    const auto base = slow.sample_seq;
    optional_wire.optional_gpioB = 0x02; // reed closed LOW, PIR active HIGH
    for (std::uint32_t ms = 2808; ms < 4300; ms += 12) {
      optional_accessories.poll(ms);
    }
    CHECK(slow.valid && slow.reed_closed && slow.pir_active);
    CHECK(slow.driver_fault_active);  // B3 LOW, nFAULT asserted
    CHECK(slow.sample_seq > base);
    optional_wire.optional_gpioB = 0x0A; // same reed/PIR, fault now HIGH
    for (std::uint32_t ms = 4308; ms < 4750; ms += 12)
      optional_accessories.poll(ms);
    CHECK(slow.valid && !slow.driver_fault_active);
    optional_wire.fail_optional_gpio = true;
    const auto last = slow.sample_seq;
    for (std::uint32_t ms = 4764; ms < 5300; ms += 12) {
      optional_accessories.poll(ms);
    }
    CHECK(!slow.valid && slow.sample_seq == last);
    CHECK(optional_accessories.readings().dock.valid);
    CHECK(optional_accessories.readings().dock.sample_seq > 0U);
    // A mux can ACK while leaving its old control register selected.
    // A missing PN532 or jammed optional lane must never preserve a cached
    // MCP dock status as current valid physical evidence.
    TwoWire stuck_wire;
    stuck_wire.nfc_connected = true;
    desk_robot::AccessorySensors stuck_accessories;
    CHECK(stuck_accessories.begin(stuck_wire));
    for (std::uint32_t ms = 0; ms < 600; ms += 12)
      stuck_accessories.poll(ms);
    CHECK(stuck_accessories.readings().dock.valid);
    const auto before_mux_fault = stuck_accessories.readings().dock.sample_seq;
    stuck_wire.optional_mux_stuck = true; // ACK but lane remains at zero
    stuck_wire.extras = 0;
    stuck_accessories.poll(600);
    CHECK(!stuck_accessories.readings().dock.valid);
    CHECK(stuck_accessories.readings().dock.sample_seq == before_mux_fault);
    CHECK(stuck_wire.ranges == 0 && stuck_wire.extras == 0);
    stuck_wire.optional_mux_stuck = false;
    for (std::uint32_t ms = 612; ms < 1100; ms += 12)
      stuck_accessories.poll(ms);
    CHECK(stuck_accessories.readings().dock.valid);
    CHECK(stuck_accessories.readings().dock.sample_seq > before_mux_fault);
    const auto before_range_fault = stuck_accessories.readings().dock.sample_seq;
    stuck_wire.ranges = 1; // 0x70 still selects a critical ToF lane
    stuck_wire.range_mux_stuck = true;
    stuck_accessories.poll(1104);
    CHECK(!stuck_accessories.readings().dock.valid);
    CHECK(stuck_accessories.readings().dock.sample_seq == before_range_fault);
    CHECK(!stuck_wire.unsafe_parallel_mux);
    stuck_wire.ranges = 0;
    stuck_wire.range_mux_stuck = false;
    for (std::uint32_t ms = 1116; ms < 1600; ms += 12)
      stuck_accessories.poll(ms);
    CHECK(stuck_accessories.readings().dock.valid);
    const auto before_failed_write = stuck_wire.transactions;
    stuck_wire.fail_optional_mux_write = true;
    stuck_accessories.poll(1608);
    CHECK(!stuck_accessories.readings().dock.valid);
    // Even if Wire::write rejects a control byte, finish BOTH attempted
    // 0x71 transmissions with STOP; stale GPIOA evidence cannot survive.
    CHECK(stuck_wire.transactions >= before_failed_write + 4);
    // The WROOM must increment MAX17048 identity on successful I2C register
    // acquisition only. Failure and retry never advance stale fuel data.
    TwoWire fuel_wire;
    desk_robot::AccessorySensors fuel_accessories;
    CHECK(fuel_accessories.begin(fuel_wire));
    for (std::uint32_t ms = 0; ms < 2800; ms += 12)
      fuel_accessories.poll(ms);
    const auto& fuel = fuel_accessories.readings().gauge;
    CHECK(fuel.fuel_valid && fuel.fuel_sample_seq > 0U);
    const auto last_good_fuel_seq = fuel.fuel_sample_seq;
    const auto last_good_fuel_at = fuel.fuel_at_ms;
    fuel_wire.fail_fuel_register_read = true;
    for (std::uint32_t ms = 2808; ms < 3700; ms += 12)
      fuel_accessories.poll(ms);
    CHECK(!fuel.fuel_valid);
    CHECK(fuel.fuel_sample_seq == last_good_fuel_seq);
    CHECK(fuel.fuel_at_ms == last_good_fuel_at);
    fuel_wire.fail_fuel_register_read = false;
    for (std::uint32_t ms = 3708; ms < 4650; ms += 12)
      fuel_accessories.poll(ms);
    CHECK(fuel.fuel_valid);
    CHECK(fuel.fuel_sample_seq > last_good_fuel_seq);
    CHECK(fuel.fuel_at_ms > last_good_fuel_at);
    // A completed AS5600 status + angle read, not a cached register, gets
    // its own identity. A broken optional mux must leave old wheel evidence
    // invalid with its former sequence and timestamp intact.
    TwoWire encoder_wire;
    desk_robot::AccessorySensors encoder_accessories;
    CHECK(encoder_accessories.begin(encoder_wire));
    for (std::uint32_t ms = 0; ms < 1008; ms += 12)
      encoder_accessories.poll(ms);
    std::uint32_t old_encoder_seq[3]{};
    std::uint32_t old_encoder_at[3]{};
    for (unsigned i = 0; i < 3; ++i) {
      const auto& a = encoder_accessories.readings().angle[i];
      CHECK(a.present && a.valid && a.sample_seq > 0U);
      old_encoder_seq[i] = a.sample_seq;
      old_encoder_at[i] = a.at_ms;
    }
    encoder_wire.fail_optional_mux_write = true;
    for (std::uint32_t ms = 1008; ms < 1416; ms += 12)
      encoder_accessories.poll(ms);
    for (unsigned i = 0; i < 3; ++i) {
      const auto& a = encoder_accessories.readings().angle[i];
      CHECK(!a.valid);
      CHECK(a.sample_seq == old_encoder_seq[i]);
      CHECK(a.at_ms == old_encoder_at[i]);
    }
    encoder_wire.fail_optional_mux_write = false;
    for (std::uint32_t ms = 1416; ms < 2424; ms += 12)
      encoder_accessories.poll(ms);
    for (unsigned i = 0; i < 3; ++i) {
      const auto& a = encoder_accessories.readings().angle[i];
      CHECK(a.valid && a.sample_seq > old_encoder_seq[i]);
      CHECK(a.at_ms > old_encoder_at[i]);
    }
    CHECK(!encoder_wire.unsafe_parallel_mux);
    CHECK(encoder_wire.ranges == 0 && encoder_wire.extras == 0);
    std::cout << "PASS optional sensor register IO, MCP GPIOB, NFC and isolated mux slots\n";
  } catch (const std::exception& e) {
    std::cerr << "FAIL " << e.what() << '\n';
    return 1;
  }
}
