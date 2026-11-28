#include <cstdint>
#include <iostream>
#include <stdexcept>
#include "Wire.h"
#include "AccessorySensors.h"
#include "PulsePad.h"
#include "ExpansionTouch.h"
#include "../lib/BodyControl/TouchDebounce.h"
#include "../include/MuxWrite.h"
TwoWire Wire;
#define CHECK(x) do { if (!(x)) throw std::runtime_error(#x); } while (false)
struct MuxWriteProbe {
  unsigned begins = 0, writes = 0, ends = 0;
  std::uint8_t address = 0, mask = 0;
  bool stop = false;
  unsigned write_count = 1, status = 0;
  void beginTransmission(std::uint8_t value) { ++begins; address = value; }
  unsigned write(std::uint8_t value) { ++writes; mask = value; return write_count; }
  unsigned endTransmission(bool value) { ++ends; stop = value; return status; }
};
// A fitted 0x71 mux can ACK even when every downstream device is absent.
static void check_empty_accessory_mux() {
  TwoWire wire;
  wire.accessory_devices_connected = false;
  desk_robot::AccessorySensors sensors;
  desk_robot::PulsePad pulse;
  desk_robot::ExpansionTouch touch;
  CHECK(sensors.begin(wire) && sensors.mux_present());
  CHECK(!pulse.begin(wire) && pulse.mux_present());
  CHECK(!touch.begin(wire) && !touch.verified());
  CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
  std::uint8_t zones = 0x5a;
  for (std::uint32_t ms = 0; ms < 1800; ms += 12) {
    const auto before = wire.transactions;
    sensors.poll(ms);
    CHECK(!pulse.poll(ms) && !touch.poll(ms, zones));
    // Only three verified mux operations: no absent-device polling.
    CHECK(wire.transactions - before == 6U);
    CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
    const auto& a = sensors.readings();
    CHECK(!a.proximity.present && !a.proximity.valid && a.proximity.raw == 0U);
    CHECK(!a.proximity.gesture_decoder_available && a.proximity.gesture_events == 0U);
    CHECK(!a.force.present && !a.force.valid && a.force.valid_mask == 0U);
    CHECK(a.force.belly_sample_seq == 0U && a.force.jaw_sample_seq == 0U);
    CHECK(!a.climate.present && !a.climate.valid && a.climate.sample_seq == 0U);
    CHECK(!a.barometer.present && !a.barometer.valid && a.barometer.sample_seq == 0U);
    CHECK(!a.gauge.fuel_present && !a.gauge.fuel_valid && a.gauge.fuel_sample_seq == 0U);
    CHECK(!a.gauge.monitor_present && !a.gauge.monitor_valid);
    CHECK(!a.gauge.pack_current_valid && a.gauge.monitor_sample_seq == 0U);
    // Missing mandatory dock evidence must NOT be manufactured as safe.
    CHECK(!a.dock.present && !a.dock.valid && a.dock.sample_seq == 0U);
    CHECK(!a.dock.left_seated && !a.dock.right_seated);
    CHECK(!a.dock.input_good && !a.dock.charge_indicated);
    CHECK(!a.optional_inputs.present && !a.optional_inputs.valid);
    CHECK(a.optional_inputs.sample_seq == 0U);
    CHECK(!a.nfc.present && !a.nfc.valid && !a.nfc.tag_visible);
    CHECK(a.nfc.scan_seq == 0U && a.nfc.tag_events == 0U);
    for (const auto& angle : a.angle)
      CHECK(!angle.present && !angle.valid && angle.sample_seq == 0U);
    CHECK(!pulse.sample().present && !pulse.sample().valid && pulse.sample().sample_seq == 0U);
    CHECK(zones == 0x5a);
  }
}

// A populated 0x71 mux is not evidence of a populated CAP1188. Reject
// floating-bus bytes and foreign IDs without retrying an unverified chip.
static void check_unverified_cap_keeps_gpio_touch_independent() {
  for (bool preferred : {false, true}) {
    for (unsigned fault = 0; fault < 4; ++fault) {
      TwoWire wire;
      wire.cap_uses_0x29 = preferred;
      wire.cap_connected = fault != 0;
      wire.cap_product_id = fault == 1 ? 0xFF : fault == 2 ? 0x00 : 0x50;
      wire.cap_manufacturer_id = fault == 3 ? 0xFF : 0x5D;
      desk_robot::ExpansionTouch cap;
      CHECK(!cap.begin(wire) && cap.present() && !cap.verified());
      // The Arduino-ESP32 fake counts deferred read attempts, including NACKs.
      const unsigned expected_reads[] = {1U, 1U, 1U, 2U};
      CHECK(wire.cap_register_requests == expected_reads[fault] + (preferred ? 1U : 0U));
      const auto after_probe = wire.transactions;
      std::uint8_t zones = 0x5A;
      desk_robot::TouchDebounce gpio;
      for (std::uint32_t ms = 0; ms <= 2000; ms += 25) {
        cap.invalidate_bus();
        CHECK(!cap.poll(ms, zones) && zones == 0x5A);
        CHECK(wire.transactions == after_probe);
        CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
        const bool edge = gpio.poll(ms >= 75 && ms < 150, ms);
        CHECK(edge == (ms == 125 || ms == 200));
        CHECK(gpio.stable() == (ms >= 125 && ms < 200));
      }
      CHECK(gpio.baseline_ready());
      CHECK(wire.cap_interrupt_clears == 0U);
    }
  }
}

