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

    def read_until(self, expected, *, size):
        assert expected == b"\n" and 0 < size <= 1920
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
    monkeypatch.setitem(transact.__globals__, "require_local_serial_device", lambda _: None)

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


@pytest.mark.parametrize("command, drive_ack", [
    ("drive 10 10", b"OK drive left=10 right=10 ms=250\n"),
    ("drive 10 10 100", b"OK drive left=10 right=10 ms=100\n"),
])
@pytest.mark.parametrize("failure", ["none", "no_local_rearm", "rearm_error", "motion_timeout"])
def test_valid_drive_duration_is_resolved_before_actuation(
    monkeypatch, capsys, command, drive_ack, failure,
):
    status = {
        "backend": "stepper_28byj48", "armed": False,
        "touch": {"active": False}, "safety": {"ready": False},
        "ranges": {
            "present_mask": 31, "valid_mask": 31,
            "mm": [45] * 5, "age_ms": [3] * 5,
        },
    }

    class CommandPort(FakePort):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def reset_input_buffer(self):
            pass

        def sleep(self, seconds):
            self.now += seconds

        def read_until(self, expected, *, size):
            assert expected == b"\n" and size == 1920
            self.now += 0.1
            current = self.writes[-1].decode("ascii").rstrip("\n")
            if current == "status":
                return json.dumps(status).encode("ascii") + b"\n"
            # Independent wire fixtures from BodyControl.cpp, not the host
            # function being tested. Unknown writes must fail the test.
            if current == "rearm" and failure == "rearm_error":
                return b"ERR rearm safety_interlock\n"
            if current == command and failure == "motion_timeout":
                return b""
            return {
                "rearm": b"OK rearm\n",
                "arm": b"OK arm\n",
                command: drive_ack,
                "keepalive": b"OK keepalive\n",
                "halt": b"OK halt\n",
            }[current]

    port = CommandPort([])
    monkeypatch.setitem(transact.__globals__, "require_local_serial_device", lambda _: None)
    monkeypatch.setitem(
        transact.__globals__, "time",
        SimpleNamespace(monotonic=lambda: port.now, sleep=port.sleep),
    )
    monkeypatch.setitem(
        transact.__globals__, "serial", SimpleNamespace(Serial=lambda *a, **kw: port),
    )
    argv = ["serial_bench.py", "--port", "fake", "--command", command]
    if failure != "no_local_rearm":
        argv.append("--local-rearm")
    monkeypatch.setattr(sys, "argv", argv)
    if failure == "no_local_rearm":
        with pytest.raises(RuntimeError, match="Refusing implicit safety recovery"):
            transact.__globals__["main"]()
        assert port.writes == [b"status\n"]
        return
    if failure == "rearm_error":
        with pytest.raises(RuntimeError, match="ERR rearm safety_interlock"):
            transact.__globals__["main"]()
        assert port.writes == [b"status\n", b"rearm\n", b"halt\n"]
        return
    if failure == "motion_timeout":
        with pytest.raises(TimeoutError, match="Uncertain USB response"):
            transact.__globals__["main"]()
        assert port.writes == [
            b"status\n", b"rearm\n", b"arm\n",
            (command + "\n").encode("ascii"), b"halt\n",
        ]
        assert "halt acknowledged" not in capsys.readouterr().out
        return
    transact.__globals__["main"]()
    assert port.writes[:4] == [
        b"status\n", b"rearm\n", b"arm\n", (command + "\n").encode("ascii"),
    ]
    assert port.writes[4:-1]
    assert set(port.writes[4:-1]) == {b"keepalive\n"}
    assert port.writes[-1] == b"halt\n"
    assert "halt acknowledged" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["arm\nhalt", "drive 99 99", "rearm\narm", "stop\r"])
def test_invalid_command_never_reaches_usb(monkeypatch, command):
    port = FakePort([b"OK arm\n"])
    clock(monkeypatch, port)
    with pytest.raises(ValueError):
        transact(port, command)
    assert port.writes == []
    assert port.reads == 0


@pytest.mark.parametrize("command", ["halt", "rearm", "stop"])
def test_valid_ack_remains_supported(monkeypatch, command):
    port = FakePort([f"OK {command}\n".encode()])
    clock(monkeypatch, port)
    assert transact(port, command) == f"OK {command}"
    assert port.writes == [f"{command}\n".encode()]


@pytest.mark.parametrize("command, reply", [
    ("drive 10 10", b"OK drive left=10 right=10 ms=100\n"),
    ("drive 10 10 100", b"OK drive left=9 right=10 ms=100\n"),
    ("drive 10 10 100", b"OK drive left=10 right=9 ms=100\n"),
    ("drive 10 10 100", b"OK drive\n"),
    ("lift 95", b"OK lift angle=96\n"),
    ("grip 95", b"OK grip angle=94\n"),
])
def test_wrong_motion_ack_is_not_success(monkeypatch, command, reply):
    port = FakePort([reply])
    clock(monkeypatch, port)
    receipt = {}
    with pytest.raises(TimeoutError, match="Uncertain USB response"):
        transact(port, command, receipt=receipt)
    assert port.writes == [(command + "\n").encode("ascii")]
    assert receipt == {}


