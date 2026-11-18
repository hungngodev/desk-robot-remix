#pragma once
#if (defined(DESK_ROBOT_STEPPER) && DESK_ROBOT_STEPPER) || \
    (defined(DESK_ROBOT_FULL_SENSORS) && DESK_ROBOT_FULL_SENSORS)
#include <Arduino.h>
#include <driver/rmt.h>
#include <freertos/ringbuf.h>
#include "NecBurst.h"

namespace desk_robot {
// RMT driver is the pinned ESP-IDF 4.4 legacy API, not Arduino 3.x.
// Read-only source of left/right NEC observations. NEVER drive/charge here.
// IrFrameQueueGate's drain bound, two-packet-per-side poll and 100ms gap
// are UNQUALIFIED engineering candidates on legacy ESP-IDF 4.4 RMT, whose
// ringbuffer does not provide arrival timestamps. These must be evaluated
// against real biased GPIO36/39 receivers, WiFi/ADC noise, NEC waveform
// edges and burst saturation before bearing or terminal motion is enabled.
// Do not promote a matching decoded ID into a charger or motor permit.
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
