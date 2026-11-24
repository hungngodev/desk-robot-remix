#include "BerryImu.h"
#include "BodyControl.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

#define CHECK(expression) do { if (!(expression)) throw std::runtime_error(#expression); } while (false)

static std::string status(desk_robot::BodyControl& body, std::uint32_t now) {
  char buffer[desk_robot::kReplyCapacity]{};
  body.execute("status", 6, now, buffer, sizeof(buffer));
  return std::string(buffer);
}

// Every signed 16-bit register value, on every axis and TEMP_OUT. Offset
// each word independently so a swapped axis or byte order cannot pass.
static void verify_mpu_register_decode() {
  desk_robot::BerryReading sample{};
  sample.model = desk_robot::BerryModel::Mpu6050;
  sample.valid = true;
  sample.at_ms = 123;
  sample.low_g_status_valid = true;
  sample.low_g_irq = true;
  sample.low_g_event_seq = 9;
  for (std::uint32_t value = 0; value < 65536U; ++value) {
    std::uint8_t bytes[14]{};
    std::int32_t expected[7]{};
    for (unsigned word = 0; word < 7; ++word) {
      const auto raw = (value + word * 7919U) & 0xffffU;
      bytes[2 * word] = static_cast<std::uint8_t>(raw >> 8);
      bytes[2 * word + 1] = static_cast<std::uint8_t>(raw & 0xffU);
      expected[word] = static_cast<std::int32_t>(raw);
      if (raw >= 32768U) expected[word] -= 65536;
    }
    desk_robot::BerryImu::decode_mpu6050(bytes, sample);
    for (unsigned axis = 0; axis < 3; ++axis) {
      CHECK(sample.accel[axis] == expected[axis]);
      CHECK(sample.gyro[axis] == expected[axis + 4]);
    }
    CHECK(sample.temperature_raw == expected[3]);
    // The decoder cannot grant freshness or overwrite acquisition metadata.
    CHECK(sample.model == desk_robot::BerryModel::Mpu6050);
    CHECK(sample.valid && sample.at_ms == 123);
    CHECK(sample.low_g_status_valid && sample.low_g_irq);
    CHECK(sample.low_g_event_seq == 9);
  }
}

