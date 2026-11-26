#include <cassert>
#include <cstdint>
#include <iostream>
#include "sensor_recovery.h"

struct FakeSensor {
  bool connected = false;
  bool started = false;
  unsigned attempts = 0;
  unsigned fresh_frames = 0;
  void probe() { ++attempts; started = connected; }
  void disconnect() { connected = false; started = false; fresh_frames = 0; }
};

struct FakeStopWire {
  uint8_t address = 0;
  uint8_t bytes[2] = {};
  unsigned writes = 0, begins = 0, ends = 0;
  unsigned rejected_write = 2;
  int result = 0;
  void beginTransmission(uint8_t value) { address = value; ++begins; }
  unsigned write(uint8_t value) {
    assert(writes < 2);
    bytes[writes] = value;
    return writes++ == rejected_write ? 0U : 1U;
  }
  int endTransmission() { ++ends; return result; }
};

int main() {
  // A partial write can still receive an ACK. Only a complete stop command
  // may start the settle interval. End the transaction on every error path.
  for (unsigned rejected = 0; rejected <= 2; ++rejected) {
    for (int result = 0; result <= 4; ++result) {
      FakeStopWire wire;
      wire.rejected_write = rejected;
      wire.result = result;
      assert(desk_robot_room::scd_request_stop(wire, 0x62) ==
             (rejected == 2 && result == 0));
      assert(wire.address == 0x62 && wire.begins == 1 && wire.ends == 1);
      assert(wire.writes == 2 && wire.bytes[0] == 0x3f && wire.bytes[1] == 0x86);
    }
  }

  using Recovery = desk_robot_room::SensorRecoverySchedule;
  Recovery schedule;
  FakeSensor devices[Recovery::kCount];
  unsigned radar_polls = 0;
  unsigned usb_polls = 0;
  const auto tick = [&](uint32_t now) {
    ++radar_polls;
    ++usb_polls;
    const bool active[] = {devices[0].started, devices[1].started, devices[2].started};
    const int selected = schedule.next(now, active);
    if (selected >= 0) devices[selected].probe();
    for (unsigned i = 0; i < Recovery::kCount; ++i) {
      if (devices[i].started) {
        ++devices[i].fresh_frames;
        schedule.record_success(static_cast<Recovery::Sensor>(i));
      }
    }
    return selected;
  };

  // Initial failure for all I2C modules, but one attempt per loop pass.
  assert(tick(100) == Recovery::kScd);
  assert(tick(101) == Recovery::kBme);
  assert(tick(102) == Recovery::kAmg);
  assert(tick(103) == -1);
  assert(devices[0].attempts == 1 && devices[1].attempts == 1 && devices[2].attempts == 1);

  // BME returns while the other sensors are still absent.
  devices[1].connected = true;
  assert(tick(5100) == Recovery::kScd);
  assert(tick(5101) == Recovery::kBme);
  assert(devices[1].started && devices[1].fresh_frames == 1);
  assert(tick(5102) == Recovery::kAmg);
  assert(tick(5103) == -1);
  assert(devices[1].fresh_frames == 3);

  // SCD and AMG have independently backed off to ten seconds.
  assert(tick(10100) == -1);
  devices[0].connected = true;
  assert(tick(15100) == Recovery::kScd);
  assert(devices[0].started && devices[0].fresh_frames == 1);
  assert(tick(15102) == Recovery::kAmg);
  // A completed sample reset BME's retry history; an independent fault
  // can retry immediately, but cannot publish a cached old tuple.
  devices[1].disconnect();
  assert(tick(15103) == Recovery::kBme);
  assert(!devices[1].started && devices[1].fresh_frames == 0);
  devices[1].connected = true;
  assert(tick(20102) == -1);
  assert(tick(20103) == Recovery::kBme);
  assert(devices[1].fresh_frames == 1);

  // An ACK without a complete conversion must not reset the backoff.
  Recovery bounded;
  bool only_scd_missing[] = {false, true, true};
  uint32_t time = 0xfffff000U;
  assert(bounded.next(time, only_scd_missing) == Recovery::kScd);
  for (uint32_t interval : {5000U, 10000U, 20000U, 40000U, 60000U,
                            60000U, 60000U}) {
    assert(bounded.next(time + interval - 1U, only_scd_missing) == -1);
    time += interval;
    assert(bounded.next(time, only_scd_missing) == Recovery::kScd);
  }
  bounded.record_success(Recovery::kScd);
  assert(bounded.next(time, only_scd_missing) == Recovery::kScd);
  assert(bounded.next(time + 4999U, only_scd_missing) == -1);
  assert(bounded.next(time + 5000U, only_scd_missing) == Recovery::kScd);

  // SCD40's stop/start settle interval must be elapsed, not a sleep.
  assert(!desk_robot_room::scd_stop_settled(1499U, 1000U));
  assert(desk_robot_room::scd_stop_settled(1500U, 1000U));
  assert(!desk_robot_room::scd_stop_settled(0x000001e0U, 0xfffffff0U));
  assert(desk_robot_room::scd_stop_settled(0x000001e4U, 0xfffffff0U));

  Recovery wrap;
  const uint32_t near_wrap = 0xfffffff0U;
  wrap.record_attempt(Recovery::kScd, near_wrap);
  bool active[] = {false, true, true};
  assert(wrap.next(0x00000040U, active) == -1);
  assert(wrap.next(static_cast<uint32_t>(near_wrap + Recovery::kRetryMs), active) == Recovery::kScd);
  assert(radar_polls == usb_polls && radar_polls >= 14);
  std::cout << "PASS isolated room sensor recovery and bounded retry schedule\n";
}
