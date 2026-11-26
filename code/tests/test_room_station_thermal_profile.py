"""Compile actual station acquisition and reporting functions for each profile."""

import configparser
import platform
import shutil
import subprocess
from pathlib import Path

import pytest

STATION = Path(__file__).resolve().parents[1] / "firmware/room_station"


@pytest.mark.parametrize("profile,enabled", [
    ("bench", 0), ("full", 0), ("bench_thermal", 1), ("full_thermal", 1),
])
@pytest.mark.parametrize("standard", ["c++11", "c++17"])
def test_thermal_profile_gates_actual_firmware(tmp_path, profile, enabled, standard):
    config = configparser.ConfigParser(interpolation=None)
    config.read(STATION / "platformio.ini")
    flags = config[f"env:feather_nrf52840_room_{profile}"]["build_flags"].split()
    assert f"-DROOM_AMG_FITTED={enabled}" in flags
    assert config["platformio"]["default_envs"] == "feather_nrf52840_room_bench"
    firmware = (STATION / "src/main.cpp").read_text()
    assert "#ifndef ROOM_AMG_FITTED\n#define ROOM_AMG_FITTED 0\n#endif" in firmware
    functions = []
    for name in ("thermal_step", "thermal_observation", "recover_sensors"):
        start = firmware.index(f"void {name}(")
        end = firmware.index("\n}", start) + 2
        functions.append(firmware[start:end])
    harness = r"""
#include <cassert>
#include <cstdint>
#include <sstream>
#include <string>
#include "sensor_recovery.h"
#define F(value) value
constexpr uint32_t kReportMs = 1000, kThermalScanMaxMs = 250, kThermalStaleMs = 3000;
constexpr unsigned AMG88xx_PIXEL_ARRAY_SIZE = 64;
constexpr uint8_t kAmgAddress = 0x69, SCD41_I2C_ADDR_62 = 0x62;
uint32_t clock_ms = 1000;
uint32_t millis() { return clock_ms; }
struct Bus {
  void beginTransmission(uint8_t) {}
  int write(uint8_t) { return 1; }
  int endTransmission() { return 0; }
} Wire;
struct Scd {
  void begin(Bus&, uint8_t) {}
  int startPeriodicMeasurement() { return 0; }
} scd;
bool scd_stop_pending, scd_valid, scd_started = true, bme_started = true;
uint32_t scd_stop_ms, scd_started_ms, last_scd_ms;
struct Completed { void invalidate() {} } bme_completed;
unsigned bme_probes;
bool begin_bme() { ++bme_probes; return true; }
struct Recovery {
  unsigned starts = 0, steps = 0;
  bool pending = false, ready = false;
  void begin() { ++starts; pending = true; }
  bool active() const { return pending; }
  bool step(Bus&, uint32_t) {
    ++steps;
    if (!pending) return false;
    pending = false; ready = true; return true;
  }
  bool take_ready() { const bool result = ready; ready = false; return result; }
} amg_recovery;
desk_robot_room::SensorRecoverySchedule sensor_recovery;
bool amg_started, thermal_scan_active, thermal_ever_requested, thermal_valid;
uint8_t thermal_next_chunk;
uint32_t thermal_requested_ms, thermal_started_ms, thermal_sample_ms;
float thermal[64], thermal_staging[64];
unsigned reads;
namespace desk_robot_room {
bool read_thermal_chunk(Bus&, uint8_t address, uint8_t chunk, float* pixels,
                        unsigned count) {
  assert(address == kAmgAddress && count == 64U - 8U * chunk);
  ++reads;
  for (unsigned i = 0; i < 8; ++i) pixels[i] = 25;
  return true;
}
}
struct Telemetry {
  std::ostringstream output;
  template <typename T> void print(T value) { output << value; }
} telemetry;
void jsbool(bool value) { telemetry.print(value ? "true" : "false"); }
void number(float value, int) { telemetry.print(value); }
""" + "\n".join(functions) + r"""
int main() {
  bme_started = false;
  recover_sensors(clock_ms);
  assert(bme_started && bme_probes == 1);
  recover_sensors(clock_ms);
  assert(amg_recovery.starts == ROOM_AMG_FITTED);
  recover_sensors(clock_ms);
  assert(amg_started == bool(ROOM_AMG_FITTED));
  // Even a responding connected device or stale valid flag must not make
  // the disabled profile touch its thermal bus or publish pixels.
  amg_started = true;
  for (unsigned i = 0; i < 8; ++i) thermal_step(clock_ms);
  assert(reads == (ROOM_AMG_FITTED ? 8U : 0U));
  assert(thermal_valid == bool(ROOM_AMG_FITTED));
  thermal_valid = true;
  thermal_sample_ms = clock_ms;
  thermal_observation(clock_ms);
  if (ROOM_AMG_FITTED) {
    assert(telemetry.output.str().find("\"pixels_c\":[25") != std::string::npos);
  } else {
    assert(amg_recovery.steps == 0);
    assert(!thermal_valid);
    assert(telemetry.output.str() == "\"amg8833\":{\"valid\":false}");
  }
}
"""
    compiler = shutil.which("c++")
    assert compiler is not None
    source = tmp_path / "thermal_profile.cpp"
    source.write_text(harness)
    binary = tmp_path / "thermal_profile"
    command = [
        compiler, f"-std={standard}", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=undefined",
        "-fno-omit-frame-pointer", f"-I{STATION / 'src'}",
        f"-DROOM_AMG_FITTED={enabled}", str(source), "-o", str(binary),
    ]
    if platform.system() == "Linux":
        command.append("-no-pie")
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=15)
