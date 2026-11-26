#include <cstdint>
#include <iostream>
#include <stdexcept>
#include "Wire.h"
#include "AccessorySensors.h"
TwoWire Wire;
#define CHECK(x) do { if (!(x)) throw std::runtime_error(#x); } while (false)

static void scan(desk_robot::AccessorySensors& bus, unsigned lo, unsigned hi) {
  for (unsigned ms = lo; ms <= hi; ms += 12) bus.poll(ms);
}

// All four dock inputs are independent; unrelated GPA bits must not
// change the decision. A rejected request must not replay on recovery.
static void check_dock_masks() {
  for (unsigned bits = 0; bits < 16; ++bits) {
    TwoWire wire;
    wire.dock_gpioA = static_cast<std::uint8_t>(0xF0U | bits);
    desk_robot::AccessorySensors bus;
    CHECK(bus.begin(wire));
    CHECK(bus.haptic_ready());
    CHECK(bus.request_haptic(1));
    scan(bus, 0, 48);
    const auto& dock = bus.readings().dock;
    CHECK(dock.valid && dock.sample_seq != 0);
    CHECK(dock.left_seated == ((bits & 1U) != 0));
    CHECK(dock.right_seated == ((bits & 2U) != 0));
    CHECK(dock.input_good == ((bits & 4U) == 0));
    CHECK(dock.charge_indicated == ((bits & 8U) == 0));
    CHECK(wire.mcp_olatb == (bits == 0x0CU ? 0x04U : 0U));
    CHECK(wire.haptic_rising_edges == (bits == 0x0CU ? 1U : 0U));
    wire.dock_gpioA = 0x0C;
    scan(bus, 60, 132);
    CHECK(wire.mcp_olatb == 0);
    CHECK(wire.haptic_rising_edges == (bits == 0x0CU ? 1U : 0U));
    CHECK(wire.mcp_iodirb == 0xFB);
    CHECK(!wire.unsafe_parallel_mux);
  }
}

// GPB0 reed, GPB1 PIR and GPB3 nFAULT remain independent of GPB2.
// The fake injects pin levels, not electrical pullup or output behavior.
static void check_shared_port_inputs() {
  for (unsigned bits = 0; bits < 16; ++bits) {
    TwoWire wire;
    wire.dock_gpioA = 0x0C;
    wire.optional_gpioB = static_cast<std::uint8_t>(0xF0U | bits);
    desk_robot::AccessorySensors bus;
    CHECK(bus.begin(wire));
    CHECK(bus.request_haptic(1));
    scan(bus, 0, 48);
    const auto& input = bus.readings().optional_inputs;
    CHECK(input.valid && input.sample_seq != 0);
    CHECK(input.reed_closed == ((bits & 1U) == 0));
    CHECK(input.pir_active == ((bits & 2U) != 0));
    CHECK(input.driver_fault_active == ((bits & 8U) == 0));
    CHECK(wire.mcp_iodirb == 0xFB && wire.mcp_olatb == 0x04);
    const auto seq = input.sample_seq;
    const unsigned changed = bits ^ 0x0FU;
    wire.optional_gpioB = static_cast<std::uint8_t>(changed);
    scan(bus, 60, 132);
    CHECK(input.valid && input.sample_seq != seq);
    CHECK(input.reed_closed == ((changed & 1U) == 0));
    CHECK(input.pir_active == ((changed & 2U) != 0));
    CHECK(input.driver_fault_active == ((changed & 8U) == 0));
    CHECK(wire.mcp_iodirb == 0xFB && wire.mcp_olatb == 0);
    CHECK(wire.haptic_rising_edges == 1);
    CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
  }
}

