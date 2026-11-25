#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace desk_robot {

// A tiny USB-only fixture policy for centering HORNLESS servos before
// measuring installed linkage travel. No motor, sensor or radio authority.
// A restart creates a new LOCAL USB centering session, never motion permission.
class ServoCenterBenchGate {
 public:
  enum class Channel : std::uint8_t { None, Lift, Grip };
  static constexpr std::uint32_t kCenterWindowMs = 400U;
  // Long or continuously refilled USB input must never starve the PWM
  // deadline in the MCU loop. Service only one bounded slice per pass.
  static constexpr std::size_t kMaxSerialBytesPerPoll = 32U;
  static std::size_t serial_budget(std::size_t pending) {
    return pending < kMaxSerialBytesPerPoll ?
        pending : kMaxSerialBytesPerPoll;
  }

  bool request(const char* command, std::uint32_t now_ms) {
    if (command == nullptr || active_ != Channel::None) return false;
    Channel next = Channel::None;
    std::uint8_t bit = 0U;
    if (std::strcmp(command, "CENTER LIFT") == 0) {
      next = Channel::Lift;
      bit = 1U;
    } else if (std::strcmp(command, "CENTER GRIP") == 0) {
      next = Channel::Grip;
      bit = 2U;
    } else {
      return false;
    }
    if ((used_ & bit) != 0U) return false;
    active_ = next;
    used_ |= bit;
    started_ms_ = now_ms;
    return true;
  }

  enum class InputResult { Incomplete, Rejected, Started };
  // Only a terminal CR immediately followed by LF is framing. Embedded CR,
  // repeated CR, control bytes and overflow poison the entire command.
  InputResult feed(int byte, std::uint32_t now_ms, bool pwm_ready) {
    if (byte == '\n') {
      line_[length_] = '\0';
      const bool started = !invalid_line_ && pwm_ready && request(line_, now_ms);
      length_ = 0;
      invalid_line_ = false;
      trailing_cr_ = false;
      return started ? InputResult::Started : InputResult::Rejected;
    }
    if (trailing_cr_) invalid_line_ = true;
    if (byte == '\r') {
      trailing_cr_ = true;
    } else if (byte < 32 || byte > 126 || length_ >= sizeof(line_) - 1) {
      invalid_line_ = true;
    } else if (!invalid_line_) {
      line_[length_++] = static_cast<char>(byte);
    }
    return InputResult::Incomplete;
  }

  Channel active() const { return active_; }
  bool should_detach(std::uint32_t now_ms) const {
    return active_ != Channel::None &&
           now_ms - started_ms_ >= kCenterWindowMs;
  }
  bool complete(std::uint32_t now_ms) {
    if (!should_detach(now_ms)) return false;
    active_ = Channel::None;
    return true;
  }
  bool already_used(Channel channel) const {
    const std::uint8_t bit = channel == Channel::Lift ? 1U :
        channel == Channel::Grip ? 2U : 0U;
    return bit != 0U && (used_ & bit) != 0U;
  }

 private:
  Channel active_ = Channel::None;
  std::uint8_t used_ = 0U;
  std::uint32_t started_ms_ = 0U;
  char line_[24]{};
  std::size_t length_ = 0;
  bool invalid_line_ = false;
  bool trailing_cr_ = false;
};

}  // namespace desk_robot
