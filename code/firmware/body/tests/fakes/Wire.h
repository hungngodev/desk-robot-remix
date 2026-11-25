#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>
#include "AccessoryReadings.h"
#include "Arduino.h"

// Deterministic sensor protocol emulator. Not a real hardware test.
class TwoWire {
 public:
  std::uint8_t ranges = 0;
  std::uint8_t extras = 0;
  bool unsafe_parallel_mux = false;
  unsigned transactions = 0;
  std::uint8_t ads_config_high = 0xC3;
  bool ads_conversion_ready = true;
  bool fail_ads_config_write = false;
  unsigned rejected_ads_config_writes = 0;
  std::uint8_t current_address = 0, register_address = 0;
  std::vector<std::uint8_t> outbound;
  std::vector<std::uint8_t> inbound;
  std::size_t pos = 0;
  bool pending_sht = false;
  bool fail_dock_gpio = false;
  bool fail_fuel_register_read = false;
  std::uint16_t ina226_shunt_raw = 0x0010U;
  bool fail_optional_gpio = false;
  bool fail_mcp_register_write = false;
  bool fail_pulse_register_write = false;
  bool fail_pulse_fifo_read_once = false; // simulate partial FIFO consumption
  bool fail_imu_register_write = false;
  unsigned failed_pulse_writes = 0;
  unsigned pulse_terminated_transmissions = 0;
  // MAX30102 FIFO pointers are explicit in host trials.
  std::uint8_t pulse_fifo_write_pointer = 4;
  std::uint8_t pulse_fifo_read_pointer = 0;
  std::uint8_t pulse_fifo_overflow = 0;
  std::uint8_t pulse_interrupt_status = 0;
  std::uint8_t pulse_interrupt_enable = 0;
  bool fail_pulse_status_read = false;
  bool pulse_clip_ir = false;
  unsigned failed_imu_writes = 0;
  unsigned imu_terminated_transmissions = 0;
  unsigned failed_mcp_writes = 0;
  unsigned mcp_terminated_transmissions = 0;
  unsigned optional_gpio_reads = 0;
  std::uint8_t optional_gpioB = 0x01; // reed open, PIR low
  std::uint8_t mcp_olatb = 0;  // BANK=0 OLATB 0x15
  std::uint8_t mcp_iodirb = 0xFF; // BANK=0 IODIRB 0x01
  unsigned haptic_rising_edges = 0;
  bool fail_mcp_latch_readback = false;
  bool nfc_connected = false;
  bool nfc_tag_present = false;
  // One complete I2C ACK with a broken PN532 checksum, not a tag removal.
  bool nfc_corrupt_scan_ack_once = false;
  unsigned nfc_corrupt_scan_acks = 0;
  std::uint8_t nfc_command = 0, nfc_phase = 0;
  unsigned nfc_scans = 0;
  unsigned dock_gpio_reads = 0;
  std::uint8_t dock_gpioA = 0x0F; // switches closed, no input or charger
  bool range_mux_stuck = false;
  bool optional_mux_stuck = false;
  bool fail_optional_mux_write = false;
  bool fail_cap_register_write = false;
  bool fail_cap_clear_write = false;
  std::uint8_t cap_main_control = 0x01;
  std::uint8_t cap_touch_bits = 0xA5; // CAP1188 sensor status mask, including release
  std::uint8_t cap_multi_touch_block = 0x80;
  std::uint8_t cap_config2 = 0x40;
  bool ignore_cap_multi_touch_write = false;
  std::uint8_t cap_config = 0x20;
  std::uint8_t cap_recal_config = 0x8A;
  std::uint8_t cap_noise_threshold = 0x01;
  bool ignore_cap_config_write = false;
  bool fail_cap_config_write = false;
  unsigned cap_interrupt_clears = 0;
  bool cap_uses_0x29 = false; // common generic breakout address
  unsigned cap_register_end_calls = 0;
  unsigned cap_failed_write_stops = 0;
  unsigned cap_register_requests = 0;
  bool optional_mux_installed = true;
  bool optional_mux_write_nack = false;
  bool optional_mux_read_nack = false;
  bool range_mux_write_nack = false;
  bool range_mux_read_nack = false;
  bool range_mux_bad_readback = false;
  bool hold_sda_on_range_disconnect = false;
  std::uint8_t hold_sda_on_range_mask = 0; // one-shot downstream hang on STOP
  std::uint16_t tof_register = 0;
  unsigned tof_samples = 0;
  bool tof_ready = true;
  bool hold_sda_after_tof_result = false;
  bool fail_tof_register_write = false;
  unsigned rejected_tof_register_writes = 0;
  unsigned tof_register_stop_transmissions = 0;
  std::uint8_t tof_raw_status = 11;
  std::uint16_t tof_force_mm = 0; // zero keeps per-lane nominal 45/300 mm
  // On-wire raw 9.7 fixed-point optical quality fields for regression.
  std::uint16_t tof_ambient_97 = 0x0123;
  std::uint16_t tof_signal_97 = 0x4567;
  unsigned imu_probe_attempts = 0;

