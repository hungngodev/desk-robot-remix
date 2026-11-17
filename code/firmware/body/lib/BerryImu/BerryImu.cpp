#include "BerryImu.h"

namespace desk_robot {

BerryModel BerryImu::identify(std::uint8_t gyro, std::uint8_t other) {
  if (gyro == 0xd4 && other == 0x49) return BerryModel::V1Lsm9ds0;
  if (gyro == 0x68 && other == 0x3d) return BerryModel::V2Lsm9ds1;
  if (gyro == 0x6a && other == 0x3d) return BerryModel::V3Lsm6dsl;
  if (gyro == 0x73 && other == 0x3d) return BerryModel::Unsupported320G;
  if (gyro == 0x68 && other == 0x00) return BerryModel::Mpu6050;
  return BerryModel::Unknown;
}

void BerryImu::decode_mpu6050(const std::uint8_t (&bytes)[14], BerryReading& sample) {
  for (int i = 0; i < 3; ++i) {
    const auto accel = static_cast<std::uint16_t>((static_cast<unsigned>(bytes[2*i]) << 8) | bytes[2*i + 1]);
    const auto gyro = static_cast<std::uint16_t>((static_cast<unsigned>(bytes[8 + 2*i]) << 8) | bytes[9 + 2*i]);
    sample.accel[i] = static_cast<std::int16_t>(accel);
    sample.gyro[i] = static_cast<std::int16_t>(gyro);
  }
}

#if defined(ARDUINO)
// The WROOM ToF adapter owns Wire initialization and its 15 ms timeout.
// Repeated-start reads share that bus; these calls never initialize another bus,
// select any TCA9548A downstream channel, or block waiting for data-ready.
bool BerryImu::read_bytes(std::uint8_t address, std::uint8_t reg,
                         std::uint8_t* data, std::uint8_t length) {
  if (wire_ == nullptr || data == nullptr || length == 0 || length > 14) return false;
  wire_->beginTransmission(address);
  const bool wrote = wire_->write(reg) == 1;
  const bool acknowledged = wire_->endTransmission(!wrote) == 0;
  if (!wrote || !acknowledged) return false;
  if (wire_->requestFrom(address, static_cast<size_t>(length), true) != length)
    return false;
  for (std::uint8_t i = 0; i < length; ++i) {
    const int n = wire_->read();
    if (n < 0) return false;
    data[i] = static_cast<std::uint8_t>(n);
  }
  return true;
}

bool BerryImu::write_byte(std::uint8_t address, std::uint8_t reg,
                         std::uint8_t value) {
  if (wire_ == nullptr) return false;
  wire_->beginTransmission(address);
  const bool wrote = wire_->write(reg) == 1 && wire_->write(value) == 1;
  const bool acknowledged = wire_->endTransmission(true) == 0;
  return wrote && acknowledged;
}

bool BerryImu::begin(TwoWire& wire, BerryModel model,
                    std::uint8_t gyro_address, std::uint8_t extra_address) {
  wire_ = &wire;
  configured_ = false;
  reading_ = BerryReading{};
  ever_polled_ = false;
  if (model == BerryModel::Unknown || model == BerryModel::Unsupported320G) return false;
  if (model == BerryModel::Mpu6050) {
    if ((gyro_address != 0x68 && gyro_address != 0x69) || extra_address != 0x00) return false;
  } else if ((gyro_address != 0x6a && gyro_address != 0x6b) ||
             (extra_address != 0x1c && extra_address != 0x1d && extra_address != 0x1e)) {
    return false;
  }
  reading_.model = model;
  gyro_address_ = gyro_address;
  extra_address_ = extra_address;

  // Limited data rates, raw telemetry only, and no magnetometer/pressure
  // configuration. Register meanings follow OzzMaker's original Arduino
  // BerryIMU variant definitions. Physical axes are NOT yet calibrated.
  bool ok = false;
  if (reading_.model == BerryModel::Mpu6050) {
    // Official InvenSense RM-MPU-6000A register map, not BerryIMU registers.
    // Wake from default sleep; all six axes; 1 kHz internal sample with
    // DLPF=3, +/-2 g and +/-250 degrees/s. No DMP or extra task.
    ok = write_byte(gyro_address_, 0x6b, 0x01) &&
         write_byte(gyro_address_, 0x6c, 0x00) &&
         write_byte(gyro_address_, 0x1a, 0x03) &&
         write_byte(gyro_address_, 0x19, 0x09) &&  // output rate 100Hz
         write_byte(gyro_address_, 0x1b, 0x00) &&
         write_byte(gyro_address_, 0x1c, 0x00);
  } else if (reading_.model == BerryModel::V1Lsm9ds0) {
    // LSM9DS0 CTRL_REG1_XM bit 2 and CTRL_REG4_G bit 7 enable
    // block-data-update on both six-byte reads. Without gyro BDU,
    // the sensor may update an MSB between the LSB/MSB I2C transfers.
    // The 245 dps full-scale setting remains unchanged (FS=00).
    ok = write_byte(extra_address_, 0x20, 0x67) &&  // 100Hz XYZ + XM BDU
         write_byte(extra_address_, 0x21, 0x00) &&  // +/-2g
         write_byte(gyro_address_, 0x20, 0x0f) &&   // 95Hz XYZ gyro
         write_byte(gyro_address_, 0x23, 0x80);    // gyro BDU + 245dps
  } else if (reading_.model == BerryModel::V2Lsm9ds1) {
    ok = write_byte(gyro_address_, 0x22, 0x44) &&  // BDU + auto increment
         write_byte(gyro_address_, 0x1e, 0x38) &&  // XYZ gyro
         write_byte(gyro_address_, 0x1f, 0x38) &&  // XYZ accelerometer
         write_byte(gyro_address_, 0x10, 0x60) &&  // 119Hz gyro, 245dps
         write_byte(gyro_address_, 0x20, 0x60);    // 119Hz accel, +/-2g
  } else if (reading_.model == BerryModel::V3Lsm6dsl) {
    ok = write_byte(gyro_address_, 0x12, 0x44) &&  // BDU + auto increment
         write_byte(gyro_address_, 0x10, 0x40) &&  // 104Hz accel, +/-2g
         write_byte(gyro_address_, 0x11, 0x40);    // 104Hz gyro, 250dps
  }
  configured_ = ok;
  return ok;
}

void BerryImu::poll(std::uint32_t now_ms) {
  if (!configured_ || (ever_polled_ && now_ms - last_poll_ms_ < 50U)) return;
  last_poll_ms_ = now_ms;
  ever_polled_ = true;
  if (reading_.model == BerryModel::Mpu6050) {
    std::uint8_t frame[14]{};
    if (!read_bytes(gyro_address_, 0x3b, frame, 14)) {
      reading_.valid = false;
      return;
    }
    decode_mpu6050(frame, reading_);
    reading_.at_ms = now_ms;
    reading_.valid = true;
    return;
  }
  const std::uint8_t gyro_reg =
      reading_.model == BerryModel::V2Lsm9ds1 ? 0x18 :
      reading_.model == BerryModel::V3Lsm6dsl ? 0x22 : 0x28;
  const std::uint8_t accel_reg = 0x28;
  const std::uint8_t reg_flag =
      reading_.model == BerryModel::V3Lsm6dsl ? 0x00 : 0x80;
  std::uint8_t gyro[6]{}, accel[6]{};
  if (!read_bytes(gyro_address_, gyro_reg | reg_flag, gyro, 6) ||
      !read_bytes(reading_.model == BerryModel::V1Lsm9ds0 ?
                      extra_address_ : gyro_address_,
                  accel_reg | reg_flag, accel, 6)) {
    reading_.valid = false;
    return;
  }
  for (int i = 0; i < 3; ++i) {
    const auto g = static_cast<std::uint16_t>(gyro[i * 2]) |
                   (static_cast<std::uint16_t>(gyro[i * 2 + 1]) << 8);
    const auto a = static_cast<std::uint16_t>(accel[i * 2]) |
                   (static_cast<std::uint16_t>(accel[i * 2 + 1]) << 8);
    reading_.gyro[i] = static_cast<std::int16_t>(g);
    reading_.accel[i] = static_cast<std::int16_t>(a);
  }
  reading_.at_ms = now_ms;
  reading_.valid = true;
}
#endif  // ARDUINO
}  // namespace desk_robot