int main() {
  try {
    using desk_robot::BerryImu;
    using desk_robot::BerryModel;
    verify_mpu_register_decode();
    CHECK(BerryImu::identify(0xd4, 0x49) == BerryModel::V1Lsm9ds0);
    CHECK(BerryImu::identify(0x68, 0x3d) == BerryModel::V2Lsm9ds1);
    CHECK(BerryImu::identify(0x6a, 0x3d) == BerryModel::V3Lsm6dsl);
    CHECK(BerryImu::identify(0x73, 0x3d) == BerryModel::Unsupported320G);
    CHECK(BerryImu::identify(0x68, 0x00) == BerryModel::Mpu6050);
    CHECK(BerryImu::identify(0x68, 0x49) == BerryModel::Unknown);
    desk_robot::BerryReading mpu;
    mpu.model = BerryModel::Mpu6050;
    const std::uint8_t mpu_wire[14] = {
      0x40, 0x00, 0xc0, 0x00, 0x00, 0x02, 0xfa, 0xfa,
      0xff, 0xf0, 0x00, 0x00, 0x01, 0x00
    };
    BerryImu::decode_mpu6050(mpu_wire, mpu);
    CHECK(mpu.accel[0] == 16384 && mpu.accel[1] == -16384 && mpu.accel[2] == 2);
    CHECK(mpu.gyro[0] == -16 && mpu.gyro[1] == 0 && mpu.gyro[2] == 256);
    CHECK(mpu.temperature_raw == static_cast<std::int16_t>(0xfafa));
    // Signed TEMP_OUT is raw evidence, not a calibrated temperature.
    const std::uint8_t mpu_hot[14] = {
      0x40, 0x00, 0xc0, 0x00, 0x00, 0x02, 0x01, 0x58,
      0xff, 0xf0, 0x00, 0x00, 0x01, 0x00
    };
    BerryImu::decode_mpu6050(mpu_hot, mpu);
    CHECK(mpu.temperature_raw == 344);
    CHECK(BerryImu::identify(0x6a, 0x49) == BerryModel::Unknown);
    CHECK(BerryImu::identify(0x00, 0x3d) == BerryModel::Unknown);

    desk_robot::BodyControl body(desk_robot::BodyProfile::StepperGuarded);
    auto reply = status(body, 1);
    CHECK(reply.find("\"imu\":{\"family\":0,\"gyro_id\":0,\"aux_id\":0,\"valid\":false") != std::string::npos);
    CHECK(!body.state().armed);

    desk_robot::BerryReading reading;
    reading.model = BerryModel::V1Lsm9ds0;
    reading.valid = true;
    reading.at_ms = 100;
    reading.accel[0] = -32768;
    reading.accel[1] = 4567;
    reading.accel[2] = 16384;
    reading.gyro[0] = -5;
    reading.gyro[1] = 31;
    reading.gyro[2] = 2000;
    body.set_imu_identity(1, 212, 73);
    body.set_imu(reading);
    reply = status(body, 120);
    CHECK(reply.find("\"imu\":{\"family\":1,\"gyro_id\":212,\"aux_id\":73,\"valid\":true") != std::string::npos);
    CHECK(reply.find("\"acc\":[-32768,4567,16384]") != std::string::npos);
    CHECK(reply.find("\"gyro\":[-5,31,2000]") != std::string::npos);
    CHECK(reply.find("\"temp_valid\":false") != std::string::npos);
    CHECK(reply.find("\"age_ms\":20") != std::string::npos);
    CHECK(reply.find("\"extras\":{\"mask\":0") != std::string::npos);
    CHECK(!body.state().armed);
    mpu.valid = true;
    mpu.at_ms = 200;
    mpu.low_g_status_valid = true;
    mpu.low_g_irq = true;
    mpu.low_g_event_seq = 7;
    body.set_imu_identity(4, 0x68, 0);
    body.set_imu(mpu);
    reply = status(body, 215);
    // A fresh MPU6050 low-g interrupt must veto motion validity even when
    // the raw six-axis frame and chip identity are otherwise healthy.
    CHECK(reply.find("\"family\":4,\"gyro_id\":104,\"aux_id\":0,\"valid\":false") != std::string::npos);
    CHECK(reply.find("\"acc\":[16384,-16384,2]") != std::string::npos);
    CHECK(reply.find("\"temp_raw\":344,\"temp_valid\":true") != std::string::npos);
    CHECK(reply.find("\"low_g_valid\":true,\"low_g_irq\":true,\"low_g_seq\":7") != std::string::npos);
    // Only a new clear observation restores freshness; no rearm follows.
    mpu.low_g_irq = false;
    mpu.at_ms = 216;
    body.set_imu(mpu);
    reply = status(body, 217);
    CHECK(reply.find("\"family\":4,\"gyro_id\":104,\"aux_id\":0,\"valid\":true") != std::string::npos);
    CHECK(reply.find("\"low_g_valid\":true,\"low_g_irq\":false,\"low_g_seq\":7") != std::string::npos);
    CHECK(!body.state().armed);
    CHECK(status(body, 500).find("\"low_g_valid\":false,\"low_g_irq\":false,\"low_g_seq\":7") != std::string::npos);
    // Switch back to Berry before the old expected status assertions.
    body.set_imu_identity(1, 212, 73);
    body.set_imu(reading);

    reply = status(body, 301);
    CHECK(reply.find("\"aux_id\":73,\"valid\":false") != std::string::npos);
    CHECK(reply.find("\"temp_valid\":false") != std::string::npos);
    CHECK(!body.state().armed);
    reading.valid = false;
    body.set_imu(reading);
    reply = status(body, 122);
    CHECK(reply.find("\"aux_id\":73,\"valid\":false") != std::string::npos);
    CHECK(reply.find("\"age_ms\":0") != std::string::npos);

    // Worst-case telemetry, counters, and all five range ages still fit
    // the existing head 768-byte limit, including a terminating NUL.
    reading.valid = true;
    for (int i = 0; i < 3; ++i) {
      reading.accel[i] = -32768;
      reading.gyro[i] = -32768;
    }
    body.set_imu(reading);
    for (std::uint32_t i = 0; i < 1000; ++i) {
      body.set_touch(true, i * 4);
      body.set_touch(false, i * 4 + 2);
    }
    reply = status(body, 4294967295U);
    CHECK(!reply.empty() && reply.back() == '}');
    CHECK(reply.size() < desk_robot::kReplyCapacity - 1);
    CHECK(reply.size() < desk_robot::kReplyCapacity);
    CHECK(!body.state().armed);
    std::cout << "PASS BerryIMU identity, fail-closed diagnostic validity, and bounded status\n";
  } catch (const std::exception& error) {
    std::cerr << "FAIL " << error.what() << '\n';
    return 1;
  }
}
