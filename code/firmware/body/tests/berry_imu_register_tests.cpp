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
    CHECK(wire.wrote(0x1d, 0x20, 0x6f)); // 100 Hz + XYZ + XM BDU bit 3
    CHECK(!wire.wrote(0x1d, 0x20, 0x67)); // bit 2 is AZEN, not BDU
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
    // Real MPU register sequencing, adapted from InvenSense and i2cdevlib.
    TwoWire mpu_wire;
    BerryImu mpu;
    CHECK(mpu.begin(mpu_wire, BerryModel::Mpu6050, 0x68, 0x00));
    CHECK(mpu.configured());
    CHECK(mpu_wire.wrote(0x68, 0x1d, 150)); // 300 mg candidate
    CHECK(mpu_wire.wrote(0x68, 0x1e, 40));  // 40 ms candidate
    CHECK(mpu_wire.wrote(0x68, 0x37, 0x00)); // status-only clear
    CHECK(mpu_wire.wrote(0x68, 0x38, 0x80)); // native FF enable
    mpu.poll(100);
    CHECK(mpu.reading().valid && mpu.reading().low_g_status_valid);
    CHECK(!mpu.reading().low_g_irq);
    CHECK(mpu.reading().low_g_event_seq == 0U);
    mpu_wire.registers[0x3a] = 0x80;
    mpu.poll(150);
    CHECK(mpu.reading().low_g_irq && mpu.reading().low_g_event_seq == 1U);
    mpu_wire.registers[0x3a] = 0x80;
    mpu.poll(200);
    CHECK(mpu.reading().low_g_event_seq == 1U); // no repeated edge
    mpu.poll(250); // INT_STATUS was cleared on read
    CHECK(!mpu.reading().low_g_irq);
    mpu_wire.registers[0x3a] = 0x80;
    mpu.poll(300);
    CHECK(mpu.reading().low_g_event_seq == 2U);
    mpu_wire.reject_read_reg = 0x3a;
    mpu.poll(350);
    CHECK(mpu.reading().valid && !mpu.reading().low_g_status_valid);
    CHECK(!mpu.reading().low_g_irq);
    CHECK(mpu.reading().low_g_event_seq == 2U);
    mpu_wire.reject_read_reg = -1;
    mpu.poll(400);
    CHECK(mpu.reading().low_g_status_valid && !mpu.reading().low_g_irq);
    mpu_wire.registers[0x3a] = 0x80;
    mpu.poll(450);
    CHECK(mpu.reading().low_g_event_seq == 3U);

    // An unreadable 14-byte conversion must invalidate the current low-g
    // status as well as the sample. A recovery with the same latched IRQ
    // must not replay it as a newly observed event.
    mpu_wire.reject_read_reg = 0x3b;
    mpu.poll(500);
    CHECK(!mpu.reading().valid);
    CHECK(!mpu.reading().low_g_status_valid);
    CHECK(!mpu.reading().low_g_irq);
    CHECK(mpu.reading().low_g_event_seq == 3U);
    mpu_wire.reject_read_reg = -1;
    mpu_wire.registers[0x3a] = 0x80;
    mpu.poll(550);
    CHECK(mpu.reading().valid && mpu.reading().low_g_status_valid);
    CHECK(mpu.reading().low_g_irq);
    CHECK(mpu.reading().low_g_event_seq == 3U);
    mpu.poll(600); // successful clear of the retained IRQ
    CHECK(mpu.reading().valid && !mpu.reading().low_g_irq);
    mpu_wire.registers[0x3a] = 0x80;
    mpu.poll(650);
    CHECK(mpu.reading().low_g_event_seq == 4U);

    TwoWire bad_readback;
    bad_readback.reject_read_reg = 0x1d;
    BerryImu unverified_ff;
    CHECK(!unverified_ff.begin(bad_readback, BerryModel::Mpu6050, 0x68, 0x00));
    CHECK(!unverified_ff.configured());

    TwoWire wrong_clear_mode;
    wrong_clear_mode.reject_read_reg = 0x37;
    BerryImu cannot_prove_latched_status;
    CHECK(!cannot_prove_latched_status.begin(
        wrong_clear_mode, BerryModel::Mpu6050, 0x68, 0x00));
    CHECK(!cannot_prove_latched_status.configured());
    std::cout << "PASS IMU register BDU, native low-g IRQ and fail-closed setup\\n";
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "FAIL LSM9DS0 register test: " << e.what() << '\n';
    return 1;
  }
}
