#include "TerminalIr.h"
#if (defined(DESK_ROBOT_STEPPER) && DESK_ROBOT_STEPPER) || \
    (defined(DESK_ROBOT_FULL_SENSORS) && DESK_ROBOT_FULL_SENSORS)
#include <freertos/FreeRTOS.h>
namespace desk_robot {

bool TerminalIr::begin_one(unsigned side, int gpio) {
  if (side > 1 || (gpio != 36 && gpio != 39)) return false;
  rmt_config_t config{};
  config.rmt_mode = RMT_MODE_RX;
  config.channel = channel_[side];
  config.gpio_num = static_cast<gpio_num_t>(gpio);
  config.clk_div = 80;               // 80MHz / 80 = 1us RMT tick
  config.mem_block_num = 1;          // 64 items > one 34-item NEC frame
  config.rx_config.filter_en = true;
  config.rx_config.filter_ticks_thresh = 150; // reject short GPIO36/39 glitch
  config.rx_config.idle_threshold = 11500;    // >9ms leader, end between bursts
  if (rmt_config(&config) != ESP_OK ||
      rmt_driver_install(config.channel, 512, 0) != ESP_OK)
    return false;
  installed_[side] = true;
  if (rmt_get_ringbuf_handle(config.channel, &ring_[side]) != ESP_OK ||
      ring_[side] == nullptr ||
      rmt_rx_start(config.channel, true) != ESP_OK)
    return false;
  return true;
}

void TerminalIr::reset() {
  ready_ = false;
  // Receiver teardown must never preserve evidence from the prior session.
  readings_.invalidate();
  queue_.reset();
  for (unsigned side = 0; side != 2; ++side) {
    if (installed_[side]) {
      rmt_rx_stop(channel_[side]);
      rmt_driver_uninstall(channel_[side]);
    }
    installed_[side] = false;
    ring_[side] = nullptr;
  }
}

bool TerminalIr::begin(int left_gpio, int right_gpio) {
  reset();
  if (left_gpio == right_gpio ||
      !begin_one(0, left_gpio) || !begin_one(1, right_gpio)) {
    reset();
    return false;
  }
  ready_ = true;
  return true;
}

void TerminalIr::poll(std::uint32_t now_ms) {
  if (!ready_) return;
  // Legacy ESP-IDF 4.4 RMT supplies no per-packet receive timestamp.
  // A late poll or queued backlog must discard both receivers' prior
  // directional evidence, not stamp an old queued NEC burst as new.
  bool window_ok = queue_.on_poll(now_ms);
  std::uint32_t candidate_code[2] = {};
  bool candidate_valid[2] = {};
  // A fixed CPU budget bounds processing of repeated ambient IR noise.
  constexpr unsigned kMaxPacketsPerSide = 8;
  for (unsigned side = 0; side != 2; ++side) {
    const bool discard_queued = !window_ok || queue_.draining(side);
    unsigned packets = 0;
    bool emptied = false;
    for (; packets < kMaxPacketsPerSide; ++packets) {
      size_t size = 0;
      auto* item = static_cast<rmt_item32_t*>(
          xRingbufferReceive(ring_[side], &size, 0));
      if (!item) {
        emptied = true;
        break;
      }
      // A poll may see at most two full packets before treating the entire
      // batch as ambiguous. Defer accepting either side until both drained.
      if (!discard_queued && packets < 2 &&
          size == 34 * sizeof(rmt_item32_t)) {
        IrMarkSpace samples[34]{};
        bool polarity_ok = true;
        for (unsigned n = 0; n != 34; ++n) {
          // Vishay demodulated carrier burst pulls output LOW; HIGH is space.
          if (item[n].level0 != 0 ||
              (n != 33 && item[n].level1 != 1)) {
            polarity_ok = false;
            break;
          }
          samples[n].mark_us = item[n].duration0;
          samples[n].space_us = item[n].duration1;
        }
        std::uint32_t code = 0;
        if (polarity_ok && decode_nec(samples, 34, code)) {
          candidate_code[side] = code;
          candidate_valid[side] = true;
        }
      }
      vRingbufferReturnItem(ring_[side], item);
    }
    if (!queue_.finish(side, packets, emptied, candidate_valid[side])) window_ok = false;
  }
  if (!window_ok) {
    // Also discard a candidate from the opposite receiver on any stall.
    // Quarantine lasts through a complete queue drain on both receivers.
    readings_.invalidate();
    return;
  }
  for (unsigned side = 0; side != 2; ++side) {
    if (candidate_valid[side])
      readings_.accept(side, candidate_code[side], now_ms);
  }
}
} // namespace desk_robot
#endif
