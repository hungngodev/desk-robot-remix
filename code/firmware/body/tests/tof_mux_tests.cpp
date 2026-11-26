#include <cstdint>
#include <initializer_list>
#include <iostream>
#include <stdexcept>
#include "Wire.h"
#include "driver/i2c.h"
#include "TofBus.h"
#include "RangeTelemetry.h"
#include "CliffGuard.h"
#include "TofResult.h"
#include "../include/TofTransactions.h"

static_assert(desk_robot::kTofPollAndRecoveryBudgetMs < desk_robot::kMaxDriveMs,
              "ToF budget must fit the actual drive permit");
static_assert(desk_robot::kTofPollAndRecoveryBudgetMs < desk_robot::kWatchdogMs,
              "ToF budget must fit the actual command watchdog");

constexpr desk_robot::TofResult cold_range;
static_assert(cold_range.signal_97 == 0 && cold_range.ambient_97 == 0 &&
              cold_range.distance_mm == 0 && !cold_range.accepted, "Range must start invalid");

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
  CHECK(bus.boot_health_mask() == (DESK_ROBOT_EXTRA_RANGERS ? 0xffU : 0x1fU));
  CHECK(Wire.getTimeOut() == desk_robot::kTofWireTimeoutMs);
  CHECK(Wire.tof_init_timeouts.size() == (DESK_ROBOT_EXTRA_RANGERS ? 8U : 5U));
  for (auto timeout : Wire.tof_init_timeouts) CHECK(timeout == 80);
  CHECK(Wire.ranges == 0 && Wire.extras == 0);
  for (std::uint32_t i = 0; i < 5; ++i) {
    const auto before = Wire.transactions;
    bus.poll(guard, 10U * i);
    CHECK(Wire.transactions - before <= desk_robot::kTofMaxPollWireCalls);
  }
  CHECK(Wire.tof_samples == 5);
  CHECK(guard.try_rearm(50));
  CHECK(guard.evaluate(50));
}

