#include "PulsePad.h"
#if defined(DESK_ROBOT_STEPPER) && DESK_ROBOT_STEPPER
namespace desk_robot {
namespace {
constexpr std::uint8_t kTofMux = 0x70;
constexpr std::uint8_t kExtraMux = 0x71;
constexpr std::uint8_t kMax30102 = 0x57;
}
bool PulsePad::select_mux(std::uint8_t address, std::uint8_t mask) {
  wire_->beginTransmission(address);
  return wire_->write(mask) == 1 && wire_->endTransmission(true) == 0;
}
bool PulsePad::select() {
  // Never expose the floor range multiplexer at the same time as an accessory.
  return select_mux(kTofMux, 0) && select_mux(kExtraMux, 1);
}
bool PulsePad::close() { return select_mux(kExtraMux, 0); }
bool PulsePad::write_reg(std::uint8_t reg, std::uint8_t value) {
  wire_->beginTransmission(kMax30102);
  const bool ok = wire_->write(reg) == 1 && wire_->write(value) == 1;
  return ok && wire_->endTransmission(true) == 0;
}
bool PulsePad::read_bytes(std::uint8_t reg, std::uint8_t* dest,
                          std::uint8_t length) {
  if (!dest || length == 0 || length > 24) return false;
  wire_->beginTransmission(kMax30102);
  if (wire_->write(reg) != 1 || wire_->endTransmission(false) != 0)
    return false;
  if (wire_->requestFrom(kMax30102, static_cast<std::size_t>(length), true) != length)
    return false;
  for (std::uint8_t i = 0; i < length; ++i) {
    if (wire_->available() < 1) return false;
    const int reading = wire_->read();
    if (reading < 0) return false;
    dest[i] = static_cast<std::uint8_t>(reading);
  }
  return true;
}
bool PulsePad::read_reg(std::uint8_t reg, std::uint8_t& value) {
  return read_bytes(reg, &value, 1);
}
bool PulsePad::begin(TwoWire& wire) {
  wire_ = &wire; // already set to 400kHz, 15ms Wire bound by TofBus
  sample_ = OpticalRaw{};
  polled_ = false;
  if (!select()) { close(); return false; }
  std::uint8_t part_id = 0;
  const bool recognized = read_reg(0xff, part_id) && part_id == 0x15U;
  bool configured = false;
  if (recognized) {
    // MAX30102 dual LED (RED/IR) mode. No claim of medical SpO2/heart rate.
    // 0x23 = 4096nA ADC, 50sps, 411us pulse from MAX3010x register map.
    // LED pilot settings intentionally low; actual paw enclosure needs trial.
    configured = write_reg(0x09, 0x03) &&
                 write_reg(0x08, 0x00) &&
                 write_reg(0x0a, 0x23) &&
                 write_reg(0x0c, 0x07) &&
                 write_reg(0x0d, 0x07) &&
                 write_reg(0x04, 0x00) &&
                 write_reg(0x05, 0x00) &&
                 write_reg(0x06, 0x00);
  }
  if (!close()) configured = false;
  sample_.present = recognized && configured;
  sample_.part_id = sample_.present ? part_id : 0;
  return sample_.present;
}
bool PulsePad::poll(std::uint32_t now_ms) {
  if (!sample_.present || (polled_ && now_ms - last_ms_ < 60U))
    return false;
  polled_ = true;
  last_ms_ = now_ms;
  if (!select()) { close(); sample_.valid = false; return false; }
  std::uint8_t write_pointer = 0, read_pointer = 0;
  bool ok = read_reg(0x04, write_pointer) && read_reg(0x06, read_pointer);
  const std::uint8_t available =
      static_cast<std::uint8_t>((write_pointer - read_pointer) & 31U);
  // Fixed max four samples/24B, short enough for the safety-first loop.
  // A backlog larger than four is not silently counted as a new heartbeat.
  const std::uint8_t n = available > 4 ? 4 : available;
  std::uint8_t data[24]{};
  if (ok && n > 0) ok = read_bytes(0x07, data, n * 6);
  const bool closed = close();
  if (!ok || !closed) { sample_.valid = false; return false; }
  if (n == 0) return false; // no fresh sample, do not fabricate one
  const std::uint8_t* latest = &data[(n - 1) * 6];
  sample_.red = optical18(latest);
  sample_.ir = optical18(latest + 3);
  sample_.valid = true;
  sample_.at_ms = now_ms;
  return true;
}
} // namespace desk_robot
#endif
