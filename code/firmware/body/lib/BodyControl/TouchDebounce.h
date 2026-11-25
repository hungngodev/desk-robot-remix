#pragma once
#include <cstdint>

namespace desk_robot {
// Raw reads may occur outside the periodic gesture poll. Any observed
// transition invalidates the old candidate, but only gesture polls can
// publish a stable edge. Unsigned elapsed time tolerates millis() wrap.
class TouchDebounce {
 public:
  void observe(bool active, std::uint32_t now_ms) noexcept {
    if (active == candidate_) return;
    candidate_ = active;
    samples_ = 1;
    last_ms_ = now_ms;
  }

  bool poll(bool active, std::uint32_t now_ms) noexcept {
    observe(active, now_ms);
    if (now_ms - last_ms_ < 25U) return false;
    last_ms_ = now_ms;
    if (samples_ < 3U) ++samples_;
    if (samples_ < 3U || candidate_ == stable_) return false;
    stable_ = candidate_;
    return true;
  }

  bool stable() const noexcept { return stable_; }

 private:
  bool stable_ = false;
  bool candidate_ = false;
  std::uint8_t samples_ = 0;
  std::uint32_t last_ms_ = 0;
};
} // namespace desk_robot