@pytest.mark.parametrize("port", ["/dev/null", "/dev/../tmp/ttyUSB0", "/tmp/ttyUSB0"])
def test_invalid_cli_port_never_opens_serial(monkeypatch, port):
    monkeypatch.setitem(
        transact.__globals__, "serial",
        SimpleNamespace(Serial=lambda *a, **kw: pytest.fail("Unexpected serial open")),
    )
    monkeypatch.setattr(sys, "argv", ["serial_bench.py", "--port", port, "--inspect"])
    with pytest.raises(SystemExit) as exc:
        transact.__globals__["main"]()
    assert exc.value.code == 2


def test_standalone_local_rearm_recovers_without_arm_or_motion(monkeypatch, capsys):
    """Standalone `--command rearm --local-rearm` never calls arm/drive/lift/grip/keepalive."""
    import json as _json

    valid_status = {
        "backend": "stepper_28byj48",
        "armed": False,
        "safety": {"ready": True, "fault": None},
        "touch": {"active": False},
        "ranges": {
            "present_mask": 31,
            "valid_mask": 31,
            "mm": [100, 100, 100, 100, 400],
            "age_ms": [10, 10, 10, 10, 10],
        },
        "extras": {
            "mask": 0, "bumper": False, "reed": False, "pir": False,
            "bumps": 0, "reed_count": 0, "pir_count": 0,
        },
    }
    sent = []

    class RecoveryPort:
        def __init__(self, replies):
            self._replies = iter(replies)
            self.now = 0.0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def reset_input_buffer(self):
            pass

        def write(self, data):
            sent.append(data.decode("ascii").strip())
            return len(data)

        def readline(self, size):
            self.now += 0.01
            return next(self._replies, b"")

        def read_until(self, expected=b"\n", size=None):
            return self.readline(size or 1920)

    fake_clock = SimpleNamespace(monotonic=lambda: port.now, sleep=lambda _s: None)
    status_line = (_json.dumps(valid_status) + "\n").encode("ascii")

    # 1. Requires explicit --local-rearm flag.
    monkeypatch.setattr(sys, "argv", [
        "serial_bench.py", "--port", "/dev/ttyUSB0", "--command", "rearm",
    ])
    with pytest.raises(SystemExit) as exc:
        transact.__globals__["main"]()
    assert exc.value.code == 2

    # 2. Clean recovery: pre-status -> rearm -> post-status; zero actuation commands.
    sent.clear()
    port = RecoveryPort([status_line, b"OK rearm\n", status_line])
    monkeypatch.setitem(transact.__globals__, "require_local_serial_device", lambda _p: None)
    monkeypatch.setitem(transact.__globals__, "serial", SimpleNamespace(Serial=lambda *a, **kw: port))
    monkeypatch.setitem(transact.__globals__, "time", fake_clock)
    monkeypatch.setattr(sys, "argv", [
        "serial_bench.py", "--port", "/dev/ttyUSB0", "--command", "rearm", "--local-rearm",
    ])
    transact.__globals__["main"]()
    assert sent == ["status", "rearm", "status"]
    assert not any(
        cmd.startswith(("arm", "drive", "lift", "grip", "keepalive"))
        for cmd in sent
    )
    receipt = _json.loads(capsys.readouterr().out)
    assert receipt["rearm_acknowledged"] is True
    assert receipt["armed"] is False
    assert receipt["requires_independent_permit_for_motion"] is True
    assert receipt["physical_qualification_pass"] is False

    # 3. ERR reply on rearm raises without any actuation.
    sent.clear()
    port = RecoveryPort([status_line, b"ERR rearm_blocked\n"])
    monkeypatch.setitem(transact.__globals__, "serial", SimpleNamespace(Serial=lambda *a, **kw: port))
    with pytest.raises(RuntimeError, match="ERR rearm_blocked"):
        transact.__globals__["main"]()
    assert sent == ["status", "rearm"]

    # 4. Timeout during rearm raises without any actuation.
    sent.clear()

    class SlowTimeoutPort(RecoveryPort):
        def readline(self, size):
            chunk = next(self._replies, b"")
            self.now += 0.01 if chunk else 0.6
            return chunk

    slow_port = SlowTimeoutPort([status_line])
    monkeypatch.setitem(
        transact.__globals__, "time",
        SimpleNamespace(monotonic=lambda: slow_port.now, sleep=lambda _s: None),
    )
    monkeypatch.setitem(transact.__globals__, "serial", SimpleNamespace(Serial=lambda *a, **kw: slow_port))
    with pytest.raises(TimeoutError, match="Uncertain USB response"):
        transact.__globals__["main"]()
    assert sent == ["status", "rearm"]

    # 5. Unqualified pre-status (e.g. touch active) refuses rearm before sending rearm.
    sent.clear()
    active_touch_status = {**valid_status, "touch": {"active": True}}
    active_touch_line = (_json.dumps(active_touch_status) + "\n").encode("ascii")
    port = RecoveryPort([active_touch_line])
    monkeypatch.setitem(transact.__globals__, "time", fake_clock)
    monkeypatch.setitem(transact.__globals__, "serial", SimpleNamespace(Serial=lambda *a, **kw: port))
    with pytest.raises(RuntimeError, match="Unqualified touch/range state"):
        transact.__globals__["main"]()
    assert sent == ["status"]
