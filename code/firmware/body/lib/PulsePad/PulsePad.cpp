#include "PulsePad.h"
#ifndef DESK_ROBOT_MAX30102_FIFO_IR_FIRST
#define DESK_ROBOT_MAX30102_FIFO_IR_FIRST 0
#endif
#if DESK_ROBOT_MAX30102_FIFO_IR_FIRST != 0 && DESK_ROBOT_MAX30102_FIFO_IR_FIRST != 1
#error MAX30102 FIFO channel order must be zero or one
#endif
#if (defined(DESK_ROBOT_STEPPER) && DESK_ROBOT_STEPPER) || \
    (defined(DESK_ROBOT_FULL_SENSORS) && DESK_ROBOT_FULL_SENSORS)
namespace desk_robot {
namespace {
constexpr std::uint8_t kTofMux = 0x70;
constexpr std::uint8_t kExtraMux = 0x71;
constexpr std::uint8_t kMax30102 = 0x57;
// MAX30102 datasheet, pp. 12-13: ALC_OVF signals contaminated ADC data.
constexpr std::uint8_t kAmbientOverflow = 0x20;
}
bool PulsePad::select_mux(std::uint8_t address, std::uint8_t mask) {
  wire_->beginTransmission(address);
  const bool wrote = wire_->write(mask) == 1;
  // Always finish a partial transfer; an ACK alone does not prove the
  // 0x70/0x71 multiplexer selected the requested channel.
  const bool acknowledged = wire_->endTransmission(true) == 0;
  if (!wrote || !acknowledged) return false;
  if (wire_->requestFrom(address, static_cast<std::size_t>(1), true) != 1 ||
      wire_->available() < 1) return false;
  return wire_->read() == mask;
}
bool PulsePad::select() {
  // Never expose the floor range multiplexer at the same time as an accessory.
  return select_mux(kTofMux, 0) && select_mux(kExtraMux, 1);
}
bool PulsePad::close() { return select_mux(kExtraMux, 0); }
bool PulsePad::write_reg(std::uint8_t reg, std::uint8_t value) {
  wire_->beginTransmission(kMax30102);
  const bool wrote = wire_->write(reg) == 1 && wire_->write(value) == 1;
  const bool acknowledged = wire_->endTransmission(true) == 0;
  return wrote && acknowledged;
}
bool PulsePad::read_bytes(std::uint8_t reg, std::uint8_t* dest,
                          std::uint8_t length) {
  if (!dest || length == 0 || length > 24) return false;
  wire_->beginTransmission(kMax30102);
  const bool wrote = wire_->write(reg) == 1;
  const bool acknowledged = wire_->endTransmission(!wrote) == 0;
  if (!wrote || !acknowledged) return false;
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
  // Bound the first FIFO observation too: setup can spend hundreds of ms
  // initializing other I2C devices before the main loop starts.
  last_ms_ = millis();
  fifo_unsynced_ = false;
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
                 write_reg(0x02, kAmbientOverflow) &&
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
  // The FIFO has no capture timestamps. After a stalled body poll, even
  // one to four buffered records may be old, despite no FIFO overflow.
  const bool missed_poll_window = now_ms - last_ms_ > 250U;
  polled_ = true;
  last_ms_ = now_ms;
  if (!select()) {
    (void)close();
    fifo_unsynced_ = true;
    sample_.valid = false;
    return false;
  }
  std::uint8_t write_pointer = 0, read_pointer = 0, overflow = 0;
  bool ok = read_reg(0x04, write_pointer) &&
            read_reg(0x05, overflow) &&
            read_reg(0x06, read_pointer);
  // MAX30102 FIFO pointers and overflow counters are five-bit values.
  // Reject corrupt reserved bits rather than masking them into a plausible
  // fresh paw-contact sample. No sensor output is used to authorize motors.
  if (!ok || ((write_pointer | read_pointer | overflow) & 0xe0U) != 0U) {
    // A failed pointer read cannot establish which FIFO records remain.
    fifo_unsynced_ = true;
    (void)close();
    sample_.valid = false;
    return false;
  }
  // Capture overflow before FIFO_DATA can clear interrupt status.
  // A flagged batch has ambiguous optical quality; never publish it as touch.
  std::uint8_t interrupt_status = 0;
  if (!read_reg(0x00, interrupt_status)) {
    fifo_unsynced_ = true;
    (void)close();
    sample_.valid = false;
    return false;
  }
  const std::uint8_t available =
      static_cast<std::uint8_t>((write_pointer - read_pointer) & 31U);
  // The MAX30102 FIFO_RD_PTR (0x06) is writable. If the body loop was
  // delayed, even a short backlog may contain stale paw contact. Reject
  // elapsed polls exceeding 250ms as well as count and overflow anomalies.
  // Drop any ambiguous backlog without assigning it a new capture time.
  // A new reading must arrive on a later poll before an event is emitted.
  if (fifo_unsynced_ || missed_poll_window || available > 4U ||
      (overflow & 31U) != 0U ||
      (interrupt_status & kAmbientOverflow) != 0U) {
    // A full FIFO can wrap both pointers to the same value. The hardware
    // overflow counter is independent evidence that samples were lost.
    // Clear both old data and the overflow flag before accepting new ones.
    const bool discarded =
        write_reg(0x06, static_cast<std::uint8_t>(write_pointer & 31U));
    const bool cleared = write_reg(0x05, 0);
    const bool closed = close();
    // On a failed flush or mux close, keep quarantine for the next poll.
    fifo_unsynced_ = !(discarded && cleared && closed);
    sample_.valid = false;
    return false;
  }
  // At most four recent samples / 24 bytes in one safety-first iteration.
  const std::uint8_t n = available;
  std::uint8_t data[24]{};
  if (n > 0) ok = read_bytes(0x07, data, n * 6);
  const bool closed = close();
  if (!ok || !closed) {
    // A partial FIFO transfer can consume samples before reporting failure.
    // Never timestamp the remainder as a new physical paw interaction.
    fifo_unsynced_ = true;
    sample_.valid = false;
    return false;
  }
  if (n == 0) {
    // Do not keep reporting the last accepted sample as presently valid
    // when the hardware FIFO has no new conversion. Preserve provenance
    // (at_ms and sample_seq) for a read-only historical diagnostic.
    sample_.valid = false;
    return false;
  }
  const std::uint8_t* latest = &data[(n - 1) * 6];
  // Default is datasheet RED/IR. Set FIFO_IR_FIRST=1 only after proving
  // the actual generic carrier's optical response with each LED isolated.
  const auto channels = decode_optical_channels(
      latest, DESK_ROBOT_MAX30102_FIFO_IR_FIRST == 1);
  // Full-scale ADC data cannot distinguish reflection from clipping.
  if (optical_channels_saturated(channels)) {
    sample_.valid = false;
    return false;
  }
  sample_.red = channels.red;
  sample_.ir = channels.ir;
  sample_.valid = true;
  sample_.at_ms = now_ms;
  ++sample_.sample_seq;
  if (sample_.sample_seq == 0U) ++sample_.sample_seq;
  return true;
}
} // namespace desk_robot
#endif
