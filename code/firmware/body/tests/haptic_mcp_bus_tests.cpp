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

int main() {
  try {
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