static void check_dock_read_dropout() {
  TwoWire wire;
  wire.dock_gpioA = 0x0C;
  desk_robot::AccessorySensors bus;
  CHECK(bus.begin(wire));
  CHECK(bus.request_haptic(1));
  wire.fail_dock_gpio = true;
  scan(bus, 0, 48);
  CHECK(!bus.readings().dock.valid);
  CHECK(!bus.readings().optional_inputs.valid);
  CHECK(wire.optional_gpio_reads == 0);
  CHECK(wire.haptic_rising_edges == 0 && wire.mcp_olatb == 0);
  wire.fail_dock_gpio = false;
  scan(bus, 60, 132);
  CHECK(bus.readings().dock.valid);
  CHECK(wire.haptic_rising_edges == 0);
  CHECK(bus.request_haptic(133));
  scan(bus, 144, 216);
  CHECK(wire.haptic_rising_edges == 1 && wire.mcp_olatb == 0x04);
  const auto seq = bus.readings().dock.sample_seq;
  const auto optional_reads = wire.optional_gpio_reads;
  wire.fail_dock_gpio = true;
  scan(bus, 228, 300);
  CHECK(!bus.readings().dock.valid && bus.readings().dock.sample_seq == seq);
  CHECK(!bus.readings().optional_inputs.valid);
  CHECK(wire.optional_gpio_reads == optional_reads);
  CHECK(wire.mcp_olatb == 0 && wire.haptic_rising_edges == 1);
  CHECK(wire.mcp_iodirb == 0xFB && !wire.unsafe_parallel_mux);
}

// A previously HIGH latch must be cleared at boot; a readback failure
// must not grant haptic authority even after communication recovers.
static void check_boot_configuration() {
  TwoWire wire;
  wire.mcp_olatb = 0x04;
  wire.dock_gpioA = 0x0C;
  desk_robot::AccessorySensors bus;
  CHECK(bus.begin(wire));
  CHECK(bus.haptic_ready());
  CHECK(wire.mcp_iodirb == 0xFB && wire.mcp_olatb == 0);
  CHECK(wire.haptic_rising_edges == 0);
  scan(bus, 0, 48);
  CHECK(wire.haptic_rising_edges == 0);

  TwoWire failed;
  failed.dock_gpioA = 0x0C;
  failed.fail_mcp_latch_readback = true;
  desk_robot::AccessorySensors unverified;
  CHECK(unverified.begin(failed));
  CHECK(!unverified.haptic_ready() && !unverified.request_haptic(1));
  failed.fail_mcp_latch_readback = false;
  scan(unverified, 0, 48);
  CHECK(failed.mcp_olatb == 0 && failed.haptic_rising_edges == 0);
  CHECK(!unverified.haptic_ready() && !unverified.request_haptic(49));

  TwoWire rejected;
  rejected.fail_mcp_register_write = true;
  desk_robot::AccessorySensors absent;
  CHECK(absent.begin(rejected)); // mux exists; mandatory dock config failed
  CHECK(!absent.readings().dock.present);
  CHECK(!absent.haptic_ready() && !absent.request_haptic(1));
  CHECK(rejected.failed_mcp_writes > 0);
  CHECK(rejected.mcp_iodirb == 0xFF && rejected.mcp_olatb == 0);
  rejected.fail_mcp_register_write = false;
  scan(absent, 0, 48);
  CHECK(!absent.readings().dock.valid);
  CHECK(!absent.haptic_ready() && rejected.haptic_rising_edges == 0);
}

// A failed deassert transaction leaves physical latch state unknown.
// Software must refuse further pulses and retry LOW without automatic rearm.
static void check_failed_deassert_write() {
  TwoWire wire;
  wire.dock_gpioA = 0x0C;
  desk_robot::AccessorySensors bus;
  CHECK(bus.begin(wire));
  CHECK(bus.request_haptic(1));
  scan(bus, 0, 48);
  CHECK(wire.mcp_olatb == 0x04 && wire.haptic_rising_edges == 1);
  const auto ends = wire.mcp_terminated_transmissions;
  wire.fail_mcp_register_write = true;
  scan(bus, 60, 132);
  // The failed direction pointer prevents any subsequent latch write.
  CHECK(wire.failed_mcp_writes >= 1);
  CHECK(wire.mcp_terminated_transmissions >= ends + 1);
  CHECK(!bus.haptic_ready() && !bus.readings().dock.valid);
  CHECK(!bus.request_haptic(133));
  CHECK(wire.mcp_olatb == 0x04); // fake rejected the write; not a motor timer
  wire.fail_mcp_register_write = false;
  scan(bus, 144, 216);
  CHECK(wire.mcp_olatb == 0 && wire.haptic_rising_edges == 1);
  CHECK(!bus.haptic_ready() && !bus.request_haptic(1800));
  CHECK(wire.mcp_iodirb == 0xFB && !wire.unsafe_parallel_mux);
}