static void check_mux_write_boundary() {
  for (unsigned address = 0x70; address <= 0x71; ++address) {
    for (unsigned mask = 0; mask <= 0xff; ++mask) {
      MuxWriteProbe wire;
      unsigned bits = 0;
      for (unsigned lane = 0; lane < 8; ++lane) bits += (mask >> lane) & 1U;
      const bool allowed = bits <= 1;
      const auto result = desk_robot::write_mux_mask(
          wire, static_cast<std::uint8_t>(address), static_cast<std::uint8_t>(mask));
      CHECK(result.ok() == allowed);
      CHECK(wire.begins == unsigned(allowed));
      CHECK(wire.writes == unsigned(allowed));
      CHECK(wire.ends == unsigned(allowed));
      if (allowed) CHECK(wire.stop && wire.address == address && wire.mask == mask);
    }
    for (unsigned count : {0U, 1U, 2U}) {
      for (unsigned status : {0U, 2U, 4U, 5U}) {
        MuxWriteProbe wire;
        wire.write_count = count;
        wire.status = status;
        const auto result = desk_robot::write_mux_mask(
            wire, static_cast<std::uint8_t>(address), 0x80);
        CHECK(result.wrote == (count == 1));
        CHECK(result.acknowledged == (status == 0));
        CHECK(result.ok() == (count == 1 && status == 0));
        CHECK(wire.begins == 1 && wire.writes == 1 && wire.ends == 1 && wire.stop);
      }
    }
  }
}
static void check_jaw_adc_rail_isolation() {
  for (const auto rail : {0x7fffU, 0x8000U}) {
    TwoWire wire;
    desk_robot::AccessorySensors sensors;
    CHECK(sensors.begin(wire));
    for (std::uint32_t ms = 0; ms <= 516; ms += 12) sensors.poll(ms);
    CHECK(wire.ads_config_high == 0xD3U);
    const auto before = sensors.readings().force;
    CHECK(before.valid && before.valid_mask == 3U);
    wire.ads_jaw_raw = static_cast<std::uint16_t>(rail);
    for (std::uint32_t ms = 528; ms <= 600; ms += 12) sensors.poll(ms);
    const auto clipped = sensors.readings().force;
    CHECK(!clipped.valid && clipped.valid_mask == 1U);
    CHECK(clipped.adc[0] == before.adc[0]);
    CHECK(clipped.belly_sample_seq == before.belly_sample_seq);
    CHECK(clipped.belly_at_ms == before.belly_at_ms);
    CHECK(clipped.adc[1] == before.adc[1]);
    CHECK(clipped.jaw_sample_seq == before.jaw_sample_seq);
    CHECK(clipped.jaw_at_ms == before.jaw_at_ms);
    CHECK(clipped.at_ms == before.at_ms);
    for (std::uint32_t ms = 612; ms <= 768; ms += 12) sensors.poll(ms);
    const auto belly = sensors.readings().force;
    CHECK(!belly.valid && belly.valid_mask == 1U);
    CHECK(belly.belly_sample_seq > before.belly_sample_seq);
    CHECK(belly.belly_at_ms > before.belly_at_ms);
    CHECK(belly.jaw_sample_seq == before.jaw_sample_seq);
    wire.ads_jaw_raw = 0xFEDCU;
    for (std::uint32_t ms = 780; ms <= 936; ms += 12) sensors.poll(ms);
    const auto recovered = sensors.readings().force;
    CHECK(recovered.valid && recovered.valid_mask == 3U);
    CHECK(recovered.jaw_sample_seq > before.jaw_sample_seq);
    CHECK(recovered.jaw_at_ms > before.jaw_at_ms);
    CHECK(recovered.belly_sample_seq == belly.belly_sample_seq);
    CHECK(recovered.belly_at_ms == belly.belly_at_ms);
    CHECK(!wire.unsafe_parallel_mux);
  }
}
static void check_belly_adc_rail_isolation() {
  for (const auto rail : {0x7fffU, 0x8000U}) {
    TwoWire wire;
    desk_robot::AccessorySensors sensors;
    CHECK(sensors.begin(wire));
    for (std::uint32_t ms = 0; ms <= 516; ms += 12) sensors.poll(ms);
    CHECK(wire.ads_config_high == 0xD3U);
    const auto before = sensors.readings().force;
    CHECK(before.valid && before.valid_mask == 3U);
    // Let channel 1 complete cleanly, then drive channel 0 (belly) to saturation.
    for (std::uint32_t ms = 528; ms <= 600; ms += 12) sensors.poll(ms);
    const auto pre_clip = sensors.readings().force;
    CHECK(pre_clip.valid && pre_clip.valid_mask == 3U);
    wire.ads_belly_raw = static_cast<std::uint16_t>(rail);
    for (std::uint32_t ms = 612; ms <= 768; ms += 12) sensors.poll(ms);
    const auto clipped = sensors.readings().force;
    CHECK(!clipped.valid && clipped.valid_mask == 2U);
    CHECK(clipped.adc[0] == pre_clip.adc[0]);
    CHECK(clipped.belly_sample_seq == pre_clip.belly_sample_seq);
    CHECK(clipped.belly_at_ms == pre_clip.belly_at_ms);
    CHECK(clipped.adc[1] == pre_clip.adc[1]);
    CHECK(clipped.jaw_sample_seq == pre_clip.jaw_sample_seq);
    CHECK(clipped.jaw_at_ms == pre_clip.jaw_at_ms);
    CHECK(clipped.at_ms == pre_clip.at_ms);
    for (std::uint32_t ms = 780; ms <= 936; ms += 12) sensors.poll(ms);
    const auto jaw = sensors.readings().force;
    CHECK(!jaw.valid && jaw.valid_mask == 2U);
    CHECK(jaw.jaw_sample_seq > pre_clip.jaw_sample_seq);
    CHECK(jaw.jaw_at_ms > pre_clip.jaw_at_ms);
    CHECK(jaw.belly_sample_seq == pre_clip.belly_sample_seq);
    wire.ads_belly_raw = 0x0400U;
    for (std::uint32_t ms = 948; ms <= 1116; ms += 12) sensors.poll(ms);
    const auto recovered = sensors.readings().force;
    CHECK(recovered.valid && recovered.valid_mask == 3U);
    CHECK(recovered.belly_sample_seq > pre_clip.belly_sample_seq);
    CHECK(recovered.belly_at_ms > pre_clip.belly_at_ms);
    CHECK(recovered.jaw_sample_seq == jaw.jaw_sample_seq);
    CHECK(recovered.jaw_at_ms == jaw.jaw_at_ms);
    CHECK(!wire.unsafe_parallel_mux);
  }
}
static void check_belly_adc_timeout_retires_jaw_evidence() {
  TwoWire wire;
  desk_robot::AccessorySensors sensors;
  CHECK(sensors.begin(wire));
  for (std::uint32_t ms = 0; ms <= 684; ms += 12) sensors.poll(ms);
  const auto before = sensors.readings().force;
  CHECK(before.valid && before.valid_mask == 3U);
  CHECK(wire.ads_config_high == 0xC3U);
  wire.ads_conversion_ready = false;
  for (std::uint32_t ms = 696; ms <= 936; ms += 12) sensors.poll(ms);
  const auto expired = sensors.readings().force;
  CHECK(936U - before.jaw_at_ms < 500U);
  CHECK(!expired.valid && expired.valid_mask == 0U);
  CHECK(expired.jaw_sample_seq == before.jaw_sample_seq);
  CHECK(expired.jaw_at_ms == before.jaw_at_ms);
  wire.ads_conversion_ready = true;
  for (std::uint32_t ms = 948; ms <= 1104; ms += 12) sensors.poll(ms);
  const auto belly = sensors.readings().force;
  CHECK(!belly.valid && belly.valid_mask == 1U);
  CHECK(belly.jaw_sample_seq == before.jaw_sample_seq);
  for (std::uint32_t ms = 1116; ms <= 1272; ms += 12) sensors.poll(ms);
  const auto recovered = sensors.readings().force;
  CHECK(recovered.valid && recovered.valid_mask == 3U);
  CHECK(recovered.jaw_sample_seq > before.jaw_sample_seq);
  CHECK(!wire.unsafe_parallel_mux);
}
static void check_ads_start_provenance() {
  TwoWire wire;
  desk_robot::AccessorySensors sensors;
  CHECK(sensors.begin(wire));
  for (std::uint32_t ms = 0; ms <= 96; ms += 12) sensors.poll(ms);
  CHECK(sensors.readings().force.belly_sample_seq == 1U);
  CHECK(sensors.readings().force.belly_at_ms == 12U);
  // A prior conversion may still be running after a lost acquisition.
  // The ADC ignores a start while busy; do not overwrite its identity.
  wire.ads_conversion_ready = false;
  for (std::uint32_t ms = 108; ms <= 180; ms += 12) sensors.poll(ms);
  CHECK(wire.ads_config_high == 0xC3U);
  CHECK(sensors.readings().force.valid_mask == 0U);
  CHECK(sensors.readings().force.jaw_sample_seq == 0U);
  wire.ads_conversion_ready = true;
  for (std::uint32_t ms = 192; ms <= 264; ms += 12) sensors.poll(ms);
  CHECK(wire.ads_config_high == 0xD3U);
  CHECK(sensors.readings().force.jaw_sample_seq == 0U);
  for (std::uint32_t ms = 276; ms <= 348; ms += 12) sensors.poll(ms);
  CHECK(sensors.readings().force.jaw_sample_seq == 1U);
  CHECK(sensors.readings().force.jaw_at_ms == 264U);
  CHECK(sensors.readings().force.valid_mask == 2U);
  CHECK(!sensors.readings().force.valid);
  for (std::uint32_t ms = 360; ms <= 516; ms += 12) sensors.poll(ms);
  CHECK(sensors.readings().force.valid);
  CHECK(sensors.readings().force.belly_at_ms == 432U);
  for (std::uint32_t ms = 528; ms <= 600; ms += 12) sensors.poll(ms);
  wire.ads_conversion_ready = false;
  for (std::uint32_t ms = 612; ms <= 936; ms += 12) sensors.poll(ms);
  CHECK(sensors.readings().force.valid_mask == 0U);
  CHECK(sensors.readings().force.jaw_sample_seq == 1U);
  wire.ads_conversion_ready = true;
  for (std::uint32_t ms = 948; ms <= 1020; ms += 12) sensors.poll(ms);
  CHECK(sensors.readings().force.jaw_sample_seq == 1U);
  for (std::uint32_t ms = 1032; ms <= 1104; ms += 12) sensors.poll(ms);
  CHECK(sensors.readings().force.jaw_sample_seq == 2U);
  CHECK(sensors.readings().force.jaw_at_ms == 1020U);
  CHECK(sensors.readings().force.valid_mask == 2U);
  CHECK(!wire.unsafe_parallel_mux);
}
// Exercise the actual optional driver entry points after a previously valid
// sample. A short count is not an ACK for a complete physical observation.
static void check_pulse_pointer_budget() {
  for (std::size_t count = 0; count < 3; ++count) {
    TwoWire wire;
    desk_robot::PulsePad pulse;
    fake_arduino_millis() = 0U;
    CHECK(pulse.begin(wire));
    wire.pulse_fifo_write_pointer = 4;
    const auto before = wire.transactions;
    CHECK(pulse.poll(0));
    // Three verified mux write/read pairs plus pointer, status and FIFO reads.
    // Each register read counts its pointer write and requestFrom.
    CHECK(wire.transactions - before == 12U);
    CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
    const auto accepted = pulse.sample();
    wire.pulse_fifo_write_pointer = 5;
    wire.next_short_read_address = 0x57;
    wire.next_short_read_request = 3;
    wire.next_short_read_count = count;
    CHECK(!pulse.poll(60));
    CHECK(wire.next_short_read_address == -1);
    CHECK(!pulse.sample().valid);
    CHECK(pulse.sample().sample_seq == accepted.sample_seq);
    CHECK(pulse.sample().at_ms == accepted.at_ms);
    CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
    CHECK(!pulse.poll(120)); // quarantine flush, not a fresh observation
    CHECK(wire.pulse_fifo_read_pointer == 5U);
    wire.pulse_fifo_write_pointer = 6;
    CHECK(pulse.poll(180));
    CHECK(pulse.sample().sample_seq == accepted.sample_seq + 1U);
    CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
  }
}
static void check_short_pulse_fifo_reads() {
  for (std::size_t count = 0; count < 12; ++count) {
    TwoWire wire;
    desk_robot::PulsePad pulse;
    fake_arduino_millis() = 0U;
    CHECK(pulse.begin(wire));
    CHECK(pulse.poll(0));
    const auto before = pulse.sample();
    wire.pulse_fifo_write_pointer = 6;
    wire.next_short_read_address = 0x57;
    wire.next_short_read_request = 12;
    wire.next_short_read_count = count;
    CHECK(!pulse.poll(100));
    CHECK(wire.next_short_read_address == -1);
    CHECK(!pulse.sample().valid);
    CHECK(pulse.sample().sample_seq == before.sample_seq);
    CHECK(pulse.sample().at_ms == before.at_ms);
    CHECK(pulse.sample().red == before.red && pulse.sample().ir == before.ir);
    CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
    // The next poll only discards the ambiguous FIFO; it cannot publish it.
    wire.pulse_fifo_write_pointer = 7;
    CHECK(!pulse.poll(200));
    CHECK(!pulse.sample().valid && pulse.sample().sample_seq == before.sample_seq);
    CHECK(wire.pulse_fifo_read_pointer == 7U);
    wire.pulse_fifo_write_pointer = 8;
    CHECK(pulse.poll(300));
    CHECK(pulse.sample().valid && pulse.sample().at_ms == 300U);
    CHECK(pulse.sample().sample_seq == before.sample_seq + 1U);
    CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
  }
}
static void check_short_cap_status_reads() {
  for (bool preferred : {false, true}) {
    TwoWire wire;
    wire.cap_uses_0x29 = preferred;
    desk_robot::ExpansionTouch touch;
    CHECK(touch.begin(wire));
    std::uint8_t zones = 0;
    CHECK(touch.poll(100, zones) && zones == 0xA5);
    wire.cap_touch_bits = 0;
    const auto clears = wire.cap_interrupt_clears;
    wire.next_short_read_address = preferred ? 0x29 : 0x28;
    wire.next_short_read_request = 1;
    wire.next_short_read_count = 0;
    CHECK(!touch.poll(180, zones));
    CHECK(wire.next_short_read_address == -1);
    CHECK(!touch.verified() && zones == 0xA5);
    CHECK(wire.cap_interrupt_clears == clears);
    CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
    for (unsigned step = 0; step < 7; ++step) {
      CHECK(!touch.poll(430 + step * 250, zones));
      CHECK(zones == 0xA5);
    }
    CHECK(touch.verified());
    CHECK(touch.poll(2010, zones) && zones == 0U);
    CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
  }
}
static void check_short_climate_reads() {
  for (std::size_t count = 0; count < 6; ++count) {
    TwoWire wire;
    desk_robot::AccessorySensors sensors;
    CHECK(sensors.begin(wire));
    for (std::uint32_t ms = 0; ms < 1008; ms += 12) sensors.poll(ms);
    const auto before = sensors.readings().climate;
    CHECK(before.valid && before.sample_seq != 0U);
    wire.next_short_read_address = 0x44;
    wire.next_short_read_request = 6;
    wire.next_short_read_count = count;
    std::uint32_t ms = 1008;
    for (; ms < 1260 && wire.next_short_read_address != -1; ms += 12)
      sensors.poll(ms);
    CHECK(wire.next_short_read_address == -1);
    const auto failed = sensors.readings().climate;
    CHECK(!failed.valid && failed.sample_seq == before.sample_seq);
    CHECK(failed.at_ms == before.at_ms && failed.temp_centi == before.temp_centi);
    CHECK(failed.humidity_centi == before.humidity_centi);
    CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
    for (const auto limit = ms + 252; ms < limit; ms += 12)
      sensors.poll(ms);
    CHECK(sensors.readings().climate.valid);
    CHECK(sensors.readings().climate.sample_seq > before.sample_seq);
  }
}
static void check_short_power_reads() {
  for (const auto address : {0x36, 0x40}) {
    TwoWire wire;
    desk_robot::AccessorySensors sensors;
    CHECK(sensors.begin(wire));
    // The first poll is lane 1, followed by lane 4 at 36 + 84*n ms.
    // Inject immediately before lane 4 to avoid the other 0x36 angle devices.
    for (std::uint32_t ms = 0; ms < 1044; ms += 12) sensors.poll(ms);
    const auto before = sensors.readings().gauge;
    CHECK(before.fuel_valid && before.monitor_valid);
    wire.next_short_read_address = address;
    wire.next_short_read_request = 2;
    wire.next_short_read_count = 1;
    sensors.poll(1044);
    CHECK(wire.next_short_read_address == -1);
    const auto failed = sensors.readings().gauge;
    if (address == 0x36) {
      CHECK(!failed.fuel_valid && failed.monitor_valid);
      CHECK(failed.fuel_sample_seq == before.fuel_sample_seq);
      CHECK(failed.fuel_at_ms == before.fuel_at_ms);
      CHECK(failed.cell_mv == before.cell_mv && failed.soc_centi == before.soc_centi);
    } else {
      CHECK(failed.fuel_valid && !failed.monitor_valid && !failed.pack_current_valid);
      CHECK(failed.monitor_sample_seq == before.monitor_sample_seq);
      CHECK(failed.monitor_at_ms == before.monitor_at_ms);
      CHECK(failed.bus_mv == before.bus_mv && failed.shunt_uv == before.shunt_uv);
    }
    CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
    for (std::uint32_t ms = 1056; ms <= 1128; ms += 12) sensors.poll(ms);
    CHECK(sensors.readings().gauge.fuel_valid && sensors.readings().gauge.monitor_valid);
    CHECK(sensors.readings().gauge.fuel_sample_seq > before.fuel_sample_seq);
    CHECK(sensors.readings().gauge.monitor_sample_seq > before.monitor_sample_seq);
  }
}
static void check_sht_crc_provenance() {
  // The bus-access callback runs immediately after requestFrom(), before
  // the production poller consumes the six bytes. Corrupt just one CRC.
  static TwoWire* active = nullptr;
  static unsigned crc_index = 0;
  static bool inject = false;
  for (const unsigned index : {2U, 5U}) {
    TwoWire wire;
    active = &wire;
    crc_index = index;
    inject = false;
    desk_robot::AccessorySensors sensors;
    CHECK(sensors.begin(wire, [] {
      // Ambient acquisitions must not silently enable any heater command.
      if (active->extras == 8U && active->current_address == 0x44U &&
          !active->outbound.empty()) {
        CHECK(active->outbound.size() == 1U);
        CHECK(active->outbound[0] == 0xFDU);
      }
      if (inject && active->extras == 8U && !active->pending_sht &&
          active->inbound.size() == 6U && active->pos == 0U) {
        active->inbound[crc_index] ^= 1U;
        inject = false;
      }
      return true;
    }));
    std::uint32_t ms = 0;
    for (; ms < 1000U && !sensors.readings().climate.valid; ms += 12U)
      sensors.poll(ms);
    const auto before = sensors.readings().climate;
    CHECK(before.valid && before.sample_seq != 0U);
    inject = true;
    for (; ms < 2000U && inject; ms += 12U) sensors.poll(ms);
    CHECK(!inject);
    const auto rejected = sensors.readings().climate;
    CHECK(!rejected.valid);
    CHECK(rejected.sample_seq == before.sample_seq);
    CHECK(rejected.at_ms == before.at_ms);
    CHECK(rejected.temp_centi == before.temp_centi);
    CHECK(rejected.humidity_centi == before.humidity_centi);
    for (; ms < 3000U && !sensors.readings().climate.valid; ms += 12U)
      sensors.poll(ms);
    const auto recovered = sensors.readings().climate;
    CHECK(recovered.valid && recovered.sample_seq == before.sample_seq + 1U);
    CHECK(recovered.at_ms > before.at_ms);
    CHECK(!wire.unsafe_parallel_mux);
    active = nullptr;
  }
}