  bool fail_begin = false;
  bool begin(int, int, int) { return !fail_begin; }
  void setTimeOut(unsigned) {}

  void beginTransmission(std::uint8_t addr) {
    if (addr == 0x68 || addr == 0x69 || addr == 0x6a || addr == 0x6b ||
        addr == 0x1c || addr == 0x1d || addr == 0x1e)
      ++imu_probe_attempts;
    current_address = addr;
    outbound.clear();
  }
  std::size_t write(std::uint8_t v) {
    if (fail_tof_register_write && current_address == 0x29 &&
        ranges != 0 && extras == 0) {
      ++rejected_tof_register_writes;
      return 0;
    }
    if (fail_optional_mux_write && current_address == 0x71) return 0;
    if (fail_pulse_register_write && current_address == 0x57) {
      ++failed_pulse_writes;
      return 0;
    }
    if (fail_imu_register_write &&
        (current_address == 0x68 || current_address == 0x69 ||
         current_address == 0x6a || current_address == 0x6b ||
         current_address == 0x1c || current_address == 0x1d ||
         current_address == 0x1e)) {
      ++failed_imu_writes;
      return 0;
    }
    if (fail_mcp_register_write && current_address == 0x20) {
      ++failed_mcp_writes;
      return 0;
    }
    const bool cap_target = current_address == 0x28 ||
        (current_address == 0x29 && extras == 1 && cap_uses_0x29);
    if (fail_cap_register_write && cap_target) return 0;
    if (fail_cap_clear_write && cap_target && outbound.size() == 1 &&
        outbound[0] == 0x00) return 0;
    outbound.push_back(v);
    return 1;
  }
  bool connected(std::uint8_t addr) const {
    if (addr == 0x70) return true;
    if (addr == 0x71) return optional_mux_installed;
    if (addr == 0x29)
      return (ranges != 0 && extras == 0 && (ranges & (ranges - 1U)) == 0) ||
             (ranges == 0 && extras == 1 && cap_uses_0x29);
    if (ranges != 0 || extras == 0) return false;
    switch (extras) {
      case 1: return (addr == 0x28 && !cap_uses_0x29) || addr == 0x57;
      case 2: return addr == 0x39 || addr == 0x36;
      case 4: return addr == 0x48;
      case 8: return addr == 0x44;
      case 16: return addr == 0x36 || addr == 0x40;
      case 32: return addr == 0x20 || (nfc_connected && addr == 0x24);
      case 64: return addr == 0x36;
      case 128: return addr == 0x36;
      default: return false;
    }
  }
  std::uint8_t endTransmission(bool stop = true) {
    ++transactions;
    if (stop && current_address == 0x29 && ranges != 0 && extras == 0)
      ++tof_register_stop_transmissions;
    if (current_address == 0x28 ||
        (current_address == 0x29 && extras == 1 && cap_uses_0x29))
      { ++cap_register_end_calls;
        if (fail_cap_register_write && stop) ++cap_failed_write_stops; }
    if (current_address == 0x20) ++mcp_terminated_transmissions;
    if (current_address == 0x57) ++pulse_terminated_transmissions;
    if (current_address == 0x68 || current_address == 0x69 ||
        current_address == 0x6a || current_address == 0x6b ||
        current_address == 0x1c || current_address == 0x1d ||
        current_address == 0x1e) ++imu_terminated_transmissions;
    if (!connected(current_address)) return 4;
    // Fail only the ADS1115 single-shot config WRITE, not its mux or reads.
    if (fail_ads_config_write && current_address == 0x48 &&
        outbound.size() == 3 && outbound[0] == 0x01) {
      ++rejected_ads_config_writes;
      return 4;
    }
    const bool cap_target = current_address == 0x28 ||
        (current_address == 0x29 && extras == 1 && cap_uses_0x29);
    if (cap_target && outbound.size() == 2) {
      if (outbound[0] == 0x2a && !ignore_cap_multi_touch_write)
        cap_multi_touch_block = outbound[1];
      if (outbound[0] == 0x44) cap_config2 = outbound[1];
      if (outbound[0] == 0x20) {
        if (fail_cap_config_write) return 4;
        if (!ignore_cap_config_write) cap_config = outbound[1];
      }
      if (outbound[0] == 0x2f) cap_recal_config = outbound[1];
      if (outbound[0] == 0x38) cap_noise_threshold = outbound[1];
      if (outbound[0] == 0x00) {
        cap_main_control = outbound[1];
        ++cap_interrupt_clears;
      }
    }
    if (current_address == 0x70) {
      if (outbound.empty()) return 0; // address-only I2C ACK probe
      if (outbound.size() != 1) return 4;
      if (range_mux_write_nack) return 4;
      if (!range_mux_stuck) {
        ranges = outbound[0];
        if (hold_sda_on_range_disconnect && ranges == 0) {
          fake_i2c_lines().sda_stuck = true;
          hold_sda_on_range_disconnect = false;
        }
        if (hold_sda_on_range_mask != 0 && ranges == hold_sda_on_range_mask) {
          fake_i2c_lines().sda_stuck = true;
          hold_sda_on_range_mask = 0;
        }
      }
    } else if (current_address == 0x71) {
      if (outbound.empty()) return 0; // address-only TCA9548A probe
      if (outbound.size() != 1) return 4;
      if (optional_mux_write_nack) return 4;
      if (!optional_mux_stuck) extras = outbound[0];
      if (extras && ranges) unsafe_parallel_mux = true;
    } else if (current_address == 0x29 && extras == 1 &&
               cap_uses_0x29 && !outbound.empty()) {
      register_address = outbound[0];
    } else if (current_address == 0x29 && !outbound.empty()) {
      if (outbound.size() < 1 || outbound.size() > 2) return 4;
      tof_register = outbound[0];
    } else if (current_address == 0x24 && !outbound.empty()) {
      if (outbound.size() < 9 || outbound[0] != 0 || outbound[1] != 0 ||
          outbound[2] != 0xff) return 4;
      nfc_command = outbound[6];
      nfc_phase = 1; // deterministic ACK, then response on separate mux slots
    } else if (!outbound.empty()) {
      register_address = outbound[0];
      if (current_address == 0x20 && outbound.size() == 2) {
        if (register_address == 0x15) {
          if ((mcp_olatb & 0x04U) == 0 && (outbound[1] & 0x04U) != 0)
            ++haptic_rising_edges;
          mcp_olatb = outbound[1];
        }
        if (register_address == 0x01) mcp_iodirb = outbound[1];
      }
      if (current_address == 0x57 && outbound.size() == 2) {
        if (register_address == 0x02) pulse_interrupt_enable = outbound[1];
        if (register_address == 0x06)
          pulse_fifo_read_pointer = outbound[1] & 31U;
        if (register_address == 0x05)
          pulse_fifo_overflow = outbound[1] & 31U;
      }
      if (current_address == 0x44 && outbound[0] == 0xFD)
        pending_sht = true;
      if (current_address == 0x48 && outbound.size() == 3 &&
          outbound[0] == 0x01) ads_config_high = outbound[1];
    }
    return 0;
  }
  std::size_t requestFrom(std::uint8_t addr, std::size_t count, bool stop = true) {
    (void)stop;
    ++transactions;
    inbound.clear();
    pos = 0;
    if (addr == 0x28 || (addr == 0x29 && extras == 1 && cap_uses_0x29))
      ++cap_register_requests;
    if (!connected(addr)) return 0;
    if (addr == 0x57 && register_address == 0x07 &&
        fail_pulse_fifo_read_once) {
      // I2C transfer drops after silicon advanced one sample.
      fail_pulse_fifo_read_once = false;
      if (count >= 6)
        pulse_fifo_read_pointer =
            static_cast<std::uint8_t>((pulse_fifo_read_pointer + 1U) & 31U);
      return 0;
    }
    if (fail_fuel_register_read && addr == 0x36 && extras == 16 &&
        (register_address == 0x02 || register_address == 0x04)) return 0;
    if (addr == 0x70) {
      if (range_mux_read_nack) return 0;
      inbound = {range_mux_bad_readback
          ? static_cast<std::uint8_t>(0xff) : ranges};
    } else if (addr == 0x71) {
      if (optional_mux_read_nack) return 0;
      inbound = {extras};
    } else if (addr == 0x29 && extras == 1 && cap_uses_0x29) {
      if (register_address == 0xFD) inbound = {0x50};
      else if (register_address == 0xFE) inbound = {0x5D};
      else if (register_address == 0x03) inbound = {cap_touch_bits};
      else if (register_address == 0x00) inbound = {cap_main_control};
      else if (register_address == 0x20) inbound = {cap_config};
      else if (register_address == 0x2f) inbound = {cap_recal_config};
      else if (register_address == 0x38) inbound = {cap_noise_threshold};
      else if (register_address == 0x2a) inbound = {cap_multi_touch_block};
      else if (register_address == 0x44) inbound = {cap_config2};
    } else if (addr == 0x29) {
      if (tof_register == 0x13 && count == 1) {
        inbound = {static_cast<std::uint8_t>(tof_ready ? 0x07 : 0)};
        // A missing conversion must NOT manufacture freshness.
      } else if (tof_register == 0x14 && count == 12) {
        inbound.assign(12, 0);
        inbound[0] = static_cast<std::uint8_t>(tof_raw_status << 3);
        inbound[6] = static_cast<std::uint8_t>(tof_ambient_97 >> 8);
        inbound[7] = static_cast<std::uint8_t>(tof_ambient_97);
        inbound[8] = static_cast<std::uint8_t>(tof_signal_97 >> 8);
        inbound[9] = static_cast<std::uint8_t>(tof_signal_97);
        const unsigned mm = tof_force_mm != 0 ? tof_force_mm :
                            (ranges == 16 ? 300 : 45);
        inbound[10] = static_cast<std::uint8_t>(mm >> 8);
        inbound[11] = static_cast<std::uint8_t>(mm);
        ++tof_samples;
        if (hold_sda_after_tof_result) {
          fake_i2c_lines().sda_stuck = true;
          hold_sda_after_tof_result = false;
        }
      }
    } else if (addr == 0x24 && nfc_connected) {
      if (nfc_phase == 1 && count == 7) {
        inbound = {1, 0, 0, 0xff, 0, 0xff, 0};
        if (nfc_command == 0x4a && nfc_corrupt_scan_ack_once) {
          nfc_corrupt_scan_ack_once = false;
          ++nfc_corrupt_scan_acks;
          inbound[5] = 0; // Invalid ACK checksum on an otherwise live bus.
        }
        nfc_phase = 2;
      } else if (nfc_phase == 2 && count >= 10) {
        const std::vector<std::uint8_t> payload = nfc_command != 0x4a
            ? std::vector<std::uint8_t>{}
            : (nfc_tag_present
               ? std::vector<std::uint8_t>{1, 1, 4, 0, 8, 4,
                   0x12, 0x34, 0x56, 0x78}
               : std::vector<std::uint8_t>{0});
        const auto len = static_cast<std::uint8_t>(2 + payload.size());
        inbound = {1, 0, 0, 0xff, len, static_cast<std::uint8_t>(-len),
                   0xd5, static_cast<std::uint8_t>(nfc_command + 1)};
        std::uint8_t sum = static_cast<std::uint8_t>(0xd5U + nfc_command + 1);
        for (std::uint8_t b : payload) {
          inbound.push_back(b);
          sum = static_cast<std::uint8_t>(sum + b);
        }
        inbound.push_back(static_cast<std::uint8_t>(-sum));
        inbound.push_back(0);
        inbound.resize(count, 0);
        if (nfc_command == 0x4a) ++nfc_scans;
        nfc_phase = 0;
      }
    } else if (addr == 0x20 && register_address == 0x12) {
      if (fail_dock_gpio) return 0;
      ++dock_gpio_reads;
      inbound = {dock_gpioA};
    } else if (addr == 0x20 && register_address == 0x13) {
      if (fail_optional_gpio) return 0;
      ++optional_gpio_reads;
      inbound = {optional_gpioB};
    } else if (addr == 0x20 && register_address == 0x15) {
      if (fail_mcp_latch_readback) return 0;
      inbound = {mcp_olatb};
    } else if (addr == 0x20 && register_address == 0x01) {
      inbound = {mcp_iodirb};
    } else if (addr == 0x44 && pending_sht && count == 6) {
      const std::uint8_t temp[2] = {0x66, 0x66};
      const std::uint8_t humidity[2] = {0x80, 0x00};
      inbound = {temp[0], temp[1], desk_robot::sensirion_crc(temp, 2),
                 humidity[0], humidity[1],
                 desk_robot::sensirion_crc(humidity, 2)};
      pending_sht = false;
    } else if (addr == 0x28 && register_address == 0xFD) inbound = {0x50};
    else if (addr == 0x28 && register_address == 0xFE) inbound = {0x5D};
    else if (addr == 0x28 && register_address == 0x03) inbound = {cap_touch_bits};
    else if (addr == 0x28 && register_address == 0x00) inbound = {cap_main_control};
    else if (addr == 0x28 && register_address == 0x20) inbound = {cap_config};
    else if (addr == 0x28 && register_address == 0x2f) inbound = {cap_recal_config};
    else if (addr == 0x28 && register_address == 0x38) inbound = {cap_noise_threshold};
    else if (addr == 0x28 && register_address == 0x2a) inbound = {cap_multi_touch_block};
    else if (addr == 0x28 && register_address == 0x44) inbound = {cap_config2};
    else if (addr == 0x57 && register_address == 0xFF) inbound = {0x15};
    else if (addr == 0x57 && register_address == 0x00) {
      if (fail_pulse_status_read) return 0;
      inbound = {pulse_interrupt_status};
      pulse_interrupt_status = 0; // read-to-clear
    }
    else if (addr == 0x57 && register_address == 0x04)
      inbound = {pulse_fifo_write_pointer};
    else if (addr == 0x57 && register_address == 0x05)
      inbound = {pulse_fifo_overflow};
    else if (addr == 0x57 && register_address == 0x06)
      inbound = {pulse_fifo_read_pointer};
    else if (addr == 0x57 && register_address == 0x07 && count <= 24 &&
             count % 6 == 0) {
      for (unsigned i = 0; i < count / 6; ++i) {
        const unsigned red = 1000 + i;
        const unsigned ir = pulse_clip_ir ? 0x3ffffU : 5000 + i;
        inbound.insert(inbound.end(), {0, static_cast<std::uint8_t>(red >> 8),
             static_cast<std::uint8_t>(red), static_cast<std::uint8_t>(ir >> 16),
             static_cast<std::uint8_t>(ir >> 8),
             static_cast<std::uint8_t>(ir)});
      }
      pulse_fifo_read_pointer =
          static_cast<std::uint8_t>((pulse_fifo_read_pointer + count / 6) & 31U);
    } else if (addr == 0x39 && register_address == 0x92) inbound = {0xAB};
    else if (addr == 0x39 && register_address == 0x9C) inbound = {42};
    else if (addr == 0x36 && extras != 16 && register_address == 0x0B)
      inbound = {0x20};
    else if (addr == 0x36 && extras != 16 && register_address == 0x0C)
      inbound = {0x07, 0xD0};
    else if (addr == 0x36 && extras == 16 && register_address == 0x02)
      inbound = {0xB4, 0x00};
    else if (addr == 0x36 && extras == 16 && register_address == 0x04)
      inbound = {0x32, 0x00};
    else if (addr == 0x40 && register_address == 0xFE)
      inbound = {0x54, 0x49};
    else if (addr == 0x40 && register_address == 0x02)
      inbound = {0x10, 0x00};
    else if (addr == 0x40 && register_address == 0x01)
      inbound = {static_cast<std::uint8_t>(ina226_shunt_raw >> 8),
                 static_cast<std::uint8_t>(ina226_shunt_raw)};
    else if (addr == 0x48 && register_address == 0x01) {
      inbound = {static_cast<std::uint8_t>(
          (ads_config_high & 0x7fU) | (ads_conversion_ready ? 0x80U : 0U)
        ), 0x83};
    }
    else if (addr == 0x48 && register_address == 0x00) {
      if (ads_config_high == 0xC3) inbound = {0x04, 0x00};
      else inbound = {0xFE, 0xDC};
    }
    return inbound.size() == count ? count : 0;
  }
  int available() const { return static_cast<int>(inbound.size() - pos); }
  int read() {
    if (pos >= inbound.size()) return -1;
    return inbound[pos++];
  }
};
extern TwoWire Wire;
