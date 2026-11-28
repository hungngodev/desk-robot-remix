#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <iostream>

#include "sensor_recovery.h"
#include "thermal_consent_gate.h"
#include "thermal_pixels.h"

#ifndef ROOM_AMG_FITTED
#define ROOM_AMG_FITTED 0
#endif

namespace {

constexpr size_t AMG88xx_PIXEL_ARRAY_SIZE = 64;
constexpr uint32_t kReportMs = 1000;
constexpr uint32_t kThermalScanMaxMs = 250;
constexpr uint8_t kAmgAddress = 0x69;

uint32_t fake_now_ms = 0;
uint32_t millis() { return fake_now_ms; }

struct FakeWire {
  int requests = 0;
  uint8_t reg = 0;
  int cursor = 0;
  void beginTransmission(uint8_t) {}
  size_t write(uint8_t value) {
    reg = value;
    return 1;
  }
  int endTransmission(bool = true) { return 0; }
  int requestFrom(uint8_t, uint8_t, bool) {
    ++requests;
    cursor = 0;
    return 16;
  }
  int available() { return 16 - cursor; }
  int read() {
    ++cursor;
    return (cursor % 2 == 1) ? 0x64 : 0x00;  // 25.0 C per pixel
  }
};

FakeWire Wire;

struct FakeAmgRecovery {
  bool reset_called = false;
  void reset() { reset_called = true; }
};

FakeAmgRecovery amg_recovery;
desk_robot_room::ThermalConsentGate thermal_consent;
desk_robot_room::SensorRecoverySchedule sensor_recovery;
bool amg_started = false;
float thermal[AMG88xx_PIXEL_ARRAY_SIZE] = {};
float thermal_staging[AMG88xx_PIXEL_ARRAY_SIZE] = {};
bool thermal_valid = false;
bool thermal_scan_active = false;
bool thermal_ever_requested = false;
uint8_t thermal_next_chunk = 0;
uint32_t thermal_requested_ms = 0;
uint32_t thermal_started_ms = 0;
uint32_t thermal_sample_ms = 0;

#include "thermal_under_test.h"

void feed_line(desk_robot_room::ThermalConsentGate& gate, const char* text) {
  for (size_t i = 0; text[i] != '\0'; ++i) {
    gate.consume(static_cast<uint8_t>(text[i]));
  }
}

}  // namespace

int main() {
  // Gate defaults OFF even when ROOM_AMG_FITTED == 1, and ignores malformed input.
  assert(!thermal_consent.allowed());
  assert(!thermal_consent.take_revoked());
  feed_line(thermal_consent, "AMG_CONSENT\n");
  feed_line(thermal_consent, "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\n");
  feed_line(thermal_consent, "AMG_CONSENT ONX\n");
  assert(!thermal_consent.allowed());

  amg_started = true;
  fake_now_ms = 100;
  thermal_step(100);
  assert(Wire.requests == 0);
  assert(!thermal_scan_active && !thermal_valid);

  // Grant consent: fitted build completes 8-chunk scan; unfitted stays inert.
  feed_line(thermal_consent, "AMG_CONSENT ON\r\n");
  assert(thermal_consent.allowed());
  assert(!thermal_consent.take_revoked());

  amg_started = true;
  for (uint32_t chunk = 0; chunk < 8; ++chunk) {
    fake_now_ms = 200U + chunk;
    thermal_step(fake_now_ms);
  }
#if ROOM_AMG_FITTED
  assert(Wire.requests == 8);
  assert(thermal_valid && !thermal_scan_active);
  assert(thermal[0] == 25.0f && thermal[63] == 25.0f);

  // Begin next scan cycle, read 3 chunks, then revoke consent mid-scan.
  for (uint32_t chunk = 0; chunk < 3; ++chunk) {
    fake_now_ms = 1200U + chunk;
    thermal_step(fake_now_ms);
  }
  assert(thermal_scan_active && thermal_next_chunk == 3);
  const int requests_before_revoke = Wire.requests;
  feed_line(thermal_consent, "AMG_CONSENT OFF\n");
  assert(!thermal_consent.allowed());
  assert(thermal_consent.take_revoked());
  assert(!thermal_consent.take_revoked());
  revoke_thermal_scan();
  assert(!thermal_scan_active && !thermal_valid && !amg_started);
  assert(amg_recovery.reset_called);
  for (size_t i = 0; i < AMG88xx_PIXEL_ARRAY_SIZE; ++i) {
    assert(thermal[i] == 0.0f && thermal_staging[i] == 0.0f);
  }

  fake_now_ms = 1210U;
  thermal_step(1210U);
  assert(Wire.requests == requests_before_revoke);
  assert(!thermal_valid && !thermal_scan_active);
#else
  assert(Wire.requests == 0);
  assert(!thermal_valid && !thermal_scan_active);
  feed_line(thermal_consent, "AMG_CONSENT OFF\n");
  assert(!thermal_consent.allowed());
  assert(thermal_consent.take_revoked());
  revoke_thermal_scan();
#endif

  std::cout << "PASS room thermal consent default-off and mid-scan revocation\n";
  return 0;
}
