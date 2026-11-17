#include "ExpansionTouch.h"

#if (defined(DESK_ROBOT_STEPPER) && DESK_ROBOT_STEPPER) || \
    (defined(DESK_ROBOT_FULL_SENSORS) && DESK_ROBOT_FULL_SENSORS)
namespace desk_robot {
bool ExpansionTouch::mux(std::uint8_t address, std::uint8_t mask) {
  if (wire_ == nullptr) return false;
  wire_->beginTransmission(address);
  const bool wrote = wire_->write(mask) == 1;
  // Complete the attempted transfer even when write() fails.
  const bool acknowledged = wire_->endTransmission(true) == 0;
  if (!wrote || !acknowledged) return false;
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
  // Always terminate the attempted register transaction, including a failed write.
  const bool acknowledged = wire_->endTransmission(false) == 0;
  if (!wrote || !acknowledged) return false;
  if (wire_->requestFrom(address_, static_cast<std::size_t>(1), true) != 1 ||
      wire_->available() < 1) return false;
  const int result = wire_->read();
  if (result < 0) return false;
  value = static_cast<std::uint8_t>(result);
  return true;
}
bool ExpansionTouch::begin(TwoWire& wire) {
  wire_ = &wire;  // existing 400kHz/15ms bounded bus, never begin twice
  present_ = false;
  verified_ = false;
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
    std::uint8_t product = 0, manufacturer = 0;
    if (read(0xFD, product) && read(0xFE, manufacturer) &&
        product == 0x50 && manufacturer == 0x5D) {
      recognized = true;
      break;
    }
  }
  if (!close()) return false;
  verified_ = recognized;
  return verified_;
}
bool ExpansionTouch::poll(std::uint32_t now_ms, std::uint8_t& zones) {
  if (!verified_ || (polled_ && now_ms - last_ms_ < 80U)) return false;
  polled_ = true;
  last_ms_ = now_ms;
  if (!select()) { close(); verified_ = false; return false; }
  std::uint8_t bits = 0;
  const bool sample_ok = read(0x03, bits);
  const bool closed = close();
  if (!sample_ok || !closed) { verified_ = false; return false; }
  zones = bits;
  return true;
}
} // namespace desk_robot
#endif