static void check_shared_mux_recovery() {
  Wire = TwoWire{};
  fake_i2c_lines() = FakeI2cLines{};
  desk_robot::TofBus bus;
  desk_robot::CliffGuard guard;
  ready(bus, guard);
  const auto errors = bus.errors();
  bus.note_shared_mux_fault(guard);
  CHECK(bus.bus_accessible() && !bus.clients_accessible() && bus.degraded());
  CHECK(bus.errors() == errors + 1U);
  CHECK(!guard.try_rearm(60));
  for (std::uint32_t at = 61; at <= 65; ++at) bus.poll(guard, at);
  CHECK(bus.degraded() && !bus.clients_accessible());
  Wire.range_mux_write_nack = true;
  bus.poll(guard, 66);
  CHECK(bus.errors() == errors + 2U && bus.degraded());
  bus.poll(guard, 67);
  CHECK(bus.errors() == errors + 3U && bus.degraded());
  Wire.range_mux_write_nack = false;
  for (std::uint32_t at = 68; at <= 72; ++at) bus.poll(guard, at);
  CHECK(!bus.clients_accessible());
  for (std::uint32_t at = 73; at <= 78; ++at) bus.poll(guard, at);
  CHECK(bus.clients_accessible() && !bus.degraded());
  CHECK(bus.errors() == errors + 3U);
  CHECK(!guard.evaluate(78)); // transport recovery never clears the latch
  CHECK(guard.try_rearm(78));
  fake_i2c_lines() = FakeI2cLines{};
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

// Independent elapsed-time oracle over all lane dropout combinations.
// A scheduled poll is not evidence when the sensor has no ready conversion.
static void dropout_matrix_and_partial_mux_recovery() {
  const auto saved_clock = fake_arduino_millis();
  for (const std::uint32_t base : {0U, 0xffffff80U}) {
    for (unsigned mask = 0; mask < 256U; ++mask) {
      Wire = TwoWire{};
      fake_i2c_lines() = FakeI2cLines{};
      fake_arduino_millis() = base;
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      CHECK(guard.configure(calibration()));
      CHECK(bus.begin(21, 22, -1));
      const std::uint8_t order[] = {0, 1, 2, 3, 4, 5, 0, 1, 2,
                                   3, 4, 6, 0, 1, 2, 3, 4, 7};
      unsigned phase = 0;
      std::uint32_t last[8]{};
      const auto poll = [&](std::uint32_t now, unsigned absent) {
        const auto lane = order[phase++ % 18];
        const bool ready = (absent & (1U << lane)) == 0;
        fake_arduino_millis() = now;
        Wire.tof_ready = ready;
        const auto conversions = Wire.tof_samples;
        const auto errors = bus.errors();
        bus.poll(guard, now);
        CHECK(bus.last_channel() == lane);
        CHECK(bus.errors() == errors);
        CHECK(Wire.tof_samples == conversions + (ready ? 1U : 0U));
        CHECK(bus.new_optical_channel() == (ready ? lane : 255));
        CHECK(bus.new_extra_channel() == (ready && lane >= 5 ? lane - 5 : 255));
        if (ready) last[lane] = now;
      };
      for (unsigned step = 0; step < 18; ++step)
        poll(base + 5U * step, 0);
      CHECK(guard.try_rearm(base + 90U));
      std::uint8_t first_stale = desk_robot::kNoFaultSensor;
      for (unsigned step = 0; step < 90; ++step) {
        const auto now = base + 90U + 5U * step;
        if (first_stale == desk_robot::kNoFaultSensor) {
          for (std::uint8_t lane = 0; lane < 5; ++lane) {
            if (now - last[lane] >= 200U) {
              first_stale = lane;
              break;
            }
          }
        }
        poll(now, mask);
        CHECK(guard.evaluate(now) == (first_stale == desk_robot::kNoFaultSensor));
        if (first_stale != desk_robot::kNoFaultSensor) {
          CHECK(guard.fault() == desk_robot::CliffFault::StaleSample);
          CHECK(guard.fault_sensor() == first_stale);
          CHECK(!guard.try_rearm(now));
        }
        for (std::uint8_t lane = 0; lane < 8; ++lane) {
          const auto raw = bus.optical_diagnostic(lane, now);
          const auto age = now - last[lane];
          CHECK(raw.present && raw.age_ms == age);
          CHECK(raw.valid == (lane < 5 ? age < 200U : age <= 350U));
          if (lane >= 5) {
            const auto extra = bus.extra_diagnostic(lane - 5, now);
            CHECK(extra.present && extra.age_ms == age);
            CHECK(extra.valid == (age <= 350U));
          }
        }
      }
      CHECK((first_stale != desk_robot::kNoFaultSensor) == ((mask & 31U) != 0));
      // Inject a shared mux failure after the independent lane dropouts.
      // The prior fault, if any, remains first; all cached evidence is revoked.
      const auto fault_time = base + 540U;
      const auto errors = bus.errors();
      fake_arduino_millis() = fault_time;
      Wire.tof_ready = true;
      if ((mask & 1U) != 0) Wire.next_stop_timeout_address = 0x70;
      else Wire.next_read_timeout_address = 0x70;
      bus.poll(guard, fault_time);
      CHECK(bus.last_channel() == order[phase++ % 18]);
      CHECK(bus.errors() == errors + 1);
      CHECK(bus.new_optical_channel() == 255 && bus.new_extra_channel() == 255);
      CHECK(guard.fault() == (first_stale == desk_robot::kNoFaultSensor
          ? desk_robot::CliffFault::BusFailure : desk_robot::CliffFault::StaleSample));
      for (std::uint8_t lane = 0; lane < 8; ++lane) {
        CHECK(!bus.optical_diagnostic(lane, fault_time).valid);
        if (lane < 5) CHECK(!guard.diagnostic(lane, fault_time).present);
        else CHECK(!bus.extra_diagnostic(lane - 5, fault_time).valid);
      }
      CHECK(!guard.try_rearm(fault_time));
      // The injected fault consumed lane zero, but failed() restarts the
      // critical sweep at lane zero without advancing the optional rotation.
      CHECK(phase % 6 == 1U);
      --phase;
      // During the first recovery sweep the usual optional slot is skipped.
      for (unsigned step = 1; step <= 5; ++step)
        poll(fault_time + 5U * step, 0);
      CHECK(bus.degraded());
      phase -= 5;
      for (unsigned step = 6; step <= 23; ++step)
        poll(fault_time + 5U * step, 0);
      CHECK(!bus.degraded());
      CHECK(!guard.evaluate(fault_time + 115U));
      CHECK(guard.try_rearm(fault_time + 115U));
      CHECK(guard.evaluate(fault_time + 115U));
    }
  }
  fake_arduino_millis() = saved_clock;
}

// Consecutive same-address reads must follow the actual selected lane.
static void fast_floor_lane_swap() {
  const auto saved_clock = fake_arduino_millis();
  for (unsigned failure = 0; failure < 4; ++failure) {
    Wire = TwoWire{};
    fake_i2c_lines() = FakeI2cLines{};
    fake_arduino_millis() = 100;
    desk_robot::TofBus bus;
    desk_robot::CliffGuard guard;
    ready(bus, guard);
    bus.poll(guard, 60); // complete side-lane slot before next floor sweep
    Wire.tof_lane_mm[0] = 36;
    Wire.tof_lane_mm[1] = 79;
    const auto now = millis();
    bus.poll(guard, now);
    CHECK(Wire.ranges == 1 && bus.last_channel() == 0);
    CHECK(guard.diagnostic(0, now).distance_mm == 36);
    CHECK(guard.diagnostic(1, now).distance_mm == 45);
    CHECK(guard.diagnostic(1, now).age_ms > 0);
    CHECK(guard.evaluate(now));
    const auto samples = Wire.tof_samples;
    const auto clears = Wire.tof_register_stop_transmissions;
    const auto errors = bus.errors();
    // Leave lane 0 connected; never simulate the new selection in the test.
    Wire.range_mux_stuck = failure == 1;
    Wire.range_mux_write_nack = failure == 2;
    Wire.range_mux_read_nack = failure == 3;
    bus.poll(guard, now); // no artificial settling delay between polls
    CHECK(bus.last_channel() == 1);
    CHECK(!Wire.unsafe_parallel_mux);
    if (failure == 0) {
      CHECK(Wire.ranges == 2 && bus.errors() == errors);
      CHECK(Wire.tof_samples == samples + 1);
      CHECK(Wire.tof_register_stop_transmissions == clears + 1);
      CHECK(bus.new_optical_channel() == 1);
      CHECK(guard.diagnostic(0, now).distance_mm == 36);
      CHECK(guard.diagnostic(1, now).distance_mm == 79);
      CHECK(guard.diagnostic(1, now).age_ms == 0);
      CHECK(guard.evaluate(now));
    } else {
      CHECK(Wire.ranges == (failure == 3 ? 2 : 1));
      CHECK(bus.errors() == errors + 1);
      CHECK(Wire.tof_samples == samples);
      CHECK(Wire.tof_register_stop_transmissions == clears);
      CHECK(bus.new_optical_channel() == 255);
      CHECK(!bus.optical_diagnostic(0, now).valid);
      CHECK(!bus.optical_diagnostic(1, now).valid);
      CHECK(!guard.diagnostic(0, now).present);
      CHECK(!guard.diagnostic(1, now).present);
      CHECK(guard.fault() == desk_robot::CliffFault::BusFailure);
      CHECK(!guard.evaluate(now) && !guard.try_rearm(now));
    }
  }
  fake_arduino_millis() = saved_clock;
}

// Range interrupt errors are explicit invalid samples, unlike a sensor that
// simply has no fresh conversion. Exercise independent failures on all eight
// lanes in one scan, including optional errors preceding a mandatory fault.
static void check_explicit_error_mask(unsigned mask) {
  Wire = TwoWire{};
  fake_i2c_lines() = FakeI2cLines{};
  fake_arduino_millis() = 0;
  desk_robot::TofBus bus;
  desk_robot::CliffGuard guard;
  ready(bus, guard);
  desk_robot::BodyControl control;
  const std::uint8_t order[] = {5, 0, 1, 2, 3, 4, 6, 0, 1,
                                2, 3, 4, 7, 0, 1, 2, 3, 4};
  std::uint32_t now = 60;
  const auto poll = [&](std::uint8_t lane, bool fault) {
    fake_arduino_millis() = now++;
    Wire.tof_interrupt_error_bits = fault ? 0x08 : 0;
    const auto errors = bus.errors();
    bus.poll(guard, now - 1U);
    desk_robot::publish_range_telemetry(bus, control, now - 1U, bus.errors() != errors);
    CHECK(bus.errors() == errors);
    CHECK(bus.last_channel() == lane);
    CHECK(bus.rejected_channel() == (fault ? lane : 255));
    CHECK(bus.new_optical_channel() == (fault ? 255 : lane));
    CHECK(bus.new_extra_channel() == (!fault && lane >= 5 ? lane - 5 : 255));
    CHECK(control.state().optical[lane].present);
    CHECK(control.state().optical[lane].valid == !fault);
    if (lane >= 5) CHECK(control.state().side_valid[lane - 5] == !fault);
  };
  for (const auto lane : order) poll(lane, false);
  std::uint8_t first = 255;
  for (const auto lane : order) {
    const bool fault = (mask & (1U << lane)) != 0;
    if (fault && lane < 5 && first == 255) first = lane;
    poll(lane, fault);
    CHECK(guard.fault_sensor() == first); // immediate, before evaluate()
    CHECK(guard.evaluate(now) == (first == 255));
    if (first != 255) CHECK(!guard.try_rearm(now));
  }
  CHECK((first != 255) == ((mask & 0x1fU) != 0));
  for (std::uint8_t lane = 0; lane < 8; ++lane) {
    const bool valid = (mask & (1U << lane)) == 0;
    CHECK(bus.optical_diagnostic(lane, now).valid == valid);
    if (lane < 5) CHECK(guard.diagnostic(lane, now).valid == valid);
    else CHECK(bus.extra_diagnostic(lane - 5, now).valid == valid);
  }
  for (const auto lane : order) {
    poll(lane, false);
    CHECK(guard.evaluate(now) == (first == 255));
    CHECK(guard.fault_sensor() == first);
  }
  CHECK(guard.try_rearm(now));
  CHECK(guard.evaluate(now));
}

static void explicit_error_mask_matrix() {
  const auto saved_clock = fake_arduino_millis();
  for (unsigned mask = 0; mask < 256U; ++mask) {
    try {
      check_explicit_error_mask(mask);
    } catch (const std::exception&) {
      std::cerr << "Explicit range error mask: " << mask << '\n';
      throw;
    }
  }
  fake_arduino_millis() = saved_clock;
}

static void raw_range_word_acceptance_is_exact() {
  // Exhaust the 16-bit wire domain, including both edges and the 8190
  // no-return word. Keep the expected interval independent of production.
  for (std::uint32_t mm = 0; mm <= 65535U; ++mm) {
    std::uint8_t raw[12]{};
    raw[0] = 11U << 3;
    raw[7] = 32U;
    raw[8] = 0x45U;
    raw[9] = 0x67U;
    raw[10] = static_cast<std::uint8_t>(mm >> 8);
    raw[11] = static_cast<std::uint8_t>(mm & 0xffU);
    const auto decoded = desk_robot::decode_tof_result(raw);
    CHECK(decoded.distance_mm == mm);
    CHECK(decoded.signal_97 == 32U && decoded.ambient_97 == 0x4567U);
    CHECK(decoded.accepted == (mm >= 30U && mm <= 1300U));
  }
}

// A narrow transport probe for the real mux helpers, independent of the
// larger sensor emulator. It records STOP and readback per fitted address.
struct MuxWriteProbe {
  std::uint8_t masks[2]{};
  unsigned stops[2]{};
  unsigned reads[2]{};
  unsigned index = 0;
  std::uint8_t pending = 0;
  int next_error = 0;
  int read_override = -1;

  void beginTransmission(std::uint8_t address) {
    CHECK(address == 0x70 || address == 0x71);
    index = address - 0x70;
  }
  unsigned write(std::uint8_t mask) { pending = mask; return 1; }
  int endTransmission(bool stop) {
    CHECK(stop);
    ++stops[index];
    const int error = next_error;
    next_error = 0;
    if (!error) masks[index] = pending;
    return error;
  }
  unsigned requestFrom(std::uint8_t address, std::size_t count, bool stop) {
    CHECK(address == 0x70 + index && count == 1 && stop);
    ++reads[index];
    return 1;
  }
  int available() const { return 1; }
  int read() const { return read_override < 0 ? masks[index] : read_override; }
};

static void checked_dual_mux_deselect_after_transfer_error() {
  const auto idle = [] { return true; };
  for (const std::uint8_t address : {0x70, 0x71}) {
    for (unsigned lane = 0; lane < 8; ++lane) {
      for (const int error : {2, 5}) { // address NACK, transaction timeout
        MuxWriteProbe wire;
        const auto mask = static_cast<std::uint8_t>(1U << lane);
        CHECK(desk_robot::checked_mux_mask(wire, address, mask, idle));
        wire.next_error = error;
        CHECK(!desk_robot::checked_mux_mask(wire, address, 0, idle));
        CHECK(wire.masks[address - 0x70] == mask);
        CHECK(wire.reads[address - 0x70] == 1);
        const auto range_stops = wire.stops[0];
        const auto accessory_stops = wire.stops[1];
        const auto range_reads = wire.reads[0];
        const auto accessory_reads = wire.reads[1];
        CHECK(desk_robot::checked_mux_mask(wire, 0x71, 0, idle));
        CHECK(desk_robot::checked_mux_mask(wire, 0x70, 0, idle));
        CHECK(wire.masks[0] == 0 && wire.masks[1] == 0);
        CHECK(wire.stops[0] == range_stops + 1 && wire.stops[1] == accessory_stops + 1);
        CHECK(wire.reads[0] == range_reads + 1 && wire.reads[1] == accessory_reads + 1);
        wire.read_override = mask;
        CHECK(!desk_robot::checked_mux_mask(wire, address, 0, idle));
      }
    }
  }
}

static void checked_mux_staggered_nacks() {
  const auto idle = [] { return true; };
  for (unsigned accessory = 0; accessory < 8; ++accessory) {
    for (unsigned range = 0; range < 8; ++range) {
      MuxWriteProbe wire;
      const auto accessory_mask = static_cast<std::uint8_t>(1U << accessory);
      const auto range_mask = static_cast<std::uint8_t>(1U << range);
      CHECK(desk_robot::checked_mux_mask(wire, 0x71, accessory_mask, idle));
      // NACKed closes must not change the retained accessory mask or read it back.
      for (unsigned attempt = 1; attempt <= 3; ++attempt) {
        wire.next_error = 2;
        CHECK(!desk_robot::checked_mux_mask(wire, 0x71, 0, idle));
        CHECK(wire.masks[0] == 0 && wire.masks[1] == accessory_mask);
        CHECK(wire.stops[0] == 0 && wire.stops[1] == attempt + 1);
        CHECK(wire.reads[0] == 0 && wire.reads[1] == 1);
      }
      // Restore accessory isolation first, then NACK the range selection.
      CHECK(desk_robot::checked_mux_mask(wire, 0x71, 0, idle));
      wire.next_error = 2;
      CHECK(!desk_robot::checked_mux_mask(wire, 0x70, range_mask, idle));
      CHECK(wire.masks[0] == 0 && wire.masks[1] == 0);
      CHECK(wire.stops[0] == 1 && wire.stops[1] == 5);
      CHECK(wire.reads[0] == 0 && wire.reads[1] == 2);
      // A subsequent verified selection affects only the range mux.
      CHECK(desk_robot::checked_mux_mask(wire, 0x71, 0, idle));
      CHECK(desk_robot::checked_mux_mask(wire, 0x70, range_mask, idle));
      CHECK(wire.masks[0] == range_mask && wire.masks[1] == 0);
      CHECK(wire.stops[0] == 2 && wire.stops[1] == 6);
      CHECK(wire.reads[0] == 1 && wire.reads[1] == 3);
    }
  }
}

int main() {
  try {
    checked_dual_mux_deselect_after_transfer_error();
    checked_mux_staggered_nacks();
    raw_range_word_acceptance_is_exact();
    fast_floor_lane_swap();
    check_shared_mux_recovery();
    dropout_matrix_and_partial_mux_recovery();
    explicit_error_mask_matrix();
    {
      // A later verified close must not erase a transient overlap,
      // regardless of which mux was enabled last.
      for (const std::uint8_t first : {0x70, 0x71}) {
        TwoWire transport;
        const std::uint8_t second = first == 0x70 ? 0x71 : 0x70;
        const auto select_mask = [&transport](std::uint8_t address,
                                               std::uint8_t mask) {
          transport.beginTransmission(address);
          CHECK(transport.write(mask) == 1);
          CHECK(transport.endTransmission(true) == 0);
        };
        select_mask(first, 1);
        CHECK(!transport.unsafe_parallel_mux);
        select_mask(second, 1);
        CHECK(transport.ranges == 1 && transport.extras == 1);
        CHECK(transport.unsafe_parallel_mux);
        select_mask(first, 0);
        select_mask(second, 0);
        CHECK(transport.unsafe_parallel_mux);
        transport = TwoWire{};
        select_mask(first, 1);
        select_mask(first, 0);
        select_mask(second, 1);
        CHECK(!transport.unsafe_parallel_mux);
      }
    }
    {
      // The pin-matrix fake must do more than return ESP_OK.
      auto& lines = fake_i2c_lines();
      lines = FakeI2cLines{};
      CHECK(digitalRead(21) == HIGH && digitalRead(22) == HIGH);
      pinMode(21, OUTPUT);
      pinMode(22, OUTPUT);
      digitalWrite(21, LOW);
      digitalWrite(22, LOW);
      lines.sda_stuck = true;
      lines.fail_restore = true;
      CHECK(i2c_set_pin(I2C_NUM_0, 21, 22, true, true, I2C_MODE_MASTER) != ESP_OK);
      CHECK(lines.sda_driven_low && lines.scl_driven_low);
      CHECK(lines.sda_mode == OUTPUT && lines.scl_mode == OUTPUT);
      lines.fail_restore = false;
      CHECK(i2c_set_pin(I2C_NUM_0, 22, 21, true, true, I2C_MODE_MASTER) != ESP_OK);
      CHECK(lines.sda_driven_low && lines.scl_driven_low);
      CHECK(i2c_set_pin(I2C_NUM_0, 21, 22, true, true, I2C_MODE_MASTER) == ESP_OK);
      CHECK(lines.sda_mode == (OUTPUT_OPEN_DRAIN | PULLUP));
      CHECK(lines.scl_mode == (OUTPUT_OPEN_DRAIN | PULLUP));
      CHECK(!lines.sda_driven_low && !lines.scl_driven_low);
      CHECK(digitalRead(21) == LOW && digitalRead(22) == HIGH);
      CHECK(lines.restore_calls == 3 && lines.clear_attempts == 0 &&
            lines.clear_pulses == 0 && lines.stops == 0 && !lines.unsafe_high);
      lines.sda_stuck = false;
      CHECK(digitalRead(21) == HIGH);
      lines = FakeI2cLines{};
    }
    {
      // A slave can hold SCL on the STOP setup edge, not only data clocks.
      for (unsigned released = 1; released <= 9; ++released) {
        auto& lines = fake_i2c_lines();
        lines = FakeI2cLines{};
        lines.sda_stuck = true;
        lines.release_after_pulses = released;
        lines.hold_scl_after_pulses = released;
        for (unsigned pulse = 0; pulse < released; ++pulse) {
          digitalWrite(22, LOW);
          digitalWrite(22, HIGH);
        }
        CHECK(digitalRead(21) == HIGH && digitalRead(22) == HIGH);
        digitalWrite(22, LOW);
        digitalWrite(21, LOW);
        digitalWrite(22, HIGH);
        CHECK(digitalRead(22) == LOW);
        digitalWrite(21, HIGH);
        CHECK(lines.stops == 0 && !lines.unsafe_high);
        CHECK(lines.clear_attempts == released && lines.clear_pulses == released);
        lines = FakeI2cLines{};
      }
    }
    {
      // Verify the transport fake itself before trusting driver regressions.
      Wire = TwoWire{};
      CHECK(Wire.getTimeOut() == 50);
      Wire.setTimeOut(15);
      CHECK(Wire.getTimeOut() == 15);
      Wire.ranges = 1;
      Wire.next_stop_timeout_address = 0x70;
      Wire.beginTransmission(0x70);
      CHECK(Wire.write(2) == 1);
      CHECK(Wire.endTransmission() == 5);
      CHECK(Wire.ranges == 1);
      Wire.next_read_timeout_address = 0x70;
      CHECK(Wire.requestFrom(0x70, 1) == 0);
      CHECK(Wire.available() == 0 && Wire.read() == -1);
      CHECK(Wire.requestFrom(0x70, 1) == 1);
      CHECK(Wire.read() == 1);
      CHECK(Wire.requestFrom(0x70, 2) == 0);
      CHECK(Wire.available() == 0 && Wire.read() == -1);
      Wire.beginTransmission(0x29);
      CHECK(Wire.write(0x14) == 1);
      CHECK(Wire.endTransmission(false) == 0);
      Wire.next_short_read_address = 0x29;
      Wire.next_short_read_request = 12;
      Wire.next_short_read_count = 11;
      CHECK(Wire.requestFrom(0x29, 12) == 11);
      CHECK(Wire.available() == 11);
      for (int i = 0; i < 11; ++i) CHECK(Wire.read() >= 0);
      CHECK(Wire.read() == -1);
      CHECK(Wire.requestFrom(0x29, 12) == 12);

      TwoWire other;
      VL53L0X sensor;
      CHECK(sensor.getBus() == &Wire && sensor.getTimeout() == 0);
      sensor.setBus(&other);
      sensor.setTimeout(80);
      CHECK(sensor.getBus() == &other && sensor.getTimeout() == 80);
      CHECK(!sensor.init());
      other.ranges = 1;
      CHECK(sensor.init() && other.tof_init_timeouts.size() == 1);
      CHECK(other.tof_init_timeouts[0] == 80);
      VL53L0X::fail_timeout() = true;
      CHECK(sensor.timeoutOccurred() && !sensor.timeoutOccurred());
      fake_arduino_millis() = 0xfffffffeU;
      const auto before = millis();
      fake_arduino_millis() = 1U;
      CHECK(millis() - before == 3U);
      fake_arduino_millis() = 0;
    }
    {
      // Pinned Wire defers the repeated START until requestFrom().
      TwoWire transfer;
      transfer.ranges = 1;
      transfer.tof_register = 0x13;
      transfer.beginTransmission(0x29);
      CHECK(transfer.write(0x14) == 1);
      CHECK(transfer.endTransmission(false) == 0);
      CHECK(transfer.tof_register == 0x13);
      CHECK(transfer.requestFrom(0x70, 1) == 0);
      CHECK(transfer.tof_register == 0x13);
      transfer.next_transfer_nack_address = 0x29;
      CHECK(transfer.requestFrom(0x29, 12) == 0);
      CHECK(transfer.available() == 0 && transfer.read() == -1);
      CHECK(transfer.tof_register == 0x13 && transfer.tof_samples == 0);
      CHECK(transfer.next_transfer_nack_address == -1);
      transfer.beginTransmission(0x29);
      CHECK(transfer.write(0x14) == 1);
      CHECK(transfer.endTransmission(false) == 0);
      CHECK(transfer.requestFrom(0x29, 12) == 12);
      CHECK(transfer.tof_register == 0x14 && transfer.tof_samples == 1);
    }
    {
      // Both TCA9548A masks remain unchanged without the explicit STOP.
      for (const std::uint8_t mux : {0x70, 0x71}) {
        TwoWire transfer;
        transfer.beginTransmission(mux);
        CHECK(transfer.write(2) == 1);
        CHECK(transfer.endTransmission(false) == 0);
        CHECK(transfer.ranges == 0 && transfer.extras == 0);
        CHECK(transfer.requestFrom(mux, 1) == 0);
        CHECK(transfer.ranges == 0 && transfer.extras == 0);
        transfer.beginTransmission(mux);
        CHECK(transfer.write(2) == 1);
        CHECK(transfer.endTransmission(true) == 0);
        CHECK(transfer.requestFrom(mux, 1) == 1);
        CHECK(transfer.read() == 2);
      }
    }
    {
      // Zero-length requests cannot consume a MAX30102 read-to-clear
      // register; a multi-byte NACK must be visible after buffering.
      TwoWire transfer;
      transfer.extras = 1;
      transfer.pulse_interrupt_status = 0x80;
      const auto status_pointer = [&transfer]() {
        transfer.beginTransmission(0x57);
        CHECK(transfer.write(0x00) == 1);
        CHECK(transfer.endTransmission(false) == 0);
      };
      status_pointer();
      CHECK(transfer.requestFrom(0x57, 0) == 0);
      CHECK(transfer.pulse_interrupt_status == 0x80);
      status_pointer();
      CHECK(transfer.requestFrom(0x57, 1) == 1);
      CHECK(transfer.read() == 0x80 && transfer.pulse_interrupt_status == 0);
      transfer.extras = 4;
      const auto config = [&transfer]() {
        transfer.beginTransmission(0x48);
        CHECK(transfer.write(0x01) == 1 && transfer.write(0xd3) == 1 &&
              transfer.write(0x83) == 1);
        return transfer.endTransmission(true);
      };
      transfer.next_transfer_nack_address = 0x48;
      CHECK(config() == 2 && transfer.ads_config_high == 0xc3);
      CHECK(config() == 0 && transfer.ads_config_high == 0xd3);
    }
    {
      // A successful result must not hide expiry of the previous clearance
      // during a stretched I2C transfer. Test both sides of the deadline and
      // millis rollover using the real scheduler, bus driver and guard.
      const auto saved_clock = fake_arduino_millis();
      for (const std::uint32_t base : {0U, 0xffffff80U}) {
        for (const std::uint32_t delay_ms : {4U, 5U, 10U}) {
          Wire = TwoWire{};
          fake_i2c_lines() = FakeI2cLines{};
          desk_robot::TofBus bus;
          desk_robot::CliffGuard guard;
          CHECK(guard.configure(calibration()));
          CHECK(bus.begin(21, 22, -1));
          for (std::uint32_t i = 0; i < 5; ++i) {
            fake_arduino_millis() = base + 20U * i;
            bus.poll(guard, millis());
          }
          // Optional work is admitted only strictly before half of the
          // 200ms freshness window. Keep lane 0's original expiry intact.
          CHECK(guard.try_rearm(base + 99U));
#if DESK_ROBOT_EXTRA_RANGERS
          fake_arduino_millis() = base + 99U;
          bus.poll(guard, millis());
          CHECK(bus.last_channel() == 5);
#endif
          fake_arduino_millis() = base + 195U;
          CHECK(guard.evaluate(millis()));
          Wire.next_tof_result_delay_ms = delay_ms;
          const auto errors = bus.errors();
          bus.poll(guard, millis());
          CHECK(bus.last_channel() == 0);
          CHECK(bus.errors() == errors);
          CHECK(Wire.next_tof_result_delay_ms == 0);
          CHECK(millis() == base + 195U + delay_ms);
          CHECK(guard.diagnostic(0, millis()).age_ms == delay_ms);
          CHECK(guard.evaluate(millis()) == (delay_ms < 5U));
          CHECK(guard.fault() == (delay_ms < 5U ? desk_robot::CliffFault::None :
                                                  desk_robot::CliffFault::StaleSample));
        }
      }
      fake_arduino_millis() = saved_clock;
    }
    {
      // A timeout, NACK or partial transfer cannot authorize a new optical sample.
      for (int failure = 0; failure < 8; ++failure) {
        Wire = TwoWire{};
        fake_i2c_lines() = FakeI2cLines{};
        desk_robot::TofBus bus;
        desk_robot::CliffGuard guard;
        ready(bus, guard);
        if (failure == 3) Wire.next_transfer_nack_address = 0x29;
        if (failure == 4) Wire.next_read_nack_address = 0x70;
        if (failure == 5) {
          // Register pointer is accepted; interrupt clear data is rejected.
          Wire.next_short_write_address = 0x29;
          Wire.next_short_write_after = 1;
        }
        if (failure == 6) {
          // An empty, ACKed optional-mux write is not a verified close.
          Wire.next_short_write_address = 0x71;
          Wire.next_short_write_after = 0;
        }
        if (failure == 7) Wire.next_read_nack_address = 0x71;
        if (failure == 0) Wire.next_stop_timeout_address = 0x70;
        if (failure == 1) Wire.next_read_timeout_address = 0x29;
        if (failure == 2) {
          Wire.next_short_read_address = 0x29;
          Wire.next_short_read_request = 12;
          Wire.next_short_read_count = 11;
        }
        fake_arduino_millis() = 60;
        const auto before = millis();
        bus.poll(guard, before);
        // Timeout paths consume the configured budget; NACK and partial
        // transfers are modeled as immediate errors by the transport fake.
        CHECK(millis() - before == (failure < 2 ? 10U : 0U));
        CHECK(!Wire.repeated_start_pending);
        CHECK(Wire.next_read_nack_address == -1);
        CHECK(Wire.next_short_write_address == -1);
        CHECK(bus.new_optical_channel() == 255);
        CHECK(bus.new_extra_channel() == 255);
        faulted(guard);
      }
    }
    {
      // Exercise both sensor timeout seams on every physical mux lane.
      // The host fake models one expired Wire transaction, not electrical
      // clock stretching or end-to-end motor stopping time.
      const auto saved_clock = fake_arduino_millis();
      const std::uint8_t order[] = {5, 0, 1, 2, 3, 4, 6, 0, 1, 2, 3, 4,
                                    7, 0, 1, 2, 3, 4};
      for (const bool clear_timeout : {false, true}) {
        for (std::uint8_t target = 0; target < 8; ++target) {
          Wire = TwoWire{};
          fake_i2c_lines() = FakeI2cLines{};
          fake_arduino_millis() = 0;
          desk_robot::TofBus bus;
          desk_robot::CliffGuard guard;
          ready(bus, guard);
          auto poll = [&](std::uint32_t at) {
            fake_arduino_millis() = at;
            bus.poll(guard, at);
          };
          std::uint32_t now = 60;
          for (const auto lane : order) {
            poll(now++);
            CHECK(bus.last_channel() == lane);
          }
          for (const auto lane : order) {
            if (lane == target) break;
            poll(now++);
          }
          CHECK(guard.evaluate(now));
          CHECK(bus.optical_diagnostic(target, now).valid);
          const auto samples = Wire.tof_samples;
          const auto stops = Wire.tof_register_stop_transmissions;
          const auto transactions = Wire.transactions;
          const auto errors = bus.errors();
          if (clear_timeout) Wire.next_stop_timeout_address = 0x29;
          else Wire.next_read_timeout_address = 0x29;
          poll(now);
          CHECK(millis() - now == 10U);
          CHECK(bus.last_channel() == target);
          CHECK(Wire.ranges == (1U << target) && Wire.extras == 0);
          CHECK(!Wire.repeated_start_pending);
          CHECK(Wire.next_read_timeout_address == -1);
          CHECK(Wire.next_stop_timeout_address == -1);
          CHECK(Wire.tof_samples == samples + (clear_timeout ? 1U : 0U));
          CHECK(Wire.tof_register_stop_transmissions == stops + (clear_timeout ? 1U : 0U));
          CHECK(Wire.transactions - transactions == (clear_timeout ? 9U : 6U));
          CHECK(Wire.transactions - transactions <= desk_robot::kTofMaxPollWireCalls);
          CHECK(bus.errors() == errors + 1);
          CHECK(bus.new_optical_channel() == 255 && bus.new_extra_channel() == 255);
          for (std::uint8_t lane = 0; lane < 8; ++lane)
            CHECK(!bus.optical_diagnostic(lane, now).valid);
          for (std::uint8_t lane = 0; lane < 5; ++lane)
            CHECK(!guard.diagnostic(lane, now).present);
          for (std::uint8_t lane = 0; lane < 3; ++lane)
            CHECK(!bus.extra_diagnostic(lane, now).valid);
          CHECK(guard.fault() == desk_robot::CliffFault::BusFailure);
          CHECK(!guard.evaluate(millis()));
          CHECK(!guard.try_rearm(millis()));
          now = millis();
          for (unsigned i = 0; i < 7; ++i) poll(++now);
          CHECK(!guard.evaluate(now)); // fresh data alone cannot clear STOP
          CHECK(guard.try_rearm(now)); // explicit rearm after fresh critical sweep
          CHECK(!Wire.repeated_start_pending && !Wire.unsafe_parallel_mux);
        }
      }
      fake_arduino_millis() = saved_clock;
    }
    {
      // A full millis revolution must not make expired diagnostics fresh.
      Wire = TwoWire{};
      fake_i2c_lines() = FakeI2cLines{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      bus.poll(guard, 60);
      CHECK(bus.extra_diagnostic(0, 60).valid);
      CHECK(bus.optical_diagnostic(5, 60).valid);
      Wire.tof_ready = false;
      bus.poll(guard, 411);
      CHECK(!bus.extra_diagnostic(0, 411).valid);
      CHECK(!bus.optical_diagnostic(5, 411).valid);
      CHECK(!guard.evaluate(411));
      bus.poll(guard, 0x7fffffffU);
      bus.poll(guard, 0xfffffff0U);
      bus.poll(guard, 61);
      CHECK(!bus.extra_diagnostic(0, 61).valid);
      CHECK(!bus.optical_diagnostic(5, 61).valid);
      CHECK(!bus.optical_diagnostic(0, 61).valid);
      CHECK(bus.optical_diagnostic(5, 61).ambient_97 == 0x0123);
      CHECK(!guard.evaluate(61));
      Wire.tof_ready = true;
      for (std::uint32_t i = 62; i < 86; ++i) bus.poll(guard, i);
      CHECK(bus.extra_diagnostic(0, 86).valid);
      CHECK(bus.optical_diagnostic(5, 86).valid);
      CHECK(!guard.evaluate(86));
    }
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
      // An accessory can hold a shared line AFTER a successful ToF poll.
      // Revoking cached evidence must also revoke its new-sample markers,
      // otherwise a later consumer could count an invalidated acquisition.
      Wire = TwoWire{};
      fake_i2c_lines() = FakeI2cLines{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      bus.poll(guard, 60);  // side lane 5
      CHECK(bus.new_extra_channel() == 0 && bus.new_optical_channel() == 5);
      CHECK(bus.extra_diagnostic(0, 60).valid);
      CHECK(bus.optical_diagnostic(5, 60).valid);
      const auto before = Wire.transactions;
      const auto errors = bus.errors();
      fake_i2c_lines().sda_stuck = true;
      bus.observe_shared_bus_fault(guard);
      CHECK(bus.new_extra_channel() == 255 && bus.new_optical_channel() == 255);
      CHECK(!bus.extra_diagnostic(0, 60).valid);
      CHECK(!bus.optical_diagnostic(5, 60).valid);
      CHECK(!bus.optical_diagnostic(0, 60).valid);
      CHECK(Wire.transactions == before && bus.errors() == errors + 1);
      faulted(guard);
      bus.observe_shared_bus_fault(guard);
      CHECK(bus.errors() == errors + 1);
      fake_i2c_lines() = FakeI2cLines{};
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
      // Two critical recovery sweeps precede side 6; lane 4 is due at 91.
      for (std::uint32_t at = 70; at <= 91; ++at) {
        bus.poll(guard, at);
        CHECK(!bus.extra_diagnostic(0, at).valid);
        if (at <= 79) CHECK(bus.last_channel() == (at - 70U) % 5U);
      }
      CHECK(bus.last_channel() == 4);
      bus.poll(guard, 92);  // first independent side 5 conversion
      CHECK(bus.last_channel() == 5 && bus.new_extra_channel() == 0);
      CHECK(bus.extra_diagnostic(0, 92).valid);
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
      // Full product predeclares 0x71: absence at cold boot must not
      // permit even one critical ranging initialization.
      Wire = TwoWire{};
      Wire.optional_mux_installed = false;
      desk_robot::TofBus bus;
      bus.note_optional_mux_present();
      CHECK(!bus.begin(21, 22, -1));
      CHECK(!bus.ready());
      CHECK(Wire.ranges == 0 && Wire.tof_samples == 0);
      Wire.optional_mux_installed = true;
      CHECK(bus.begin(21, 22, -1));
      CHECK(bus.ready() && Wire.extras == 0);
    }
    {
      // NACK on the optional mux command, NACK on its control readback,
      // or a rejected write buffer must all prevent any new 0x70 sample.
      for (unsigned fault = 0; fault < 3; ++fault) {
        Wire = TwoWire{};
        desk_robot::TofBus bus;
        desk_robot::CliffGuard guard;
        ready(bus, guard);
        bus.poll(guard, 60);
        CHECK(bus.extra_diagnostic(0, 60).valid);
        const auto before = Wire.tof_samples;
        const auto selected = Wire.ranges;
        Wire.optional_mux_write_nack = fault == 0;
        Wire.optional_mux_read_nack = fault == 1;
        Wire.fail_optional_mux_write = fault == 2;
        bus.poll(guard, 61);
        CHECK(Wire.tof_samples == before && Wire.ranges == selected);
        CHECK(!bus.extra_diagnostic(0, 62).valid);
        CHECK(!bus.optical_diagnostic(0, 62).valid);
        faulted(guard);
        Wire.optional_mux_write_nack = false;
        Wire.optional_mux_read_nack = false;
        Wire.fail_optional_mux_write = false;
        for (std::uint32_t at = 62; at < 68; ++at) bus.poll(guard, at);
        CHECK(!guard.evaluate(70)); // no automatic recovery
        CHECK(guard.try_rearm(70));
      }
    }
    {
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      CHECK(!bus.bus_accessible());
      Wire.fail_begin = true;
      CHECK(!bus.begin(21, 22, -1));
      CHECK(!bus.ready() && !bus.bus_accessible());
      CHECK(Wire.transactions == 0);
      CHECK(bus.probe_imu().family == 0 && Wire.transactions == 0);
    }
    {
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      CHECK(bus.bus_accessible());
      auto& lines = fake_i2c_lines();
      lines.sda_stuck = true;
      CHECK(!bus.bus_accessible());
      const auto before = Wire.transactions;
      bus.observe_shared_bus_fault(guard);
      CHECK(Wire.transactions == before);
      faulted(guard);
      lines.release_after_pulses = 1;
      lines.fail_restore = true;
      bus.poll(guard, 60);
      CHECK(!bus.bus_accessible());
      lines.fail_restore = false;
      bus.poll(guard, 160);
      CHECK(bus.bus_accessible());
      CHECK(!guard.try_rearm(160)); // recovery is not a new range sweep
      fake_i2c_lines() = FakeI2cLines{};
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
      fake_i2c_lines() = FakeI2cLines{};
      Wire.hold_sda_on_range_disconnect = true;
      desk_robot::TofBus bus;
      CHECK(!bus.begin(21, 22, -1));
      CHECK(!bus.ready() && !bus.bus_accessible());
      CHECK(Wire.ranges == 0 && Wire.extras == 0);
      CHECK(!Wire.hold_sda_on_range_disconnect);
      fake_i2c_lines() = FakeI2cLines{};
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
      CHECK(Wire.ranges == 0 && Wire.extras == 0);
      // Simulate a previous selected range lane.
      // An ACKed but ineffective disconnect must NOT probe a downstream IMU.
      Wire.ranges = 1;
      Wire.range_mux_stuck = true;
      CHECK(bus.probe_imu().family == 0);
      CHECK(Wire.imu_probe_attempts == 0);
      Wire.range_mux_stuck = false;
      auto& lines = fake_i2c_lines();
      lines.scl_stuck = true;
      const auto blocked = Wire.transactions;
      CHECK(bus.probe_imu().family == 0);
      CHECK(Wire.transactions == blocked);
      CHECK(Wire.imu_probe_attempts == 0);
      lines.scl_stuck = false;
      Wire.hold_sda_on_range_disconnect = true;
      CHECK(bus.probe_imu().family == 0);
      CHECK(Wire.transactions - blocked == 3);
      CHECK(Wire.imu_probe_attempts == 0);
      lines.sda_stuck = false;
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
      // All non-11 values of the four-bit raw device status are invalid,
      // including phase and signal failures with plausible distances.
      for (std::uint8_t status = 0; status < 16; ++status) {
        Wire = TwoWire{};
        desk_robot::TofBus trial_bus;
        desk_robot::CliffGuard trial_guard;
        ready(trial_bus, trial_guard);
        Wire.tof_raw_status = status;
        const bool accepted = status == 11;
        trial_bus.poll(trial_guard, 60); // optional lane 5, read-only
        CHECK(trial_bus.extra_diagnostic(0, 60).valid == accepted);
        CHECK(trial_guard.evaluate(60));
        trial_bus.poll(trial_guard, 61); // critical floor 0
        CHECK(trial_guard.diagnostic(0, 61).valid == accepted);
        CHECK(trial_bus.optical_diagnostic(0, 61).valid == accepted);
        CHECK(trial_guard.evaluate(61) == accepted);
        CHECK(trial_guard.fault() == (accepted
            ? desk_robot::CliffFault::None : desk_robot::CliffFault::InvalidSample));
        CHECK(trial_guard.try_rearm(61) == accepted);
      }
    }
    {
      // Status 11 alone is not sufficient: a weak return with plausible
      // geometry must invalidate the exact lane even under bright ambient.
      const std::uint8_t order[] = {5, 0, 1, 2, 3, 4, 6, 0, 1, 2, 3, 4, 7};
      for (std::uint8_t target = 0; target < 8; ++target) {
        for (std::uint16_t signal : {0U, 31U, 32U, 33U, 256U}) {
          Wire = TwoWire{};
          desk_robot::TofBus bus;
          desk_robot::CliffGuard guard;
          ready(bus, guard);
          std::uint32_t now = 60;
          for (const auto lane : order) {
            if (lane == target) break;
            bus.poll(guard, now++);
          }
          CHECK(guard.evaluate(now));
          Wire.tof_raw_status = 11;
          Wire.tof_signal_97 = signal;
          Wire.tof_ambient_97 = 0x4567;
          bus.poll(guard, now);
          CHECK(bus.last_channel() == target);
          const bool accepted = signal >= 32U;
          const auto raw = bus.optical_diagnostic(target, now);
          CHECK(raw.present && raw.signal_97 == signal && raw.ambient_97 == 0x4567);
          CHECK(raw.valid == accepted);
          if (target < 5) {
            CHECK(guard.diagnostic(target, now).valid == accepted);
            CHECK(guard.evaluate(now) == accepted);
            CHECK(guard.try_rearm(now) == accepted);
            if (!accepted) {
              CHECK(guard.fault() == desk_robot::CliffFault::InvalidSample);
              CHECK(guard.fault_sensor() == target);
            }
          } else {
            CHECK(bus.extra_diagnostic(target - 5, now).valid == accepted);
            CHECK(guard.evaluate(now)); // read-only lane cannot stop or arm
          }
        }
      }
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
      // Every sub-minimum range, including literal zero, must fail closed.
      // A valid 30 mm conversion still meets this test's calibration.
      for (std::uint16_t too_close = 0; too_close < 30; ++too_close) {
        Wire = TwoWire{};
        desk_robot::TofBus bus;
        desk_robot::CliffGuard guard;
        ready(bus, guard);
        Wire.tof_force_mm = too_close;
        Wire.tof_force_zero = too_close == 0;
        bus.poll(guard, 60); // diagnostic side lane
        const auto side = bus.extra_diagnostic(0, 60);
        CHECK(side.present && !side.valid && side.distance_mm == too_close);
        CHECK(guard.evaluate(60)); // side lane has no movement authority
        bus.poll(guard, 61); // safety-critical floor lane
        const auto floor = guard.diagnostic(0, 61);
        CHECK(floor.present && !floor.valid && floor.distance_mm == too_close);
        CHECK(!bus.optical_diagnostic(0, 61).valid);
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
        CHECK(bus.boot_health_mask() == 0 && Wire.ranges == 0);
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
      // Restarting the same instance must discard prior successful lane bits.
      Wire = TwoWire{};
      fake_i2c_lines() = FakeI2cLines{};
      desk_robot::TofBus bus;
      CHECK(bus.begin(21, 22, -1));
      CHECK(bus.boot_health_mask() == (DESK_ROBOT_EXTRA_RANGERS ? 0xffU : 0x1fU));
      Wire.tof_missing_lanes = 1;
      CHECK(!bus.begin(21, 22, -1));
      CHECK(!bus.ready() && bus.boot_health_mask() == 0 && Wire.ranges == 0);
      Wire.tof_missing_lanes = 0;
      CHECK(bus.begin(21, 22, -1));
      CHECK(bus.ready());
    }
    {
      // Per-lane faults must not be hidden by a healthy shared mux or by
      // successful initialization of the preceding lanes.
      const auto saved_clock = fake_arduino_millis();
      for (std::uint8_t lane = 0; lane < (DESK_ROBOT_EXTRA_RANGERS ? 8U : 5U); ++lane) {
        const auto mask = static_cast<std::uint8_t>(1U << lane);
        for (auto fault : {&TwoWire::tof_missing_lanes, &TwoWire::tof_wrong_model_lanes,
                           &TwoWire::tof_spad_timeout_lanes, &TwoWire::tof_phase_timeout_lanes}) {
          Wire = TwoWire{};
          fake_i2c_lines() = FakeI2cLines{};
          fake_arduino_millis() = 0;
          Wire.*fault = mask;
          desk_robot::TofBus bus;
          CHECK(!bus.begin(21, 22, -1));
          CHECK(!bus.ready());
          CHECK(bus.boot_health_mask() == static_cast<unsigned>(mask - 1U));
          CHECK(Wire.ranges == 0);
          const bool missing = fault == &TwoWire::tof_missing_lanes;
          CHECK(Wire.tof_init_timeouts.size() == static_cast<unsigned>(lane) + (missing ? 0U : 1U));
          const bool calibration_timeout = fault == &TwoWire::tof_spad_timeout_lanes ||
                                           fault == &TwoWire::tof_phase_timeout_lanes;
          CHECK(fake_arduino_millis() == (calibration_timeout ? 81U : 0U));
          desk_robot::CliffGuard guard;
          CHECK(guard.configure(calibration()));
          bus.poll(guard, 100);
          CHECK(Wire.tof_samples == 0);
          CHECK(!guard.evaluate(100));
          CHECK(!guard.try_rearm(100));
          for (std::uint8_t critical = 0; critical < 5; ++critical)
            CHECK(!guard.diagnostic(critical, 100).present);
        }
        // A device that disappears AFTER a successful start must fault on
        // its next scheduled register transaction, not publish cached range.
        Wire = TwoWire{};
        fake_i2c_lines() = FakeI2cLines{};
        fake_arduino_millis() = 0;
        desk_robot::TofBus bus;
        desk_robot::CliffGuard guard;
        ready(bus, guard);
        Wire.tof_missing_lanes = mask;
        for (std::uint32_t now = 60; now < 80 && guard.fault() == desk_robot::CliffFault::None; ++now) {
          const auto before = Wire.tof_samples;
          bus.poll(guard, now);
          if (guard.fault() != desk_robot::CliffFault::None)
            CHECK(Wire.tof_samples == before);
        }
        faulted(guard);
        CHECK(!guard.try_rearm(80));
      }
      Wire = TwoWire{};
      fake_i2c_lines() = FakeI2cLines{};
      fake_arduino_millis() = saved_clock;
    }
    {
      // A WROOM-only restart need not clear the mux control registers.
      // Start with either retained lane, not the fake's default zero masks.
      for (const bool accessory_retained : {false, true}) {
        Wire = TwoWire{};
        fake_i2c_lines() = FakeI2cLines{};
        if (accessory_retained) Wire.extras = 1;
        else Wire.ranges = 16;
        desk_robot::TofBus bus;
        CHECK(bus.begin(21, 22, -1));
        CHECK(Wire.ranges == 0 && Wire.extras == 0);
        CHECK(!Wire.unsafe_parallel_mux);
      }
    }
    {
      // Model an observed mux supply fault followed by power-on reset.
      // A cleared control mask is not a fresh safety measurement.
      Wire = TwoWire{};
      fake_i2c_lines() = FakeI2cLines{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      Wire.ranges = 0;
      Wire.extras = 0;
      Wire.range_mux_write_nack = true;
      const auto samples = Wire.tof_samples;
      bus.poll(guard, 60);
      CHECK(Wire.tof_samples == samples);
      faulted(guard);
      Wire.range_mux_write_nack = false;
      CHECK(!guard.try_rearm(61));
      for (std::uint32_t at = 61; at < 73; ++at) bus.poll(guard, at);
      CHECK(!guard.evaluate(73));
      CHECK(!Wire.unsafe_parallel_mux);
      CHECK(guard.try_rearm(73));
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
      CHECK(Wire.transactions == transactions + 4);
      CHECK(Wire.transactions - transactions <= desk_robot::kTofMaxRecoveryWireCalls);
      CHECK(Wire.ranges == 0 && Wire.extras == 0 && bus.bus_accessible());
      CHECK(bus.new_optical_channel() == 255 && bus.new_extra_channel() == 255);
      CHECK(!guard.try_rearm(61));
      for (std::uint32_t at = 62; at < 68; ++at) bus.poll(guard, at);
      CHECK(!guard.evaluate(70)); // recovery is not automatic rearm
      CHECK(guard.try_rearm(70)); // fresh complete sweep + local operator
      fake_i2c_lines() = FakeI2cLines{};
    }
    {
      // Line release alone cannot admit a sibling I2C client. A failed
      // mux readback remains quarantined, including through a retry delay.
      for (unsigned fault = 0; fault < 3; ++fault) {
        Wire = TwoWire{};
        fake_i2c_lines() = FakeI2cLines{};
        desk_robot::TofBus bus;
        desk_robot::CliffGuard guard;
        ready(bus, guard);
        auto& lines = fake_i2c_lines();
        Wire.ranges = fault == 0 ? 0 : 1;
        Wire.extras = fault == 0 ? 1 : 0;
        Wire.optional_mux_stuck = fault == 0;
        Wire.range_mux_stuck = fault == 1;
        lines.sda_stuck = true;
        lines.release_after_pulses = 9;
        const auto samples = Wire.tof_samples;
        bus.poll(guard, 0xfffffff0U);
        faulted(guard);
        if (fault == 2) lines.sda_stuck = false;
        CHECK(!bus.bus_accessible());
        bus.poll(guard, 0xfffffff1U);
        CHECK(Wire.tof_samples == samples);
        CHECK(lines.clear_pulses == (fault == 2 ? 0U : 9U));
        if (fault < 2) {
          CHECK(!bus.bus_accessible());
          CHECK(digitalRead(21) == HIGH && digitalRead(22) == HIGH);
          CHECK(bus.probe_imu().family == 0);
          const auto transactions = Wire.transactions;
          bus.poll(guard, 0x54U); // 99 ms, including rollover
          CHECK(!bus.bus_accessible() && Wire.transactions == transactions);
          Wire.optional_mux_stuck = Wire.range_mux_stuck = false;
          bus.poll(guard, 0x55U); // 100 ms
        }
        CHECK(bus.bus_accessible());
        CHECK(Wire.ranges == 0 && Wire.extras == 0);
        CHECK(Wire.tof_samples == samples);
        CHECK(bus.new_optical_channel() == 255 && bus.new_extra_channel() == 255);
        CHECK(!guard.try_rearm(0x55U));
      }
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
      // A slave may stretch SCL after any successful data-clear clock.
      // Distinguish attempted releases from real edges to catch continuing
      // to pulse a physically held clock after the bounded stretch wait.
      for (unsigned held = 1; held < 9; ++held) {
        Wire = TwoWire{};
        fake_i2c_lines() = FakeI2cLines{};
        desk_robot::TofBus bus;
        desk_robot::CliffGuard guard;
        ready(bus, guard);
        auto& lines = fake_i2c_lines();
        lines.sda_stuck = true;
        lines.release_after_pulses = 9;
        lines.hold_scl_after_pulses = held;
        const auto transactions = Wire.transactions;
        const auto samples = Wire.tof_samples;
        bus.poll(guard, 60);
        faulted(guard);
        bus.poll(guard, 61);
        CHECK(lines.clear_attempts == held + 1 && lines.clear_pulses == held);
        CHECK(lines.stops == 0 && lines.restore_calls == 1 && !lines.unsafe_high);
        CHECK(!bus.bus_accessible() && Wire.transactions == transactions);
        lines.scl_stuck = false;
        lines.hold_scl_after_pulses = 0;
        bus.poll(guard, 160);
        CHECK(lines.clear_attempts == held + 1 && !bus.bus_accessible());
        bus.poll(guard, 161);
        CHECK(lines.clear_attempts == 10 && lines.clear_pulses == 9);
        CHECK(lines.stops == 1 && lines.restore_calls == 2 && !lines.unsafe_high);
        CHECK(Wire.transactions == transactions + 4 && Wire.tof_samples == samples);
        CHECK(Wire.ranges == 0 && Wire.extras == 0 && bus.bus_accessible());
        CHECK(!guard.try_rearm(161));
      }
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
      Wire = TwoWire{};
      desk_robot::TofBus bus;
      desk_robot::CliffGuard guard;
      ready(bus, guard);
      const auto clears = Wire.tof_register_stop_transmissions;
      const auto samples = Wire.tof_samples;
      Wire.hold_sda_after_tof_result = true;
      bus.poll(guard, 60);
      CHECK(Wire.tof_samples == samples + 1);
      CHECK(Wire.tof_register_stop_transmissions == clears);
      CHECK(bus.new_extra_channel() == 255 && bus.new_optical_channel() == 255);
      faulted(guard);
      fake_i2c_lines() = FakeI2cLines{};
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
      CHECK(Wire.transactions - transactions == 7);
      CHECK(Wire.ranges == 0 && Wire.extras == 0 && bus.bus_accessible());
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
    {
      // Error bits override readiness even with a plausible status-11
      // distance in the unread result block. Exercise every lane.
      const std::uint8_t order[] = {5, 0, 1, 2, 3, 4,
                                    6, 0, 1, 2, 3, 4,
                                    7, 0, 1, 2, 3, 4};
      for (const std::uint8_t bits : {0x08, 0x10, 0x18}) {
        for (const bool conversion_ready : {false, true}) {
          for (std::uint8_t target = 0; target < 8; ++target) {
            Wire = TwoWire{};
            fake_i2c_lines() = FakeI2cLines{};
            desk_robot::TofBus bus;
            desk_robot::CliffGuard guard;
            ready(bus, guard);
            desk_robot::BodyControl control;
            const auto poll = [&](std::uint32_t now) {
              const auto errors = bus.errors();
              bus.poll(guard, now);
              desk_robot::publish_range_telemetry(
                  bus, control, now, bus.errors() != errors);
            };
            for (std::uint32_t now = 60; now < 78; ++now)
              poll(now);
            std::uint32_t now = 80;
            for (const auto lane : order) {
              if (lane == target) break;
              poll(now++);
            }
            const auto prior = bus.optical_diagnostic(target, now);
            const auto previous = control.state();
            for (const auto& raw : previous.optical) CHECK(raw.present && raw.valid);
            for (const auto valid : previous.side_valid) CHECK(valid);
            CHECK(prior.present && prior.valid);
            const auto prior_samples = Wire.tof_samples;
            Wire.tof_ready = conversion_ready;
            Wire.tof_interrupt_error_bits = bits;
            poll(now);
            CHECK(bus.last_channel() == target);
            CHECK(bus.rejected_channel() == target);
            for (std::uint8_t lane = 0; lane < 8; ++lane) {
              const auto& published = control.state().optical[lane];
              CHECK(published.present && published.valid == (lane != target));
              CHECK(published.at_ms == previous.optical[lane].at_ms);
              CHECK(published.ambient_97 == previous.optical[lane].ambient_97);
              CHECK(published.signal_97 == previous.optical[lane].signal_97);
            }
            for (std::uint8_t index = 0; index < 3; ++index) {
              CHECK(control.state().side_valid[index] == (target != index + 5));
              CHECK(control.state().side_at_ms[index] == previous.side_at_ms[index]);
              CHECK(control.state().side_mm[index] == previous.side_mm[index]);
            }
            CHECK(Wire.tof_samples == prior_samples);
            CHECK(bus.new_optical_channel() == 255);
            CHECK(bus.new_extra_channel() == 255);
            const auto optical = bus.optical_diagnostic(target, now);
            CHECK(optical.present && !optical.valid);
            CHECK(optical.age_ms == prior.age_ms);
            CHECK(optical.signal_97 == prior.signal_97);
            if (target < 5) {
              CHECK(guard.fault() == desk_robot::CliffFault::InvalidSample);
              CHECK(guard.fault_sensor() == target);
              CHECK(!guard.evaluate(now));
              CHECK(!guard.try_rearm(now));
            } else {
              const auto extra = bus.extra_diagnostic(target - 5, now);
              CHECK(extra.present && !extra.valid);
              CHECK(extra.age_ms == prior.age_ms);
              CHECK(guard.evaluate(now)); // optional lane is read-only
            }
            Wire.tof_interrupt_error_bits = 0;
            Wire.tof_ready = true;
            for (std::uint32_t step = 1; step <= 18; ++step) {
              poll(now + step);
              CHECK(bus.rejected_channel() == 255);
            }
            CHECK(bus.optical_diagnostic(target, now + 18).valid);
            CHECK(control.state().optical[target].valid);
            if (target >= 5) CHECK(control.state().side_valid[target - 5]);
            if (target < 5) {
              CHECK(!guard.evaluate(now + 18));
              CHECK(guard.try_rearm(now + 18));
            } else {
              CHECK(guard.evaluate(now + 18));
            }
          }
        }
      }
    }
    {
      // Exercise upstream probe_imu() across MPU6050 (0x68/0x69), BerryIMU
      // V1 (0x1d)/V2/V3 positive matches, and ambiguous multi-device rejection.
      auto configure_mpu = [](std::uint8_t addr) {
        Wire.add_upstream_imu_reg(addr, 0x75, 0x68);
      };
      auto configure_berry = [](std::uint8_t gyro_addr, std::uint8_t gyro_id,
                                std::uint8_t aux_addr, std::uint8_t aux_id) {
        Wire.add_upstream_imu_reg(gyro_addr, 0x0f, gyro_id);
        Wire.add_upstream_imu_reg(aux_addr, 0x0f, aux_id);
      };
      // Positive single MPU6050 on 0x68 and 0x69.
      for (std::uint8_t addr : {std::uint8_t{0x68}, std::uint8_t{0x69}}) {
        Wire = TwoWire{};
        configure_mpu(addr);
        desk_robot::TofBus bus;
        desk_robot::CliffGuard guard;
        ready(bus, guard);
        const auto id = bus.probe_imu();
        CHECK(id.family == 4 && id.gyro_id == 0x68 && id.aux_id == 0);
        CHECK(id.gyro_address == addr && id.aux_address == 0);
      }
      // Positive BerryIMU V1 (including 0x1d aux), V2, V3.
      struct BerryCase {
        std::uint8_t gyro_id;
        std::uint8_t aux_addr;
        std::uint8_t aux_id;
        std::uint8_t expected_family;
      };
      const BerryCase berry_cases[] = {
          {0xd4, 0x1d, 0x49, 1},
          {0x68, 0x1c, 0x3d, 2},
          {0x6a, 0x1c, 0x3d, 3},
      };
      for (const auto& c : berry_cases) {
        Wire = TwoWire{};
        configure_berry(0x6a, c.gyro_id, c.aux_addr, c.aux_id);
        desk_robot::TofBus bus;
        desk_robot::CliffGuard guard;
        ready(bus, guard);
        const auto id = bus.probe_imu();
        CHECK(id.family == c.expected_family);
        CHECK(id.gyro_id == c.gyro_id && id.aux_id == c.aux_id);
        CHECK(id.gyro_address == 0x6a && id.aux_address == c.aux_addr);
      }
      // Ambiguous or failed mux isolation cases must all fail closed.
      {
        Wire = TwoWire{};
        configure_mpu(0x68);
        configure_mpu(0x69);
        desk_robot::TofBus bus;
        desk_robot::CliffGuard guard;
        ready(bus, guard);
        CHECK(bus.probe_imu().family == 0);
      }
      {
        Wire = TwoWire{};
        configure_mpu(0x68);
        Wire.add_upstream_imu_reg(0x6a, 0x0f, 0xd4);
        desk_robot::TofBus bus;
        desk_robot::CliffGuard guard;
        ready(bus, guard);
        CHECK(bus.probe_imu().family == 0);
      }
      {
        Wire = TwoWire{};
        configure_mpu(0x68);
        Wire.add_upstream_imu_reg(0x1c, 0x0f, 0x3d);
        desk_robot::TofBus bus;
        desk_robot::CliffGuard guard;
        ready(bus, guard);
        CHECK(bus.probe_imu().family == 0);
      }
      {
        Wire = TwoWire{};
        Wire.add_upstream_imu_reg(0x6a, 0x0f, 0xd4);
        Wire.add_upstream_imu_reg(0x6b, 0x0f, 0x68);
        Wire.add_upstream_imu_reg(0x1c, 0x0f, 0x3d);
        desk_robot::TofBus bus;
        desk_robot::CliffGuard guard;
        ready(bus, guard);
        CHECK(bus.probe_imu().family == 0);
      }
      {
        Wire = TwoWire{};
        Wire.add_upstream_imu_reg(0x6a, 0x0f, 0x68);
        Wire.add_upstream_imu_reg(0x1c, 0x0f, 0x3d);
        Wire.add_upstream_imu_reg(0x1e, 0x0f, 0x49);
        desk_robot::TofBus bus;
        desk_robot::CliffGuard guard;
        ready(bus, guard);
        CHECK(bus.probe_imu().family == 0);
      }
      {
        // Mismatched Berry ID pair (V1 gyro 0xd4 + V2/V3 aux 0x3d).
        Wire = TwoWire{};
        configure_berry(0x6a, 0xd4, 0x1c, 0x3d);
        desk_robot::TofBus bus;
        desk_robot::CliffGuard guard;
        ready(bus, guard);
        CHECK(bus.probe_imu().family == 0);
      }
      {
        // Active downstream mux lane with stuck range mux cannot accept MPU.
        Wire = TwoWire{};
        configure_mpu(0x68);
        desk_robot::TofBus bus;
        desk_robot::CliffGuard guard;
        ready(bus, guard);
        Wire.ranges = 0x01;
        Wire.range_mux_stuck = true;
        CHECK(bus.probe_imu().family == 0);
      }
    }
    {
      // All prior accessory lanes crossed with every next optical lane.
      // Simultaneous faults on both muxes must not permit any range result.
      // Digital transaction faults only; this is not electrical qualification.
      const std::uint8_t order[] = {5, 0, 1, 2, 3, 4,
                                    6, 0, 1, 2, 3, 4, 7};
      for (std::uint8_t retained = 0; retained < 8; ++retained) {
        for (std::uint8_t target = 0; target < 8; ++target) {
          for (unsigned accessory_fault = 0; accessory_fault < 5; ++accessory_fault) {
            for (unsigned range_fault = 0; range_fault < 5; ++range_fault) {
              Wire = TwoWire{};
              fake_i2c_lines() = FakeI2cLines{};
              desk_robot::TofBus bus;
              desk_robot::CliffGuard guard;
              ready(bus, guard);
              std::uint32_t now = 60;
              for (const auto lane : order) {
                if (lane == target) break;
                bus.poll(guard, now++);
              }
              CHECK(guard.evaluate(now));
              Wire.ranges = 0;
              Wire.extras = static_cast<std::uint8_t>(1U << retained);
              Wire.optional_mux_stuck = accessory_fault == 1;
              Wire.optional_mux_write_nack = accessory_fault == 2;
              Wire.optional_mux_read_nack = accessory_fault == 3;
              Wire.optional_mux_installed = accessory_fault != 4;
              Wire.range_mux_stuck = range_fault == 1;
              Wire.range_mux_write_nack = range_fault == 2;
              Wire.range_mux_bad_readback = range_fault == 3;
              if (range_fault == 4)
                Wire.hold_sda_on_range_mask = static_cast<std::uint8_t>(1U << target);
              const auto samples = Wire.tof_samples;
              bus.poll(guard, now);
              CHECK(bus.last_channel() == target);
              CHECK(!Wire.unsafe_parallel_mux);
              if (accessory_fault == 0 && range_fault == 0) {
                CHECK(Wire.extras == 0 && Wire.ranges == (1U << target));
                CHECK(Wire.tof_samples == samples + 1);
                CHECK(bus.new_optical_channel() == target);
                CHECK(guard.evaluate(now));
                continue;
              }
              CHECK(Wire.tof_samples == samples);
              CHECK(bus.new_optical_channel() == 255 && bus.new_extra_channel() == 255);
              CHECK(guard.fault() == desk_robot::CliffFault::BusFailure);
              CHECK(!guard.evaluate(now) && !guard.try_rearm(now));
              for (std::uint8_t lane = 0; lane < 8; ++lane)
                CHECK(!bus.optical_diagnostic(lane, now).valid);
              for (std::uint8_t lane = 0; lane < 5; ++lane)
                CHECK(!guard.diagnostic(lane, now).present);
              // A failure in the first mux must prevent a write to the second.
              if (accessory_fault != 0) CHECK(Wire.ranges == 0);
              Wire.optional_mux_stuck = Wire.optional_mux_write_nack =
                Wire.optional_mux_read_nack = false;
              Wire.optional_mux_installed = true;
              Wire.range_mux_stuck = Wire.range_mux_write_nack =
                Wire.range_mux_bad_readback = false;
              Wire.hold_sda_on_range_mask = 0;
              fake_i2c_lines() = FakeI2cLines{}; // simulated removal of held line
              for (unsigned i = 0; i < 12; ++i) bus.poll(guard, ++now);
              CHECK(!guard.evaluate(now));
              CHECK(guard.try_rearm(now));
              CHECK(!Wire.unsafe_parallel_mux);
            }
          }
        }
      }
    }
    std::cout << "PASS cheap VL53L0X TCA9548A selected-channel readback and fail-closed cliff paths\n";
    return 0;
  } catch (const std::exception& ex) {
    std::cerr << "FAIL mux verification: " << ex.what() << '\n';
    return 1;
  }
}
