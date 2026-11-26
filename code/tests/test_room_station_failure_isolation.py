"""Exercise real firmware report composition with an isolated SCD transport fault."""

import json
import platform
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "firmware/room_station/src"


@pytest.mark.parametrize("fault", ["readiness", "measurement"])
def test_scd_failure_does_not_hide_healthy_room_sensors(tmp_path, fault):
    source = (SOURCE / "main.cpp").read_text()
    names = ("scd_step", "scd_observation", "bme_observation", "radar_observation",
             "soil_observation", "thermal_observation", "report", "loop")
    functions = []
    for name in names:
        start = source.index(f"void {name}(")
        end = source.index("\n}", start) + 2
        functions.append(source[start:end])
    harness = r"""
#include <cstdint>
#include <cmath>
#include <iostream>
#include <sstream>
#include "bme_completed_sample.h"
#include "scd_sample_freshness.h"
#include "sensor_recovery.h"
#include "radar_sample_clock.h"
#include "radar_data_frame_gate.h"
using std::isfinite;
#define F(value) value
#define ROOM_SOIL_FITTED 0
constexpr uint32_t kScdNoSampleMs = 15000, kScdStaleMs = 8500, kReportMs = 1000;
constexpr uint32_t kBmeStaleMs = 3000, kRadarStaleMs = 3000, kThermalStaleMs = 3000;
constexpr unsigned AMG88xx_PIXEL_ARRAY_SIZE = 64;
uint32_t clock_ms, scd_started_ms, last_scd_ms, sequence, thermal_sample_ms;
uint32_t millis() { return clock_ms; }
bool scd_started = true, scd_valid, thermal_valid;
uint16_t co2_ppm;
float scd_temp, scd_humidity, thermal[64];
bool finite_temperature(float t) { return isfinite(t) && t >= -40 && t <= 125; }
struct FakeScd {
  int readiness_error = 0, measurement_error = 0;
  int getDataReadyStatus(bool& ready) { ready = true; return readiness_error; }
  int readMeasurement(uint16_t& ppm, float& t, float& rh) {
    ppm = 700; t = 22; rh = 40; return measurement_error;
  }
} scd;
desk_robot_room::BmeCompletedSample bme_completed;
desk_robot_room::SensorRecoverySchedule sensor_recovery;
desk_robot_room::RadarSampleClock radar_sample_clock;
desk_robot_room::RadarTargetSample radar_completed;
struct Telemetry {
  std::ostringstream output;
  void reset() { output.str(""); output.clear(); }
  template <typename T> void print(T value) { output << value; }
  void println(const char* value) { output << value << '\n'; }
} telemetry;
void jsbool(bool value) { telemetry.print(value ? "true" : "false"); }
void number(float value, int = 2) { telemetry.print(value); }
int usb_port, watchdog_registers;
int* NRF_WDT = &watchdog_registers;
bool room_watchdog_ready = true;
uint32_t last_report_ms;
unsigned passes;
struct UsbTx {
  void queue_report(Telemetry& value) { std::cout << value.output.str(); }
  void queue_ack(int) {}
  void step(int) {}
} usb_tx;
struct SerialPort {
  int available() { return 0; }
  int read() { return -1; }
} Serial;
struct EpochSync {
  bool consume(uint8_t) { return false; }
  int token() { return 0; }
} usb_epoch_sync;
struct Radar {
  void read() {}
} radar;
struct RadarUart {
  void begin_poll() {}
  bool take_completed_data_frame() { return true; }
  desk_robot_room::RadarTargetSample completed_sample() {
    return {true, false, true, 0, static_cast<uint16_t>(49 + clock_ms / 1000)};
  }
} radar_uart;
struct Watchdog {
  void completed_pass(int&) { ++passes; }
} room_watchdog;
void recover_sensors(uint32_t) {}
void thermal_step(uint32_t) {}
void soil_step() {}
// A healthy completed conversion is supplied by the simulated BME driver.
void bme_step(uint32_t now) {
  const unsigned i = now / 1000 - 1;
  bme_completed.publish(23 + i, 41, 100000, 12345 + i, now);
}
""" + "\n".join(functions) + r"""
int main(int argc, char**) {
  for (unsigned i = 0; i < 7; ++i) {
    clock_ms = 1000U + 1000U * i;
    if (i == 1) {
      if (argc == 2) scd.readiness_error = 1;
      else scd.measurement_error = 1;
    }
    loop();
  }
  return passes == 7 ? 0 : 1;
}
"""
    native = tmp_path / "room_failure.cpp"
    native.write_text(harness)
    executable = tmp_path / "room_failure"
    command = [
        "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=undefined",
        "-fno-omit-frame-pointer", f"-I{SOURCE}", str(native), "-o", str(executable),
    ]
    if platform.system() == "Linux":
        command.append("-no-pie")
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    args = [str(executable)]
    if fault == "readiness":
        args.append(fault)
    result = subprocess.run(args, check=True, capture_output=True, text=True, timeout=15)
    frames = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(frames) == 7
    for i, frame in enumerate(frames):
        now = 1000 + 1000 * i
        assert frame["seq"] == i + 1
        assert frame["at_ms"] == now
        readings = frame["readings"]
        if i == 0:
            assert readings["scd40"]["valid"] is True
            assert readings["scd40"]["co2_ppm"] == 700
        else:
            assert readings["scd40"] == {"valid": False}
        assert readings["bme688"] == {
            "valid": True, "sample_ms": now, "temp_c": 23 + i,
            "humidity_pct": 41, "pressure_pa": 100000, "gas_ohms": 12345 + i,
        }
        assert readings["ld2410c"] == {
            "valid": True, "sample_ms": now, "presence": True, "stationary": False,
            "moving": True, "stationary_cm": 0, "moving_cm": 50 + i,
        }
        assert readings["soil"] == readings["amg8833"] == {"valid": False}
