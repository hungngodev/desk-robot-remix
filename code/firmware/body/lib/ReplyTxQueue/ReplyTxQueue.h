#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace desk_robot {
// A pair of complete replies fits without heap allocation. Backpressure must
// NEVER stop command parsing or local STOP: an unqueued reply is dropped and
// the requester times out fail-closed. No partially enqueued JSON frames.
template <std::size_t Capacity>
class ReplyTxQueue {
 public:
  static_assert(Capacity >= 4, "Reply TX queue needs a complete line");
  bool enqueue_line(const char* line) {
    if (line == nullptr) return false;
    const std::size_t length = std::strlen(line);
    if (length > Capacity - 2 || length + 2 > Capacity - count_) {
      ++dropped_;
      return false;
    }
    for (std::size_t i = 0; i < length; ++i) push(line[i]);
    push('\r');
    push('\n');
    return true;
  }

  // HardwareSerial::availableForWrite reports already-free UART space.
  // Write no more than 32 bytes of that space per safety service cycle;
  // never wait for a full JSON reply to drain on the physical wire.
  template <typename SerialPort>
  std::size_t drain(SerialPort& serial, std::size_t budget = 32) {
    if (count_ == 0 || budget == 0) return 0;
    const int available = serial.availableForWrite();
    if (available <= 0) return 0;
    std::size_t allowed = budget < 32 ? budget : 32;
    const std::size_t free = static_cast<std::size_t>(available);
    if (allowed > free) allowed = free;
    if (allowed > count_) allowed = count_;
    if (allowed > Capacity - front_) allowed = Capacity - front_;
    const std::size_t written = serial.write(
        reinterpret_cast<const std::uint8_t*>(bytes_ + front_), allowed);
    const std::size_t accepted = written <= allowed ? written : allowed;
    front_ = (front_ + accepted) % Capacity;
    count_ -= accepted;
    return accepted;
  }

  std::size_t pending() const { return count_; }
  std::size_t dropped() const { return dropped_; }

 private:
  void push(char value) {
    bytes_[(front_ + count_) % Capacity] = value;
    ++count_;
  }
  char bytes_[Capacity]{};
  std::size_t front_ = 0;
  std::size_t count_ = 0;
  std::size_t dropped_ = 0;
};
}  // namespace desk_robot