static void check_address_scoped_wire_faults() {
  TwoWire wire;
  wire.next_transfer_nack_address = 0x70;
  CHECK(wire.requestFrom(0x71, 1) == 1);
  CHECK(wire.next_transfer_nack_address == 0x70);
  CHECK(wire.requestFrom(0x70, 1) == 0);
  CHECK(wire.available() == 0 && wire.read() == -1);
  CHECK(wire.next_transfer_nack_address == -1);
  CHECK(wire.requestFrom(0x70, 1) == 1);

  wire.extras = 1;
  wire.cap_main_control = 0x81;
  wire.next_short_write_address = 0x28;
  wire.next_short_write_after = 1;
  wire.beginTransmission(0x28);
  CHECK(wire.write(0x00) == 1);
  CHECK(wire.write(0x80) == 0 && wire.write(0x80) == 0);
  CHECK(wire.endTransmission(true) == 0); // Accepted prefix may still ACK.
  CHECK(wire.cap_main_control == 0x81 && wire.cap_interrupt_clears == 0);
  CHECK(wire.next_short_write_address == -1);
  wire.beginTransmission(0x28);
  CHECK(wire.write(0x00) == 1 && wire.write(0x80) == 1);
  CHECK(wire.endTransmission(true) == 0 && wire.cap_interrupt_clears == 1);
}

