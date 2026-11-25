"""Host contract for the Feather's single-attempt CDC transport."""
import platform
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_room_usb_adapter_never_retries_a_short_fifo_write(tmp_path):
    src = (ROOT / "code/firmware/room_station/src/main.cpp").read_text()
    assert "usb_tx.step(usb_port);" in src
    adapter = "class RoomUsbPort" + src.split("class RoomUsbPort", 1)[1].split(
        "RoomUsbPort usb_port;", 1
    )[0]
    harness = r"""
#include <cassert>
#include <cstddef>
#include <cstdint>
bool connected = true;
uint32_t capacity = 64, accepted = 0, writes = 0, flushes = 0;
bool tud_cdc_connected() { return connected; }
uint32_t tud_cdc_write_available() { return capacity; }
uint32_t tud_cdc_write(const void*, uint32_t count) {
  ++writes;
  assert(count == 64);
  return accepted;
}
uint32_t tud_cdc_write_flush() { ++flushes; return 0; }
""" + adapter + r"""
int main() {
  RoomUsbPort port;
  uint8_t bytes[64] = {};
  assert(port && port.availableForWrite() == 64);
  // Capacity can change after the advisory FIFO-space check. Zero and
  // partial writes must return directly to the sensor loop, without retry.
  assert(port.write(bytes, 64) == 0 && writes == 1);
  accepted = 7;
  assert(port.write(bytes, 64) == 7 && writes == 2);
  accepted = 64;
  assert(port.write(bytes, 64) == 64 && writes == 3);
  port.flush();
  assert(flushes == 1);
  connected = false;
  capacity = 0;
  assert(!port && port.availableForWrite() == 0);
}
"""
    compiler = shutil.which("g++") or shutil.which("c++")
    assert compiler is not None
    source = tmp_path / "usb_try_write.cpp"
    source.write_text(harness)
    executable = tmp_path / "usb_try_write"
    cmd = [
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=undefined",
        "-fno-omit-frame-pointer",
    ]
    if platform.system() == "Linux":
        cmd.append("-no-pie")
    subprocess.run([*cmd, str(source), "-o", str(executable)], check=True,
                   capture_output=True, text=True, timeout=30)
    subprocess.run([str(executable)], check=True, capture_output=True,
                   text=True, timeout=5)
