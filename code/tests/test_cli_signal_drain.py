import re
import signal
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest


def test_cli_serve_bounds_request_drain_before_runtime_cleanup(monkeypatch):
    import uvicorn
    from desk_robot import api, cli

    settings = SimpleNamespace(mode="hardware")
    app = object()
    calls = []
    monkeypatch.setattr(cli, "load_settings", lambda path: settings)
    monkeypatch.setattr(cli, "load_env", lambda path: None)
    monkeypatch.setattr(api, "create_app", lambda config: app)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(sys, "argv", ["desk-robot", "serve"])

    cli.main()

    assert calls == [((app,), {
        "host": "127.0.0.1", "port": 8765, "timeout_graceful_shutdown": 1,
    })]


# Use the actual CLI and Uvicorn signal handlers, but never construct hardware.
_SIGNAL_CHILD = '''
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from desk_robot import api, cli

trace = Path(sys.argv[1])
def record(event):
    with trace.open("a") as stream:
        stream.write(event + "\\n")

async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        assert (await receive())["type"] == "lifespan.startup"
        await send({"type": "lifespan.startup.complete"})
        assert (await receive())["type"] == "lifespan.shutdown"
        record("cleanup")
        await send({"type": "lifespan.shutdown.complete"})
    elif scope["type"] == "http":
        record("request")
        try:
            await asyncio.Event().wait()
        finally:
            record("cancelled")

cli.load_settings = lambda path: SimpleNamespace(mode="hardware")
cli.load_env = lambda path: None
api.create_app = lambda settings: app
sys.argv = ["desk-robot", "serve", "--port", "0"]
cli.main()
'''


def _wait_for_child(predicate, process, log, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process.poll() is None:
        if result := predicate():
            return result
        time.sleep(0.02)
    pytest.fail(f"Child did not reach expected state: {log.read_text()}")


def test_cli_sigint_cancels_pending_request_and_runs_lifespan(tmp_path):
    trace = tmp_path / "trace"
    log = tmp_path / "server.log"
    with log.open("wb") as output, subprocess.Popen(
        [sys.executable, "-c", _SIGNAL_CHILD, str(trace)],
        stdin=subprocess.DEVNULL, stdout=output, stderr=output,
    ) as process:
        try:
            port = _wait_for_child(
                lambda: re.search(r"Uvicorn running on http://127\.0\.0\.1:(\d+)",
                                  log.read_text()), process, log,
            )
            with socket.create_connection(("127.0.0.1", int(port.group(1))), timeout=3) as conn:
                conn.sendall(b"GET /blocked HTTP/1.1\r\nHost: localhost\r\n\r\n")
                _wait_for_child(lambda: trace.exists() and trace.read_text() == "request\n",
                                process, log)
                process.send_signal(signal.SIGINT)
                code = process.wait(timeout=6)
                assert code in (0, -signal.SIGINT, 128 + signal.SIGINT)
            assert trace.read_text().splitlines() == ["request", "cancelled", "cleanup"]
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
