"""USB framing rejects malformed input without losing the causal epoch."""

import json
import sys
from types import SimpleNamespace

import pytest
from desk_robot.room_station import MAX_FRAME_BYTES, SENSORS, RoomSerialFeed, RoomStationDecoder


def _frame(seq=1):
    return json.dumps({
        "v": 1, "station": "room-pod-01", "seq": seq, "at_ms": seq * 100,
        "readings": {sensor: {"valid": False} for sensor in SENSORS},
    }).encode()


@pytest.mark.parametrize("control", [b"\t", b"\r", b"\n", b"\x00", b"\x1b", b"\x7f"])
def test_decoder_rejects_embedded_control_without_advancing_counter(control):
    decoder = RoomStationDecoder()
    bad = _frame().replace(b'"seq": ', b'"seq":' + control)
    with pytest.raises(ValueError):
        decoder.accept(bad + b"\r\n", now=1.0)
    assert decoder.accept(_frame() + b"\r\n", now=1.0).seq == 1


@pytest.mark.parametrize("ending", [b"", b"\n", b"\r\n"])
def test_decoder_accepts_exact_frame_terminators_at_size_limit(ending):
    raw = _frame()
    padded = raw + b" " * (MAX_FRAME_BYTES - len(raw) - len(ending)) + ending
    assert RoomStationDecoder().accept(padded, now=1.0).seq == 1
    with pytest.raises(ValueError, match="Oversized"):
        RoomStationDecoder().accept(b" " + padded, now=1.0)


def test_usb_recovery_after_split_line_64k_garbage_and_duplicate_keys(monkeypatch):
    split = _frame(1)
    garbage = b"x" * (64 * 1024)
    duplicate = _frame(4).replace(b'"valid": false', b'"valid": true, "valid": false', 1)
    control = _frame(3).replace(b'"seq": ', b'"seq":\t')
    # An idle read denotes a serial timeout, not a line delimiter.
    chunks = [split[:20], b"", split[20:] + b"\n"]
    chunks.extend(garbage[i:i + MAX_FRAME_BYTES + 1]
                  for i in range(0, len(garbage), MAX_FRAME_BYTES + 1))
    chunks.extend([_frame(5) + b"\n", duplicate + b"\n", control + b"\n",
                   _frame(2) + b"\r\n", b""])
    observed = []

    class Port:
        ack = None
        reads = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def write(self, request):
            self.ack = b"SYNC_ACK " + request[6:-1] + b"\n"
            return len(request)

        def read_until(self, expected, size):
            assert expected == b"\n" and size == MAX_FRAME_BYTES + 1
            if self.ack is not None:
                ack, self.ack = self.ack, None
                return ack
            chunk = chunks[self.reads]
            self.reads += 1
            assert len(chunk) <= size
            return chunk

    port = Port()
    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=lambda *a, **kw: port))
    monkeypatch.setattr("desk_robot.room_station.require_local_serial_device", lambda _: None)
    feed = RoomSerialFeed("/dev/cu.test", lambda observation: observed.append(observation.seq))
    feed._read_port(lambda: port.reads < len(chunks))
    assert observed == [2]
    assert feed.received == 1
    assert feed.rejected == 4  # split, entire garbage line, duplicate, control
    assert feed.callback_failures == 0


def test_oversized_text_rejected_before_utf8_allocation():
    class OversizedText(str):
        def encode(self, *args, **kwargs):
            pytest.fail("Oversized text must not be encoded")

    with pytest.raises(ValueError, match="Invalid station USB line"):
        RoomStationDecoder().accept(OversizedText("x" * 65536), now=1.0)


def test_text_frame_limit_counts_utf8_bytes_not_characters():
    raw = _frame().decode()
    text = raw.replace("room-pod-01", "é" * (MAX_FRAME_BYTES // 2))
    assert len(text) < MAX_FRAME_BYTES < len(text.encode())
    with pytest.raises(ValueError, match="Invalid station USB line"):
        RoomStationDecoder().accept(text, now=1.0)
