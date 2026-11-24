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
    {
      // A held SDA is not an ordinary NACK. Latch and invalidate BEFORE
      // touching GPIO; only a later poll clears the bus.
      Wire = TwoWire{};
      fake_i2c_lines() = FakeI2cLines{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      auto& lines = fake_i2c_lines();
      const auto samples = Wire.tof_samples;
      const auto transactions = Wire.transactions;
      lines.sda_stuck = true;
      lines.release_after_pulses = 9;
      bus.poll(guard, 60);
      faulted(guard);
      CHECK(Wire.transactions == transactions);
      CHECK(lines.restore_calls == 0 && lines.clear_pulses == 0);
      bus.poll(guard, 61);
      CHECK(lines.clear_pulses == 9 && lines.stops == 1);
      CHECK(!lines.unsafe_high && digitalRead(21) == HIGH &&
            digitalRead(22) == HIGH);
      CHECK(lines.restore_calls == 1 && Wire.tof_samples == samples);
      CHECK(Wire.transactions == transactions);
      CHECK(bus.new_optical_channel() == 255 && bus.new_extra_channel() == 255);
      CHECK(!guard.try_rearm(61));
      for (std::uint32_t at = 62; at < 68; ++at) bus.poll(guard, at);
      CHECK(!guard.evaluate(70)); // recovery is not automatic rearm
      CHECK(guard.try_rearm(70)); // fresh complete sweep + local operator
      fake_i2c_lines() = FakeI2cLines{};
    }
    {
      // Permanently held SDA: at most nine data-clear clocks per attempt,
      // bounded retry cadence and no valid cached motion evidence.
      Wire = TwoWire{};
      fake_i2c_lines() = FakeI2cLines{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      auto& lines = fake_i2c_lines();
      lines.sda_stuck = true;
      bus.poll(guard, 60);
      bus.poll(guard, 61);
      CHECK(lines.clear_pulses == 9 && lines.stops == 0);
      CHECK(!lines.unsafe_high && lines.restore_calls == 1);
      const auto transactions = Wire.transactions;
      for (std::uint32_t at = 62; at < 161; ++at) bus.poll(guard, at);
      CHECK(lines.restore_calls == 1 && Wire.transactions == transactions);
      CHECK(!guard.try_rearm(160));
      bus.poll(guard, 161);
      CHECK(lines.clear_pulses == 18 && lines.restore_calls == 2);
      faulted(guard);
      fake_i2c_lines() = FakeI2cLines{};
    }
    {
      Wire = TwoWire{};
      fake_i2c_lines() = FakeI2cLines{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      auto& lines = fake_i2c_lines();
      lines.scl_stuck = true;
      lines.sda_stuck = true;
      bus.poll(guard, 60);
      bus.poll(guard, 61);
      CHECK(lines.clear_pulses == 0 && lines.stops == 0);
      CHECK(!lines.unsafe_high && lines.restore_calls == 1);
      faulted(guard);
      fake_i2c_lines() = FakeI2cLines{};
    }
    {
      // A pin matrix restore failure must not let idle GPIOs qualify
      // samples. Shared Wire buffers are never torn down during recovery.
      Wire = TwoWire{};
      fake_i2c_lines() = FakeI2cLines{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      auto& lines = fake_i2c_lines();
      lines.sda_stuck = true;
      lines.release_after_pulses = 1;
      lines.fail_restore = true;
      bus.poll(guard, 60);
      bus.poll(guard, 61);
      const auto samples = Wire.tof_samples;
      CHECK(lines.clear_pulses == 1 && lines.stops == 1);
      bus.poll(guard, 62);
      CHECK(Wire.tof_samples == samples && lines.restore_calls == 1);
      CHECK(!guard.try_rearm(62));
      lines.fail_restore = false;
      bus.poll(guard, 161);
      CHECK(Wire.tof_samples == samples && lines.restore_calls == 2);
      for (std::uint32_t at = 162; at < 168; ++at) bus.poll(guard, at);
      CHECK(guard.try_rearm(170));
      fake_i2c_lines() = FakeI2cLines{};
    }
    {
      // An ordinary NACK on idle lines uses the checked mux retry, not
      // GPIO recovery. The original bus failure stays latched.
      Wire = TwoWire{};
      fake_i2c_lines() = FakeI2cLines{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      Wire.range_mux_write_nack = true;
      bus.poll(guard, 60);
      Wire.range_mux_write_nack = false;
      bus.poll(guard, 61);
      CHECK(fake_i2c_lines().restore_calls == 0);
      CHECK(fake_i2c_lines().clear_pulses == 0);
      CHECK(!guard.try_rearm(61));
    }
    {
      // A newly connected downstream lane can hang the bus at the mux
      // STOP. Skip the readback transaction, latch, then clear next poll.
      Wire = TwoWire{};
      fake_i2c_lines() = FakeI2cLines{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      auto& lines = fake_i2c_lines();
      lines.release_after_pulses = 9;
      Wire.hold_sda_on_range_mask = 32; // next side lane 5
      const auto samples = Wire.tof_samples;
      const auto transactions = Wire.transactions;
      bus.poll(guard, 60);
      CHECK(Wire.ranges == 32 && lines.sda_stuck);
      // Optional mux write/readback and range mux write only.
      CHECK(Wire.transactions - transactions == 3);
      CHECK(Wire.tof_samples == samples && lines.clear_pulses == 0);
      faulted(guard);
      bus.poll(guard, 61);
      CHECK(lines.clear_pulses == 9 && lines.stops == 1);
      CHECK(Wire.transactions - transactions == 3);
      for (std::uint32_t at = 62; at < 67; ++at) bus.poll(guard, at);
      CHECK(!guard.evaluate(70));
      CHECK(guard.try_rearm(70));
      fake_i2c_lines() = FakeI2cLines{};
    }
    {
      // Distinct results across all eight lanes expose wrong attribution
      // that identical nominal floor readings cannot catch. Alternate with
      // an accessory owner and skip one conversion without refreshing it.
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      const std::uint8_t order[] = {5, 0, 1, 2, 3, 4,
                                    6, 0, 1, 2, 3, 4,
                                    7, 0, 1, 2, 3, 4};
      for (std::uint32_t step = 0; step < sizeof(order); ++step) {
        const auto lane = order[step];
        const auto now = 60U + step;
        desk_robot::RangeDiagnostic before[8]{};
        desk_robot::TofOpticalDiagnostic optical_before[8]{};
        for (std::uint8_t i = 0; i < 8; ++i) {
          before[i] = i < 5 ? guard.diagnostic(i, now)
                            : bus.extra_diagnostic(i - 5, now);
          optical_before[i] = bus.optical_diagnostic(i, now);
        }
        // Simulate the previous accessory transaction leaving its same-
        // address CAP1188 lane selected, with the range mux disconnected.
        Wire.ranges = 0;
        Wire.extras = 1;
        Wire.cap_uses_0x29 = true;
        const auto cap_reads = Wire.cap_register_requests;
        const auto samples = Wire.tof_samples;
        Wire.tof_ready = step != 2; // floor 1 has no new conversion
        Wire.tof_force_mm = static_cast<std::uint16_t>(
            lane < 4 ? 35U + step : 200U + step);
        Wire.tof_ambient_97 = static_cast<std::uint16_t>(0x1200U + step);
        Wire.tof_signal_97 = static_cast<std::uint16_t>(0x3400U + step);
        bus.poll(guard, now);
        CHECK(Wire.extras == 0 && Wire.ranges == (1U << lane));
        CHECK(Wire.cap_register_requests == cap_reads);
        CHECK(!Wire.unsafe_parallel_mux);
        CHECK(Wire.tof_samples == samples + (Wire.tof_ready ? 1U : 0U));
        CHECK(bus.new_optical_channel() == (Wire.tof_ready ? lane : 255));
        CHECK(bus.new_extra_channel() ==
              (Wire.tof_ready && lane >= 5 ? lane - 5 : 255));
        for (std::uint8_t i = 0; i < 8; ++i) {
          const auto range = i < 5 ? guard.diagnostic(i, now)
                                   : bus.extra_diagnostic(i - 5, now);
          const auto optical = bus.optical_diagnostic(i, now);
          if (i == lane && Wire.tof_ready) {
            CHECK(range.present && range.valid && range.age_ms == 0);
            CHECK(range.distance_mm == Wire.tof_force_mm);
            CHECK(optical.present && optical.valid && optical.age_ms == 0);
            CHECK(optical.ambient_97 == Wire.tof_ambient_97);
            CHECK(optical.signal_97 == Wire.tof_signal_97);
          } else {
            CHECK(range.present == before[i].present);
            CHECK(range.valid == before[i].valid);
            CHECK(range.distance_mm == before[i].distance_mm);
            CHECK(range.age_ms == before[i].age_ms);
            CHECK(optical.present == optical_before[i].present);
            CHECK(optical.valid == optical_before[i].valid);
            CHECK(optical.age_ms == optical_before[i].age_ms);
            CHECK(optical.ambient_97 == optical_before[i].ambient_97);
            CHECK(optical.signal_97 == optical_before[i].signal_97);
          }
        }
        CHECK(guard.evaluate(now));
      }
      // This fake checks digital isolation and sample ownership only.
      // Actual bus-free timing and concurrent optical emitters need a bench.
    }
    std::cout << "PASS cheap VL53L0X TCA9548A selected-channel readback and fail-closed cliff paths\n";
    return 0;
  } catch (const std::exception& ex) {
    std::cerr << "FAIL mux verification: " << ex.what() << '\n';
    return 1;
  }
}
