#include "TofBus.h"
#include "TofResult.h"
#include "../../include/MuxWrite.h"
#include "BerryImu.h"

#if (defined(DESK_ROBOT_STEPPER) && DESK_ROBOT_STEPPER) || \
    (defined(DESK_ROBOT_FULL_SENSORS) && DESK_ROBOT_FULL_SENSORS)

#include <driver/i2c.h>

namespace desk_robot {

bool TofBus::quiesce_optional_mux() {
  if (!physical_bus_accessible()) return false;
  if (!optional_mux_present_) return true;
  // A fitted optional bus must not keep a lane selected while the local
  // guard reads the 0x70 floor mux. Verify the CONTROL REGISTER, not just
  // ACK: a stuck mux could expose a different sensor at the shared 0x29.
  if (!write_mux_mask(wire_, kOptionalMuxAddress, 0).ok() || !bus_idle()) return false;
  if (wire_.requestFrom(kOptionalMuxAddress, static_cast<size_t>(1), true) != 1 ||
      wire_.available() < 1) return false;
  return wire_.read() == 0 && bus_idle();
}

bool TofBus::quiesce_range_mux() {
  if (!physical_bus_accessible()) return false;
  return write_mux_mask(wire_, kMuxAddress, 0).ok() && bus_idle() &&
         wire_.requestFrom(kMuxAddress, static_cast<size_t>(1), true) == 1 &&
         wire_.available() >= 1 && wire_.read() == 0 && bus_idle();
}

bool TofBus::select(std::uint8_t channel) {
  if (channel >= kRangeCount || !quiesce_optional_mux()) return false;
  const auto expected = static_cast<std::uint8_t>(1U << channel);
  const auto result = write_mux_mask(wire_, kMuxAddress, expected);
  // The STOP activates the new downstream lane. A hung sensor can
  // pull SDA/SCL low here even though the mux write itself ACKed. Do not
  // start another potentially blocking readback transaction on held lines.
  if (!result.ok() || !bus_idle()) return false;
  // TCA9548A SCPS207H, section 7.5.4: one-byte control register readback.
  // The explicit STOP above activates the selected channel before reading.
  // A wrong/multiple channel must never be accepted as a cliff measurement.
  if (wire_.requestFrom(kMuxAddress, static_cast<size_t>(1), true) != 1 ||
      wire_.available() < 1) return false;
  return wire_.read() == expected && bus_idle();
}

bool TofBus::read_register(std::uint8_t reg, std::uint8_t* out, std::uint8_t length) {
  if (!out || length == 0 || length > kMaxSampleBytes) return false;
  wire_.beginTransmission(kSensorAddress);
  const bool written = wire_.write(reg) == 1;
  // Only an accepted register pointer may use the repeated START. An
  // unsuccessful write must terminate with STOP so the next safety read
  // does not inherit a half-open I2C transaction.
  const int result = wire_.endTransmission(!written);
  if (!written || result != 0) return false;
  if (wire_.requestFrom(kSensorAddress, static_cast<size_t>(length), true) != length) return false;
  for (std::uint8_t n = 0; n < length; ++n) {
    if (wire_.available() < 1) return false;
    const int sample = wire_.read();
    if (sample < 0) return false;
    out[n] = static_cast<std::uint8_t>(sample);
  }
  return true;
}

bool TofBus::write_byte(std::uint8_t reg, std::uint8_t value) {
  wire_.beginTransmission(kSensorAddress);
  const bool written = wire_.write(reg) == 1 && wire_.write(value) == 1;
  const int result = wire_.endTransmission(true);
  return written && result == 0;
}

void TofBus::failed(CliffGuard& guard) {
  ++bus_errors_;
  scan_.transport_fault();
  if (!physical_bus_accessible()) recovery_quarantine_ = true;
  // A sibling transaction can fault after poll() published a conversion.
  // Revoke its acquisition notifications along with the stored validity.
  new_extra_channel_ = 255;
  new_optical_channel_ = 255;
  rejected_channel_ = 255;
  // Every range lane shares this mux and I2C controller. A bus fault
  // invalidates optional side/rear evidence too, not only the five critical
  // floor/front samples. Retain presence and last measured millimeters for
  // diagnostics, but do not publish these values as currently valid.
  for (auto& sample : extra_) sample.valid = false;
  for (auto& sample : optical_) sample.valid = false;
  guard.bus_fault();
}

void TofBus::observe_shared_bus_fault(CliffGuard& guard) {
  // A sibling client may hold a line after the current floor scan. Retire
  // evidence immediately, but leave actual GPIO recovery to a later poll.
  if (!physical_bus_accessible() && !recovery_quarantine_) failed(guard);
}

// The pinned ESP-IDF driver already attempts a nine-clock clear on some
// transaction failures. Only take over the GPIOs if the physical lines
// remain low on a later poll. All Wire clients run in the same body loop.
bool TofBus::bus_idle() const {
  return digitalRead(sda_pin_) == HIGH && digitalRead(scl_pin_) == HIGH;
}

bool TofBus::recover_bus() {
  // No Wire.end()/begin(): Arduino ESP32 2.0.17 frees shared buffers
  // during end(), and a failed reopen can strand another client's Wire
  // mutex. The synchronous body loop owns the bus between transactions.
  // Adapt the pinned IDF v4.4.7 driver/i2c.c i2c_master_clear_bus pattern
  // (Apache-2.0): detach GPIO outputs temporarily, then restore the
  // SAME I2C_NUM_0 pin matrix via the public i2c_set_pin API.
  // NXP UM10204 section 3.1.16: use open drain, never push-pull HIGH.
  // Preload the release latch before selecting GPIO output. The ESP32
  // OUTPUT_OPEN_DRAIN mode includes input, so actual line levels are read.
  digitalWrite(sda_pin_, HIGH);
  digitalWrite(scl_pin_, HIGH);
  pinMode(sda_pin_, OUTPUT_OPEN_DRAIN | PULLUP);
  pinMode(scl_pin_, OUTPUT_OPEN_DRAIN | PULLUP);
  pins_restored_ = false;
  const auto scl_released = [this]() {
    // A slave holding SCL low cannot be clocked out. Bound the stretch
    // allowance instead of waiting indefinitely for a shorted line.
    for (unsigned i = 0; i < 10; ++i) {
      if (digitalRead(scl_pin_) == HIGH) return true;
      delayMicroseconds(5);
    }
    return digitalRead(scl_pin_) == HIGH;
  };

  delayMicroseconds(5);
  bool clear = scl_released();
  if (clear && digitalRead(sda_pin_) == LOW) {
    for (unsigned i = 0; i < 9 && digitalRead(sda_pin_) == LOW; ++i) {
      digitalWrite(scl_pin_, LOW);
      delayMicroseconds(5);
      digitalWrite(scl_pin_, HIGH); // open-drain release
      if (!scl_released()) {
        clear = false;
        break;
      }
      delayMicroseconds(5);
    }
    clear = clear && digitalRead(sda_pin_) == HIGH;
    if (clear) {
      // Generate STOP only after the slave releases SDA. The STOP setup
      // edge is not a data-clear clock pulse.
      digitalWrite(scl_pin_, LOW);
      digitalWrite(sda_pin_, LOW);
      delayMicroseconds(5);
      digitalWrite(scl_pin_, HIGH);
      clear = scl_released();
      delayMicroseconds(5);
      digitalWrite(sda_pin_, HIGH);
      delayMicroseconds(5);
    }
  }
  digitalWrite(sda_pin_, HIGH);
  digitalWrite(scl_pin_, HIGH);
  if ((!clear || !bus_idle()) && mux_reset_pin_ >= 0) {
    // TI TCA9548A RESET disconnects downstream lanes. This is only
    // available with an actual reset GPIO; production ties RESET high.
    digitalWrite(mux_reset_pin_, LOW);
    delayMicroseconds(10);
    digitalWrite(mux_reset_pin_, HIGH);
    delay(2);
  }
  // Restore on every path, including an unresponsive slave. Do not
  // modify Wire's buffers, mutex, configured frequency or timeout.
  // Arduino ESP32 2.0.17 defines global Wire as TwoWire(0).
  pins_restored_ = i2c_set_pin(I2C_NUM_0, sda_pin_, scl_pin_, true, true,
                              I2C_MODE_MASTER) == ESP_OK;
  return pins_restored_ && bus_idle();
}

bool TofBus::begin(int sda, int scl, int mux_reset_pin) {
  initialized_ = false;
  sda_pin_ = sda;
  scl_pin_ = scl;
  mux_reset_pin_ = mux_reset_pin;
  pins_restored_ = true;
  recovery_attempted_ = false;
  recovery_quarantine_ = false;
  scan_.reset();
  new_extra_channel_ = 255;
  new_optical_channel_ = 255;
  rejected_channel_ = 255;
  for (auto& sample : extra_) sample = ExtraSample{};
  for (auto& sample : optical_) sample = OpticalSample{};
  // Pinned Pololu VL53L0X setup uses an 80ms timeout per device.
  // The critical polling path uses nonblocking status checks and the Wire
  // controller's independent 10ms I2C transaction timeout.
  wire_started_ = wire_.begin(sda, scl, 400000);
  if (!wire_started_) return false;
  wire_.setTimeOut(10);
  if (!bus_accessible()) return false;
  // Optional second mux: 0x71 (A0 high, A1/A2 low). No second board is
  // required for the existing five sensor firmware, and an absent board NACK
  // must not block prototype diagnostics. A fitted board is always set to
  // zero selected lanes before any critical ranging transaction.
  wire_.beginTransmission(kOptionalMuxAddress);
  const bool detected_optional_mux = wire_.endTransmission(true) == 0;
  // Once another accessory has observed 0x71, a later transient NACK
  // cannot downgrade the safety isolation requirement. A known mux that
  // cannot be quiesced must keep every floor range unqualified.
  optional_mux_present_ = optional_mux_present_ || detected_optional_mux;
  if (optional_mux_present_ && !quiesce_optional_mux()) return false;
  // The final WROOM allocation does not have a spare boot-safe output.
  // With mux_reset_pin = -1, physically tie TCA9548A RESET high to 3.3V.
  if (mux_reset_pin >= 0) {
    pinMode(mux_reset_pin, OUTPUT);
    digitalWrite(mux_reset_pin, LOW);
    delayMicroseconds(10);
    digitalWrite(mux_reset_pin, HIGH);
    delay(2);
  }
  for (std::uint8_t channel = 0; channel < kRangeCount; ++channel) {
    // Separate object preserves each device's calibration/stop variable.
    VL53L0X& sensor = devices_[channel];
    sensor.setBus(&wire_);
    sensor.setTimeout(80);
    if (!select(channel) || !sensor.init() || sensor.timeoutOccurred() ||
        !sensor.setMeasurementTimingBudget(33000)) return false;
    sensor.startContinuous();
    if (sensor.last_status != 0 || sensor.timeoutOccurred()) return false;
  }
  // Continuous ranging runs inside each sensor with its mux lane closed.
  // Verify both muxes are isolated before reporting startup ready.
  const bool optional_closed = quiesce_optional_mux();
  const bool range_closed = quiesce_range_mux();
  if (!optional_closed || !range_closed) return false;
  next_channel_ = 0;
  initialized_ = true;
  return true;
}

ImuIdentity TofBus::probe_imu() {
  // I2C address/WHO_AM_I pairs come from OzzMaker's BerryIMU version
  // comparison and ST device datasheets, NOT an assumed photographed chip.
  // This probe does not initialize or read movement sensors. We reuse Wire
  // already initialized by begin(), so there is no second I2C controller.
  ImuIdentity result{};
  if (!bus_accessible()) return result;
  // TCA9548A may have left a downstream branch selected. Disconnect it for
  // the upstream IMU read, without changing the active ToF measurement plan.
  if (!quiesce_optional_mux()) return ImuIdentity{};
  if (!quiesce_range_mux()) return ImuIdentity{};

  auto identity = [this](std::uint8_t address, std::uint8_t& value) {
    if (!bus_idle()) return false;
    wire_.beginTransmission(address);
    const bool wrote = wire_.write(static_cast<std::uint8_t>(0x0f)) == 1;
    const bool acknowledged = wire_.endTransmission(!wrote) == 0;
    // Arduino ESP32 2.0.17 retains Wire's lock after endTransmission(false).
    // Complete requestFrom before testing line state; never abandon a
    // pending repeated START (upstream libraries/Wire/src/Wire.cpp).
    if (!wrote || !acknowledged) return false;
    if (wire_.requestFrom(address, static_cast<size_t>(1), true) != 1 ||
        wire_.available() < 1) return false;
    const int byte = wire_.read();
    if (byte < 0 || !bus_idle()) return false;
    value = static_cast<std::uint8_t>(byte);
    return true;
  };
  // Standard MPU6050 WHO_AM_I is register 0x75 (NOT Berry 0x0f).
  // AD0 selects either 0x68 or 0x69. Do not trust ACK without the 0x68 ID.
  std::uint8_t mpu_matches = 0;
  std::uint8_t mpu_address = 0;
  for (std::uint8_t addr : {static_cast<std::uint8_t>(0x68), static_cast<std::uint8_t>(0x69)}) {
    if (!bus_idle()) return ImuIdentity{};
    wire_.beginTransmission(addr);
    const bool wrote = wire_.write(static_cast<std::uint8_t>(0x75)) == 1;
    const bool acknowledged = wire_.endTransmission(!wrote) == 0;
    // Complete the combined transaction to release the Wire lock.
    if (wrote && acknowledged &&
        wire_.requestFrom(addr, static_cast<size_t>(1), true) == 1 &&
        wire_.available() >= 1) {
      const int value = wire_.read();
      if (value == 0x68) { ++mpu_matches; mpu_address = addr; }
    }
  }
  // OzzMaker exposes several BerryIMU revisions. A WHO_AM_I response is
  // not unique to one address; reject ambiguous multi-device probes rather
  // than quietly selecting whichever chip responds first.
  std::uint8_t gyro_matches = 0;
  std::uint8_t aux_matches = 0;
  for (std::uint8_t addr : {static_cast<std::uint8_t>(0x6a),
                            static_cast<std::uint8_t>(0x6b)}) {
    std::uint8_t id = 0;
    if (identity(addr, id) && (id == 0xd4 || id == 0x68 ||
                              id == 0x6a || id == 0x73)) {
      ++gyro_matches;
      result.gyro_id = id;
      result.gyro_address = addr;
    }
  }
  for (std::uint8_t addr : {static_cast<std::uint8_t>(0x1e),
                            static_cast<std::uint8_t>(0x1d),
                            static_cast<std::uint8_t>(0x1c)}) {
    std::uint8_t id = 0;
    if (identity(addr, id) && (id == 0x49 || id == 0x3d)) {
      ++aux_matches;
      result.aux_id = id;
      result.aux_address = addr;
    }
  }
  if (!bus_idle()) return ImuIdentity{};
  if (mpu_matches > 0) {
    if (mpu_matches != 1 || gyro_matches != 0 || aux_matches != 0)
      return ImuIdentity{}; // ambiguous installed IMUs: fail closed
    result.family = static_cast<std::uint8_t>(BerryModel::Mpu6050);
    result.gyro_id = 0x68;
    result.aux_id = 0;
    result.gyro_address = mpu_address;
    result.aux_address = 0;
    return result;
  }
  if (gyro_matches != 1 || aux_matches != 1) {
    return ImuIdentity{};  // no guessed chip, no movement permission
  }
  // Reuse the same paired model classifier as the 6-axis sampler.
  const BerryModel model = BerryImu::identify(result.gyro_id, result.aux_id);
  if (model == BerryModel::V1Lsm9ds0 || model == BerryModel::V2Lsm9ds1 ||
      model == BerryModel::V3Lsm6dsl)
    result.family = static_cast<std::uint8_t>(model);
  // All nonmatching combinations remain unknown, never treated as qualified.
  return result;
}

RangeDiagnostic TofBus::extra_diagnostic(std::uint8_t index,
                                         std::uint32_t now_ms) const {
  RangeDiagnostic result{};
  if (index >= 3 || !extra_[index].present) return result;
  const auto& sample = extra_[index];
  result.present = true;
  result.age_ms = now_ms - sample.at_ms;
  // Optional side/rear readings are diagnostics, not indefinitely valid
  // evidence. Mirror the Mac 350 ms freshness acceptance, retaining raw mm.
  result.valid = sample.valid && result.age_ms <= 350U;
  result.distance_mm = sample.mm;
  return result;
}

TofOpticalDiagnostic TofBus::optical_diagnostic(
    std::uint8_t channel, std::uint32_t now_ms) const {
  TofOpticalDiagnostic result{};
  if (channel >= kRangeCount || !optical_[channel].present) return result;
  const auto& raw = optical_[channel];
  result.present = true;
  result.age_ms = now_ms - raw.at_ms;
  // Five floor/front lanes have the 200ms CliffGuard bound. The three
  // read-only side/rear lanes use the existing 350ms Mac freshness policy.
  result.valid = raw.valid && (
      channel < kFloorAndFrontCount
          ? result.age_ms < 200U : result.age_ms <= 350U);
  result.ambient_97 = raw.ambient_97;
  result.signal_97 = raw.signal_97;
  return result;
}

void TofBus::poll(CliffGuard& guard, std::uint32_t now_ms) {
  const auto poll_started_ms = static_cast<std::uint32_t>(millis());
  // Retire expired evidence while polling, so a full millis revolution
  // cannot make a cached conversion fresh again. Only acquisition renews it.
  for (auto& sample : extra_) {
    if (sample.present && now_ms - sample.at_ms > 350U) sample.valid = false;
  }
  for (std::uint8_t lane = 0; lane < kRangeCount; ++lane) {
    auto& sample = optical_[lane];
    const auto age = now_ms - sample.at_ms;
    if (sample.present && (lane < kFloorAndFrontCount ? age >= 200U : age > 350U))
      sample.valid = false;
  }
  new_extra_channel_ = 255;
  new_optical_channel_ = 255;
  rejected_channel_ = 255;
  if (!initialized_) {
    failed(guard);
    return;
  }
  // Detect a held line before a transaction can block. On first
  // detection return with the guard fault latched, without additional
  // recovery work before the body loop can apply its safety stop.
  if (recovery_quarantine_ || !physical_bus_accessible()) {
    if (!recovery_quarantine_) {
      failed(guard);
      return;
    }
    recovery_quarantine_ = true;
    // Do not hammer a permanently shorted bus. Unsigned elapsed time is
    // rollover-safe; a successful recovery never supplies a range sample.
    if (recovery_attempted_ && now_ms - last_recovery_ms_ < 100U) return;
    recovery_attempted_ = true;
    last_recovery_ms_ = now_ms;
    // A released line is not proof of mux isolation. Keep sibling Wire
    // clients quarantined until both fitted muxes read back as closed.
    // If the slave released on its own, skip the GPIO clock takeover.
    if ((!physical_bus_accessible() && !recover_bus()) ||
        !quiesce_optional_mux() || !quiesce_range_mux()) {
      failed(guard);
      return;
    }
    recovery_quarantine_ = false;
    recovery_attempted_ = false;
    return;
  }
  // The pinned driver or removal of a fault may already have cleared
  // the lines. Normal checked mux selection is still required below.
  recovery_attempted_ = false;
  // Five mandatory floor/front opportunities precede any optional read.
  // Defer optional work after a slow sweep; the guard still enforces actual
  // sample freshness independently of the scheduler's admission heuristic.
  const auto freshness_ms = guard.configured() ? guard.configuration().freshness_ms : 200U;
  const std::uint8_t channel = scan_.next(now_ms, freshness_ms);
  next_channel_ = channel;
  if (!select(channel)) {
    failed(guard);
    return;
  }
  // VL53L0X uses a single-byte register address, not the older 16-bit map.
  // Poll readiness once; never block waiting for an optical conversion.
  std::uint8_t ready = 0;
  if (!read_register(0x13, &ready, 1) || !bus_idle()) {
    failed(guard);
    return;
  }
  // ST VL53L0X_GetInterruptMaskStatus: bits 3/4 indicate range
  // error independently of readiness. Never publish a stale result.
  if ((ready & 0x18U) != 0) {
    rejected_channel_ = channel;
    optical_[channel].valid = false;
    if (channel < kFloorAndFrontCount) {
      // Zero is an invalid sentinel: no distance was acquired.
      guard.sample(channel, 0, false, now_ms);
    } else {
      extra_[channel - kFloorAndFrontCount].valid = false;
    }
    // Acknowledge without granting clearance. Failed clear is a bus fault.
    if (!write_byte(0x0B, 0x01) || !bus_idle()) failed(guard);
    else scan_.transport_succeeded(channel);
    return;
  }
  if ((ready & 0x07U) == 0) {
    // No new conversion: CliffGuard must reject stale floor samples.
    // The checked status read proves transport only, not optical clearance.
    scan_.transport_succeeded(channel);
    return;
  }
  std::uint8_t result[kMaxSampleBytes]{};
  if (!read_register(0x14, result, kMaxSampleBytes) || !bus_idle() ||
      !write_byte(0x0B, 0x01) || !bus_idle()) {
    failed(guard);
    return;
  }
  scan_.transport_succeeded(channel);
  // A plausible distance with a weak return is not clearance. Decode the
  // complete result using ST's register layout and the pinned driver limit.
  const auto decoded = decode_tof_result(result);
  const auto distance = decoded.distance_mm;
  const bool accepted = decoded.accepted;
  auto& optics = optical_[channel];
  optics.present = true;
  optics.valid = accepted;
  optics.ambient_97 = decoded.ambient_97;
  optics.signal_97 = decoded.signal_97;
  optics.at_ms = now_ms;
  new_optical_channel_ = channel;
  if (channel < kFloorAndFrontCount) {
    // The scan-start timestamp conservatively dates the new reading, but
    // must not conceal expiry of the old reading during synchronous I2C.
    // Assess the previous clearance at actual elapsed completion time
    // before replacing it. Unsigned elapsed arithmetic handles rollover.
    const auto elapsed_ms = static_cast<std::uint32_t>(millis()) - poll_started_ms;
    guard.evaluate(now_ms + elapsed_ms);
    guard.sample(channel, distance, accepted, now_ms);
  } else {
    auto& sample = extra_[channel - kFloorAndFrontCount];
    sample.present = true;
    sample.valid = accepted;
    sample.mm = distance;
    sample.at_ms = now_ms;
    new_extra_channel_ = channel - kFloorAndFrontCount;
    // Extra measured ranges still require geometry, policy and stopping trials.
  }
}

}  // namespace desk_robot

#endif  // DESK_ROBOT_STEPPER
