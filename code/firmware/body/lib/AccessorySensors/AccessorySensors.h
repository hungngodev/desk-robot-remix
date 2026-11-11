#pragma once
#if defined(DESK_ROBOT_STEPPER) && DESK_ROBOT_STEPPER
#include <Arduino.h>
#include <Wire.h>
#include "AccessoryReadings.h"
#include "Bmp280Math.h"
#include "GestureDecoder.h"
namespace desk_robot {
// One optional mux operation per 12ms after the critical ranging pass.
// Reuses manufacturer register maps and Sensirion CRC, never Arduino libraries
// that block for entire gestures/multiple conversion cycles in the guard loop.
class AccessorySensors {
 public:
  bool begin(TwoWire& wire);
  void poll(std::uint32_t now_ms);
  const AccessoryReadings& readings() const { return data_; }
 private:
  TwoWire* wire_ = nullptr;
  bool mux_present_ = false;
  std::uint8_t next_lane_ = 1;
  std::uint32_t last_ms_ = 0;
  bool started_ = false;
  bool sht_pending_ = false;
  std::uint32_t sht_started_ = 0;
  bool ads_pending_ = false;
  std::uint8_t ads_channel_ = 0;
  std::uint32_t ads_started_ = 0;
  AccessoryReadings data_{};
  Bmp280Trim bmp_trim_{};
  GestureDecoder gesture_{};
  std::uint32_t gesture_started_ms_ = 0;
  bool gesture_collecting_ = false;
  bool mux(std::uint8_t address, std::uint8_t mask);
  bool select(std::uint8_t lane);
  bool close();
  bool probe(std::uint8_t address);
  bool read(std::uint8_t address, std::uint8_t reg,
            std::uint8_t* dest, std::uint8_t count);
  bool read16(std::uint8_t address, std::uint8_t reg, std::uint16_t& result);
  bool write8(std::uint8_t address, std::uint8_t reg, std::uint8_t value);
  bool write16(std::uint8_t address, std::uint8_t reg, std::uint16_t value);
  bool write_command(std::uint8_t address, std::uint8_t command);
  void angle(std::uint8_t index, std::uint32_t now_ms);
  void gesture_proximity(std::uint32_t now_ms);
  void gesture_fifo(std::uint32_t now_ms);
  void force(std::uint32_t now_ms);
  void climate(std::uint32_t now_ms);
  void barometer(std::uint32_t now_ms);
  void power(std::uint32_t now_ms);
  void dock_status(std::uint32_t now_ms);
};
} // namespace desk_robot
#endif
