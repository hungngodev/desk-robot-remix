#include "soil_sample.h"
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <string>

#ifndef EXPECT_SOIL_ENABLED
#error "The host harness must provide the expected profile independently"
#endif

constexpr int A0 = 0;
int readings[3] = {};
std::size_t adc_reads = 0;
uint32_t clock_ms = 0;

int analogRead(int pin) {
  assert(pin == A0 && adc_reads < 3);
  return readings[adc_reads++];
}
uint32_t millis() { return clock_ms; }
#define F(value) value
struct FakeTelemetry {
  std::string output;
  void print(const char* value) { output += value; }
  void print(char value) { output += value; }
  template <typename T> void print(T value) { output += std::to_string(value); }
} telemetry;

#include "soil_profile_under_test.h"

void expect_observation(uint32_t now, const char* expected) {
  telemetry.output.clear();
  soil_observation(now);
  assert(telemetry.output == expected);
}
void acquire(int a, int b, int c, uint32_t now) {
  readings[0] = a;
  readings[1] = b;
  readings[2] = c;
  adc_reads = 0;
  clock_ms = now;
  soil_step();
  assert(adc_reads == (EXPECT_SOIL_ENABLED ? 3U : 0U));
}

int main() {
  const char* invalid = "\"soil\":{\"valid\":false}";
  expect_observation(0, invalid);
  acquire(2000, 2002, 2001, 100);
#if EXPECT_SOIL_ENABLED
  const char* valid = "\"soil\":{\"valid\":true,\"sample_ms\":100,\"raw_adc\":2001}";
  expect_observation(100, valid);
  expect_observation(100 + kReportMs, valid);
  expect_observation(101 + kReportMs, invalid);
#else
  expect_observation(100, invalid);
#endif
  const int faults[][3] = {{0, 1, 1}, {-1, 1, 1}, {4095, 4094, 4094},
                           {4096, 4094, 4094}, {1000, 1100, 1257}};
  for (const auto& fault : faults) {
    // Start each fault case with a valid acquisition to catch retained data.
    acquire(2000, 2002, 2001, 200);
    acquire(fault[0], fault[1], fault[2], 201);
    expect_observation(201, invalid);
  }
  acquire(3000, 3001, 3002, 300);
#if EXPECT_SOIL_ENABLED
  expect_observation(300, "\"soil\":{\"valid\":true,\"sample_ms\":300,\"raw_adc\":3001}");
#else
  expect_observation(300, invalid);
#endif
}