// A second disconnect during recovery must restart identity validation;
// neither the missing chip nor a foreign replacement is a release sample.
static void check_cap_interrupted_recovery() {
  for (bool preferred : {false, true}) {
    TwoWire wire;
    wire.cap_uses_0x29 = preferred;
    desk_robot::ExpansionTouch touch;
    CHECK(touch.begin(wire));
    std::uint8_t zones = 0;
    CHECK(touch.poll(100, zones) && zones == 0xA5);
    const auto clears = wire.cap_interrupt_clears;
    auto unavailable = [&](std::uint32_t now) {
      CHECK(!touch.poll(now, zones) && !touch.verified());
      CHECK(zones == 0xA5 && wire.cap_interrupt_clears == clears);
      CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
    };
    wire.cap_connected = false;
    wire.cap_touch_bits = 0;
    for (std::uint32_t now : {180U, 430U, 680U}) {
      unavailable(now);
      const auto transfers = wire.transactions;
      unavailable(now + 249U);
      CHECK(wire.transactions == transfers);
    }
    wire.cap_connected = true;
    unavailable(930);
    unavailable(1180);
    wire.cap_connected = false;
    unavailable(1430);
    wire.cap_connected = true;
    wire.cap_manufacturer_id = 0xFF;
    unavailable(1680);
    wire.cap_manufacturer_id = 0x5D;
    for (unsigned step = 0; step < 6; ++step)
      unavailable(1930 + step * 250);
    CHECK(!touch.poll(3430, zones) && touch.verified() && zones == 0xA5);
    CHECK(wire.cap_interrupt_clears == clears);
    wire.cap_touch_bits = 0xA5;
    CHECK(touch.poll(3510, zones) && zones == 0xA5);
    wire.cap_touch_bits = 0;
    CHECK(touch.poll(3590, zones) && zones == 0);
    CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
  }
}

