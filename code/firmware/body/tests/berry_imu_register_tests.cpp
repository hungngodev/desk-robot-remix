#include "BerryImu.h"
#include "Wire.h"
#include <iostream>
#include <stdexcept>

#define CHECK(x) do { if (!(x)) throw std::runtime_error(#x); } while (false)

int main() {
  try {
    using desk_robot::BerryImu;
    using desk_robot::BerryModel;
    // External bus loss must invalidate current IRQ evidence, but preserve
    // the historical counter and edge fence across uint32_t rollover.
    {
      TwoWire wire;
      BerryImu imu;
      CHECK(imu.begin(wire, BerryModel::Mpu6050, 0x69, 0));
      wire.registers[0x3a] = 0x80;
      imu.poll(0xffffffd0U);
      CHECK(imu.fresh(0xffffffd0U));
      CHECK(imu.reading().low_g_irq && imu.reading().low_g_event_seq == 1U);
      imu.invalidate_bus();
      CHECK(!imu.fresh(0xffffffd1U));
      CHECK(!imu.reading().low_g_status_valid && !imu.reading().low_g_irq);
      CHECK(imu.reading().low_g_event_seq == 1U);
      CHECK(imu.reading().at_ms == 0xffffffd0U);
      wire.registers[0x3a] = 0x80;
      imu.poll(2U); // 50 ms across rollover
      CHECK(imu.fresh(2U) && imu.reading().low_g_irq);
      CHECK(imu.reading().low_g_event_seq == 1U);
      imu.poll(52U);
      CHECK(!imu.reading().low_g_irq);
      wire.registers[0x3a] = 0x80;
      imu.poll(102U);
      CHECK(imu.reading().low_g_event_seq == 2U);
    }

    // An ACK without verified scale, rate or power configuration must
    // not permit calibrated MPU6050 data or any fresh sample.
    for (int reg : {0x6b, 0x6c, 0x19, 0x1a, 0x1b, 0x1c}) {
      TwoWire unreadable;
      unreadable.reject_read_reg = reg;
      BerryImu candidate;
      CHECK(!candidate.begin(unreadable, BerryModel::Mpu6050, 0x68, 0));
      CHECK(!candidate.configured());
      candidate.poll(100);
      CHECK(!candidate.fresh(100));

      TwoWire ignored;
      ignored.ignore_write_reg = reg;
      ignored.registers[reg] = 0xff;
      CHECK(!candidate.begin(ignored, BerryModel::Mpu6050, 0x68, 0));
      CHECK(!candidate.configured());
      candidate.poll(150);
      CHECK(!candidate.fresh(150));
    }

    // All retained ST variants must verify configuration before publishing
    // raw diagnostic axes. Their counts must not acquire MPU low-g metadata.
    for (const auto model : {BerryModel::V1Lsm9ds0, BerryModel::V2Lsm9ds1,
                             BerryModel::V3Lsm6dsl}) {
      const bool v1 = model == BerryModel::V1Lsm9ds0;
      const bool v3 = model == BerryModel::V3Lsm6dsl;
      const std::uint8_t gyro_reg = v1 ? 0xa8 : (v3 ? 0x22 : 0x98);
      const std::uint8_t accel_reg = v3 ? 0x28 : 0xa8;
      const int config_reg = v1 ? 0x23 : (v3 ? 0x12 : 0x22);
      TwoWire ignored;
      ignored.ignore_write_reg = config_reg;
      BerryImu candidate;
      CHECK(!candidate.begin(ignored, model, 0x6b, 0x1d));
      CHECK(!candidate.configured());
      candidate.poll(100);
      CHECK(!candidate.fresh(100));
      TwoWire unreadable;
      unreadable.reject_read_reg = config_reg;
      CHECK(!candidate.begin(unreadable, model, 0x6b, 0x1d));
      CHECK(!candidate.configured());

      TwoWire sample_wire;
      CHECK(candidate.begin(sample_wire, model, 0x6b, 0x1d));
      auto& accel_bank = v1 ? sample_wire.extra_registers : sample_wire.registers;
      // Distinct signed rails and asymmetric words expose swaps and sign errors.
      const std::uint8_t gyro_bytes[6] = {0x00, 0x80, 0xff, 0x7f, 0x34, 0x12};
      const std::uint8_t accel_bytes[6] = {0xff, 0xff, 0x01, 0x00, 0x00, 0xc0};
      for (unsigned i = 0; i < 6; ++i) {
        sample_wire.registers[gyro_reg + i] = gyro_bytes[i];
        accel_bank[accel_reg + i] = accel_bytes[i];
      }
      candidate.poll(100);
      CHECK(candidate.fresh(100));
      const auto& r = candidate.reading();
      CHECK(r.model == model);
      CHECK(r.gyro[0] == -32768 && r.gyro[1] == 32767 && r.gyro[2] == 4660);
      CHECK(r.accel[0] == -1 && r.accel[1] == 1 && r.accel[2] == -16384);
      CHECK(!r.low_g_status_valid && !r.low_g_irq && r.low_g_event_seq == 0U);
      CHECK(r.temperature_raw == 0);
      sample_wire.partial_read_reg = accel_reg;
      candidate.poll(150);
      CHECK(!candidate.fresh(150) && r.at_ms == 100U);
      CHECK(r.gyro[0] == -32768 && r.accel[2] == -16384);
      sample_wire.partial_read_reg = -1;
      candidate.poll(200);
      CHECK(candidate.fresh(200) && r.at_ms == 200U);
    }

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

    // This driver polls direct output registers, not a FIFO. MPU6050
    // INT_STATUS bit 4 (FIFO_OFLOW_INT) must not be mistaken for bit 7
    // (FF_INT), nor invalidate or replace a successful direct conversion.
    // Synthetic status bits exercise decoding, not actual FIFO draining.
    TwoWire direct_wire;
    BerryImu direct;
    CHECK(direct.begin(direct_wire, BerryModel::Mpu6050, 0x68, 0x00));
    for (const auto& write : direct_wire.writes) {
      CHECK(write.reg != 0x23); // FIFO_EN not configured
      CHECK(write.reg != 0x6a); // USER_CTRL FIFO_EN/reset not configured
    }
    direct_wire.registers[0x3b] = 0x40; // accel X = 16384
    direct_wire.registers[0x45] = 0xff; // gyro Y = -128
    direct_wire.registers[0x46] = 0x80;
    direct.poll(100);
    CHECK(direct.fresh(100));
    CHECK(direct.reading().accel[0] == 16384);
    CHECK(direct.reading().gyro[1] == -128);
    direct_wire.registers[0x3a] = 0x10;
    direct_wire.registers[0x3b] = 0x20; // new direct sample
    direct.poll(150);
    CHECK(direct.fresh(150) && direct.reading().at_ms == 150U);
    CHECK(direct.reading().accel[0] == 8192);
    CHECK(direct.reading().gyro[1] == -128);
    CHECK(direct.reading().low_g_status_valid && !direct.reading().low_g_irq);
    CHECK(direct.reading().low_g_event_seq == 0U);
    CHECK(direct_wire.registers[0x3a] == 0U); // clear on status read
    direct_wire.registers[0x3a] = 0x90; // simultaneous FF and overflow
    direct.poll(200);
    CHECK(direct.fresh(200) && direct.reading().at_ms == 200U);
    CHECK(direct.reading().low_g_irq && direct.reading().low_g_event_seq == 1U);
    direct_wire.registers[0x3a] = 0x10;
    direct_wire.reject_read_reg = 0x3b;
    direct.poll(250);
    CHECK(!direct.fresh(250));
    CHECK(direct.reading().at_ms == 200U); // no invented fresh sample
    CHECK(direct.reading().accel[0] == 8192);
    CHECK(direct.reading().gyro[1] == -128);
    CHECK(!direct.reading().low_g_status_valid && !direct.reading().low_g_irq);
    CHECK(direct.reading().low_g_event_seq == 1U);
    direct_wire.reject_read_reg = -1;
    direct_wire.registers[0x3b] = 0x10;
    direct.poll(300);
    CHECK(direct.fresh(300) && direct.reading().at_ms == 300U);
    CHECK(direct.reading().accel[0] == 4096);
    CHECK(direct.reading().gyro[1] == -128);
    CHECK(direct.reading().low_g_status_valid && !direct.reading().low_g_irq);
    CHECK(direct.reading().low_g_event_seq == 1U);

    // The fake must not leak stale RX bytes after a failed acquisition.
    TwoWire fault_wire;
    fault_wire.registers[0x3b] = 0x40;
    fault_wire.beginTransmission(0x68);
    CHECK(fault_wire.write(0x3b) == 1);
    CHECK(fault_wire.endTransmission(false) == 0);
    CHECK(fault_wire.requestFrom(0x68, 14) == 14);
    CHECK(fault_wire.available() == 14);
    fault_wire.reject_read_reg = 0x3b;
    fault_wire.beginTransmission(0x68);
    CHECK(fault_wire.write(0x3b) == 1);
    CHECK(fault_wire.endTransmission(false) == 0);
    CHECK(fault_wire.requestFrom(0x68, 14) == 0);
    CHECK(fault_wire.available() == 0 && fault_wire.read() == -1);
    fault_wire.reject_read_reg = -1;
    fault_wire.partial_read_reg = 0x3b;
    fault_wire.beginTransmission(0x68);
    CHECK(fault_wire.write(0x3b) == 1);
    CHECK(fault_wire.endTransmission(false) == 0);
    CHECK(fault_wire.requestFrom(0x68, 14) == 13);
    for (int i = 0; i < 13; ++i) CHECK(fault_wire.read() >= 0);
    CHECK(fault_wire.read() == -1);
    CHECK(fault_wire.requestFrom(0x68, 14) == 0);
    fault_wire.next_stop_status = 5;
    fault_wire.beginTransmission(0x68);
    CHECK(fault_wire.write(0x1d) == 1 && fault_wire.write(150) == 1);
    CHECK(fault_wire.endTransmission(true) == 5);
    CHECK(fault_wire.writes.empty() && fault_wire.registers[0x1d] == 0);

    TwoWire timeout_wire;
    timeout_wire.next_stop_status = 5;
    BerryImu timeout_imu;
    CHECK(!timeout_imu.begin(timeout_wire, BerryModel::Mpu6050, 0x68, 0));
    CHECK(!timeout_imu.configured());
    CHECK(timeout_wire.writes.empty());
    CHECK(timeout_imu.begin(timeout_wire, BerryModel::Mpu6050, 0x68, 0));
    timeout_imu.poll(100);
    CHECK(timeout_imu.fresh(100));
    timeout_wire.partial_read_reg = 0x3b;
    timeout_wire.registers[0x3b] = 0x40;
    timeout_imu.poll(150);
    CHECK(!timeout_imu.fresh(150));
    CHECK(timeout_imu.reading().at_ms == 100);
    CHECK(timeout_imu.reading().accel[0] == 0);
    timeout_wire.partial_read_reg = -1;
    timeout_imu.poll(200);
    CHECK(timeout_imu.fresh(200));
    CHECK(timeout_imu.reading().accel[0] == 16384);

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
