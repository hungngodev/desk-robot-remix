#pragma once

#if (defined(DESK_ROBOT_STEPPER) && DESK_ROBOT_STEPPER) || \
    (defined(DESK_ROBOT_FULL_SENSORS) && DESK_ROBOT_FULL_SENSORS)

// Five critical ST VL53L0X measurements via TCA9548A channels 0..4.
// Full-feature profile adds three side/rear read-only channels 5..7.
// Reuse pinned Pololu VL53L0X initialization, but poll the ready/result
// registers with bounded checked I2C operations rather than its blocking read.
// Raw DEVICE status 11 is valid; reject 0, invalid/out-of-range results.
// Cheap generic GY-530 carriers require actual 3.3V-level and desk-edge trials.
// Source: https://github.com/pololu/vl53l0x-arduino (MIT).

#include <Arduino.h>
#include <Wire.h>
#include <VL53L0X.h>
#include "RangeScanOrder.h"

#ifndef DESK_ROBOT_EXTRA_RANGERS
#define DESK_ROBOT_EXTRA_RANGERS 0
#endif
#include "CliffGuard.h"

namespace desk_robot {

// Only reads WHO_AM_I: no sensor fusion, driver selection or motion authority.
// The photographed owned BerryIMU is likely V1 but its chip is unverified.
// 1 = V1 LSM9DS0, 2 = V2 LSM9DS1, 3 = V3 LSM6DSL, 0 = unknown.
// Exactly the optical quality words ALREADY present in VL53L0X 0x14 result.
// On wire these are unsigned 9.7 fixed-point Mcps, NOT calibrated SNR.
// They never relax the immediate local raw range/status CliffGuard gate.
struct TofOpticalDiagnostic {
  bool present = false;
  bool valid = false;
  std::uint16_t ambient_97 = 0;
  std::uint16_t signal_97 = 0;
  std::uint32_t age_ms = 0;
};

struct ImuIdentity {
  std::uint8_t family = 0;
  std::uint8_t gyro_id = 0;
  std::uint8_t aux_id = 0;
  std::uint8_t gyro_address = 0;
  std::uint8_t aux_address = 0;
};

class TofBus {
 public:
  // These are board pins, not alternate addresses; every device is 0x29.
  bool begin(int sda, int scl, int mux_reset_pin);
  // Poll at most one channel per call. Never block waiting for ready.
  // A stuck line first faults the guard; a later poll may clear the bus.
  // Any bus fault or invalid data immediately feeds the local CliffGuard.
  void poll(CliffGuard& guard, std::uint32_t now_ms);
  bool ready() const { return initialized_; }
  // The optional 0x71 mux can NACK our first startup probe and then be
  // independently recognized by a later touch or accessory driver. Once
  // observed, ALWAYS prove 0x71 is disabled before selecting a 0x70 lane:
  // both generic CAP1188 and VL53L0X carriers can answer at 0x29.
  // Also predeclare 0x71 for a build whose hardware topology requires it.
  // Never clear the required quiescence rule on a later transient NACK.
  void note_optional_mux_present() { optional_mux_present_ = true; }
  std::uint8_t last_channel() const { return next_channel_; }
  std::uint32_t errors() const { return bus_errors_; }
  // 0 left, 1 right, 2 rear. Read-only; no new motion permission.
  RangeDiagnostic extra_diagnostic(std::uint8_t index, std::uint32_t now_ms) const;
  std::uint8_t new_extra_channel() const { return new_extra_channel_; }
  // Read-only, eight-channel quality diagnostics from the SAME 12-byte
  // sample as the raw cliff input. A successful I2C read does not mean that
  // an optical result is motion-safe or physically calibrated.
  TofOpticalDiagnostic optical_diagnostic(std::uint8_t channel,
                                           std::uint32_t now_ms) const;
  std::uint8_t new_optical_channel() const { return new_optical_channel_; }
  // One-time read-only probe on the existing upstream 3.3V I2C bus,
  // after Wire has initialized. Do not call from the motor polling loop.
  ImuIdentity probe_imu();

 private:
  static constexpr std::uint8_t kMuxAddress = 0x70;
  static constexpr std::uint8_t kOptionalMuxAddress = 0x71;
  static constexpr std::uint8_t kSensorAddress = 0x29;
  static constexpr std::uint8_t kFloorAndFrontCount = 5;
  static constexpr std::uint8_t kRangeCount = 5 + (DESK_ROBOT_EXTRA_RANGERS ? 3 : 0);
  static constexpr std::uint8_t kMaxSampleBytes = 12;
  TwoWire& wire_ = Wire;
  VL53L0X devices_[kRangeCount]{};
  RangeScanOrder scan_{DESK_ROBOT_EXTRA_RANGERS != 0};
  std::uint8_t next_channel_ = 0;
  std::uint8_t new_extra_channel_ = 255;
  std::uint8_t new_optical_channel_ = 255;
  struct OpticalSample {
    bool present = false;
    bool valid = false;
    std::uint16_t ambient_97 = 0;
    std::uint16_t signal_97 = 0;
    std::uint32_t at_ms = 0;
  };
  OpticalSample optical_[kRangeCount]{};
  struct ExtraSample {
    bool present = false;
    bool valid = false;
    std::uint16_t mm = 0;
    std::uint32_t at_ms = 0;
  };
  ExtraSample extra_[3]{};
  bool initialized_ = false;
  int sda_pin_ = -1;
  int scl_pin_ = -1;
  int mux_reset_pin_ = -1;
  bool pins_restored_ = true;
  bool recovery_pending_ = false;
  bool recovery_attempted_ = false;
  std::uint32_t last_recovery_ms_ = 0;
  bool optional_mux_present_ = false; // second 8-lane interaction bus if fitted
  std::uint32_t bus_errors_ = 0;

  // Always quiesce any fitted interaction mux before a critical range read.
  bool quiesce_optional_mux();
  bool select(std::uint8_t channel);
  bool read_register(std::uint8_t reg, std::uint8_t* dest, std::uint8_t bytes);
  bool write_byte(std::uint8_t reg, std::uint8_t value);
  bool bus_idle() const;
  bool recover_bus();
  void failed(CliffGuard& guard);
};

}  // namespace desk_robot

#endif  // DESK_ROBOT_STEPPER
