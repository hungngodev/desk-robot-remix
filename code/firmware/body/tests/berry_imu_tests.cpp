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

int main() {
  try {
    using desk_robot::BerryImu;
    using desk_robot::BerryModel;
    CHECK(BerryImu::identify(0xd4, 0x49) == BerryModel::V1Lsm9ds0);
    CHECK(BerryImu::identify(0x68, 0x3d) == BerryModel::V2Lsm9ds1);
    CHECK(BerryImu::identify(0x6a, 0x3d) == BerryModel::V3Lsm6dsl);
    CHECK(BerryImu::identify(0x73, 0x3d) == BerryModel::Unsupported320G);
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
    CHECK(reply.find("\"age_ms\":20") != std::string::npos);
    CHECK(!body.state().armed);

    reply = status(body, 301);
    CHECK(reply.find("\"aux_id\":73,\"valid\":false") != std::string::npos);
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
    CHECK(reply.size() < 768);
    CHECK(!body.state().armed);
    std::cout << "PASS BerryIMU identity, fail-closed diagnostic validity, and bounded status\n";
  } catch (const std::exception& error) {
    std::cerr << "FAIL " << error.what() << '\n';
    return 1;
  }
}
