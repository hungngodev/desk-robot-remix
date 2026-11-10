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
      if (outbound.size() != 1) return 4;
      ranges = outbound[0];
    } else if (current_address == 0x71) {
      if (outbound.size() != 1) return 4;
      extras = outbound[0];
      if (extras && ranges) unsafe_parallel_mux = true;
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
    if (addr == 0x44 && pending_sht && count == 6) {
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
