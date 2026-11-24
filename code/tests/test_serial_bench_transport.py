"""Exercise USB framing without a connected or armed robot."""
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

transact = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/serial_bench.py"
))["transact_serial"]


class FakePort:
    def __init__(self, fragments, *, short=False):
        self.fragments = iter(fragments)
        self.short = short
        self.writes = []
        self.reads = 0
        self.now = 0.0

    def write(self, data):
        self.writes.append(data)
        return len(data) - int(self.short)

    def readline(self, size):
        assert size == 1920
        self.reads += 1
        self.now += 0.1
        return next(self.fragments, b"")


def clock(monkeypatch, port):
    monkeypatch.setitem(
        transact.__globals__, "time",
        SimpleNamespace(monotonic=lambda: port.now),
    )


@pytest.mark.parametrize("fragments", [
    [b"OK stop\n"],
    [b"OK ", b"stop\r", b"\n"],
])
def test_complete_ack_across_read_timeouts(monkeypatch, fragments):
    port = FakePort(fragments)
    clock(monkeypatch, port)
    assert transact(port, "stop") == "OK stop"
    assert port.writes == [b"stop\n"]


def test_unterminated_ack_is_not_success(monkeypatch):
    port = FakePort([b"OK stop"])
    clock(monkeypatch, port)
    with pytest.raises(TimeoutError, match="no movement command will be retried"):
        transact(port, "stop")
    assert port.writes == [b"stop\n"]


def test_short_write_is_never_retried(monkeypatch):
    port = FakePort([b"OK stop\n"], short=True)
    clock(monkeypatch, port)
    with pytest.raises(RuntimeError, match="Short USB write"):
        transact(port, "stop")
    assert port.writes == [b"stop\n"]
    assert port.reads == 0


def test_fragmented_status_is_parsed_only_after_newline(monkeypatch):
    port = FakePort([b'{"armed":', b'false}', b'\r\n'])
    clock(monkeypatch, port)
    assert transact(port, "status") == {"armed": False}
    assert port.writes == [b"status\n"]


@pytest.mark.parametrize("fragments, error", [
    ([b"x" * 1900, b"x" * 20], "reply capacity"),
    ([b"OK\r stop\n"], "Malformed USB response framing"),
    ([b"ERR disarmed\n"], "ERR disarmed"),
])
def test_invalid_reply_fails_without_retry(monkeypatch, fragments, error):
    port = FakePort(fragments)
    clock(monkeypatch, port)
    with pytest.raises(RuntimeError, match=error):
        transact(port, "stop")
    assert port.writes == [b"stop\n"]
