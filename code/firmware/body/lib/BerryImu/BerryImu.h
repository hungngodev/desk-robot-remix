#pragma once

#include <cstdint>

// OzzMaker BerryIMU identity/register mapping reference:
// https://github.com/ozzmaker/BerryIMU/tree/master/arduino-BerryIMU
// This is a bounded shared-I2C adapter, not an independent motion authority.
// No board revision, pin voltage, mounting axis or calibration is assumed.
#if defined(ARDUINO)
#include <Wire.h>
#endif

namespace desk_robot {

enum class BerryModel : std::uint16_t {
  Unknown = 0,
  V1Lsm9ds0 = 1,
  V2Lsm9ds1 = 2,
  V3Lsm6dsl = 3,
  Mpu6050 = 4, // six-axis InvenSense sensor, no BerryIMU aux sensor
  Unsupported320G = 320
};

struct BerryReading {
  BerryModel model = BerryModel::Unknown;
  bool valid = false;
  std::int16_t accel[3]{};
  std::int16_t gyro[3]{};
  // Read-only MPU6050 TEMP_OUT raw register, not a calibrated temperature.
  // Other IMU families do not supply this value through this adapter.
  std::int16_t temperature_raw = 0;
  // InvenSense FF_THR/FF_DUR + INT_STATUS read-only low-g interrupt.
  // No physical fall qualification, motion authority or extra hardware.
  bool low_g_status_valid = false;
  bool low_g_irq = false;
  std::uint32_t low_g_event_seq = 0;  // rises on a new sampled IRQ edge
  std::uint32_t at_ms = 0;
};

class BerryImu {
 public:
  // Both identities must agree. A single I2C ACK is NOT a recognized IMU.
  static BerryModel identify(std::uint8_t gyro_who, std::uint8_t extra_who);
  // Big-endian MPU sample: accel 0..5, temperature 6..7, gyro 8..13.
  static void decode_mpu6050(const std::uint8_t (&bytes)[14], BerryReading& sample);
  const BerryReading& reading() const { return reading_; }
  void invalidate_bus() {
    reading_.valid = false;
    reading_.low_g_status_valid = false;
    reading_.low_g_irq = false;
  }
  bool configured() const { return configured_; }
  bool fresh(std::uint32_t now_ms) const {
    return configured_ && reading_.valid &&
           now_ms - reading_.at_ms <= 200U;
  }
#if defined(ARDUINO)
  // Call only after TofBus initializes Wire on the same upstream GPIO21/22.
  // Reuse the existing ToF owner's one-time WHO_AM_I probe, not a second scan.
  bool begin(TwoWire& wire, BerryModel model, std::uint8_t gyro_address,
             std::uint8_t extra_address);
  // One bounded six-axis sample at most every 50 ms. No busy waits or retry.
  void poll(std::uint32_t now_ms);
#endif

 private:
  BerryReading reading_{};
  bool configured_ = false;
#if defined(ARDUINO)
  // Poll cadence is firmware-only; host builds must not carry unused fields.
  std::uint32_t last_poll_ms_ = 0;
  bool ever_polled_ = false;
  TwoWire* wire_ = nullptr;
  std::uint8_t gyro_address_ = 0;
  std::uint8_t extra_address_ = 0;
  bool last_low_g_irq_ = false; // suppress repeated IRQ status polls
  bool read_bytes(std::uint8_t address, std::uint8_t reg,
                  std::uint8_t* data, std::uint8_t length);
  bool write_byte(std::uint8_t address, std::uint8_t reg,
                  std::uint8_t value);
#endif
};
}  // namespace desk_robot
