#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>
#include "AccessoryReadings.h"

// Deterministic sensor protocol emulator. Not a real hardware test.
class TwoWire {
 public:
  std::uint8_t ranges = 0;
  std::uint8_t extras = 0;
  bool unsafe_parallel_mux = false;
  unsigned transactions = 0;
  std::uint8_t ads_config_high = 0xC3;
  std::uint8_t current_address = 0, register_address = 0;
  std::vector<std::uint8_t> outbound;
  std::vector<std::uint8_t> inbound;
  std::size_t pos = 0;
  bool pending_sht = false;
  bool fail_dock_gpio = false;
  bool nfc_connected = false;
  bool nfc_tag_present = false;
  std::uint8_t nfc_command = 0, nfc_phase = 0;
  unsigned nfc_scans = 0;
  unsigned dock_gpio_reads = 0;
  std::uint8_t dock_gpioA = 0x0F; // switches closed, no input or charger

  void beginTransmission(std::uint8_t addr) {
    current_address = addr;
    outbound.clear();
  }
  std::size_t write(std::uint8_t v) {
    outbound.push_back(v);
    return 1;
  }
  bool connected(std::uint8_t addr) const {
    if (addr == 0x70 || addr == 0x71) return true;
    if (ranges != 0 || extras == 0) return false;
    switch (extras) {
      case 1: return addr == 0x28 || addr == 0x57;
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
    (void)stop;
    ++transactions;
    if (!connected(current_address)) return 4;
    if (current_address == 0x70) {
      if (outbound.empty()) return 0; // address-only I2C ACK probe
      if (outbound.size() != 1) return 4;
      ranges = outbound[0];
    } else if (current_address == 0x71) {
      if (outbound.empty()) return 0; // address-only TCA9548A probe
      if (outbound.size() != 1) return 4;
      extras = outbound[0];
      if (extras && ranges) unsafe_parallel_mux = true;
    } else if (current_address == 0x24 && !outbound.empty()) {
      if (outbound.size() < 9 || outbound[0] != 0 || outbound[1] != 0 ||
          outbound[2] != 0xff) return 4;
      nfc_command = outbound[6];
      nfc_phase = 1; // deterministic ACK, then response on separate mux slots
    } else if (!outbound.empty()) {
      register_address = outbound[0];
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
    if (!connected(addr)) return 0;
    if (addr == 0x24 && nfc_connected) {
      if (nfc_phase == 1 && count == 7) {
        inbound = {1, 0, 0, 0xff, 0, 0xff, 0};
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
    } else if (addr == 0x44 && pending_sht && count == 6) {
      const std::uint8_t temp[2] = {0x66, 0x66};
      const std::uint8_t humidity[2] = {0x80, 0x00};
      inbound = {temp[0], temp[1], desk_robot::sensirion_crc(temp, 2),
                 humidity[0], humidity[1],
                 desk_robot::sensirion_crc(humidity, 2)};
      pending_sht = false;
    } else if (addr == 0x28 && register_address == 0xFD) inbound = {0x50};
    else if (addr == 0x28 && register_address == 0xFE) inbound = {0x5D};
    else if (addr == 0x28 && register_address == 0x03) inbound = {0xA5};
    else if (addr == 0x57 && register_address == 0xFF) inbound = {0x15};
    else if (addr == 0x57 && register_address == 0x04) inbound = {4};
    else if (addr == 0x57 && register_address == 0x06) inbound = {0};
    else if (addr == 0x57 && register_address == 0x07 && count <= 24 &&
             count % 6 == 0) {
      for (unsigned i = 0; i < count / 6; ++i) {
        const unsigned red = 1000 + i, ir = 5000 + i;
        inbound.insert(inbound.end(), {0, static_cast<std::uint8_t>(red >> 8),
             static_cast<std::uint8_t>(red), 0,
             static_cast<std::uint8_t>(ir >> 8),
             static_cast<std::uint8_t>(ir)});
      }
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
      inbound = {0x00, 0x10};
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
