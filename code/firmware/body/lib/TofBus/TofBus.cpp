#include "TofBus.h"
#include "BerryImu.h"

#if defined(DESK_ROBOT_STEPPER) && DESK_ROBOT_STEPPER

namespace desk_robot {

bool TofBus::quiesce_optional_mux() {
  if (!optional_mux_present_) return true;
  // A fitted optional bus must not keep a channel selected while the local
  // guard acquires the 0x70 floor sensor. A nonresponding second mux becomes
  // a real bus fault, rather than allowing unsafe mixed channel reads.
  wire_.beginTransmission(kOptionalMuxAddress);
  const bool wrote = wire_.write(static_cast<std::uint8_t>(0)) == 1;
  return wrote && wire_.endTransmission(true) == 0;
}

bool TofBus::select(std::uint8_t channel) {
  if (channel >= kRangeCount || !quiesce_optional_mux()) return false;
  wire_.beginTransmission(kMuxAddress);
  if (wire_.write(static_cast<std::uint8_t>(1U << channel)) != 1) return false;
  return wire_.endTransmission(true) == 0;
}

bool TofBus::read_register(std::uint16_t reg, std::uint8_t* out, std::uint8_t length) {
  if (!out || length == 0 || length > kMaxSampleBytes) return false;
  wire_.beginTransmission(kSensorAddress);
  const bool written =
      wire_.write(static_cast<std::uint8_t>(reg >> 8)) == 1 &&
      wire_.write(static_cast<std::uint8_t>(reg)) == 1;
  const int result = wire_.endTransmission(false);
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

bool TofBus::write_byte(std::uint16_t reg, std::uint8_t value) {
  wire_.beginTransmission(kSensorAddress);
  const bool written =
      wire_.write(static_cast<std::uint8_t>(reg >> 8)) == 1 &&
      wire_.write(static_cast<std::uint8_t>(reg)) == 1 &&
      wire_.write(value) == 1;
  const int result = wire_.endTransmission(true);
  return written && result == 0;
}

void TofBus::failed(CliffGuard& guard) {
  ++bus_errors_;
  guard.bus_fault();
}

bool TofBus::begin(int sda, int scl, int mux_reset_pin) {
  initialized_ = false;
  scan_.reset();
  new_extra_channel_ = 255;
  for (auto& sample : extra_) sample = ExtraSample{};
  // Pololu sensor setup is bounded by its 80ms init timeout. Actual I2C
  // requests also require Wire's own 15ms timeout, independent of the sensor.
  wire_.begin(sda, scl, 400000);
  wire_.setTimeOut(15);
  // Optional second mux: 0x71 (A0 high, A1/A2 low). No second board is
  // required for the existing five sensor firmware, and an absent board NACK
  // must not block prototype diagnostics. A fitted board is always set to
  // zero selected lanes before any critical ranging transaction.
  wire_.beginTransmission(kOptionalMuxAddress);
  optional_mux_present_ = wire_.endTransmission(true) == 0;
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
  device_.setBus(&wire_);
  device_.setTimeout(80);
  for (std::uint8_t channel = 0; channel < kRangeCount; ++channel) {
    if (!select(channel) || !device_.init() || device_.timeoutOccurred() ||
        !device_.setRangeTiming(20, 0)) {
      return false;
    }
    device_.startContinuous();
    if (device_.last_status != 0) return false;
  }
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
  // TCA9548A may have left a downstream branch selected. Disconnect it for
  // the upstream IMU read, without changing the active ToF measurement plan.
  if (!quiesce_optional_mux()) return ImuIdentity{};
  wire_.beginTransmission(kMuxAddress);
  if (wire_.write(static_cast<std::uint8_t>(0)) == 1) {
    wire_.endTransmission(true);
  }

  auto identity = [this](std::uint8_t address, std::uint8_t& value) {
    wire_.beginTransmission(address);
    if (wire_.write(static_cast<std::uint8_t>(0x0f)) != 1 ||
        wire_.endTransmission(false) != 0) return false;
    if (wire_.requestFrom(address, static_cast<size_t>(1), true) != 1 ||
        wire_.available() < 1) return false;
    const int byte = wire_.read();
    if (byte < 0) return false;
    value = static_cast<std::uint8_t>(byte);
    return true;
  };
  // Standard MPU6050 WHO_AM_I is register 0x75 (NOT Berry 0x0f).
  // AD0 selects either 0x68 or 0x69. Do not trust ACK without the 0x68 ID.
  std::uint8_t mpu_matches = 0;
  std::uint8_t mpu_address = 0;
  for (std::uint8_t addr : {static_cast<std::uint8_t>(0x68), static_cast<std::uint8_t>(0x69)}) {
    std::uint8_t id = 0;
    wire_.beginTransmission(addr);
    if (wire_.write(static_cast<std::uint8_t>(0x75)) == 1 &&
        wire_.endTransmission(false) == 0 &&
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
  result.valid = sample.valid;
  result.distance_mm = sample.mm;
  result.age_ms = now_ms - sample.at_ms;
  return result;
}

void TofBus::poll(CliffGuard& guard, std::uint32_t now_ms) {
  new_extra_channel_ = 255;
  if (!initialized_) {
    failed(guard);
    return;
  }
  // Five mandatory floor/front reads always precede one extra side/rear
  // read, preserving the local guard cadence even on the full eight profile.
  const std::uint8_t channel = scan_.next();
  next_channel_ = channel;
  if (!select(channel)) {
    failed(guard);
    return;
  }
  // Check the actual data-ready register rather than blocking inside the
  // vendor library's read loop, so watchdog and phase updates keep running.
  std::uint8_t ready = 0;
  if (!read_register(0x0031, &ready, 1)) {
    failed(guard);
    return;
  }
  if ((ready & 1U) != 0U) {
    // No new result yet. Never renew a stale sample with a cached value.
    return;
  }
  std::uint8_t result[kMaxSampleBytes]{};
  if (!read_register(0x0089, result, kMaxSampleBytes) ||
      !write_byte(0x0086, 0x01)) {
    failed(guard);
    return;
  }
  // ST ULD/Pololu mapping: raw status 9 means a valid range_status 0.
  // Other codes include insufficient signal, sigma and hardware failures.
  const bool valid = (result[0] & 0x1fU) == 9U;
  const auto distance = static_cast<std::uint16_t>(
      (static_cast<std::uint16_t>(result[13]) << 8) | result[14]);
  // A zero-SPAD result is explicitly rejected; Pololu's generic reader
  // would divide by zero while calculating signal/spad.
  const bool spads_nonzero = result[3] > 0;
  const bool accepted =
      valid && spads_nonzero && distance >= 1 && distance <= 1300;
  if (channel < kFloorAndFrontCount) {
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
