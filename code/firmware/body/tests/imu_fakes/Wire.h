#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>

// Dedicated narrow host fake for BerryImu.cpp compiled with ARDUINO=1.
// Unlike the shared TCA9548A fake, this captures literal IMU register writes.
class TwoWire {
 public:
  struct Write {
    std::uint8_t address;
    std::uint8_t reg;
    std::uint8_t value;
  };
  std::vector<Write> writes;
  bool reject_writes = false;

  void beginTransmission(std::uint8_t address) {
    address_ = address;
    bytes_.clear();
  }
  std::size_t write(std::uint8_t value) {
    if (reject_writes) return 0;
    bytes_.push_back(value);
    return 1;
  }
  std::uint8_t endTransmission(bool = true) {
    if (bytes_.size() != 2) return 4;
    writes.push_back({address_, bytes_[0], bytes_[1]});
    return 0;
  }
  std::size_t requestFrom(std::uint8_t, std::size_t, bool = true) { return 0; }
  int read() { return -1; }

  bool wrote(std::uint8_t address, std::uint8_t reg,
             std::uint8_t value) const {
    for (const auto& op : writes)
      if (op.address == address && op.reg == reg && op.value == value)
        return true;
    return false;
  }

 private:
  std::uint8_t address_ = 0;
  std::vector<std::uint8_t> bytes_;
};
