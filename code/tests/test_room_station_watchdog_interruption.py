"""DRX-1779: model watchdog reset, not physical I2C timeout or availability."""

import platform
import shutil
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "firmware/room_station/src/main.cpp"


@pytest.mark.parametrize("standard", ["c++11", "c++17"])
def test_stalled_i2c_pass_cannot_send_usb_or_feed_watchdog(tmp_path, standard):
    source = SOURCE.read_text()
    watchdog = source.split("class RoomLoopWatchdog", 1)[1].split(
        "RoomLoopWatchdog room_watchdog;", 1
    )[0]
    loop = source.split("void loop() {", 1)[1]
    harness = r"""
#include <cassert>
#include <cstdint>
class RoomLoopWatchdog""" + watchdog + r"""
struct Registers {
  uint32_t RUNSTATUS = 0, CONFIG = 0, CRV = 0, RREN = 0;
  uint32_t TASKS_START = 0, RR[8] = {};
} regs;
Registers* NRF_WDT = &regs;
RoomLoopWatchdog room_watchdog;
bool room_watchdog_ready;
uint32_t clock_ms = 1000, last_report_ms = 0;
constexpr uint32_t kReportMs = 1000;
uint32_t millis() { return clock_ms; }
struct SerialPort {
  int available() { return 0; }
  int read() { return -1; }
} Serial;
struct Sync {
  bool consume(uint8_t) { return false; }
  int token() { return 0; }
  bool take_revoked() { return false; }
} usb_epoch_sync, thermal_consent;
struct Radar {
  void begin_poll() {}
  void read() {}
  bool take_completed_data_frame() { return false; }
  int completed_sample() { return 0; }
} radar, radar_uart;
int radar_completed;
struct RadarClock {
  void observe(bool, bool, uint32_t) {}
} radar_sample_clock;
int usb_port;
unsigned sends = 0, reports = 0;
struct UsbTx {
  void queue_ack(int) {}
  void step(int) { ++sends; }
} usb_tx;
void revoke_thermal_scan() {}
struct SimulatedWatchdogReset {};
unsigned stall_stage = 0;
void sensor_call(unsigned stage) {
  if (stall_stage != stage) return;
  // Model an external reset interrupting a call that never returns.
  // Do not model a normal I2C NACK or claim host timing is real WDT timing.
  assert(regs.RR[0] == 0);
  assert(regs.CONFIG == 9 && regs.RREN == 1 && regs.CRV == 131071);
  clock_ms += (regs.CRV + 1) / 32768 * 1000;
  throw SimulatedWatchdogReset{};
}
void recover_sensors(uint32_t) { sensor_call(1); }
void bme_step(uint32_t) { sensor_call(2); }
void thermal_step(uint32_t) { sensor_call(3); }
void scd_step(uint32_t) { sensor_call(4); }
void soil_step() {}
void report(uint32_t) { ++reports; }
void loop() {""" + loop + r"""
int main() {
  room_watchdog_ready = room_watchdog.begin(regs);
  assert(room_watchdog_ready);
  loop();
  assert(sends == 1 && reports == 1 && regs.RR[0] == 0x6E524635U);
  for (unsigned stage = 1; stage <= 4; ++stage) {
    stall_stage = stage;
    clock_ms += 1000;
    const uint32_t before = clock_ms;
    const unsigned old_sends = sends, old_reports = reports;
    regs.RR[0] = 0; // fake register records writes in this pass only
    bool interrupted = false;
    try { loop(); }
    catch (const SimulatedWatchdogReset&) { interrupted = true; }
    assert(interrupted && clock_ms - before == 4000);
    assert(sends == old_sends && reports == old_reports && regs.RR[0] == 0);
    // Simulate a fresh firmware instance after reset. A persistent fault
    // interrupts again; clearing the fault permits a completed pass.
    room_watchdog = RoomLoopWatchdog{};
    regs = Registers{};
    room_watchdog_ready = room_watchdog.begin(regs);
    clock_ms = 1000;
    last_report_ms = 0;
    interrupted = false;
    try { loop(); }
    catch (const SimulatedWatchdogReset&) { interrupted = true; }
    assert(interrupted && sends == old_sends && regs.RR[0] == 0);
    room_watchdog = RoomLoopWatchdog{};
    regs = Registers{};
    room_watchdog_ready = room_watchdog.begin(regs);
    clock_ms = 1000;
    last_report_ms = 0;
    stall_stage = 0;
    loop();
    assert(sends == old_sends + 1 && reports == old_reports + 1);
    assert(regs.RR[0] == 0x6E524635U);
  }
}
"""
    compiler = shutil.which("g++") or shutil.which("c++")
    assert compiler is not None
    native = tmp_path / "room_watchdog_interruption.cpp"
    native.write_text(harness)
    executable = tmp_path / "room_watchdog_interruption"
    command = [
        compiler, f"-std={standard}", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=undefined",
        "-fno-omit-frame-pointer",
    ]
    if platform.system() == "Linux":
        command.append("-no-pie")
    subprocess.run([*command, str(native), "-o", str(executable)], check=True,
                   capture_output=True, text=True, timeout=30)
    subprocess.run([str(executable)], check=True, capture_output=True,
                   text=True, timeout=5)
