#pragma once
#if (defined(DESK_ROBOT_STEPPER) && DESK_ROBOT_STEPPER) || \
    (defined(DESK_ROBOT_FULL_SENSORS) && DESK_ROBOT_FULL_SENSORS)
#include <Arduino.h>
#include <Wire.h>
#include "AccessoryReadings.h"
#include "Bmp280Math.h"
#include "GestureDecoder.h"
#include "Pn532Frames.h"
#include "HapticPulse.h"
#ifndef DESK_ROBOT_ENABLE_HAPTIC
#define DESK_ROBOT_ENABLE_HAPTIC 0
#endif
namespace desk_robot {
// One optional mux operation per 12ms after the critical ranging pass.
// Reuses manufacturer register maps and Sensirion CRC, never Arduino libraries
// that block for entire gestures/multiple conversion cycles in the guard loop.
class AccessorySensors {
 public:
  bool begin(TwoWire& wire);
  void poll(std::uint32_t now_ms);
  const AccessoryReadings& readings() const { return data_; }
  // Independent of successful downstream initialization and final close.
  bool mux_present() const { return mux_present_; }
  // Local CAP1188 transition only. No speech/network motor commands.
  // Available solely in the isolated hardware one-shot lab build.
  bool request_haptic(std::uint32_t now_ms) {
#if DESK_ROBOT_ENABLE_HAPTIC
    return haptic_.request(now_ms);
#else
    (void)now_ms;
    return false;
#endif
  }
  bool haptic_ready() const {
#if DESK_ROBOT_ENABLE_HAPTIC
    return haptic_.ready();
#else
    return false;
#endif
  }
 private:
  TwoWire* wire_ = nullptr;
  bool mux_present_ = false;
  std::uint8_t next_lane_ = 1;
  std::uint32_t last_ms_ = 0;
  bool started_ = false;
#if DESK_ROBOT_ENABLE_HAPTIC
  HapticPulse haptic_{};
  bool haptic_needs_low_ = false;
  void haptic_step(std::uint32_t now_ms);
#endif
  bool sht_pending_ = false;
  std::uint32_t sht_started_ = 0;
  bool ads_pending_ = false;
  std::uint8_t ads_channel_ = 0;
  std::uint32_t ads_started_ = 0;
  AccessoryReadings data_{};
  enum class NfcStage : std::uint8_t {
    Disabled, StartSam, SamAck, SamResponse,
    StartRetry, RetryAck, RetryResponse, Idle, ScanAck, ScanResponse
  };
  NfcStage nfc_stage_ = NfcStage::Disabled;
  std::uint32_t nfc_phase_at_ms_ = 0;
  std::uint32_t nfc_last_scan_at_ms_ = 0;
  Bmp280Trim bmp_trim_{};
  GestureDecoder gesture_{};
  std::uint32_t gesture_started_ms_ = 0;
  bool gesture_collecting_ = false;
  bool mux(std::uint8_t address, std::uint8_t mask);
  bool verified_mux(std::uint8_t address, std::uint8_t mask);
  void invalidate_cached();
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
  void optional_gpio(std::uint32_t now_ms); // slow MCP GPIOB0 reed, B1 PIR
  bool nfc_write(std::uint8_t command, const std::uint8_t* body, std::size_t size);
  int nfc_read(std::uint8_t* frame, std::uint8_t count); // 1 ready, 0 pending, -1 fault
  void nfc_poll(std::uint32_t now_ms);
};
} // namespace desk_robot
#endif
