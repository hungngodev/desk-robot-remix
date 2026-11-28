#pragma once
#include <cstddef>
#include <cstdint>

// Minimal host stand-ins for the optional mux RESET path in the ToF adapter.
// Production ESP32 builds always use the real Arduino framework definitions.
#define OUTPUT 0x03
#define LOW 0
#define HIGH 1
#define PULLUP 0x04
#define OUTPUT_OPEN_DRAIN 0x13

// Deterministic open-drain line model for the WROOM GPIO21/22 bus.
// An external device may release SDA after N real SCL rising edges.
struct FakeI2cLines {
  bool sda_stuck = false;
  bool scl_stuck = false;
  bool sda_driven_low = false;
  bool scl_driven_low = false;
  int sda_mode = OUTPUT_OPEN_DRAIN;
  int scl_mode = OUTPUT_OPEN_DRAIN;
  unsigned release_after_pulses = 0;
  // Hold the next clock release after this many completed data-clear clocks.
  unsigned hold_scl_after_pulses = 0;
  unsigned clear_attempts = 0;
  unsigned clear_pulses = 0;
  unsigned stops = 0;
  unsigned restore_calls = 0;
  bool fail_restore = false;
  bool unsafe_high = false;
};
inline FakeI2cLines& fake_i2c_lines() {
  static FakeI2cLines lines;
  return lines;
}
inline int digitalRead(int pin) {
  const auto& lines = fake_i2c_lines();
  if (pin == 21) return lines.sda_stuck || lines.sda_driven_low ? LOW : HIGH;
  if (pin == 22) return lines.scl_stuck || lines.scl_driven_low ? LOW : HIGH;
  return HIGH;
}
inline void pinMode(int pin, int mode) {
  auto& lines = fake_i2c_lines();
  if (pin == 21) lines.sda_mode = mode;
  else if (pin == 22) lines.scl_mode = mode;
}
inline void digitalWrite(int pin, int value) {
  auto& lines = fake_i2c_lines();
  if (pin != 21 && pin != 22) return;
  const int mode = pin == 21 ? lines.sda_mode : lines.scl_mode;
  if ((mode & OUTPUT_OPEN_DRAIN) != OUTPUT_OPEN_DRAIN && value == HIGH)
    lines.unsafe_high = true;
  if (pin == 21) {
    const bool was_low = lines.sda_driven_low;
    lines.sda_driven_low = value == LOW;
    if (was_low && value == HIGH && digitalRead(22) == HIGH &&
        digitalRead(21) == HIGH)
      ++lines.stops;
  } else {
    const bool was_low = lines.scl_driven_low;
    lines.scl_driven_low = value == LOW;
    if (was_low && value == HIGH) {
      if (!lines.sda_driven_low) ++lines.clear_attempts;
      if (lines.hold_scl_after_pulses &&
          lines.clear_pulses >= lines.hold_scl_after_pulses)
        lines.scl_stuck = true;
      // STOP setup is also subject to clock stretching, but is not a
      // data-clear pulse while the master holds SDA low.
      if (lines.scl_stuck || lines.sda_driven_low) return;
      ++lines.clear_pulses;
      if (lines.release_after_pulses &&
          lines.clear_pulses >= lines.release_after_pulses)
        lines.sda_stuck = false;
    }
  }
}
inline void delayMicroseconds(unsigned) {}
inline void delay(unsigned) {}
// Share one deterministic clock across fake Arduino translation units.
inline std::uint32_t& fake_arduino_millis() {
  static std::uint32_t now = 0;
  return now;
}
// ESP32 unsigned long is 32-bit; Linux LP64 unsigned long is not.
inline std::uint32_t millis() { return fake_arduino_millis(); }
