#pragma once
#include <cstdint>
#include <cstddef>
#include <freertos/ringbuf.h>
using esp_err_t = int;
constexpr esp_err_t ESP_OK = 0;
using gpio_num_t = int;
enum rmt_channel_t { RMT_CHANNEL_0, RMT_CHANNEL_1 };
enum rmt_mode_t { RMT_MODE_RX };
// Model only the fields consumed by the legacy receiver. Unlike the ESP
// bitfield ABI, this is a host fixture; size checks use sizeof on both sides.
struct rmt_item32_t {
  std::uint32_t duration0 : 15;
  std::uint32_t level0 : 1;
  std::uint32_t duration1 : 15;
  std::uint32_t level1 : 1;
};
struct rmt_config_t {
  rmt_mode_t rmt_mode;
  rmt_channel_t channel;
  gpio_num_t gpio_num;
  unsigned clk_div, mem_block_num;
  struct { bool filter_en; unsigned filter_ticks_thresh, idle_threshold; } rx_config;
};
esp_err_t rmt_config(const rmt_config_t* config);
esp_err_t rmt_driver_install(rmt_channel_t channel, std::size_t bytes, int flags);
esp_err_t rmt_get_ringbuf_handle(rmt_channel_t channel, RingbufHandle_t* handle);
esp_err_t rmt_rx_start(rmt_channel_t channel, bool reset);
esp_err_t rmt_rx_stop(rmt_channel_t channel);
esp_err_t rmt_driver_uninstall(rmt_channel_t channel);
