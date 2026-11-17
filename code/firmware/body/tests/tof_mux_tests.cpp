#include <cstdint>
#include <iostream>
#include <stdexcept>
#include "Wire.h"
#include "TofBus.h"
#include "CliffGuard.h"

TwoWire Wire; // host fake, never a real bus
#define CHECK(expr) do { if (!(expr)) throw std::runtime_error(#expr); } while (false)

static desk_robot::CliffConfig calibration() {
  desk_robot::CliffConfig c{};
  c.calibrated = true;
  for (auto& floor : c.floor) { floor.min_mm = 30; floor.max_mm = 80; }
  c.front_obstacle_mm = 100;
  c.front_max_mm = 800;
  c.freshness_ms = 200;
  return c;
}

static void ready(desk_robot::TofBus& bus, desk_robot::CliffGuard& guard) {
  CHECK(guard.configure(calibration()));
  CHECK(bus.begin(21, 22, -1));
  CHECK(bus.ready());
  CHECK(Wire.extras == 0);
  for (std::uint32_t i = 0; i < 5; ++i)
    bus.poll(guard, 10U * i);
  CHECK(Wire.tof_samples == 5);
  CHECK(guard.try_rearm(50));
  CHECK(guard.evaluate(50));
}

static void faulted(desk_robot::CliffGuard& guard) {
  CHECK(guard.fault() == desk_robot::CliffFault::BusFailure);
  CHECK(!guard.evaluate(60));
  CHECK(!guard.try_rearm(60));
  // Bus faults delete prior sample provenance; old floor readings cannot
  // be recycled to rearm on a plausible but misselected mux lane.
  for (std::uint8_t lane = 0; lane < 5; ++lane)
    CHECK(!guard.diagnostic(lane, 60).present);
}

int main() {
  try {
    {
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      const auto before = Wire.tof_samples;
      Wire.range_mux_stuck = true; // command ACKed, old channel remains
      bus.poll(guard, 60);
      CHECK(Wire.tof_samples == before); // never read wrong floor lane
      faulted(guard);
      Wire.range_mux_stuck = false;
      // A fresh five-channel sweep is mandatory before operator rearm.
      for (std::uint32_t n = 0; n < 5; ++n)
        bus.poll(guard, 61 + n);
      CHECK(guard.try_rearm(70));
    }
    {
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      Wire.range_mux_write_nack = true;
      bus.poll(guard, 60);
      faulted(guard);
    }
    {
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      Wire.range_mux_read_nack = true; // write ACK alone is not proof
      bus.poll(guard, 60);
      faulted(guard);
    }
    {
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      Wire.range_mux_bad_readback = true; // wrong/multiple lanes reported
      bus.poll(guard, 60);
      faulted(guard);
    }
    {
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      Wire.extras = 1; // optional mux left on a competing lane
      Wire.optional_mux_stuck = true;
      bus.poll(guard, 60); // cannot prove optional mux quiescent
      faulted(guard);
    }
    {
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      bus.poll(guard, 60); // first optional left range, lane 5
      const auto fresh = bus.extra_diagnostic(0, 60);
      CHECK(fresh.present && fresh.valid);
      CHECK(fresh.distance_mm == 45 && fresh.age_ms == 0);
      CHECK(bus.extra_diagnostic(0, 410).valid); // exactly 350ms
      const auto stale = bus.extra_diagnostic(0, 411);
      CHECK(stale.present && !stale.valid);
      CHECK(stale.distance_mm == 45 && stale.age_ms == 351);
      CHECK(!bus.extra_diagnostic(3, 411).present);
    }
    {
      // A mux fault after a valid optional range must invalidate its source,
      // even before the 350ms freshness window expires.
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      bus.poll(guard, 60);  // first optional lane 5
      CHECK(bus.extra_diagnostic(0, 60).valid);
      Wire.range_mux_bad_readback = true;
      bus.poll(guard, 61); // next selected lane cannot be trusted
      faulted(guard);
      const auto invalid = bus.extra_diagnostic(0, 62);
      CHECK(invalid.present && !invalid.valid);
      CHECK(invalid.distance_mm == 45);
      Wire.range_mux_bad_readback = false;
      // The scanner rotates side 5, 6, 7 after each five critical lanes.
      // Already acquired side 5 before the bus fault, then polled critical 0
      // at failure. It must wait through side 6 and side 7 before returning
      // to a NEW side 5 read. No cached value may become valid meanwhile.
      for (std::uint32_t at = 70; at < 86; ++at)
        bus.poll(guard, at);
      CHECK(!bus.extra_diagnostic(0, 86).valid);
      bus.poll(guard, 86);  // first independent side 5 conversion
      CHECK(bus.extra_diagnostic(0, 86).valid);
    }
    {
      Wire = TwoWire{};
      Wire.optional_mux_installed = false; // five sensor bench profile
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      CHECK(Wire.tof_samples == 5);
      CHECK(Wire.extras == 0);
      Wire.range_mux_stuck = true;
      bus.poll(guard, 60);
      faulted(guard); // critical mux validation is still required
    }
    {
      Wire = TwoWire{};
      Wire.range_mux_stuck = true; // init must reject unverified lane
      desk_robot::TofBus bus;
      CHECK(!bus.begin(21, 22, -1));
      CHECK(!bus.ready());
    }
    {
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      CHECK(bus.begin(21, 22, -1));
      // The last initialized range lane is still selected (channel 7).
      // An ACKed but ineffective disconnect must NOT probe a downstream IMU.
      Wire.range_mux_stuck = true;
      CHECK(bus.probe_imu().family == 0);
      CHECK(Wire.imu_probe_attempts == 0);
      Wire.range_mux_stuck = false;
      Wire.range_mux_read_nack = true;
      CHECK(bus.probe_imu().family == 0);
      CHECK(Wire.imu_probe_attempts == 0);
      Wire.range_mux_read_nack = false;
      CHECK(bus.probe_imu().family == 0); // this fake has no physical IMU
      CHECK(Wire.imu_probe_attempts > 0); // only after proven disconnect
    }
    std::cout << "PASS cheap VL53L0X TCA9548A selected-channel readback and fail-closed cliff paths\n";
    return 0;
  } catch (const std::exception& ex) {
    std::cerr << "FAIL mux verification: " << ex.what() << '\n';
    return 1;
  }
}
