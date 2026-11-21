#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

// Narrow host fake for real BerryImu.cpp compiled under ARDUINO=1.
// Captures register writes, simulates repeated-start readback and models
// the MPU6050 INT_STATUS read-to-clear event contract.
class TwoWire {
 public:
  struct Write {
    std::uint8_t address;
    std::uint8_t reg;
    std::uint8_t value;
  };
  std::vector<Write> writes;
  std::array<std::uint8_t, 256> registers{};
  bool reject_writes = false;
  int reject_read_reg = -1;

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
    if (bytes_.size() == 1) {
      read_address_ = address_;
      read_register_ = bytes_[0];
      return 0;
    }
    if (bytes_.size() != 2) return 4;
    writes.push_back({address_, bytes_[0], bytes_[1]});
    registers[bytes_[0]] = bytes_[1];
    return 0;
  }
  std::size_t requestFrom(std::uint8_t address, std::size_t count,
                          bool = true) {
    if (address != read_address_ ||
        static_cast<int>(read_register_) == reject_read_reg ||
        count > 14U) return 0;
    remaining_ = count;
    return count;
  }
  int read() {
    if (!remaining_) return -1;
    --remaining_;
    const auto reg = read_register_++;
    const auto value = registers[reg];
    if (reg == 0x3a) registers[reg] = 0; // MPU FF_INT clears on status read
    return value;
  }
  bool wrote(std::uint8_t address, std::uint8_t reg,
             std::uint8_t value) const {
    for (const auto& op : writes)
      if (op.address == address && op.reg == reg && op.value == value)
        return true;
    return false;
  }

 private:
  std::uint8_t address_ = 0;
  std::uint8_t read_address_ = 0;
  std::uint8_t read_register_ = 0;
  std::size_t remaining_ = 0;
  std::vector<std::uint8_t> bytes_;
};
