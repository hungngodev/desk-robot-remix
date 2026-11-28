"""USB epoch and exclusive ownership regression across runtime and bench."""
import fcntl
import json
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from desk_robot import room_station

ROOT = Path(__file__).resolve().parents[2]


def _frame(seq, stamp, raw):
    readings = {name: {"valid": False} for name in room_station.SENSORS}
    readings["soil"] = {"valid": True, "sample_ms": stamp, "raw_adc": raw}
    return json.dumps({
        "v": 1, "station": room_station.STATION, "seq": seq,
        "at_ms": stamp, "readings": readings,
    }).encode() + b"\n"


def test_runtime_bench_runtime_handoff_discards_previous_epoch(monkeypatch, tmp_path):
    capture = runpy.run_path(str(ROOT / "code/scripts/bench_room_station.py"))["capture"]
    monkeypatch.setitem(capture.__globals__, "_git_sha", lambda: None)
    lock_path = tmp_path / "serial-lock"
    lock_path.touch()
    frames = [_frame(80, 80000, 1000), _frame(81, 81000, 2000), _frame(1, 1000, 3000)]
    clock = [10.0]
    opens = []
    previous_ack = []
    observations = []
    conflicts = []
    nonces = iter(f"{n:016x}" for n in range(1, 10))
    monkeypatch.setattr(room_station.secrets, "token_hex", lambda _: next(nonces))
    monkeypatch.setattr(room_station, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    class Port:
        """Model CDC buffering using real POSIX advisory lock contention."""

        def __init__(self, path, *, baudrate, timeout, write_timeout, exclusive):
            assert path == "/dev/cu.room-test"
            assert (baudrate, timeout, write_timeout, exclusive) == (115200, .25, .25, True)
            self.lock = lock_path.open("rb")
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.lock.close()
                raise
            self.epoch = len(opens)
            opens.append(self.epoch)
            self.lines = []
            if self.epoch:
                self.lines.extend((previous_ack[-1], frames[self.epoch - 1]))
            self.first_write = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.lock.close()

        def write(self, request):
            assert request.startswith(b"\nSYNC ") and request.endswith(b"\n")
            ack = b"SYNC_ACK " + request[6:-1] + b"\r\n"
            previous_ack.append(ack)
            if self.first_write:
                self.first_write = False
                self.lines.extend((ack, frames[self.epoch]))
            return len(request)

        def read_until(self, expected, *, size):
            assert expected == b"\n" and size == room_station.MAX_FRAME_BYTES + 1
            if self.lines:
                return self.lines.pop(0)
            if self.epoch == 0:
                raise OSError("simulated USB unplug")
            clock[0] += 1.0
            return b""

    monkeypatch.setattr(room_station, "require_local_serial_device", lambda _: None)
    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=Port))

    def bench():
        return capture("/dev/cu.room-test", seconds=0.5, clock=lambda: clock[0])

    def observed(item):
        observations.append((item.seq, item.readings["soil"]["raw_adc"]))
        if len(observations) == 1:
            conflicts.append(bench())

    reader = room_station.RoomSerialFeed("/dev/cu.room-test", observed)
    with pytest.raises(OSError, match="simulated USB unplug"):
        reader._read_port(lambda: True)
    assert observations == [(80, 1000)]
    assert opens == [0]
    assert conflicts[0]["serial_error_type"] == "BlockingIOError"
    assert conflicts[0]["accepted_frames"] == 0
    assert not conflicts[0]["read_only_usb_sample_captured"]

    report = bench()
    assert report["serial_error_type"] is None
    assert report["accepted_frames"] == 1
    assert report["first_station_sequence"] == report["last_station_sequence"] == 81
    assert report["new_sensor_acquisitions"]["soil"] == 1
    assert report["read_only_usb_sample_captured"]
    assert not report["motion_authorized"] and not report["charging_verified"]

    reader._read_port(lambda: len(observations) < 2)
    assert opens == [0, 1, 2]
    assert observations == [(80, 1000), (1, 3000)]
    assert reader.received == 2 and reader.callback_failures == 0


def test_firmware_epoch_parser_retires_partial_command_after_unplug(tmp_path):
    compiler = shutil.which("g++")
    assert compiler is not None
    source = tmp_path / "epoch.cpp"
    source.write_text(r'''
#include <cassert>
#include <cstring>
#include "usb_epoch_sync.h"
using desk_robot_room::UsbEpochSync;
unsigned send(UsbEpochSync& parser, const char* bytes) {
    unsigned accepted = 0;
    for (; *bytes; ++bytes) accepted += parser.consume(*bytes);
    return accepted;
}
int main() {
    UsbEpochSync parser;
    assert(send(parser, "SYNC 0123456789abcdef\n") == 1);
    assert(std::strcmp(parser.token(), "0123456789abcdef") == 0);
    // The powered device may retain a partial command after USB disconnect.
    assert(send(parser, "SYNC deadbeef") == 0);
    assert(send(parser, "\nSYNC fedcba9876543210\n") == 1);
    assert(std::strcmp(parser.token(), "fedcba9876543210") == 0);
    assert(send(parser, "SYNC 00000000000000000\n") == 0);
    assert(send(parser, "SYNC ABCDEF0123456789\n") == 0);
    assert(std::strcmp(parser.token(), "fedcba9876543210") == 0);
    assert(send(parser, "\nSYNC 0000000000000001\n") == 1);
    assert(std::strcmp(parser.token(), "0000000000000001") == 0);
}
''')
    executable = tmp_path / "epoch"
    includes = ROOT / "code/firmware/room_station/src"
    command = [
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=undefined",
        "-fno-omit-frame-pointer", f"-I{includes}",
    ]
    if sys.platform.startswith("linux"):
        command.append("-no-pie")
    subprocess.run([*command, str(source), "-o", str(executable)],
                   check=True, capture_output=True, text=True, timeout=30)
    subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=15)
