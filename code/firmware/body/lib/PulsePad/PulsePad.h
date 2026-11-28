#pragma once
#if (defined(DESK_ROBOT_STEPPER) && DESK_ROBOT_STEPPER) || \
    (defined(DESK_ROBOT_FULL_SENSORS) && DESK_ROBOT_FULL_SENSORS)
#include <Arduino.h>
#include <Wire.h>
#include "OpticalRaw.h"
namespace desk_robot {
// Bounded MAX30102 optical paw adapter. Explicitly not a medical or HR sensor.
// Uses SparkFun's documented register/FIFO model without their potentially
// 250ms blocking convenience getIR() in our safety-critical loop.
class PulsePad {
 public:
  bool begin(TwoWire& wire);
  // Maximum four red+IR FIFO records (24B) per call, 60ms polling cadence.
  // No access to motor pins, arm, safety guard, or lift servo.
  bool poll(std::uint32_t now_ms);
  const OpticalRaw& sample() const { return sample_; }
  void invalidate_bus() {
    sample_.valid = false;
    fifo_unsynced_ = true;
    if (recovering_) recovery_step_ = 0;
  }
  // Acknowledged 0x71 even if selection/readback or optical init failed.
  bool mux_present() const { return mux_present_; }
 private:
  TwoWire* wire_ = nullptr;
  OpticalRaw sample_{};
  std::uint32_t last_ms_ = 0;
  bool polled_ = false;
  bool mux_present_ = false;
  // After ambiguous I2C FIFO consumption, discard old records before reuse.
  bool fifo_unsynced_ = false;
  bool recovering_ = false;
  std::uint8_t recovery_step_ = 0;
  bool configure_setting(std::uint8_t step);
  void recover_configuration();
  bool select();
  bool close();
  bool select_mux(std::uint8_t address, std::uint8_t mask);
  bool write_reg(std::uint8_t reg, std::uint8_t value);
  bool read_reg(std::uint8_t reg, std::uint8_t& value);
  bool read_bytes(std::uint8_t reg, std::uint8_t* dest, std::uint8_t length);
};
} // namespace desk_robot
#endif
