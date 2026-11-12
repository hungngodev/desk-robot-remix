#pragma once
#if defined(DESK_ROBOT_STEPPER) && DESK_ROBOT_STEPPER
#include <Arduino.h>
#include <driver/rmt.h>
#include <freertos/ringbuf.h>
#include "NecBurst.h"

namespace desk_robot {
// RMT driver is the pinned ESP-IDF 4.4 legacy API, not Arduino 3.x.
// Read-only source of left/right NEC observations. NEVER drive/charge here.
class TerminalIr {
 public:
  bool begin(int left_gpio, int right_gpio);
  void poll(std::uint32_t now_ms);
  IrPairEvidence evidence(std::uint32_t now_ms) const {
    return readings_.assess(now_ms);
  }
 private:
  bool begin_one(unsigned side, int gpio);
  void reset();
  rmt_channel_t channel_[2] = {RMT_CHANNEL_0, RMT_CHANNEL_1};
  RingbufHandle_t ring_[2] = {nullptr, nullptr};
  bool installed_[2] = {false, false};
  bool ready_ = false;
  IrFrameQueueGate queue_{};
  DualIrEvidence readings_{};
};
} // namespace desk_robot
#endif
