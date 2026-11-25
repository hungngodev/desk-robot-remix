#pragma once
#include <cstddef>
#include <cstdint>
#include <cassert>
#include <string>

constexpr int LOW = 0, HIGH = 1, OUTPUT = 3;
inline bool stuck_bus = false;
inline uint32_t clock_ms = 0;
inline unsigned outputs_low = 0;
inline void digitalWrite(int, int level) { assert(level == LOW); ++outputs_low; }
inline void pinMode(int, int mode) { assert(mode == OUTPUT); }
inline int digitalRead(int) { return stuck_bus ? LOW : HIGH; }
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
inline FakeSerial Serial;
