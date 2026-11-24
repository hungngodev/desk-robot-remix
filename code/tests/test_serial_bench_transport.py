"""Exercise USB framing without a connected or armed robot."""
import json
import runpy
import sys
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


def test_read_only_cli_reports_matched_goodput_and_rtt(monkeypatch, capsys):
    status = {
        "backend": "stepper_28byj48", "armed": False,
        "touch": {"active": False}, "safety": {"ready": False},
        "ranges": {
            "present_mask": 31, "valid_mask": 31,
            "mm": [45] * 5, "age_ms": [3] * 5,
        },
    }
    reply = json.dumps(status).encode("ascii") + b"\r\n"

    class InspectPort(FakePort):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def reset_input_buffer(self):
            pass

        def sleep(self, seconds):
            self.now += seconds

    # The first status reply takes two reads; exclude a complete unrelated
    # diagnostic line from matched bytes, but include its time in RTT.
    port = InspectPort([b"boot diagnostic\n", reply, reply])

    def open_port(name, baud, *, timeout, write_timeout):
        assert (name, baud, timeout, write_timeout) == ("fake", 115200, 0.03, 0.15)
        return port

    monkeypatch.setitem(
        transact.__globals__, "time",
        SimpleNamespace(monotonic=lambda: port.now, sleep=port.sleep),
    )
    monkeypatch.setitem(
        transact.__globals__, "serial", SimpleNamespace(Serial=open_port),
    )
    monkeypatch.setattr(
        sys, "argv", ["serial_bench.py", "--port", "fake", "--inspect", "--samples", "2"],
    )
    transact.__globals__["main"]()
    report = json.loads(capsys.readouterr().out)
    metrics = report["serial_bench"]
    assert port.writes == [b"status\n", b"status\n"]
    assert metrics["successful_status_transactions"] == 2
    assert metrics["request_bytes"] == 14
    assert metrics["matched_response_bytes"] == len(reply) * 2
    assert metrics["sample_window_ms"] == pytest.approx(400)
    assert metrics["status_transactions_per_second"] == pytest.approx(5)
    assert metrics["matched_response_bytes_per_second"] == pytest.approx(len(reply) * 5)
    assert metrics["matched_request_response_bytes_per_second"] == pytest.approx(
        (len(reply) * 2 + 14) / 0.4, abs=0.001,
    )
    assert metrics["round_trip_ms"] == {"min": 100.0, "median": 150.0, "max": 200.0}
    assert metrics["physical_line_rate_verified"] is False
    assert report["physical_qualification_pass"] is False


def test_failed_transaction_does_not_publish_success_receipt(monkeypatch):
    port = FakePort([b"OK stop"])
    clock(monkeypatch, port)
    receipt = {}
    with pytest.raises(TimeoutError):
        transact(port, "stop", receipt=receipt)
    assert receipt == {}
