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
    {
      // A STOP on the range mux can ACK and then expose a held SDA.
      // The accessory client must yield immediately, not spend another
      // timeout on readback or best-effort close before the safety loop.
      TwoWire hung_wire;
      desk_robot::AccessorySensors hung_bus;
      CHECK(hung_bus.begin(hung_wire, [] {
        return digitalRead(21) == HIGH && digitalRead(22) == HIGH;
      }));
      for (unsigned ms = 0; ms <= 48; ms += 12) hung_bus.poll(ms);
      CHECK(hung_bus.readings().dock.valid);
      hung_wire.hold_sda_on_range_disconnect = true;
      const auto before = hung_wire.transactions;
      hung_bus.poll(60);
      CHECK(fake_i2c_lines().sda_stuck);
      CHECK(hung_wire.transactions == before + 1);
      CHECK(!hung_bus.readings().dock.valid);
      CHECK(!hung_bus.readings().gauge.fuel_valid);
      fake_i2c_lines() = FakeI2cLines{};
      hung_bus.poll(72);
      CHECK(hung_wire.transactions > before + 1);
      CHECK(!hung_bus.readings().dock.valid); // no new GPIOA acquisition yet
      CHECK(!hung_wire.unsafe_parallel_mux);
    }
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
    // A transport ACK does not prove the selected optical mode or cadence.
    // A failed readback must leave the optional sensor unpublished and close
    // its mux, even though the MAX30102 identity and mux both responded.
    for (int reg : {0x09, 0x08, 0x0a, 0x0c, 0x0d, 0x02}) {
      for (bool ignored : {false, true}) {
        TwoWire faulty;
        if (reg == 0x02) faulty.pulse_interrupt_enable = 0xff;
        else faulty.pulse_config[reg] = 0xff;
        if (ignored) faulty.ignore_pulse_config_write_reg = reg;
        else faulty.fail_pulse_config_read_reg = reg;
        desk_robot::PulsePad candidate;
        CHECK(!candidate.begin(faulty));
        CHECK(candidate.mux_present());
        CHECK(!candidate.sample().present && !candidate.sample().valid);
        CHECK(!candidate.poll(100));
        CHECK(candidate.sample().sample_seq == 0U);
        CHECK(faulty.ranges == 0 && faulty.extras == 0);
      }
    }
    Wire.cap_input_enable = 0x01;
    CHECK(touch.begin(Wire));
    CHECK(Wire.cap_input_enable == 0xFF);
    CHECK(Wire.ranges == 0 && Wire.extras == 0);
    // Common generic CAP1188 address 0x29 works on isolated 0x71 lane 0,
    // without requiring a special 0x28 resistor-strap carrier.
    TwoWire generic_touch_wire;
    generic_touch_wire.cap_uses_0x29 = true;
    generic_touch_wire.cap_input_enable = 0x0F;
    generic_touch_wire.cap_config = 0xF8; // unrelated bits + disabled filters
    generic_touch_wire.cap_config2 = 0x45; // RF disabled; preserve unrelated bits
    generic_touch_wire.cap_recal_config = 0x7F;
    generic_touch_wire.cap_noise_threshold = 0x03;
    desk_robot::ExpansionTouch generic_touch;
    CHECK(generic_touch.begin(generic_touch_wire));
    CHECK(generic_touch.verified());
    CHECK(generic_touch_wire.cap_input_enable == 0xFF);
    for (bool preferred : {false, true}) {
      TwoWire disabled_input_wire;
      disabled_input_wire.cap_uses_0x29 = preferred;
      disabled_input_wire.cap_input_enable = 0x7F;
      disabled_input_wire.ignore_cap_input_enable_write = true;
      desk_robot::ExpansionTouch disabled_input_touch;
      CHECK(!disabled_input_touch.begin(disabled_input_wire));
      CHECK(!disabled_input_touch.verified());
      CHECK(disabled_input_wire.extras == 0 && disabled_input_wire.ranges == 0);
    }
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
      CHECK(failed_config.present()); // mux ACK survives failed CAP init
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

    // A formerly verified CAP1188 must recover from a real address NACK,
    // without publishing old zones or monopolizing the shared safety bus.
    for (bool preferred : {false, true}) {
      TwoWire recovery_wire;
      recovery_wire.cap_uses_0x29 = preferred;
      desk_robot::ExpansionTouch recovery_cap;
      std::uint8_t recovery_zones = 0;
      CHECK(recovery_cap.begin(recovery_wire));
      CHECK(recovery_cap.poll(100, recovery_zones));
      recovery_wire.cap_connected = false;
      recovery_zones = 0xBC;
      CHECK(!recovery_cap.poll(180, recovery_zones));
      CHECK(!recovery_cap.verified() && recovery_zones == 0xBC);
      const auto transfers = recovery_wire.transactions;
      CHECK(!recovery_cap.poll(200, recovery_zones));
      CHECK(recovery_wire.transactions == transfers);
      recovery_wire.cap_connected = true;
      recovery_wire.cap_config = 0xF8;
      recovery_wire.cap_config2 = 0x45;
      recovery_wire.cap_recal_config = 0x7F;
      recovery_wire.cap_multi_touch_block = 0x80;
      recovery_wire.cap_noise_threshold = 3;
      recovery_wire.cap_input_enable = 0x01;
      for (unsigned step = 0; step < 7; ++step) {
        CHECK(!recovery_cap.poll(430 + step * 250, recovery_zones));
        CHECK(recovery_cap.verified() == (step == 6));
        CHECK(recovery_zones == 0xBC && recovery_wire.extras == 0 &&
              recovery_wire.ranges == 0);
      }
      CHECK(recovery_wire.cap_config == 0xC0 && recovery_wire.cap_config2 == 0x41);
      CHECK(recovery_wire.cap_recal_config == 0x0A &&
            recovery_wire.cap_multi_touch_block == 0);
      CHECK(recovery_wire.cap_noise_threshold == 1);
      CHECK(recovery_wire.cap_input_enable == 0xFF);
      recovery_wire.cap_touch_bits = 0xA5;
      CHECK(recovery_cap.poll(2010, recovery_zones));
      CHECK(recovery_zones == 0xA5 && recovery_wire.extras == 0 &&
            !recovery_wire.unsafe_parallel_mux);
    }
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
    // The hardware FIFO pointers wrap independently of the uint32 clock.
    // Exercise all admissible wrapped counts and verify the newest record,
    // not just that a read succeeded. Both carrier-order builds run this.
    for (unsigned count = 1; count <= 4; ++count) {
      TwoWire ring_wire;
      desk_robot::PulsePad ring;
      CHECK(ring.begin(ring_wire));
      ring_wire.pulse_fifo_read_pointer = 31U;
      ring_wire.pulse_fifo_write_pointer = static_cast<std::uint8_t>(count - 1U);
      CHECK(ring.poll(100));
      CHECK(ring.sample().valid && ring.sample().sample_seq == 1U);
      CHECK(ring.sample().at_ms == 100U);
#if DESK_ROBOT_MAX30102_FIFO_IR_FIRST
      CHECK(ring.sample().red == 5000U + count - 1U);
      CHECK(ring.sample().ir == 1000U + count - 1U);
#else
      CHECK(ring.sample().red == 1000U + count - 1U);
      CHECK(ring.sample().ir == 5000U + count - 1U);
#endif
      CHECK(ring_wire.pulse_fifo_read_pointer == ring_wire.pulse_fifo_write_pointer);
      CHECK(!ring.poll(200));
      CHECK(!ring.sample().valid && ring.sample().sample_seq == 1U);
      CHECK(ring.sample().at_ms == 100U);
      CHECK(ring_wire.ranges == 0 && ring_wire.extras == 0);
      CHECK(!ring_wire.unsafe_parallel_mux);
    }
    // Five wrapped records exceed the bounded fresh-read budget even
    // without an overflow flag. Flush them without publishing a sample.
    TwoWire ring_backlog_wire;
    desk_robot::PulsePad ring_backlog;
    CHECK(ring_backlog.begin(ring_backlog_wire));
    ring_backlog_wire.pulse_fifo_read_pointer = 30U;
    ring_backlog_wire.pulse_fifo_write_pointer = 3U;
    CHECK(!ring_backlog.poll(100));
    CHECK(!ring_backlog.sample().valid && ring_backlog.sample().sample_seq == 0U);
    CHECK(ring_backlog_wire.pulse_fifo_read_pointer == 3U);
    ring_backlog_wire.pulse_fifo_write_pointer = 4U;
    CHECK(ring_backlog.poll(200));
    CHECK(ring_backlog.sample().valid && ring_backlog.sample().sample_seq == 1U);
    CHECK(ring_backlog.sample().at_ms == 200U);
    CHECK(ring_backlog_wire.ranges == 0 && ring_backlog_wire.extras == 0);
    CHECK(!ring_backlog_wire.unsafe_parallel_mux);
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
    // ALC saturation is independent of FIFO overflow.
    TwoWire ambient_pulse_wire;
    desk_robot::PulsePad ambient_pulse;
    CHECK(ambient_pulse.begin(ambient_pulse_wire));
    CHECK(ambient_pulse_wire.pulse_interrupt_enable == 0x20U);
    CHECK(ambient_pulse.poll(0));
    const auto good_optical = ambient_pulse.sample();
    ambient_pulse_wire.pulse_fifo_write_pointer = 6;
    ambient_pulse_wire.pulse_interrupt_status = 0x20U;
    CHECK(!ambient_pulse.poll(100));
    CHECK(!ambient_pulse.sample().valid);
    CHECK(ambient_pulse.sample().sample_seq == good_optical.sample_seq);
    CHECK(ambient_pulse.sample().at_ms == good_optical.at_ms);
    CHECK(ambient_pulse_wire.pulse_fifo_read_pointer == 6U);
    CHECK(ambient_pulse_wire.ranges == 0 && ambient_pulse_wire.extras == 0);
    ambient_pulse_wire.pulse_fifo_write_pointer = 7;
    ambient_pulse_wire.pulse_clip_ir = true;
    CHECK(!ambient_pulse.poll(200));
    CHECK(!ambient_pulse.sample().valid);
    CHECK(ambient_pulse.sample().sample_seq == good_optical.sample_seq);
    CHECK(ambient_pulse.sample().ir == good_optical.ir);
    ambient_pulse_wire.pulse_clip_ir = false;
    ambient_pulse_wire.pulse_fifo_write_pointer = 8;
    ambient_pulse_wire.fail_pulse_status_read = true;
    CHECK(!ambient_pulse.poll(300));
    CHECK(!ambient_pulse.sample().valid);
    CHECK(ambient_pulse.sample().sample_seq == good_optical.sample_seq);
    ambient_pulse_wire.fail_pulse_status_read = false;
    CHECK(!ambient_pulse.poll(400)); // quarantine flush, not fresh contact
    CHECK(ambient_pulse_wire.pulse_fifo_read_pointer == 8U);
    ambient_pulse_wire.pulse_fifo_write_pointer = 9;
    CHECK(ambient_pulse.poll(500));
    CHECK(ambient_pulse.sample().valid);
    CHECK(ambient_pulse.sample().sample_seq == good_optical.sample_seq + 1U);
    CHECK(ambient_pulse.sample().at_ms == 500U);
    CHECK(ambient_pulse_wire.ranges == 0 && ambient_pulse_wire.extras == 0);
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
    CHECK(stuck_extra_pulse.mux_present()); // ACK is not chip readiness
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
    // A transport failure on either ADS1115 read is a shared ADC fault,
    // not an independent channel conversion timeout.
    for (const int reg : {0x00, 0x01}) {
      TwoWire adc_read_fault_wire;
      desk_robot::AccessorySensors adc_read_fault;
      CHECK(adc_read_fault.begin(adc_read_fault_wire));
      for (std::uint32_t ms = 0; ms < 2400; ms += 12)
        adc_read_fault.poll(ms);
      CHECK(adc_read_fault.readings().force.valid_mask == 3U);
      adc_read_fault_wire.fail_ads_read_register = reg;
      std::uint32_t resume = 0;
      bool failed = false;
      for (std::uint32_t ms = 2400; ms < 3600; ms += 12) {
        const auto before = adc_read_fault.readings().force;
        adc_read_fault.poll(ms);
        if (adc_read_fault_wire.rejected_ads_reads == 0U) continue;
        const auto& after = adc_read_fault.readings().force;
        CHECK(!after.valid && after.valid_mask == 0U);
        CHECK(after.belly_sample_seq == before.belly_sample_seq);
        CHECK(after.jaw_sample_seq == before.jaw_sample_seq);
        CHECK(after.belly_at_ms == before.belly_at_ms);
        CHECK(after.jaw_at_ms == before.jaw_at_ms);
        CHECK(adc_read_fault_wire.ranges == 0 && adc_read_fault_wire.extras == 0);
        CHECK(!adc_read_fault_wire.unsafe_parallel_mux);
        failed = true;
        resume = ms + 12;
        break;
      }
      CHECK(failed);
      adc_read_fault_wire.fail_ads_read_register = -1;
      bool partial_pair = false, complete_pair = false;
      for (std::uint32_t ms = resume; ms < resume + 2400; ms += 12) {
        adc_read_fault.poll(ms);
        const auto& after = adc_read_fault.readings().force;
        if (after.valid_mask == 1U || after.valid_mask == 2U) {
          CHECK(!after.valid);
          partial_pair = true;
        }
        if (after.valid_mask == 3U) {
          CHECK(partial_pair && after.valid);
          complete_pair = true;
          break;
        }
      }
      CHECK(partial_pair && complete_pair);
      CHECK(!adc_read_fault_wire.unsafe_parallel_mux);
    }
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
    // A failed startup close cannot erase discovery of the shared mux.
    TwoWire failed_close_wire;
    failed_close_wire.extras = 1;
    failed_close_wire.optional_mux_stuck = true;
    desk_robot::AccessorySensors failed_close;
    CHECK(!failed_close.begin(failed_close_wire));
    CHECK(failed_close.mux_present());
    TwoWire externally_faulted_wire;
    desk_robot::AccessorySensors externally_faulted;
    CHECK(externally_faulted.begin(externally_faulted_wire));
    for (std::uint32_t ms = 0; ms < 600; ms += 12)
      externally_faulted.poll(ms);
    CHECK(externally_faulted.readings().dock.valid);
    const auto dock_seq = externally_faulted.readings().dock.sample_seq;
    const auto transactions = externally_faulted_wire.transactions;
    externally_faulted.invalidate_bus();
    CHECK(!externally_faulted.readings().dock.valid);
    CHECK(externally_faulted.readings().dock.sample_seq == dock_seq);
    CHECK(externally_faulted_wire.transactions == transactions);
    TwoWire external_pulse_wire;
    desk_robot::PulsePad external_pulse;
    CHECK(external_pulse.begin(external_pulse_wire));
    CHECK(external_pulse.poll(0));
    const auto pulse_seq = external_pulse.sample().sample_seq;
    external_pulse.invalidate_bus();
    CHECK(!external_pulse.sample().valid);
    CHECK(external_pulse.sample().sample_seq == pulse_seq);
    CHECK(!external_pulse.poll(100)); // quarantine old FIFO on resumption
    CHECK(external_pulse.sample().sample_seq == pulse_seq);
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
    // ACKing devices with plausible voltage/SOC but the wrong VERSION
    // must not become fuel evidence. INA226 remains independently usable.
    for (const unsigned version : {0x0000U, 0xFFFFU, 0x1000U, 0x0020U}) {
      TwoWire wrong_gauge;
      wrong_gauge.fuel_version = static_cast<std::uint16_t>(version);
      desk_robot::AccessorySensors wrong_accessories;
      CHECK(wrong_accessories.begin(wrong_gauge));
      for (std::uint32_t ms = 0; ms < 1000; ms += 12)
        wrong_accessories.poll(ms);
      const auto& wrong = wrong_accessories.readings().gauge;
      CHECK(!wrong.fuel_present && !wrong.fuel_valid);
      CHECK(wrong.fuel_sample_seq == 0U);
      CHECK(wrong.monitor_present && wrong.monitor_valid);
    }
    for (const unsigned version : {0x0010U, 0x001FU}) {
      TwoWire family_gauge;
      family_gauge.fuel_version = static_cast<std::uint16_t>(version);
      desk_robot::AccessorySensors family_accessories;
      CHECK(family_accessories.begin(family_gauge));
      for (std::uint32_t ms = 0; ms < 1000; ms += 12)
        family_accessories.poll(ms);
      CHECK(family_accessories.readings().gauge.fuel_valid);
    }
    TwoWire failed_identity;
    failed_identity.fail_fuel_version_read = true;
    desk_robot::AccessorySensors failed_identity_accessories;
    CHECK(failed_identity_accessories.begin(failed_identity));
    for (std::uint32_t ms = 0; ms < 1000; ms += 12)
      failed_identity_accessories.poll(ms);
    const auto& unidentified = failed_identity_accessories.readings().gauge;
    CHECK(!unidentified.fuel_present && !unidentified.fuel_valid);
    CHECK(unidentified.fuel_sample_seq == 0U);
    CHECK(unidentified.monitor_valid);
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
    // An uninstalled accessory mux is not a wedged shared bus. All
    // optional drivers report unavailable and stay inert across later
    // loop iterations. Required dock/fuel policy remains separate;
    // tof_mux_tests exercises actual critical ranging without 0x71.
    TwoWire missing_mux_wire;
    missing_mux_wire.optional_mux_installed = false;
    desk_robot::AccessorySensors missing_accessories;
    desk_robot::ExpansionTouch missing_touch;
    desk_robot::PulsePad missing_paw;
    CHECK(!missing_accessories.begin(missing_mux_wire));
    CHECK(!missing_touch.begin(missing_mux_wire));
    CHECK(!missing_paw.begin(missing_mux_wire));
    CHECK(!missing_touch.present() && !missing_touch.verified());
    CHECK(!missing_paw.sample().present && !missing_paw.sample().valid);
    CHECK(!missing_paw.mux_present() && !missing_accessories.mux_present());
    const auto after_missing_probe = missing_mux_wire.transactions;
    std::uint8_t missing_zones = 0x5a;
    for (std::uint32_t ms = 0; ms < 1200; ms += 12) {
      missing_accessories.poll(ms);
      CHECK(!missing_touch.poll(ms, missing_zones));
      CHECK(!missing_paw.poll(ms));
      CHECK(missing_mux_wire.transactions == after_missing_probe);
      CHECK(missing_mux_wire.ranges == 0 && missing_mux_wire.extras == 0);
    }
    CHECK(missing_zones == 0x5a);
    CHECK(!missing_mux_wire.unsafe_parallel_mux);
    CHECK(missing_paw.sample().sample_seq == 0U);
    const auto& missing = missing_accessories.readings();
    CHECK(!missing.proximity.present && !missing.proximity.valid);
    CHECK(missing.proximity.gesture_events == 0U);
    CHECK(!missing.climate.present && !missing.climate.valid);
    CHECK(missing.climate.sample_seq == 0U);
    CHECK(!missing.barometer.present && !missing.barometer.valid);
    CHECK(missing.barometer.sample_seq == 0U);
    CHECK(!missing.force.present && !missing.force.valid);
    CHECK(missing.force.valid_mask == 0U);
    CHECK(missing.force.belly_sample_seq == 0U &&
          missing.force.jaw_sample_seq == 0U);
    CHECK(!missing.gauge.fuel_present && !missing.gauge.fuel_valid);
    CHECK(!missing.gauge.monitor_present && !missing.gauge.monitor_valid);
    CHECK(!missing.gauge.pack_current_valid);
    CHECK(missing.gauge.fuel_sample_seq == 0U &&
          missing.gauge.monitor_sample_seq == 0U);
    CHECK(!missing.dock.present && !missing.dock.valid);
    CHECK(missing.dock.sample_seq == 0U);
    CHECK(!missing.optional_inputs.present && !missing.optional_inputs.valid);
    CHECK(missing.optional_inputs.sample_seq == 0U);
    CHECK(!missing.nfc.present && !missing.nfc.valid);
    CHECK(missing.nfc.scan_seq == 0U && missing.nfc.tag_events == 0U);
    for (const auto& angle : missing.angle) {
      CHECK(!angle.present && !angle.valid);
      CHECK(angle.sample_seq == 0U);
    }
    // A fitted accessory mux with missing individual peripherals must
    // continue sampling the installed devices. The fake's default lane 3
    // has SHT41 but no BMP280; lane 5 has MCP23017 but no PN532.
    TwoWire partial_accessory_wire;
    desk_robot::AccessorySensors partial_accessories;
    CHECK(partial_accessories.begin(partial_accessory_wire));
    for (std::uint32_t ms = 0; ms < 600; ms += 12)
      partial_accessories.poll(ms);
    const auto& partial = partial_accessories.readings();
    CHECK(partial.climate.present && partial.climate.valid);
    CHECK(partial.dock.present && partial.dock.valid);
    const auto climate_before = partial.climate.sample_seq;
    const auto dock_before = partial.dock.sample_seq;
    CHECK(climate_before > 0U && dock_before > 0U);
    for (std::uint32_t ms = 600; ms < 1800; ms += 12) {
      partial_accessories.poll(ms);
      CHECK(!partial.barometer.present && !partial.barometer.valid);
      CHECK(partial.barometer.sample_seq == 0U);
      CHECK(!partial.nfc.present && !partial.nfc.valid);
      CHECK(partial.nfc.scan_seq == 0U && partial.nfc.tag_events == 0U);
      CHECK(!partial_accessory_wire.unsafe_parallel_mux);
      CHECK(partial_accessory_wire.ranges == 0 && partial_accessory_wire.extras == 0);
    }
    CHECK(partial.climate.valid && partial.climate.sample_seq > climate_before);
    CHECK(partial.dock.valid && partial.dock.sample_seq > dock_before);
    CHECK(partial.dock.sample_seq == partial_accessory_wire.dock_gpio_reads);
    CHECK(partial_accessory_wire.nfc_scans == 0U);
    // INA226 saturated signed endpoints (0x7FFF and 0x8000) must invalidate
    // monitor and pack current while preserving previous sequence and timestamp.
    TwoWire shunt_sat_wire;
    desk_robot::AccessorySensors shunt_accessories;
    CHECK(shunt_accessories.begin(shunt_sat_wire));
    for (std::uint32_t ms = 0; ms < 1000; ms += 12)
      shunt_accessories.poll(ms);
    const auto& sat_gauge = shunt_accessories.readings().gauge;
    CHECK(sat_gauge.monitor_valid && sat_gauge.shunt_uv == 40);