// External shared-bus invalidation must cancel queued work and clear an
// already asserted latch on the next verified lane 5 pass, never replay it.
static void check_external_bus_invalidation() {
  for (bool active : {false, true}) {
    TwoWire wire;
    wire.dock_gpioA = 0x0C;
    wire.optional_gpioB = 0xFB; // unrelated input bits must not enter OLATB
    desk_robot::AccessorySensors bus;
    CHECK(bus.begin(wire));
    CHECK(bus.request_haptic(1));
    if (active) scan(bus, 0, 48);
    CHECK(wire.mcp_olatb == (active ? 0x04U : 0U));
    const auto edges = wire.haptic_rising_edges;
    bus.invalidate_bus();
    CHECK(!bus.haptic_ready());
    CHECK(!bus.readings().dock.valid);
    CHECK(!bus.readings().optional_inputs.valid);
    CHECK(!bus.request_haptic(49));
    // Invalidation itself must not issue unisolated bus transactions.
    CHECK(wire.ranges == 0 && wire.extras == 0);
    CHECK(wire.mcp_olatb == (active ? 0x04U : 0U));
    scan(bus, active ? 60U : 0U, 132);
    CHECK(bus.readings().dock.valid);
    CHECK(wire.mcp_olatb == 0);
    CHECK(wire.haptic_rising_edges == edges);
    CHECK(wire.mcp_iodirb == 0xFB && !wire.unsafe_parallel_mux);
    CHECK(!bus.haptic_ready() && !bus.request_haptic(1800));
    scan(bus, 144, 216);
    CHECK(wire.mcp_olatb == 0 && wire.haptic_rising_edges == edges);
  }
}

static void check_runtime_port_configuration_fault() {
  for (unsigned fault = 0; fault < 4; ++fault) {
    TwoWire wire;
    wire.dock_gpioA = 0x0C;
    desk_robot::AccessorySensors bus;
    CHECK(bus.begin(wire));
    CHECK(wire.mcp_iodira == 0xFF && wire.mcp_iodirb == 0xFB);
    CHECK(bus.request_haptic(1));
    scan(bus, 0, 48);
    CHECK(wire.mcp_olatb == 0x04 && bus.readings().dock.valid);
    const auto seq = bus.readings().dock.sample_seq;
    const auto reads = wire.optional_gpio_reads;
    if (fault == 0) wire.mcp_iodira = 0xFE;
    if (fault == 1) wire.mcp_iodirb = 0xF9;
    if (fault == 2) wire.mcp_gppua = 0;
    if (fault == 3) wire.mcp_gppub = 0;
    scan(bus, 60, 132);
    CHECK(!bus.readings().dock.valid && bus.readings().dock.sample_seq == seq);
    CHECK(!bus.readings().optional_inputs.valid);
    CHECK(wire.optional_gpio_reads == reads);
    CHECK(!bus.haptic_ready() && !bus.request_haptic(133));
    CHECK(wire.mcp_iodira == 0xFF && wire.mcp_iodirb == 0xFF);
    CHECK(wire.mcp_olatb == 0 && wire.haptic_rising_edges == 1);
    // Even restored registers cannot rearm a latched configuration fault.
    wire.mcp_gppua = 0x0F;
    wire.mcp_gppub = 0x01;
    scan(bus, 144, 216);
    CHECK(!bus.readings().dock.valid && !bus.haptic_ready());
    CHECK(wire.haptic_rising_edges == 1 && !wire.unsafe_parallel_mux);
  }
}

static void check_unverified_direction_blocks_latch() {
  TwoWire wire;
  wire.dock_gpioA = 0x0C;
  desk_robot::AccessorySensors bus;
  CHECK(bus.begin(wire));
  CHECK(bus.request_haptic(1));
  scan(bus, 0, 48);
  CHECK(wire.mcp_olatb == 0x04 && wire.haptic_rising_edges == 1);
  wire.fail_mcp_direction_readback = true;
  scan(bus, 60, 132);
  CHECK(!bus.readings().dock.valid && !bus.haptic_ready());
  // The external one-shot owns the physical deadline. Software cannot
  // write even LOW until it verifies the port configuration again.
  CHECK(wire.mcp_olatb == 0x04 && !bus.request_haptic(133));
  wire.fail_mcp_direction_readback = false;
  scan(bus, 144, 216);
  CHECK(bus.readings().dock.valid && wire.mcp_olatb == 0);
  CHECK(wire.haptic_rising_edges == 1 && !bus.haptic_ready());
  CHECK(!wire.unsafe_parallel_mux);
}

