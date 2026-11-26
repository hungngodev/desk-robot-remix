"""USB handshake timing must fail closed before the decoder sees telemetry."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from desk_robot import room_station as module


@pytest.mark.parametrize("phase", ["write", "ack", "frame", "empty"])
@pytest.mark.parametrize("bad_clock", [99.0, float("nan"), float("inf")])
def test_usb_clock_fault_retires_connection(monkeypatch, phase, bad_clock):
    clock = [100.0]
    reads = []
    decoded = []
    observed = []
    closed = []

    class Decoder:
        def __init__(self, **kwargs):
            pass

        def accept(self, line, *, now):
            decoded.append((line, now))
            return object()

    class Port:
        def __init__(self, *args, **kwargs):
            self.ack = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            closed.append(True)

        def write(self, request):
            self.ack = b"SYNC_ACK " + request[6:-1] + b"\r\n"
            if phase == "write":
                clock[0] = bad_clock
            return len(request)

        def read_until(self, *args, **kwargs):
            reads.append(True)
            if self.ack is not None:
                ack, self.ack = self.ack, None
                if phase == "ack":
                    clock[0] = bad_clock
                return ack
            clock[0] = bad_clock
            return b"" if phase == "empty" else b"{}\n"

    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(module, "RoomStationDecoder", Decoder)
    monkeypatch.setattr(module, "require_local_serial_device", lambda _: None)
    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=Port))
    feed = module.RoomSerialFeed("/dev/cu.test", observed.append)
    with pytest.raises(RuntimeError, match="Invalid or backwards Mac USB clock"):
        feed._read_port(lambda: len(reads) < 5)
    assert closed == [True]
    assert not decoded
    assert not observed
    assert feed.received == 0