// A failed CAP1188 interrupt clear or read must not publish a false release.
static void check_cap_transport_faults() {
  for (bool preferred : {false, true}) {
    for (unsigned fault = 0; fault < 6; ++fault) {
      TwoWire wire;
      wire.cap_uses_0x29 = preferred;
      const int address = preferred ? 0x29 : 0x28;
      desk_robot::ExpansionTouch touch;
      CHECK(touch.begin(wire));
      std::uint8_t zones = 0;
      CHECK(touch.poll(100, zones) && zones == 0xA5);
      wire.cap_touch_bits = 0;
      wire.cap_main_control = 0x81;
      const auto clears = wire.cap_interrupt_clears;
      const auto start = fake_arduino_millis();
      switch (fault) {
        case 0:
          wire.next_short_write_address = address;
          wire.next_short_write_after = 1;
          break;
        case 1: wire.next_transfer_nack_address = address; break;
        case 2: wire.next_read_timeout_address = address; break;
        case 3: wire.next_stop_timeout_address = address; break;
        case 4: wire.next_read_nack_address = 0x70; break;  // range mux readback NACK
        case 5: wire.next_read_nack_address = address; break;  // CAP1188 register read NACK
      }
      CHECK(!touch.poll(180, zones));
      CHECK(!touch.verified() && zones == 0xA5);
      CHECK(wire.cap_interrupt_clears == clears);
      CHECK(wire.cap_main_control == 0x81);
      CHECK(wire.next_short_write_address == -1);
      CHECK(wire.next_transfer_nack_address == -1);
      CHECK(wire.next_read_timeout_address == -1);
      CHECK(wire.next_stop_timeout_address == -1);
      CHECK(wire.next_read_nack_address == -1);
      CHECK(fake_arduino_millis() - start ==
            ((fault == 2 || fault == 3) ? wire.timeout_ms : 0U));
      CHECK(!wire.repeated_start_pending);
      CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
      for (unsigned step = 0; step < 7; ++step)
        CHECK(!touch.poll(430 + step * 250, zones) && zones == 0xA5);
      CHECK(touch.verified());
      CHECK(touch.poll(2010, zones) && zones == 0U);
      CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
    }
  }
}

// ACKed uniform register bytes must not become new touch or pulse evidence.
static void check_uniform_sensor_faults() {
  for (bool preferred : {false, true}) {
    for (std::uint8_t fill : {std::uint8_t(0), std::uint8_t(0xff)}) {
      TwoWire wire;
      wire.cap_uses_0x29 = preferred;
      desk_robot::ExpansionTouch touch;
      CHECK(touch.begin(wire));
      std::uint8_t zones = 0;
      CHECK(touch.poll(100, zones) && zones == 0xA5);
      wire.cap_touch_bits = fill;
      CHECK(touch.poll(180, zones) && zones == fill); // real extreme mask
      wire.cap_touch_bits = 0xA5;
      CHECK(touch.poll(260, zones) && zones == 0xA5);
      const auto clears = wire.cap_interrupt_clears;
      wire.cap_touch_bits = wire.cap_main_control = fill;
      wire.cap_product_id = wire.cap_manufacturer_id = fill;
      CHECK(!touch.poll(340, zones) && !touch.verified());
      CHECK(zones == 0xA5 && wire.cap_interrupt_clears == clears);
      CHECK(!touch.poll(590, zones) && !touch.verified());
      wire.cap_product_id = 0x50;
      wire.cap_manufacturer_id = 0x5D;
      for (unsigned step = 0; step < 7; ++step)
        CHECK(!touch.poll(840 + step * 250, zones) && zones == 0xA5);
      CHECK(touch.verified() && touch.poll(2420, zones) && zones == fill);
      CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
    }
  }
  for (int fill : {0, 0xff}) {
    TwoWire wire;
    fake_arduino_millis() = 0;
    desk_robot::PulsePad pulse;
    CHECK(pulse.begin(wire) && pulse.poll(0));
    const auto before = pulse.sample();
    wire.pulse_fifo_write_pointer = 6;
    wire.pulse_fifo_fill = fill;
    CHECK(!pulse.poll(60) && !pulse.sample().valid);
    CHECK(pulse.sample().sample_seq == before.sample_seq);
    CHECK(pulse.sample().at_ms == before.at_ms);
    CHECK(pulse.sample().red == before.red && pulse.sample().ir == before.ir);
    wire.pulse_fifo_fill = -1;
    wire.pulse_fifo_write_pointer = 7;
    CHECK(!pulse.poll(120) && !pulse.sample().valid); // quarantine flush
    wire.pulse_fifo_write_pointer = 8;
    CHECK(pulse.poll(180) && pulse.sample().valid);
    CHECK(pulse.sample().sample_seq == before.sample_seq + 1U);
    CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
  }
}

