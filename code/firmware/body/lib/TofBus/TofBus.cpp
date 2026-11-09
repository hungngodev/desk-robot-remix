#include "TofBus.h"

namespace desk_robot {

bool TofBus::select(std::uint8_t channel) {
  if (channel >= kFloorAndFrontCount) return false;
  wire_.beginTransmission(kMuxAddress);
  if (wire_.write(static_cast<std::uint8_t>(1U << channel)) != 1) return false;
  return wire_.endTransmission(true) == 0;
}

bool TofBus::read_register(std::uint16_t reg, std::uint8_t* out, std::uint8_t length) {
  if (!out || length == 0 || length > kMaxSampleBytes) return false;
  wire_.beginTransmission(kSensorAddress);
  if (wire_.write(static_cast<std::uint8_t>(reg >> 8)) != 1 ||
      wire_.write(static_cast<std::uint8_t>(reg)) != 1 ||
      wire_.endTransmission(false) != 0) {
    return false;
  }
  if (wire_.requestFrom(kSensorAddress, length, true) != length) return false;
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
  return wire_.write(static_cast<std::uint8_t>(reg >> 8)) == 1 &&
         wire_.write(static_cast<std::uint8_t>(reg)) == 1 &&
         wire_.write(value) == 1 &&
         wire_.endTransmission(true) == 0;
}

void TofBus::failed(CliffGuard& guard) {
  ++bus_errors_;
  guard.bus_fault();
}

bool TofBus::begin(int sda, int scl, int mux_reset_pin) {
  initialized_ = false;
  // Pololu sensor setup is bounded by its 80ms init timeout. Actual I2C
  // requests also require Wire's own 15ms timeout, independent of the sensor.
  wire_.begin(sda, scl, 400000);
  wire_.setTimeOut(15);
  pinMode(mux_reset_pin, OUTPUT);
  digitalWrite(mux_reset_pin, LOW);
  delayMicroseconds(10);
  digitalWrite(mux_reset_pin, HIGH);
  delay(2);
  device_.setBus(&wire_);
  device_.setTimeout(80);
  for (std::uint8_t channel = 0; channel < kFloorAndFrontCount; ++channel) {
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

void TofBus::poll(CliffGuard& guard, std::uint32_t now_ms) {
  if (!initialized_) {
    failed(guard);
    return;
  }
  const std::uint8_t channel = next_channel_;
  next_channel_ = (next_channel_ + 1) % kFloorAndFrontCount;
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
  guard.sample(channel, distance,
               valid && spads_nonzero && distance >= 1 && distance <= 1300,
               now_ms);
}

}  // namespace desk_robot
