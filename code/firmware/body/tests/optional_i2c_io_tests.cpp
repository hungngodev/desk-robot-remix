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
    std::cout << "PASS optional sensor register IO, NFC framing and isolated mux slots\n";
  } catch (const std::exception& e) {
    std::cerr << "FAIL " << e.what() << '\n';
    return 1;
  }
}
