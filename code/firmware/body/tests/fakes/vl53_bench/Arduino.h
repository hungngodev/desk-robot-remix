#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <cassert>
#include <string>

constexpr int LOW = 0, HIGH = 1, OUTPUT = 3;
// Defined once by the bench test, also under C++11.
extern bool stuck_bus;
extern uint32_t clock_ms;
extern unsigned outputs_low;
extern std::array<unsigned, 40> low_writes, output_modes, input_reads;
inline void digitalWrite(int pin, int level) {
  assert(pin >= 0 && pin < 40 && level == LOW);
  ++outputs_low;
  ++low_writes[pin];
}
inline void pinMode(int pin, int mode) {
  assert(pin >= 0 && pin < 40 && mode == OUTPUT);
  assert(low_writes[pin] == 1);  // Preload LOW before switching to output.
  ++output_modes[pin];
}
inline int digitalRead(int pin) {
  assert(pin == 21 || pin == 22);
  ++input_reads[pin];
  return stuck_bus ? LOW : HIGH;
}
inline uint32_t millis() { return clock_ms; }
inline void delay(unsigned) {}
struct FakeSerial {
  std::string last;
  unsigned valid = 0, samples = 0;
  void begin(unsigned) {}
  void println(const char* value) { last = value; }
  void printf(const char*, unsigned long, unsigned, unsigned ok, unsigned) {
    valid = ok;
    ++samples;
  }
};
extern FakeSerial Serial;
