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
  Unsupported320G = 320
};

struct BerryReading {
  BerryModel model = BerryModel::Unknown;
  bool valid = false;
  std::int16_t accel[3]{};
  std::int16_t gyro[3]{};
  std::uint32_t at_ms = 0;
};

class BerryImu {
 public:
  // Both identities must agree. A single I2C ACK is NOT a recognized IMU.
  static BerryModel identify(std::uint8_t gyro_who, std::uint8_t extra_who);
  const BerryReading& reading() const { return reading_; }
  bool configured() const { return configured_; }
  bool fresh(std::uint32_t now_ms) const {
    return configured_ && reading_.valid &&
           now_ms - reading_.at_ms <= 200U;
  }
#if defined(ARDUINO)
  // Call only after TofBus initializes Wire on the same upstream GPIO21/22.
  bool begin(TwoWire& wire);
  // One bounded six-axis sample at most every 50 ms. No busy waits or retry.
  void poll(std::uint32_t now_ms);
#endif

 private:
  BerryReading reading_{};
  bool configured_ = false;
  std::uint32_t last_poll_ms_ = 0;
  bool ever_polled_ = false;
#if defined(ARDUINO)
  TwoWire* wire_ = nullptr;
  std::uint8_t gyro_address_ = 0;
  std::uint8_t extra_address_ = 0;
  bool read_bytes(std::uint8_t address, std::uint8_t reg,
                  std::uint8_t* data, std::uint8_t length);
  bool write_byte(std::uint8_t address, std::uint8_t reg,
                  std::uint8_t value);
#endif
};
}  // namespace desk_robot