#if defined(DESK_ROBOT_PACK_SHUNT_MOHM) && DESK_ROBOT_PACK_SHUNT_MOHM == 5
    CHECK(sat_gauge.pack_current_valid && sat_gauge.pack_current_ma == 8);
#else
    CHECK(!sat_gauge.pack_current_valid && sat_gauge.pack_current_ma == 0);
#endif
    const auto good_mon_seq = sat_gauge.monitor_sample_seq;
    const auto good_mon_at = sat_gauge.monitor_at_ms;
    CHECK(good_mon_seq > 0U && good_mon_at > 0U);
    shunt_sat_wire.ina226_shunt_raw = 0x7FFFU;
    for (std::uint32_t ms = 1008; ms < 1300; ms += 12)
      shunt_accessories.poll(ms);
    CHECK(!sat_gauge.monitor_valid);
    CHECK(!sat_gauge.pack_current_valid);
    CHECK(sat_gauge.monitor_sample_seq == good_mon_seq);
    CHECK(sat_gauge.monitor_at_ms == good_mon_at);
    shunt_sat_wire.ina226_shunt_raw = 0x8000U;
    for (std::uint32_t ms = 1308; ms < 1600; ms += 12)
      shunt_accessories.poll(ms);
    CHECK(!sat_gauge.monitor_valid);
    CHECK(!sat_gauge.pack_current_valid);
    CHECK(sat_gauge.monitor_sample_seq == good_mon_seq);
    CHECK(sat_gauge.monitor_at_ms == good_mon_at);
    shunt_sat_wire.ina226_shunt_raw = 0x0010U;
    for (std::uint32_t ms = 1608; ms < 1900; ms += 12)
      shunt_accessories.poll(ms);
    CHECK(sat_gauge.monitor_valid && sat_gauge.monitor_sample_seq > good_mon_seq);
    CHECK(sat_gauge.monitor_at_ms > good_mon_at);
    // Cached register contents without CVRF must not gain new provenance.
    const auto ready_seq = sat_gauge.monitor_sample_seq;
    const auto ready_at = sat_gauge.monitor_at_ms;
    const auto fuel_seq = sat_gauge.fuel_sample_seq;
    shunt_sat_wire.ina226_conversion_ready = false;
    for (std::uint32_t ms = 1908; ms < 2200; ms += 12)
      shunt_accessories.poll(ms);
    CHECK(!sat_gauge.monitor_valid && !sat_gauge.pack_current_valid);
    CHECK(sat_gauge.monitor_sample_seq == ready_seq);
    CHECK(sat_gauge.monitor_at_ms == ready_at);
    CHECK(sat_gauge.fuel_valid && sat_gauge.fuel_sample_seq > fuel_seq);
    shunt_sat_wire.ina226_conversion_ready = true;
    shunt_sat_wire.ina226_shunt_raw = 0xffc4U; // -60 counts = -150uV
    for (std::uint32_t ms = 2208; ms < 2500; ms += 12)
      shunt_accessories.poll(ms);
    CHECK(sat_gauge.monitor_valid && sat_gauge.monitor_sample_seq > ready_seq);
    CHECK(sat_gauge.shunt_uv == -150);
