#include "TofArray.h"

namespace desk_robot {

bool TofArray::select(std::uint8_t channel) {
  if (bus_ == nullptr || channel >= kChannels) return false;
  // Every sensor retains its factory address 0x29. The mux guarantees that
  // only one downstream sensor is visible to this WROOM I2C master at a time.
  bus_->beginTransmission(kMuxAddress);
  bus_->write(static_cast<std::uint8_t>(1U << channel));
  return bus_->endTransmission() == 0;
}

void TofArray::failure() {
  ready_ = false;
  if (guard_) guard_->bus_fault();  // latched, never self-clear
  if (bus_) {
    bus_->beginTransmission(kMuxAddress);
    bus_->write(static_cast<std::uint8_t>(0));
    bus_->endTransmission();
  }
}

bool TofArray::begin(TwoWire& bus, int reset_pin, CliffGuard& guard) {
  bus_ = &bus;
  guard_ = &guard;
  ready_ = false;
  next_channel_ = 0;
  for (std::uint8_t ch = 0; ch < kChannels; ++ch) {
    sample_seen_[ch] = false;
    last_read_ms_[ch] = 0;
  }
  // RESET wiring is optional on TCA9548A modules but is reserved on WROOM 4.
  // Set a connected reset output HIGH, then deselect all mux channels.
  // No motor is enabled during this sequence.
  if (reset_pin >= 0) {
    pinMode(reset_pin, OUTPUT);
    digitalWrite(reset_pin, LOW);
    delay(2);
    digitalWrite(reset_pin, HIGH);
    delay(2);
  }
  if (!select(0)) {
    failure();
    return false;
  }
  for (std::uint8_t ch = 0; ch < kChannels; ++ch) {
    if (!select(ch)) {
      failure();
      return false;
    }
    auto& device = sensors_[ch];
    device.setBus(&bus);
    device.setTimeout(250); // Sensor calibration at boot may take longer; motors are OFF
    bus.beginTransmission(kRangerAddress);
    if (bus.endTransmission() != 0 || !device.init()) {
      failure();
      return false;
    }
    // Use Pololu's real timing budget, not a made-up 35ms 5-sensor scan.
    // Each device ranges continuously while the mux selects another channel.
    // Front and floor validity are independently checked in CliffGuard.
    if (!device.setMeasurementTimingBudget(20000)) {
      failure();
      return false;
    }
    device.startContinuous();
    if (device.timeoutOccurred()) {
      failure();
      return false;
    }
    device.setTimeout(12); // Runtime loop is bounded separately from startup
  }
  // Leave no downstream address connected when the CPU is not probing.
  bus.beginTransmission(kMuxAddress);
  bus.write(static_cast<std::uint8_t>(0));
  if (bus.endTransmission() != 0) {
    failure();
    return false;
  }
  ready_ = true;
  return true;
}

void TofArray::poll(std::uint32_t now_ms) {
  if (!ready_ || guard_ == nullptr || bus_ == nullptr) return;
  const std::uint8_t ch = next_channel_;
  next_channel_ = (next_channel_ + 1) % kChannels;

  if (!select(ch)) {
    failure();
    return;
  }

  auto& device = sensors_[ch];
  // Pololu's readRangeContinuousMillimeters() waits for the ready bit. We
  // first probe it ourselves so an unready channel does not stall the 1ms
  // body loop or let the companion continue moving on a stale other corner.
  const std::uint8_t ready = device.readReg(VL53L0X::RESULT_INTERRUPT_STATUS);
  if (device.last_status != 0) {
    failure();
    return;
  }
  if ((ready & 0x07) == 0) {
    // Missing update is NOT a healthy reading. Existing freshness policy
    // expires and latches a local stop before movement resumes.
    if (sample_seen_[ch] && now_ms - last_read_ms_[ch] >= 100) {
      guard_->sample(ch, 0, false, now_ms);
    }
    return;
  }

  const std::uint16_t mm = device.readRangeContinuousMillimeters();
  if (device.timeoutOccurred() || device.last_status != 0) {
    failure();
    return;
  }
  const bool valid = mm != 0 && mm != 65535;
  last_read_ms_[ch] = now_ms;
  sample_seen_[ch] = true;
  guard_->sample(ch, mm, valid, now_ms);
}

}  // namespace desk_robot
