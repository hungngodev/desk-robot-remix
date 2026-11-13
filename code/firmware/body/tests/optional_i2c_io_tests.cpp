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
    CHECK(pulse.begin(Wire));
    CHECK(touch.begin(Wire));
    CHECK(Wire.ranges == 0 && Wire.extras == 0);
    std::uint8_t bits = 0;
    for (std::uint32_t now_ms = 0; now_ms < 1600; now_ms += 12) {
      accessories.poll(now_ms);
      pulse.poll(now_ms);
      touch.poll(now_ms, bits);
      CHECK(Wire.ranges == 0 && Wire.extras == 0);
      CHECK(!Wire.unsafe_parallel_mux);
    }
    CHECK(bits == 0xA5);
    CHECK(pulse.sample().present);
    CHECK(pulse.sample().valid);
    CHECK(pulse.sample().red == 1003);
    CHECK(pulse.sample().ir == 5003);
    CHECK(pulse.sample().sample_seq > 0U);
    const auto& read = accessories.readings();
    for (unsigned i = 0; i < 3; ++i) {
      CHECK(read.angle[i].present);
      CHECK(read.angle[i].valid);
      CHECK(read.angle[i].angle == 2000);
      CHECK(read.angle[i].magnet_status == 0x20);
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
    CHECK(read.gauge.fuel_present && read.gauge.fuel_valid);
    CHECK(read.gauge.cell_mv == 3600);
    CHECK(read.gauge.soc_centi == 5000);
    CHECK(read.gauge.monitor_present && read.gauge.monitor_valid);
    CHECK(read.gauge.bus_mv == 5120);
    CHECK(read.gauge.shunt_uv == 40);
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
    // A separate GPIOB read can host slow reed/PIR while GPIOA continues
    // owning the compulsory independent dock stop/PGOOD evidence.
    TwoWire optional_wire;
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
    const auto base = slow.sample_seq;
    optional_wire.optional_gpioB = 0x02; // reed closed LOW, PIR active HIGH
    for (std::uint32_t ms = 2808; ms < 4300; ms += 12) {
      optional_accessories.poll(ms);
    }
    CHECK(slow.valid && slow.reed_closed && slow.pir_active);
    CHECK(slow.sample_seq > base);
    optional_wire.fail_optional_gpio = true;
    const auto last = slow.sample_seq;
    for (std::uint32_t ms = 4308; ms < 5300; ms += 12) {
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
    std::cout << "PASS optional sensor register IO, MCP GPIOB, NFC and isolated mux slots\n";
  } catch (const std::exception& e) {
    std::cerr << "FAIL " << e.what() << '\n';
    return 1;
  }
}