#if defined(DESK_ROBOT_PACK_SHUNT_MOHM) && DESK_ROBOT_PACK_SHUNT_MOHM == 5
    CHECK(sat_gauge.pack_current_valid && sat_gauge.pack_current_ma == -30);
#else
    CHECK(!sat_gauge.pack_current_valid);
#endif
    // A failure of any INA226 register invalidates current only.
    // Independent MAX17048 conversions must continue to advance.
    for (const int reg : {0x01, 0x02, 0x06}) {
      TwoWire ina_wire;
      desk_robot::AccessorySensors ina_accessories;
      CHECK(ina_accessories.begin(ina_wire));
      for (std::uint32_t ms = 0; ms < 1008; ms += 12)
        ina_accessories.poll(ms);
      const auto before = ina_accessories.readings().gauge;
      CHECK(before.monitor_valid && before.fuel_valid);
      ina_wire.fail_ina_read_register = reg;
      for (std::uint32_t ms = 1008; ms < 1344; ms += 12)
        ina_accessories.poll(ms);
      const auto after = ina_accessories.readings().gauge;
      CHECK(!after.monitor_valid && !after.pack_current_valid);
      CHECK(after.monitor_sample_seq == before.monitor_sample_seq);
      CHECK(after.monitor_at_ms == before.monitor_at_ms);
      CHECK(after.fuel_valid && after.fuel_sample_seq > before.fuel_sample_seq);
      ina_wire.fail_ina_read_register = -1;
      for (std::uint32_t ms = 1344; ms < 1680; ms += 12)
        ina_accessories.poll(ms);
      const auto recovered = ina_accessories.readings().gauge;
      CHECK(recovered.monitor_valid);
      CHECK(recovered.monitor_sample_seq > before.monitor_sample_seq);
      CHECK(recovered.monitor_at_ms > before.monitor_at_ms);
      CHECK(ina_wire.extras == 0 && !ina_wire.unsafe_parallel_mux);
    }

    // A failed SHT41 conversion command must invalidate the preceding
    // accepted sample; unrelated force and battery inputs stay live.
    TwoWire sht_wire;
    desk_robot::AccessorySensors sht_accessories;
    CHECK(sht_accessories.begin(sht_wire));
    for (std::uint32_t ms = 0; ms < 1008; ms += 12)
      sht_accessories.poll(ms);
    CHECK(sht_accessories.readings().climate.valid);
    sht_wire.fail_sht_command = true;
    for (std::uint32_t ms = 1008; ms < 1344; ms += 12)
      sht_accessories.poll(ms);
    const auto failed_climate = sht_accessories.readings().climate;
    CHECK(!failed_climate.valid);
    for (std::uint32_t ms = 1344; ms < 1680; ms += 12)
      sht_accessories.poll(ms);
    const auto& current_climate = sht_accessories.readings().climate;
    CHECK(!current_climate.valid);
    CHECK(current_climate.sample_seq == failed_climate.sample_seq);
    CHECK(current_climate.at_ms == failed_climate.at_ms);
    CHECK(sht_accessories.readings().gauge.fuel_valid);
    CHECK(sht_accessories.readings().force.valid);
    sht_wire.fail_sht_command = false;
    for (std::uint32_t ms = 1680; ms < 2016; ms += 12)
      sht_accessories.poll(ms);
    CHECK(current_climate.valid);
    CHECK(current_climate.sample_seq > failed_climate.sample_seq);
    CHECK(sht_wire.extras == 0 && !sht_wire.unsafe_parallel_mux);
    std::cout << "PASS optional sensor register IO, MCP GPIOB, NFC and isolated mux slots\n";
  } catch (const std::exception& e) {
    std::cerr << "FAIL " << e.what() << '\n';
    return 1;
  }
}
