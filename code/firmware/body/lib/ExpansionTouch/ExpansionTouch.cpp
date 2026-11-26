#include "ExpansionTouch.h"
#include "../../include/MuxWrite.h"

#if (defined(DESK_ROBOT_STEPPER) && DESK_ROBOT_STEPPER) || \
    (defined(DESK_ROBOT_FULL_SENSORS) && DESK_ROBOT_FULL_SENSORS)
namespace desk_robot {
bool ExpansionTouch::mux(std::uint8_t address, std::uint8_t mask) {
  if (wire_ == nullptr) return false;
  if (!write_mux_mask(*wire_, address, mask).ok()) return false;
  // A TCA9548A may ACK while a channel is stuck selected. Verify its
  // control register after STOP before exposing optional sensors to the
  // same physical bus as safety-critical 0x29 ranging.
  if (wire_->requestFrom(address, static_cast<std::size_t>(1), true) != 1 ||
      wire_->available() < 1) return false;
  return wire_->read() == mask;
}
bool ExpansionTouch::select() {
  // Never expose safety 0x29 sensors and optional 0x29 devices at once.
  return mux(kRangeMux, 0) && mux(kExpansionMux, 1);
}
bool ExpansionTouch::close() { return mux(kExpansionMux, 0); }
bool ExpansionTouch::read(std::uint8_t reg, std::uint8_t& value) {
  wire_->beginTransmission(address_);
  const bool wrote = wire_->write(reg) == 1;
  // Preserve repeated START after a successful register write, but send
  // STOP after a failed write so a rejected CAP1188 transaction cannot
  // leave the shared bus open across safety-critical ranging polls.
  const bool acknowledged = wire_->endTransmission(!wrote) == 0;
  if (!wrote || !acknowledged) return false;
  if (wire_->requestFrom(address_, static_cast<std::size_t>(1), true) != 1 ||
      wire_->available() < 1) return false;
  const int result = wire_->read();
  if (result < 0) return false;
  value = static_cast<std::uint8_t>(result);
  return true;
}
// Preserve the exact single-register CAP1188 configuration sequence from
// Adafruit's BSD-licensed CAP1188 library, without copying its unbounded
// transport or choosing branded hardware. See:
// https://github.com/adafruit/Adafruit_CAP1188_Library
bool ExpansionTouch::write(std::uint8_t reg, std::uint8_t value) {
  wire_->beginTransmission(address_);
  const bool wrote = wire_->write(reg) == 1 && wire_->write(value) == 1;
  // Always terminate a rejected write before returning to safety ranging.
  const bool acknowledged = wire_->endTransmission(true) == 0;
  return wrote && acknowledged;
}
// Retain the upstream CAP1188 simultaneous-electrode configuration and
// Microchip DS00001620C sections 5.5.2, 6.6, 6.17 and 6.19 noise settings.
// Never force recalibration on a held touch; preserve unrelated bits.
bool ExpansionTouch::configure_bits(std::uint8_t reg, std::uint8_t mask,
                                    std::uint8_t value) {
  std::uint8_t old_value = 0, actual = 0;
  if (!read(reg, old_value)) return false;
  const auto desired = static_cast<std::uint8_t>(
      (old_value & ~mask) | (value & mask));
  return (desired == old_value || write(reg, desired)) &&
         read(reg, actual) && (actual & mask) == (desired & mask);
}
bool ExpansionTouch::configure_step(std::uint8_t step) {
  switch (step) {
    case 0: {
      std::uint8_t product = 0, manufacturer = 0;
      return read(0xFD, product) && product == 0x50 &&
             read(0xFE, manufacturer) && manufacturer == 0x5D;
    }
    case 1: return configure_bits(0x2A, 0x80, 0x00);  // simultaneous touch
    case 2: return configure_bits(0x38, 0x03, 0x01);  // 37.5% noise threshold
    case 3: return configure_bits(0x2F, 0x7F, 0x0A);  // baseline tracking
    case 4: return configure_bits(0x20, 0x38, 0x00);  // filters on, held recal off
    case 5: return configure_bits(0x44, 0x04, 0x00);  // RF noise filter on
    case 6: return configure_bits(0x21, 0xFF, 0xFF);  // all eight inputs, DS00001620C §6.7
    default: return false;
  }
}
void ExpansionTouch::invalidate_bus() {
  // Never start probing hardware that was not verified at startup.
  if (!verified_ && !recovering_) return;
  verified_ = false;
  recovering_ = true;
  recovery_step_ = 0;
}
bool ExpansionTouch::begin(TwoWire& wire) {
  wire_ = &wire;  // existing 400kHz/15ms bounded bus, never begin twice
  present_ = false;
  verified_ = false;
  recovering_ = false;
  recovery_step_ = 0;
  polled_ = false;
  wire_->beginTransmission(kExpansionMux);
  present_ = wire_->endTransmission(true) == 0;
  if (!present_) return false;
  if (!select()) { close(); return false; }
  // The range mux is positively verified OFF before address probes.
  // Use chip identity instead of an ACK; never talk to the ToF sensor
  // at 0x29 and misinterpret it as an 8-pad touch controller.
  bool recognized = false;
  const std::uint8_t candidates[] = {kPreferredAddress, kAlternativeAddress};
  for (const std::uint8_t candidate : candidates) {
    address_ = candidate;
    if (configure_step(0)) {
      recognized = true;
      break;
    }
  }
  bool configured = recognized;
  for (std::uint8_t step = 1; configured && step < kRecoverySteps; ++step)
    configured = configure_step(step);
  const bool closed = close();
  verified_ = configured && closed;
  return verified_;
}
bool ExpansionTouch::poll(std::uint32_t now_ms, std::uint8_t& zones) {
  if ((!verified_ && !recovering_) ||
      (polled_ && now_ms - last_ms_ < (recovering_ ? 250U : 80U))) return false;
  polled_ = true;
  last_ms_ = now_ms;
  if (!select()) { close(); invalidate_bus(); return false; }
  if (recovering_) {
    // At most one identity or configuration step per poll, never a full
    // startup sequence in the safety loop. Close even on a failed step.
    const bool configured = configure_step(recovery_step_);
    const bool closed = close();
    if (!configured || !closed) { invalidate_bus(); return false; }
    if (++recovery_step_ == kRecoverySteps) {
      recovering_ = false;
      verified_ = true;
    }
    return false;  // Only a subsequent successful status read publishes touch.
  }
  std::uint8_t bits = 0;
  const bool sample_ok = read(0x03, bits);
  // CAP1188 can assert MAIN.INT on RELEASE when the contact mask is zero.
  // Follow the upstream touched() path and acknowledge every completed
  // status read, while preserving unrelated MAIN bits. A failed clear
  // invalidates this poll instead of publishing a false release.
  bool cleared = true;
  if (sample_ok) {
    std::uint8_t main_control = 0;
    cleared = read(0x00, main_control) &&
              write(0x00, static_cast<std::uint8_t>(main_control & ~0x01U));
  }
  const bool closed = close();
  if (!sample_ok || !cleared || !closed) { invalidate_bus(); return false; }
  zones = bits;
  return true;
}
} // namespace desk_robot
#endif
