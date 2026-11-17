#pragma once
#include <cstdint>

// Pure bounded pulse request scheduler for the MCP23017 GPB2 edge output.
// Caller must use an independently current-limited, hardware timed driver.
// The MCP23017 latch alone is NOT a fail-safe motor timer if I2C wedges.
namespace desk_robot {
class HapticPulse {
 public:
  enum class Action : std::uint8_t { None, TurnOn, TurnOff };
  void configure(bool verified_low) {
    ready_ = verified_low;
    queued_ = active_ = false;
    // No automatic replay of events across reconnect or initialization.
    ever_started_ = false;
  }
  bool request(std::uint32_t now_ms) {
    if (!ready_ || queued_ || active_ ||
        (ever_started_ && now_ms - last_started_ms_ < 1500U)) return false;
    queued_ = true;
    requested_ms_ = now_ms;
    return true;
  }
  Action next(std::uint32_t now_ms, bool verified_undocked) {
    if (!ready_) return Action::None;
    // A completed edge pulse always needs the next available GPIOB slot to
    // deassert, including when a charging/seat sensor becomes active.
    if (active_) return Action::TurnOff;
    if (!queued_) return Action::None;
    if (!verified_undocked || now_ms - requested_ms_ > 250U) {
      queued_ = false;
      return Action::None;
    }
    return Action::TurnOn;
  }
  void completed(Action action, bool acknowledged_low_or_high,
                 std::uint32_t now_ms) {
    if (action == Action::None) return;
    if (!acknowledged_low_or_high) {
      // Output state is unknown on a failed Wire transaction. A hardware
      // monostable must limit the external coin motor independently.
      ready_ = queued_ = active_ = false;
      return;
    }
    if (action == Action::TurnOn) {
      active_ = ever_started_ = true;
      queued_ = false;
      last_started_ms_ = now_ms;
    } else {
      active_ = false;
    }
  }
  void fault() { ready_ = queued_ = active_ = false; }
  bool ready() const { return ready_; }
  bool active() const { return active_; }
 private:
  bool ready_ = false, queued_ = false, active_ = false;
  bool ever_started_ = false;
  std::uint32_t requested_ms_ = 0, last_started_ms_ = 0;
};
}  // namespace desk_robot
