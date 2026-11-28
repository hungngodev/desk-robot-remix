#pragma once
#include "Arduino.h"

// Host stand-in for the pinned ESP-IDF v4.4.7 I2C pin matrix API.
enum i2c_port_t { I2C_NUM_0 = 0 };
enum i2c_mode_t { I2C_MODE_MASTER = 1 };
constexpr int ESP_OK = 0;
inline int i2c_set_pin(i2c_port_t port, int sda, int scl, bool sda_pullup,
                       bool scl_pullup, i2c_mode_t mode) {
  auto& lines = fake_i2c_lines();
  ++lines.restore_calls;
  if (port != I2C_NUM_0 || sda != 21 || scl != 22 ||
      !sda_pullup || !scl_pullup || mode != I2C_MODE_MASTER ||
      lines.fail_restore)
    return -1;
  // IDF v4.4.7 restores open-drain direction and releases output latches.
  // Do not invent bus-clear clocks or erase externally held line faults.
  lines.sda_mode = OUTPUT_OPEN_DRAIN | PULLUP;
  lines.scl_mode = OUTPUT_OPEN_DRAIN | PULLUP;
  lines.sda_driven_low = false;
  lines.scl_driven_low = false;
  return ESP_OK;
}
