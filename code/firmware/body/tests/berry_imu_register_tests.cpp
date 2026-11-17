#include "BerryImu.h"
#include "Wire.h"
#include <iostream>
#include <stdexcept>

#define CHECK(x) do { if (!(x)) throw std::runtime_error(#x); } while (false)

int main() {
  try {
    using desk_robot::BerryImu;
    using desk_robot::BerryModel;
    TwoWire wire;
    BerryImu imu;
    CHECK(imu.begin(wire, BerryModel::V1Lsm9ds0, 0x6b, 0x1d));
    CHECK(imu.configured());
    CHECK(wire.writes.size() == 4);
    CHECK(wire.wrote(0x1d, 0x20, 0x67)); // XM BDU bit 2 set
    CHECK(wire.wrote(0x1d, 0x21, 0x00)); // +/-2 g unchanged
    CHECK(wire.wrote(0x6b, 0x20, 0x0f)); // gyro XYZ enabled
    CHECK(wire.wrote(0x6b, 0x23, 0x80)); // gyro BDU bit 7 set
    CHECK(!wire.wrote(0x6b, 0x23, 0x00)); // reject torn sample config

    // A failed configuration transaction must not enable telemetry.
    TwoWire failed_wire;
    failed_wire.reject_writes = true;
    BerryImu failed;
    CHECK(!failed.begin(failed_wire, BerryModel::V1Lsm9ds0,
                        0x6b, 0x1d));
    CHECK(!failed.configured());
    CHECK(failed_wire.writes.empty());

    // Wrong chip/addresses must not talk on the bus.
    TwoWire invalid_wire;
    BerryImu invalid;
    CHECK(!invalid.begin(invalid_wire, BerryModel::V1Lsm9ds0,
                         0x68, 0x1d));
    CHECK(invalid_wire.writes.empty());
    std::cout << "PASS LSM9DS0 register BDU, full-scale and fail-closed setup\n";
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "FAIL LSM9DS0 register test: " << e.what() << '\n';
    return 1;
  }
}