int main() {
  try {
    check_unverified_direction_blocks_latch();
    check_runtime_port_configuration_fault();
    check_external_bus_invalidation();
    check_boot_configuration();
    check_failed_deassert_write();
    check_dock_masks();
    check_shared_port_inputs();
    check_dock_read_dropout();

    // Full range bus stays disconnected, real dock GPIOA must be fresh.
    TwoWire wire;
    wire.dock_gpioA = 0x0C;  // two switches unseated, no PGOOD/CHG
    desk_robot::AccessorySensors bus;
    CHECK(bus.begin(wire));
    CHECK(bus.haptic_ready());
    CHECK(wire.mcp_iodirb == 0xFB); // GPB2 output, GPB0/1 remain inputs
    CHECK(wire.mcp_olatb == 0);
    CHECK(bus.request_haptic(1));
    scan(bus, 0, 48); // one actual fresh GPIOA read before latch HIGH
    CHECK(wire.dock_gpio_reads > 0);
    CHECK(wire.haptic_rising_edges == 1);
    CHECK(wire.mcp_olatb == 0x04);
    CHECK(wire.ranges == 0 && wire.extras == 0 && !wire.unsafe_parallel_mux);
    scan(bus, 60, 132); // next channel 5 must deassert
    CHECK(wire.mcp_olatb == 0 && wire.haptic_rising_edges == 1);
    CHECK(bus.haptic_ready());

    // An actual contact disables new vibration even if touch arrived.
    wire.dock_gpioA = 0x0F;
    CHECK(bus.request_haptic(1680));
    scan(bus, 1680, 1752);
    CHECK(wire.mcp_olatb == 0 && wire.haptic_rising_edges == 1);
    // Resume a later independent touch only after undocked fresh GPIOA.
    wire.dock_gpioA = 0x0C;
    CHECK(bus.request_haptic(1764));
    scan(bus, 1764, 1836);
    CHECK(wire.haptic_rising_edges == 2 && wire.mcp_olatb == 0x04);
    // The stop must run even if a contact becomes seated during pulse.
    wire.dock_gpioA = 0x0F;
    scan(bus, 1848, 1920);
    CHECK(wire.mcp_olatb == 0 && bus.haptic_ready());

    // A write with rejected readback cannot make active state authoritative.
    TwoWire failed_readback;
    failed_readback.dock_gpioA = 0x0C;
    desk_robot::AccessorySensors guarded;
    CHECK(guarded.begin(failed_readback));
    CHECK(guarded.request_haptic(1));
    failed_readback.fail_mcp_latch_readback = true;
    scan(guarded, 0, 48);
    CHECK(failed_readback.haptic_rising_edges == 1);
    CHECK(!guarded.haptic_ready());
    CHECK(!guarded.readings().dock.valid);
    CHECK(!guarded.request_haptic(100));
    failed_readback.fail_mcp_latch_readback = false;
    scan(guarded, 60, 132);
    CHECK(failed_readback.mcp_olatb == 0);
    CHECK(!guarded.haptic_ready()); // never silently re-arm after bus fault
    CHECK(!failed_readback.unsafe_parallel_mux);

    // A stuck critical mux cannot be bypassed to turn on the haptic output.
    TwoWire stuck;
    stuck.dock_gpioA = 0x0C;
    desk_robot::AccessorySensors separated;
    CHECK(separated.begin(stuck));
    CHECK(separated.request_haptic(1));
    stuck.ranges = 1;
    stuck.range_mux_stuck = true;
    scan(separated, 0, 48);
    CHECK(stuck.haptic_rising_edges == 0);
    CHECK(stuck.mcp_olatb == 0);
    CHECK(!separated.haptic_ready());

    std::cout << "PASS guarded haptic register IO, dock-first, fault and mux\n";
  } catch (const std::exception& error) {
    std::cerr << "FAIL " << error.what() << '\n';
    return 1;
  }
}
