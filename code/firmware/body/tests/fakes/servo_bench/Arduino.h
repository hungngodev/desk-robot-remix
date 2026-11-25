#pragma once

#include <algorithm>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <string>

#define LOW 0
#define OUTPUT 3

namespace servo_bench_fake {
extern std::uint32_t clock_ms;
extern int attached_pin;
extern std::uint32_t attached_at, detached_at;
extern unsigned writes;
}

struct FakeServoSerial {
  std::deque<int> rx;
  std::string sent;
  int free = 0;
  unsigned blocking_prints = 0;
  unsigned rx_read_ms = 0;
  void begin(int) {}
  int available() { return static_cast<int>(rx.size()); }
  int read() {
    if (rx.empty()) return -1;
    const int byte = rx.front();
    rx.pop_front();
    servo_bench_fake::clock_ms += rx_read_ms;
    return byte;
  }
  int availableForWrite() { return free; }
  std::size_t write(const std::uint8_t* data, std::size_t count) {
    assert(count <= static_cast<std::size_t>(free));
    assert(count <= 32);
    sent.append(reinterpret_cast<const char*>(data), count);
    free -= static_cast<int>(count);
    return count;
  }
  // Model a synchronous UART call under backpressure. It must never be
  // invoked while the fixture has attached PWM.
  void println(const char*) {
    if (servo_bench_fake::attached_pin >= 0 && free == 0) {
      servo_bench_fake::clock_ms += 500;
      ++blocking_prints;
    }
  }
  void feed(const std::string& bytes) {
    for (unsigned char byte : bytes) rx.push_back(byte);
  }
};
extern FakeServoSerial Serial;
inline std::uint32_t millis() { return servo_bench_fake::clock_ms; }
inline void pinMode(int, int) {}
inline void digitalWrite(int, int value) { assert(value == LOW); }
inline double ledcSetup(int, int, int) { return 50; }
inline void ledcWrite(int, unsigned) { ++servo_bench_fake::writes; }
inline void ledcAttachPin(int pin, int) {
  assert(servo_bench_fake::attached_pin == -1);
  servo_bench_fake::attached_pin = pin;
  servo_bench_fake::attached_at = millis();
}
inline void ledcDetachPin(int pin) {
  assert(servo_bench_fake::attached_pin == pin);
  servo_bench_fake::attached_pin = -1;
  servo_bench_fake::detached_at = millis();
}
