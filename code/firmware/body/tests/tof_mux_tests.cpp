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
      // Optical quality is decoded from the SAME accepted 12-byte result,
      // not a new blocking I2C read or a separate motion authorization.
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      const auto floor = bus.optical_diagnostic(0, 50);
      CHECK(floor.present && floor.valid && floor.age_ms == 50);
      CHECK(floor.ambient_97 == 0x0123 && floor.signal_97 == 0x4567);
      CHECK(!bus.optical_diagnostic(0, 200).valid);
      CHECK(bus.optical_diagnostic(0, 200).signal_97 == 0x4567);
      CHECK(bus.new_optical_channel() == 4);

      Wire.tof_ready = false;
      bus.poll(guard, 60);  // no completed side conversion
      CHECK(bus.new_optical_channel() == 255);
      CHECK(!bus.optical_diagnostic(5, 60).present);
      Wire.tof_ready = true;
      bus.poll(guard, 61);  // a distinct completed critical conversion
      CHECK(bus.new_optical_channel() == 0);
      const auto renewed = bus.optical_diagnostic(0, 61);
      CHECK(renewed.present && renewed.valid && renewed.age_ms == 0);
      CHECK(!bus.optical_diagnostic(8, 61).present);
    }
    {
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      bus.poll(guard, 60);  // optional range lane 5
      const auto side = bus.optical_diagnostic(5, 410);
      CHECK(side.present && side.valid && side.age_ms == 350);
      CHECK(side.ambient_97 == 0x0123 && side.signal_97 == 0x4567);
      CHECK(!bus.optical_diagnostic(5, 411).valid);
      Wire.range_mux_bad_readback = true;
      bus.poll(guard, 61);  // fault invalidates old optical evidence
      CHECK(!bus.optical_diagnostic(5, 62).valid);
      CHECK(bus.optical_diagnostic(5, 62).signal_97 == 0x4567);
      CHECK(!bus.optical_diagnostic(0, 62).valid);
      faulted(guard); // optical metadata did not weaken the local latch
    }
    {
      // The previous case deliberately left mux readback corrupted. New
      // bench scenarios must reset the fake bus before expecting startup.
      Wire = TwoWire{};
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
      // The 0x71 touch mux NACKed at the very start of ToF init. Later
      // CAP1188 or other 0x71 discovery must UPGRADE the sensor isolation
      // contract, not leave the 0x29 cliff read exposed to a stuck CAP lane.
      Wire = TwoWire{};
      Wire.optional_mux_installed = false;
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      CHECK(Wire.ranges == 16);  // initialized critical lane four
      Wire.optional_mux_installed = true;
      Wire.extras = 1;  // 0x29 CAP1188 remains selected
      Wire.optional_mux_stuck = true;
      bus.note_optional_mux_present();
      const auto before = Wire.tof_samples;
      bus.poll(guard, 60);
      CHECK(Wire.tof_samples == before);
      CHECK(Wire.ranges == 16); // reject BEFORE changing critical lane
      faulted(guard);
      // After a correct verified disconnect, only a fresh critical sweep
      // plus local rearm can restore permission.
      Wire.optional_mux_stuck = false;
      for (std::uint32_t at = 61; at < 66; ++at) bus.poll(guard, at);
      CHECK(guard.try_rearm(70));
      CHECK(guard.evaluate(70));
      Wire.optional_mux_installed = false; // later I2C NACK is NOT absence
      bus.poll(guard, 71);
      faulted(guard);
    }
    {
      // A later CAP1188/accessory discovery upgrades mux isolation
      // permanently for this bus owner. Reinitialization during a transient
      // 0x71 NACK must NOT forget that 0x29 can also be exposed on that mux.
      Wire = TwoWire{};
      Wire.optional_mux_installed = false;
      desk_robot::TofBus bus;
      CHECK(bus.begin(21, 22, -1)); // legitimate five-sensor startup
      bus.note_optional_mux_present(); // independently observed later
      Wire.extras = 1; // previous optional 0x29 lane might remain selected
      const auto prior = Wire.tof_samples;
      CHECK(!bus.begin(21, 22, -1)); // temporary 0x71 NACK: fail closed
      CHECK(!bus.ready());
      CHECK(Wire.tof_samples == prior);
      desk_robot::CliffGuard guard;
      CHECK(guard.configure(calibration()));
      bus.poll(guard, 50);
      CHECK(!guard.evaluate(50));
      CHECK(!guard.try_rearm(50));
      // The same object can recover only once the previously known mux
      // acknowledges a verified disconnect of its selected branch.
      Wire.optional_mux_installed = true;
      CHECK(bus.begin(21, 22, -1));
      CHECK(bus.ready());
      CHECK(Wire.extras == 0);
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
    {
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      // A not-ready interrupt must not refresh any old floor observation.
      Wire.tof_ready = false;
      const auto prior = Wire.tof_samples;
      for (std::uint32_t n = 60; n < 72; ++n) bus.poll(guard, n);
      CHECK(Wire.tof_samples == prior);
      CHECK(!guard.evaluate(260)); // previously valid samples have expired
      CHECK(guard.fault() == desk_robot::CliffFault::StaleSample);
    }
    {
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      Wire.tof_raw_status = 1; // ST raw status 11 is the only accepted value
      bus.poll(guard, 60); // optional lane 5, read-only
      bus.poll(guard, 61); // critical floor 0
      CHECK(guard.fault() == desk_robot::CliffFault::InvalidSample);
      CHECK(!guard.evaluate(61));
      CHECK(!guard.try_rearm(61));
    }
    {
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      Wire.tof_force_mm = 8190; // VL53L0X no-reflection/out-of-range code
      bus.poll(guard, 60); // optional lane 5
      bus.poll(guard, 61); // critical floor 0
      CHECK(guard.fault() == desk_robot::CliffFault::InvalidSample);
      CHECK(!guard.evaluate(61));
    }
    {
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      CHECK(bus.begin(21, 22, -1));
      Wire.fail_imu_register_write = true;
      const auto before = Wire.imu_terminated_transmissions;
      CHECK(bus.probe_imu().family == 0);
      CHECK(Wire.failed_imu_writes > 0);
      CHECK(Wire.imu_terminated_transmissions - before >= Wire.failed_imu_writes);
      CHECK(Wire.ranges == 0 && Wire.extras == 0);
    }
    {
      // A rejected VL53L0X register pointer must use I2C STOP, not a
      // repeated START. All previous cliff evidence then becomes invalid.
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      const auto before = Wire.tof_register_stop_transmissions;
      Wire.fail_tof_register_write = true;
      bus.poll(guard, 60);
      CHECK(Wire.rejected_tof_register_writes >= 1);
      CHECK(Wire.tof_register_stop_transmissions > before);
      faulted(guard);
      Wire.fail_tof_register_write = false;
      for (std::uint32_t at = 61; at < 66; ++at) bus.poll(guard, at);
      CHECK(guard.try_rearm(70)); // requires five entirely new samples
    }
    {
      // The near-field floor minimum is inclusive: 15/29 fail, 30 passes.
      for (const std::uint16_t too_close : {15U, 29U}) {
        Wire = TwoWire{};
        desk_robot::TofBus bus;
        desk_robot::CliffGuard guard;
        ready(bus, guard);
        Wire.tof_force_mm = too_close;
        bus.poll(guard, 60); // diagnostic side lane
        bus.poll(guard, 61); // safety-critical floor lane
        CHECK(guard.fault() == desk_robot::CliffFault::InvalidSample);
        CHECK(!guard.evaluate(61));
        CHECK(!guard.try_rearm(61));
      }
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      Wire.tof_force_mm = 30;
      bus.poll(guard, 60);
      bus.poll(guard, 61);
      CHECK(guard.fault() == desk_robot::CliffFault::None);
      CHECK(guard.evaluate(61));
    }
    {
      // A mux ACK cannot qualify an uninitialized optical device.
      // Four independent Pololu startup failure paths must fail closed.
      for (int failure = 0; failure < 4; ++failure) {
        Wire = TwoWire{};
        bool& injected = failure == 0 ? VL53L0X::fail_init() :
                         failure == 1 ? VL53L0X::fail_timeout() :
                         failure == 2 ? VL53L0X::fail_timing_budget() :
                                        VL53L0X::fail_start_status();
        injected = true;
        desk_robot::TofBus bus;
        CHECK(!bus.begin(21, 22, -1));
        CHECK(!bus.ready());
        injected = false;
        desk_robot::CliffGuard guard;
        CHECK(guard.configure(calibration()));
        bus.poll(guard, 50);
        // MissingSample is already latched on configured guards. The failed
        // bus cannot replace that first fault with BusFailure or grant rearm.
        CHECK(guard.fault() != desk_robot::CliffFault::None);
        CHECK(!guard.evaluate(50));
        CHECK(!guard.try_rearm(50));
        for (std::uint8_t lane = 0; lane < 5; ++lane)
          CHECK(!guard.diagnostic(lane, 50).present);
      }
    }
    std::cout << "PASS cheap VL53L0X TCA9548A selected-channel readback and fail-closed cliff paths\n";
    return 0;
  } catch (const std::exception& ex) {
    std::cerr << "FAIL mux verification: " << ex.what() << '\n';
    return 1;
  }
}
