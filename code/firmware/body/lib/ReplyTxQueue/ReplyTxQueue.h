#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace desk_robot {
// Complete normal replies are buffered without heap allocation. A separate
// pair of small urgent reply slots protects STOP/HALT acknowledgement from
// saturated status JSON, without ever preempting a partially sent frame.
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


  // Called ONLY for a completed local STOP/HALT response, after the actuator
  // has already been stopped. The independent lane is not an emergency stop
  // implementation. Never truncate a prior partially transmitted JSON line.
  bool enqueue_priority_line(const char* line) {
    if (line == nullptr) return false;
    const std::size_t length = std::strlen(line);
    if (length > kPriorityLineCapacity - 2 || priority_count_ == kPrioritySlots) {
      ++dropped_;
      return false;
    }
    const std::size_t slot = (priority_start_ + priority_count_) % kPrioritySlots;
    std::memcpy(priority_[slot], line, length);
    priority_[slot][length] = '\r';
    priority_[slot][length + 1] = '\n';
    priority_lengths_[slot] = length + 2;
    ++priority_count_;
    return true;
  }

  // HardwareSerial::availableForWrite reports already-free UART space.
  // Never enqueue more than 32 bytes per service cycle; urgent replies overtake
  // whole pending status lines only at a frame boundary.
  template <typename SerialPort>
  std::size_t drain(SerialPort& serial, std::size_t budget = 32) {
    if (pending() == 0 || budget == 0) return 0;
    const int available = serial.availableForWrite();
    if (available <= 0) return 0;
    std::size_t allowed = budget < 32 ? budget : 32;
    const std::size_t free = static_cast<std::size_t>(available);
    if (allowed > free) allowed = free;

    if (priority_count_ && !normal_line_partial_) {
      const std::size_t remaining =
          priority_lengths_[priority_start_] - priority_offset_;
      if (allowed > remaining) allowed = remaining;
      const std::size_t written = serial.write(
          reinterpret_cast<const std::uint8_t*>(
              priority_[priority_start_] + priority_offset_), allowed);
      const std::size_t accepted = written <= allowed ? written : allowed;
      priority_offset_ += accepted;
      if (priority_offset_ == priority_lengths_[priority_start_]) {
        priority_start_ = (priority_start_ + 1) % kPrioritySlots;
        --priority_count_;
        priority_offset_ = 0;
      }
      return accepted;
    }

    if (allowed > count_) allowed = count_;
    if (allowed > Capacity - front_) allowed = Capacity - front_;
    if (priority_count_ && normal_line_partial_) {
      // Finish only the already-started line, not the next queued status.
      for (std::size_t i = 0; i < allowed; ++i) {
        if (bytes_[front_ + i] == '\n') {
          allowed = i + 1;
          break;
        }
      }
    }
    if (!allowed) return 0;
    const std::size_t written = serial.write(
        reinterpret_cast<const std::uint8_t*>(bytes_ + front_), allowed);
    const std::size_t accepted = written <= allowed ? written : allowed;
    for (std::size_t i = 0; i < accepted; ++i)
      normal_line_partial_ = bytes_[front_ + i] != '\n';
    front_ = (front_ + accepted) % Capacity;
    count_ -= accepted;
    return accepted;
  }

  std::size_t pending() const {
    std::size_t result = count_;
    for (std::size_t i = 0; i < priority_count_; ++i)
      result += priority_lengths_[(priority_start_ + i) % kPrioritySlots];
    return result - priority_offset_;
  }
  std::size_t dropped() const { return dropped_; }

 private:
  static constexpr std::size_t kPrioritySlots = 2;
  static constexpr std::size_t kPriorityLineCapacity = 64;
  void push(char value) {
    bytes_[(front_ + count_) % Capacity] = value;
    ++count_;
  }
  char bytes_[Capacity]{};
  std::size_t front_ = 0;
  std::size_t count_ = 0;
  bool normal_line_partial_ = false;
  char priority_[kPrioritySlots][kPriorityLineCapacity]{};
  std::size_t priority_lengths_[kPrioritySlots]{};
  std::size_t priority_start_ = 0;
  std::size_t priority_count_ = 0;
  std::size_t priority_offset_ = 0;
  std::size_t dropped_ = 0;
};
}  // namespace desk_robot
