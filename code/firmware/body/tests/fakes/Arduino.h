#pragma once
#include <cstddef>
#include <cstdint>

// Minimal host stand-ins for the optional mux RESET path in the ToF adapter.
// Production ESP32 builds always use the real Arduino framework definitions.
#define OUTPUT 1
#define LOW 0
#define HIGH 1
inline void pinMode(int, int) {}
inline void digitalWrite(int, int) {}
inline void delayMicroseconds(unsigned) {}
inline void delay(unsigned) {}
// Share one deterministic clock across fake Arduino translation units.
inline std::uint32_t& fake_arduino_millis() {
  static std::uint32_t now = 0;
  return now;
}
inline unsigned long millis() { return fake_arduino_millis(); }
