"""Regression for the USB transaction read bound and disconnect receipt."""

import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

transact = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/serial_bench.py"
))["transact_serial"]


class Port:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.sizes = []
        self.writes = []
        self.now = 0.0

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def read_until(self, expected, *, size):
        assert expected == b"\n"
        self.sizes.append(size)
        self.now += 0.1
        chunk = next(self.chunks, b"")
        if isinstance(chunk, OSError):
            raise chunk
        return chunk

    def readline(self, size):
        pytest.fail("Unbounded per-read timeout used instead of read_until")


def test_fragmented_status_uses_remaining_reply_capacity(monkeypatch):
    port = Port([b'{"armed":', b"", b"false}\r", b"\n"])
    monkeypatch.setitem(transact.__globals__, "time", SimpleNamespace(monotonic=lambda: port.now))
    receipt = {}
    assert transact(port, "status", receipt=receipt) == {"armed": False}
    assert port.sizes == [1920, 1911, 1911, 1904]
    assert receipt["matched_response_bytes"] == 17
    assert port.writes == [b"status\n"]


@pytest.mark.parametrize("chunks, error", [
    ([b"x" * 1900, b"x" * 20], RuntimeError),
    ([b"x" * 1900, b"x" * 21], RuntimeError),
    ([b'{"armed":', OSError("unplugged")], OSError),
    ([b"x"] * 6, TimeoutError),
])
def test_incomplete_reply_never_publishes_receipt(monkeypatch, chunks, error):
    port = Port(chunks)
    monkeypatch.setitem(transact.__globals__, "time", SimpleNamespace(monotonic=lambda: port.now))
    receipt = {}
    with pytest.raises(error):
        transact(port, "status", receipt=receipt)
    assert receipt == {}
    assert port.writes == [b"status\n"]
    assert port.sizes[0] == 1920
    assert all(0 < size <= 1920 for size in port.sizes)
    if error is TimeoutError:
        assert len(port.sizes) == 5