int main() {
  try {
    check_address_scoped_wire_faults();
    check_cap_transport_faults();
    check_uniform_sensor_faults();
    check_cap_interrupted_recovery();
    check_sht_crc_provenance();
    check_mux_write_boundary();
    check_empty_accessory_mux();
    check_unverified_cap_keeps_gpio_touch_independent();
    check_jaw_adc_rail_isolation();
    check_belly_adc_rail_isolation();
    check_ads_start_provenance();
    check_belly_adc_timeout_retires_jaw_evidence();
    check_pulse_pointer_budget();
    check_short_pulse_fifo_reads();
    check_short_cap_status_reads();
    check_short_climate_reads();
    check_short_power_reads();
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
    // Even an apparently disconnected range mux needs a verified zero.
    // Startup must not report success after silently skipping every lane.
    for (int fault = 0; fault < 4; ++fault) {
      TwoWire isolation_wire;
      isolation_wire.range_mux_write_nack = fault == 0;
      isolation_wire.range_mux_read_nack = fault == 1;
      isolation_wire.range_mux_bad_readback = fault == 2;
      isolation_wire.range_mux_stuck = fault == 3;
      isolation_wire.ranges = fault == 3 ? 1 : 0;
      desk_robot::AccessorySensors isolation;
      CHECK(!isolation.begin(isolation_wire));
      CHECK(isolation.mux_present());
      CHECK(!isolation.readings().dock.present);
      CHECK(!isolation.readings().force.present);
      CHECK(isolation_wire.extras == 0);
      CHECK(!isolation_wire.unsafe_parallel_mux);
      // Removing the fault permits a fresh verified initialization.
      isolation_wire.range_mux_write_nack = false;
      isolation_wire.range_mux_read_nack = false;
      isolation_wire.range_mux_bad_readback = false;
      isolation_wire.range_mux_stuck = false;
      CHECK(isolation.begin(isolation_wire));
      CHECK(isolation_wire.ranges == 0 && isolation_wire.extras == 0);
      CHECK(!isolation_wire.unsafe_parallel_mux);
    }
    {
      // A shared mux NACK must reach the range owner even if both GPIO
      // lines are high and best-effort close succeeds.
      TwoWire mux_wire;
      desk_robot::AccessorySensors mux_bus;
      CHECK(mux_bus.begin(mux_wire));
      mux_wire.range_mux_write_nack = true;
      CHECK(!mux_bus.poll(0));
      CHECK(mux_bus.poll(1)); // skipped slot is not another fault
      CHECK(!mux_bus.poll(12));
      mux_wire.range_mux_write_nack = false;
      CHECK(mux_bus.poll(24));
    }
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
    // Each defined bit must be verified independently. A blanket 0xff
    // readback fault cannot detect a missing bit in a multi-bit mask.
    struct OpticalSetting { int reg; unsigned value; unsigned mask; };
    constexpr OpticalSetting optical_settings[] = {
        {0x09, 0x03, 0xc7}, // dual LED mode, reset, shutdown
        {0x08, 0x00, 0xff}, // averaging, rollover, almost-full
        {0x0a, 0x23, 0x7f}, // ADC range, sample rate, pulse width
        {0x0c, 0x07, 0xff}, // red LED amplitude
        {0x0d, 0x07, 0xff}, // IR LED amplitude
        {0x02, 0x20, 0xe0}, // defined interrupt enable bits
    };
    for (const auto& setting : optical_settings) {
      for (unsigned bit = 1; bit <= 0x80; bit <<= 1) {
        TwoWire readback;
        const auto altered = static_cast<std::uint8_t>(setting.value ^ bit);
        if (setting.reg == 0x02) readback.pulse_interrupt_enable = altered;
        else readback.pulse_config[setting.reg] = altered;
        readback.ignore_pulse_config_write_reg = setting.reg;
        desk_robot::PulsePad candidate;
        const bool expected = (setting.mask & bit) == 0;
        CHECK(candidate.begin(readback) == expected);
        CHECK(candidate.sample().present == expected);
        CHECK(!candidate.sample().valid && candidate.sample().sample_seq == 0U);
        CHECK(readback.ranges == 0 && readback.extras == 0);
        if (!expected) CHECK(!candidate.poll(100));
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
    // PDATA remains readable after consumption; do not renew its evidence
    // without PVALID. Gesture FIFO completion is independently observable.
    {
      TwoWire optical_wire;
      optical_wire.apds_auto_ready = false;
      optical_wire.apds_status = 0x01; // AVALID alone is not PVALID
      desk_robot::AccessorySensors optical;
      CHECK(optical.begin(optical_wire));
      std::uint32_t now = 12;
      const auto poll_cycle = [&]() {
        for (unsigned lane = 0; lane < 7; ++lane, now += 12)
          CHECK(optical.poll(now));
      };
      const auto& prox = optical.readings().proximity;
      poll_cycle();
      CHECK(prox.present && !prox.valid && prox.at_ms == 0U);
      CHECK(optical_wire.apds_pdata_reads == 0U);
      optical_wire.apds_status = 0x02;
      poll_cycle();
      CHECK(prox.valid && prox.raw == 42U && prox.at_ms > 0U);
      CHECK(optical_wire.apds_pdata_reads == 1U);
      CHECK((optical_wire.apds_status & 0x02U) == 0U);
      const auto first_at = prox.at_ms;
      optical_wire.apds_pdata = 77;
      poll_cycle();
      CHECK(!prox.valid && prox.raw == 42U && prox.at_ms == first_at);
      CHECK(optical_wire.apds_pdata_reads == 1U);

      // A full, directional gesture can arrive with no new proximity ADC
      // sample. GVALID falling closes the three-record FIFO session.
      optical_wire.apds_gesture_status = 1;
      optical_wire.apds_gesture_fifo = {80, 20, 50, 50, 50, 50, 50, 50,
                                       20, 80, 50, 50};
      poll_cycle();
      CHECK(optical_wire.apds_gesture_fifo.empty());
      CHECK(prox.gesture_events == 0U);
      optical_wire.apds_gesture_status = 0;
      poll_cycle();
      CHECK(prox.gesture_events == 1U && prox.gesture_direction == 1U);
      CHECK(!prox.valid && prox.raw == 42U && prox.at_ms == first_at);
      CHECK(optical_wire.apds_pdata_reads == 1U);

      optical_wire.apds_status = 0x02;
      for (const int reg : {0x93, 0x9C}) {
        optical_wire.fail_apds_read_register = reg;
        poll_cycle();
        CHECK(!prox.valid && prox.raw == 42U && prox.at_ms == first_at);
        CHECK(optical_wire.apds_pdata_reads == 1U);
      }
      optical_wire.fail_apds_read_register = -1;
      poll_cycle();
      CHECK(prox.valid && prox.raw == 77U && prox.at_ms > first_at);
      CHECK(optical_wire.apds_pdata_reads == 2U);
      const auto recovered_at = prox.at_ms;
      optical_wire.apds_status = 0x02;
      optical_wire.apds_pdata = 255;
      poll_cycle();
      CHECK(!prox.valid && prox.saturated() && prox.at_ms == recovered_at);
      CHECK(!optical_wire.unsafe_parallel_mux);
    }
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
    CHECK(stalled_ads.readings().force.valid_mask == 0U);
    CHECK(!stalled_ads.readings().force.valid);
    // Explicitly start another ADC single shot and wait for completion.
    // Old data may become valid ONLY after that later actual conversion.
    for (std::uint32_t ms = 1800; ms <= 1968; ms += 12)
      stalled_ads.poll(ms);
    CHECK(stalled_ads.readings().force.jaw_sample_seq >
          jaw_seq_before_pause);
    CHECK(stalled_ads.readings().force.jaw_at_ms >
          jaw_stamp_before_pause);
    CHECK(stalled_ads.readings().force.valid_mask == 2U);
    CHECK(!stalled_ads.readings().force.valid);
    for (std::uint32_t ms = 1980; ms <= 2136; ms += 12)
      stalled_ads.poll(ms);
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
    CHECK(!nfc_accessories.nfc_collection_enabled());
    for (std::uint32_t ms = 0; ms < 600; ms += 12) {
      nfc_accessories.poll(ms);
      CHECK(!nfc_wire.unsafe_parallel_mux);
    }
    const auto& nfc = nfc_accessories.readings().nfc;
    CHECK(nfc_wire.nfc_scans == 0U && !nfc.present && !nfc.valid &&
          !nfc.tag_visible && nfc.tag_token == 0U && nfc.tag_events == 0U &&
          nfc.scan_seq == 0U);
    nfc_accessories.set_nfc_collection_enabled(true, 600);
    CHECK(nfc_accessories.nfc_collection_enabled());
    for (std::uint32_t ms = 612; ms < 3200; ms += 12) {
      nfc_accessories.poll(ms);
      CHECK(!nfc_wire.unsafe_parallel_mux);
      CHECK(nfc_wire.ranges == 0 && nfc_wire.extras == 0);
    }
    CHECK(nfc.present && nfc.valid && nfc.tag_visible);
    CHECK(nfc.tag_events == 1U && nfc.tag_token != 0U);
    CHECK(nfc.scan_seq > 1U);
    CHECK(nfc_wire.dock_gpio_reads > 0);
    nfc_wire.nfc_tag_present = false;
    for (std::uint32_t ms = 3204; ms < 4800; ms += 12) {
      nfc_accessories.poll(ms);
      CHECK(!nfc_wire.unsafe_parallel_mux);
    }
    CHECK(nfc.valid && !nfc.tag_visible && nfc.tag_events == 1U);
    nfc_wire.nfc_tag_present = true;
    for (std::uint32_t ms = 4800; ms < 6700; ms += 12) {
      nfc_accessories.poll(ms);
      CHECK(!nfc_wire.unsafe_parallel_mux);
    }
    CHECK(nfc.valid && nfc.tag_visible && nfc.tag_events == 2U);
    CHECK(nfc_wire.dock_gpio_reads > 0);
    const unsigned previous_scans = nfc_wire.nfc_scans;
    nfc_wire.fail_dock_gpio = true;
    for (std::uint32_t ms = 6708; ms < 7400; ms += 12) {
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
    recovery.set_nfc_collection_enabled(true, 0);
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
        CHECK(!current.tag_visible && current.tag_token == 0U && current.uid_length == 0U);
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
    // An in-flight PN532 ScanResponse interrupted by shared-bus invalidation or
    // dock GPIO failure or contact transition must not consume the stale response.
    enum class NfcBoundary { BusFault, DockNack, DockEntry, DockRemoval };
    for (auto boundary : {NfcBoundary::BusFault, NfcBoundary::DockNack,
                          NfcBoundary::DockEntry, NfcBoundary::DockRemoval}) {
      TwoWire inflight_wire;
      inflight_wire.nfc_connected = true;
      inflight_wire.nfc_tag_present = true;
      inflight_wire.dock_gpioA = boundary == NfcBoundary::DockRemoval ? 0x0d : 0x0c;
      desk_robot::AccessorySensors inflight;
      CHECK(inflight.begin(inflight_wire));
      inflight.set_nfc_collection_enabled(true, 0);
      std::uint32_t ms = 0;
      for (; ms < 2600; ms += 12) inflight.poll(ms);
      const auto baseline = inflight.readings().nfc;
      CHECK(baseline.valid && baseline.tag_visible && baseline.tag_events == 1U);
      // Advance into an active 0x4a ScanResponse wait (nfc_phase == 2) without completing it.
      bool armed_scan_response = false;
      for (; ms < 6000; ms += 12) {
        inflight.poll(ms);
        if (inflight_wire.nfc_command == 0x4a && inflight_wire.nfc_phase == 2) {
          armed_scan_response = true;
          break;
        }
      }
      CHECK(armed_scan_response);
      const auto pre_fault_seq = inflight.readings().nfc.scan_seq;
      const auto pre_fault_scans = inflight_wire.nfc_scans;
      ms += 12;
      if (boundary == NfcBoundary::BusFault) {
        inflight.invalidate_bus();
      } else {
        inflight_wire.fail_dock_gpio = boundary == NfcBoundary::DockNack;
        if (boundary == NfcBoundary::DockEntry) inflight_wire.dock_gpioA = 0x0d;
        if (boundary == NfcBoundary::DockRemoval) inflight_wire.dock_gpioA = 0x0c;
        for (int step = 0; step < 7; ++step, ms += 12) inflight.poll(ms);
        CHECK(inflight.readings().dock.valid == (boundary != NfcBoundary::DockNack));
      }
      CHECK(!inflight.readings().nfc.valid);
      CHECK(!inflight.readings().nfc.tag_visible);
      CHECK(inflight.readings().nfc.tag_token == 0U);
      CHECK(inflight.readings().nfc.uid_length == 0U);
      CHECK(inflight.readings().nfc.tag_events == baseline.tag_events);
      CHECK(inflight.readings().nfc.scan_seq == pre_fault_seq);
      // Restore the bus; leave nfc_phase == 2 in Wire. If the phase were not
      // reset, the first lane-5 recovery slot would accept that stale frame.
      inflight_wire.fail_dock_gpio = false;
      bool saw_fresh_sam = false;
      for (int i = 0; i < 60; ++i, ms += 12) {
        inflight.poll(ms);
        if (inflight_wire.nfc_command == 0x14) {
          saw_fresh_sam = true;
          break;
        }
        CHECK(inflight.readings().nfc.scan_seq == pre_fault_seq);
        CHECK(inflight_wire.nfc_scans == pre_fault_scans);
      }
      CHECK(saw_fresh_sam);
      CHECK(!inflight.readings().nfc.valid);
      CHECK(inflight.readings().nfc.scan_seq == pre_fault_seq);
      for (int i = 0; i < 200; ++i, ms += 12) {
        inflight.poll(ms);
        if (inflight.readings().nfc.valid &&
            inflight.readings().nfc.scan_seq > pre_fault_seq) {
          break;
        }
      }
      const auto& after = inflight.readings().nfc;
      CHECK(after.valid && after.tag_visible);
      CHECK(after.tag_token == baseline.tag_token);
      CHECK(after.tag_events == baseline.tag_events);
      CHECK(after.scan_seq > pre_fault_seq);
      CHECK(inflight_wire.nfc_scans == pre_fault_scans + 1U);
    }
    // 868sCBh: revoking NFC acquisition consent during a pending ScanResponse
    // must retire the in-flight scan, clear stale NFC fields, and perform no
    // further PN532 transfers.
    {
      TwoWire revoke_wire;
      revoke_wire.nfc_connected = true;
      revoke_wire.nfc_tag_present = true;
      desk_robot::AccessorySensors revoke;
      CHECK(revoke.begin(revoke_wire));
      revoke.set_nfc_collection_enabled(true, 0);
      std::uint32_t ms = 0;
      for (; ms < 2600; ms += 12) revoke.poll(ms);
      CHECK(revoke.readings().nfc.valid && revoke.readings().nfc.tag_visible);
      bool armed_scan = false;
      for (; ms < 6000; ms += 12) {
        revoke.poll(ms);
        if (revoke_wire.nfc_command == 0x4a && revoke_wire.nfc_phase == 2) {
          armed_scan = true;
          break;
        }
      }
      CHECK(armed_scan);
      const unsigned scans_before = revoke_wire.nfc_scans;
      revoke.set_nfc_collection_enabled(false, ms);
      CHECK(!revoke.nfc_collection_enabled());
      const auto& cleared = revoke.readings().nfc;
      CHECK(!cleared.present && !cleared.valid && !cleared.tag_visible &&
            cleared.tag_token == 0U && cleared.tag_events == 0U &&
            cleared.scan_seq == 0U && cleared.at_ms == 0U);
      for (int i = 0; i < 60; ++i, ms += 12) {
        revoke.poll(ms);
        CHECK(!revoke_wire.unsafe_parallel_mux);
      }
      CHECK(revoke_wire.nfc_scans == scans_before);
      CHECK(!cleared.present && !cleared.valid && cleared.scan_seq == 0U &&
            cleared.tag_events == 0U);
    }
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
    // MAX30102 power-ready is a downstream reset, not merely mux isolation.
    // Preserve provenance, verify settings in bounded slices, and discard
    // pre-recovery FIFO records before accepting a new optical observation.
    {
      TwoWire reset_wire;
      desk_robot::PulsePad reset_pulse;
      reset_wire.pulse_interrupt_status = 1;
      CHECK(reset_pulse.begin(reset_wire));
      CHECK(reset_wire.pulse_interrupt_status == 0);
      CHECK(reset_pulse.poll(0));
      const auto seq = reset_pulse.sample().sample_seq;
      const auto at = reset_pulse.sample().at_ms;
      reset_wire.pulse_fifo_write_pointer =
          (reset_wire.pulse_fifo_read_pointer + 1U) & 31U;
      const auto old_read = reset_wire.pulse_fifo_read_pointer;
      reset_wire.pulse_interrupt_status = 1;
      for (auto& reg : reset_wire.pulse_config) reg = 0;
      reset_wire.pulse_interrupt_enable = 0;
      CHECK(!reset_pulse.poll(60));
      CHECK(!reset_pulse.sample().valid);
      CHECK(reset_wire.pulse_fifo_read_pointer == old_read);
      reset_wire.ignore_pulse_config_write_reg = 0x0c;
      for (std::uint32_t ms = 120; ms <= 780; ms += 60) {
        CHECK(!reset_pulse.poll(ms));
        CHECK(!reset_pulse.sample().valid);
        CHECK(reset_pulse.sample().sample_seq == seq && reset_pulse.sample().at_ms == at);
        CHECK(reset_wire.ranges == 0 && reset_wire.extras == 0);
      }
      reset_wire.ignore_pulse_config_write_reg = -1;
      for (std::uint32_t ms = 840; ms <= 1320; ms += 60) {
        CHECK(!reset_pulse.poll(ms));
        CHECK(reset_pulse.sample().sample_seq == seq);
        CHECK(reset_wire.ranges == 0 && reset_wire.extras == 0);
      }
      CHECK(reset_wire.pulse_config[0x09] == 3 && reset_wire.pulse_config[0x0a] == 0x23);
      CHECK(reset_wire.pulse_config[0x0c] == 7 && reset_wire.pulse_config[0x0d] == 7);
      CHECK(reset_wire.pulse_interrupt_enable == 0x20);
      reset_wire.pulse_fifo_write_pointer =
          (reset_wire.pulse_fifo_read_pointer + 1U) & 31U;
      CHECK(reset_pulse.poll(1380));
      CHECK(reset_pulse.sample().sample_seq == seq + 1U);
      // If the reset flag was lost during a failed transfer, a mode
      // mismatch after shared bus quarantine also requires configuration.
      reset_pulse.invalidate_bus();
      reset_wire.pulse_config[0x09] = 0;
      reset_wire.pulse_fifo_write_pointer =
          (reset_wire.pulse_fifo_read_pointer + 1U) & 31U;
      CHECK(!reset_pulse.poll(1440));
      for (std::uint32_t ms = 1500; ms <= 1920; ms += 60) {
        CHECK(!reset_pulse.poll(ms));
        CHECK(!reset_pulse.sample().valid);
      }
      reset_wire.pulse_fifo_write_pointer =
          (reset_wire.pulse_fifo_read_pointer + 1U) & 31U;
      CHECK(reset_pulse.poll(1980));
      CHECK(reset_pulse.sample().sample_seq == seq + 2U);
      CHECK(!reset_wire.unsafe_parallel_mux);
    }
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
    // PGOOD changes independently of the seat switches.
    {
      TwoWire power_wire;
      power_wire.dock_gpioA = 0x0d;
      desk_robot::AccessorySensors power_accessories;
      CHECK(power_accessories.begin(power_wire));
      std::uint32_t ms = 0;
      for (; ms < 600; ms += 12) power_accessories.poll(ms);
      const auto& power = power_accessories.readings();
      const auto& gauge = power.gauge;
      CHECK(power.dock.left_seated && !power.dock.input_good);
      CHECK(gauge.fuel_valid && gauge.monitor_valid);
      for (const auto pins : {0x09U, 0x0dU}) {
        power_wire.dock_gpioA = static_cast<std::uint8_t>(pins);
        const auto dock_seq = power.dock.sample_seq;
        auto before = gauge;
        for (int step = 0; step < 7 && power.dock.sample_seq == dock_seq; ++step) {
          before = gauge;
          power_accessories.poll(ms);
          ms += 12;
        }
        CHECK(power.dock.sample_seq != dock_seq);
        CHECK(power.dock.input_good == (pins == 0x09U));
        CHECK(power.dock.left_seated);
        CHECK(before.fuel_valid && before.monitor_valid);
        CHECK(!gauge.fuel_valid && !gauge.monitor_valid && !gauge.pack_current_valid);
        CHECK(gauge.fuel_sample_seq == before.fuel_sample_seq);
        CHECK(gauge.monitor_sample_seq == before.monitor_sample_seq);
        CHECK(gauge.fuel_at_ms == before.fuel_at_ms);
        CHECK(gauge.monitor_at_ms == before.monitor_at_ms);
        // Next lane 4 reads MAX17048 again but drains the possibly old CVRF.
        for (int step = 0; step < 6; ++step, ms += 12)
          power_accessories.poll(ms);
        CHECK(gauge.fuel_valid && gauge.fuel_sample_seq != before.fuel_sample_seq);
        CHECK(!gauge.monitor_valid && !gauge.pack_current_valid);
        CHECK(gauge.monitor_sample_seq == before.monitor_sample_seq);
        CHECK(gauge.monitor_at_ms == before.monitor_at_ms);
        // A subsequent conversion-ready read renews INA226 identity.
        for (int step = 0; step < 7; ++step, ms += 12)
          power_accessories.poll(ms);
        CHECK(gauge.fuel_valid && gauge.monitor_valid);
        CHECK(gauge.monitor_sample_seq != before.monitor_sample_seq);
        CHECK(gauge.monitor_at_ms > before.monitor_at_ms);
        CHECK(!power_wire.unsafe_parallel_mux);
      }
    }
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
    // Both direction registers reset to inputs even without haptics;
    // lost pullups must still revoke the dock sample after an expander reset.
    TwoWire reset_mcp_wire;
    desk_robot::AccessorySensors reset_mcp;
    CHECK(reset_mcp.begin(reset_mcp_wire));
    for (std::uint32_t ms = 0; ms <= 48; ms += 12) reset_mcp.poll(ms);
    CHECK(reset_mcp.readings().dock.valid);
    CHECK(reset_mcp_wire.mcp_iodira == 0xFF && reset_mcp_wire.mcp_iodirb == 0xFF);
    const auto reset_dock_seq = reset_mcp.readings().dock.sample_seq;
    reset_mcp_wire.mcp_gppua = reset_mcp_wire.mcp_gppub = 0;
    for (std::uint32_t ms = 60; ms <= 132; ms += 12) reset_mcp.poll(ms);
    CHECK(!reset_mcp.readings().dock.valid && !reset_mcp.readings().optional_inputs.valid);
    CHECK(reset_mcp.readings().dock.sample_seq == reset_dock_seq);
    reset_mcp_wire.mcp_gppua = 0x0F;
    reset_mcp_wire.mcp_gppub = 0x01;
    for (std::uint32_t ms = 144; ms <= 216; ms += 12) reset_mcp.poll(ms);
    CHECK(!reset_mcp.readings().dock.valid);
    // Reject a corrupt INA226 bus word before refreshing either monitor
    // provenance or current. MAX17048 is an independent acquisition.
    {
      TwoWire bus_wire;
      desk_robot::AccessorySensors bus_accessories;
      CHECK(bus_accessories.begin(bus_wire));
      for (std::uint32_t ms = 0; ms < 1000; ms += 12)
        bus_accessories.poll(ms);
      const auto before = bus_accessories.readings().gauge;
      const auto& live = bus_accessories.readings().gauge;
      CHECK(before.monitor_valid && before.fuel_valid && before.bus_mv == 5120U);
      bus_wire.ina226_shunt_raw = 0xffc4U;
      std::uint32_t now = 1008;
      for (const auto bad : {0x8000U, 0xffffU}) {
        bus_wire.ina226_bus_raw = static_cast<std::uint16_t>(bad);
        const auto end = now + 300U;
        for (; now < end; now += 12) bus_accessories.poll(now);
        CHECK(!live.monitor_valid && !live.pack_current_valid);
        CHECK(live.monitor_sample_seq == before.monitor_sample_seq);
        CHECK(live.monitor_at_ms == before.monitor_at_ms);
        CHECK(live.bus_mv == before.bus_mv && live.shunt_uv == before.shunt_uv);
        CHECK(live.fuel_valid && live.fuel_sample_seq > before.fuel_sample_seq);
      }
      bus_wire.ina226_bus_raw = 0x0c80U;
      const auto end = now + 300U;
      for (; now < end; now += 12) bus_accessories.poll(now);
      CHECK(live.monitor_valid && live.bus_mv == 4000U && live.shunt_uv == -150);
      CHECK(live.monitor_sample_seq > before.monitor_sample_seq);
      CHECK(live.monitor_at_ms > before.monitor_at_ms);
#if defined(DESK_ROBOT_PACK_SHUNT_MOHM) && DESK_ROBOT_PACK_SHUNT_MOHM == 5
      CHECK(live.pack_current_valid && live.pack_current_ma == -30);
#else
      CHECK(!live.pack_current_valid);
#endif
    }
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
    for (std::uint32_t ms = 1344; ms < 1680; ms += 12) {
      const auto before = sht_wire.transactions;
      sht_accessories.poll(ms);
      if (ms % 84U == 24U) {
        // Two verified mux selections, one failed SHT command, and one
        // verified close. No same-slice retry or absent BMP280 transfer.
        CHECK(sht_wire.transactions - before == 7U);
      }
      CHECK(sht_wire.ranges == 0 && sht_wire.extras == 0);
      CHECK(!sht_wire.unsafe_parallel_mux);
    }
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
