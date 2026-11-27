"""Regressions for Wave 2 runtime, API receipt, signal, pet, memory, and controller fixes."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib.util
import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import time
import types
from contextlib import ExitStack
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

import pytest
from desk_robot import api as api_module
from desk_robot.api import create_app
from desk_robot.cli import _doctor_report, _run_uvicorn_server
from desk_robot.config import load_settings
from desk_robot.controller import Coordinator, OperationError
from desk_robot.memory import MemoryStore
from desk_robot.multimodal import CameraFrameHub
from desk_robot.pet import PeerBatchResult, PetController, PetState
from desk_robot.private_files import validate_private_directory_ancestry
from desk_robot.room_station import RoomObservation
from desk_robot.runtime import Runtime
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
CODE = ROOT / "code"
TOOLS_PATH = CODE / "laptop/server/overlay/desk_robot_tools.py"


def _signed_headers(
    token: str,
    *,
    robot_id: str,
    device_id: str,
    generation: int,
    method: str,
    path: str,
    receipt_id: str,
    issued_us: int,
) -> dict[str, str]:
    message = json.dumps(
        [1, robot_id, device_id, generation, method.upper(), path, issued_us, receipt_id],
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return {
        "X-Desk-Robot-Tool-Receipt": "1",
        "X-Desk-Robot-Tool-Receipt-Id": receipt_id,
        "X-Desk-Robot-Tool-Receipt-At-Us": str(issued_us),
        "X-Desk-Robot-Tool-Receipt-Device": device_id,
        "X-Desk-Robot-Tool-Receipt-Generation": str(generation),
        "X-Desk-Robot-Tool-Receipt-Signature": hmac.new(
            token.encode("utf-8"), message, hashlib.sha256,
        ).hexdigest(),
    }


def _receipt_app_setup(settings, monkeypatch, *, clock=None):
    settings.mode = "hardware"
    robot_id = settings.robots[0].id
    settings.robots[0].device_id = "mac-01"
    speech_token = "s" * 40
    monkeypatch.setenv("DESK_ROBOT_SPEECH_TOKEN", speech_token)
    hub = CameraFrameHub([robot.id for robot in settings.robots])
    visual = SimpleNamespace(
        _turn_epoch={robot.id: 3 for robot in settings.robots},
        hub=hub,
    )

    class Head:
        def __init__(self):
            self.status_calls = 0

        async def status(self):
            self.status_calls += 1
            return {
                "robot_id": robot_id,
                "backend": "reported_head",
                "armed": False,
                "safety": {"fault": "none"},
            }

    head = Head()

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(
            robot=lambda rid: settings.robot(rid),
            heads={robot_id: head},
        ),
        multimodal=visual,
        _voice_turn_generations={robot_id: 7},
        voice_events=SimpleNamespace(monitor_ready=True, _event_generation=11),
        pet=SimpleNamespace(voice_monitor_ready=True),
        start=noop,
        close=noop,
    )
    if clock is not None:
        monkeypatch.setattr(api_module.time, "monotonic", clock.monotonic)
        monkeypatch.setattr(api_module.time, "monotonic_ns", clock.monotonic_ns)
        monkeypatch.setattr(api_module.time, "time_ns", clock.time_ns)
    return create_app(settings, runtime=runtime), robot_id, speech_token, hub, head


def test_room_context_outage_resets_after_recovery(settings, caplog):
    """First failure of a new outage logs even <10s after recovery."""
    rt = Runtime(settings)
    rt.settings.room_station_context_enabled = True
    grant = rt.settings.room_station_consent_generation
    assert grant is not None
    calls = 0

    def flaky_consumer(_obs, *, epoch=None, grant_generation=None):
        nonlocal calls
        calls += 1
        if calls in (1, 2, 4):
            raise RuntimeError("transient consumer fault")

    rt._on_room_observation = flaky_consumer
    obs = RoomObservation(
        seq=1,
        at_ms=100,
        received_at=1.0,
        readings={},
        summary="Room station idle",
    )

    def deliver(conn_epoch: int = 0) -> None:
        rt._room_dispatch_pending = (obs, grant, True, conn_epoch)
        rt._room_dispatch_enqueued = True
        rt._deliver_room_observation()

    with caplog.at_level(logging.ERROR):
        deliver()  # fail #1 -> logged
        deliver()  # fail #2 (<10s) -> suppressed
        deliver()  # success -> clears outage state
        deliver()  # fail #4 (<10s) -> new outage -> logged!

    errors = [rec.getMessage() for rec in caplog.records if rec.levelno == logging.ERROR]
    assert len(errors) == 2
    assert "(1 total)" in errors[0]
    assert "(3 total)" in errors[1]
    assert rt.room_context_failures == 3


def test_tool_receipt_replay_capacity_fails_closed_without_eviction(
    settings, tokens, monkeypatch,
):
    """Filling the replay map fails closed and still rejects earlier unexpired IDs."""
    class Clock:
        def __init__(self):
            self.mono_ns = 100_000_000_000

        def monotonic(self) -> float:
            return self.mono_ns / 1_000_000_000

        def monotonic_ns(self) -> int:
            return self.mono_ns

        def time_ns(self) -> int:
            return 1_700_000_000_000_000_000

    clock = Clock()
    monkeypatch.setattr(api_module, "_TOOL_RECEIPT_MAX_REPLAY_ENTRIES", 2)
    app, robot_id, speech_token, _hub, head = _receipt_app_setup(
        settings, monkeypatch, clock=clock,
    )
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    url = f"/v1/robots/{robot_id}/status"
    with TestClient(app) as client:
        for i, rid in enumerate(("a" * 32, "b" * 32), start=1):
            hdrs = _signed_headers(
                speech_token,
                robot_id=robot_id,
                device_id="mac-01",
                generation=7,
                method="GET",
                path=url,
                receipt_id=rid,
                issued_us=clock.monotonic_ns() // 1000,
            )
            assert client.get(url, headers={**tool, **hdrs}).status_code == 200
            assert head.status_calls == i

        # 3rd unique receipt in the same window must fail closed (map at cap=2).
        third = _signed_headers(
            speech_token,
            robot_id=robot_id,
            device_id="mac-01",
            generation=7,
            method="GET",
            path=url,
            receipt_id="c" * 32,
            issued_us=clock.monotonic_ns() // 1000,
        )
        assert client.get(url, headers={**tool, **third}).status_code == 409
        # Replaying the first receipt must ALSO still be rejected (no LRU eviction).
        replay_first = _signed_headers(
            speech_token,
            robot_id=robot_id,
            device_id="mac-01",
            generation=7,
            method="GET",
            path=url,
            receipt_id="a" * 32,
            issued_us=clock.monotonic_ns() // 1000,
        )
        assert client.get(url, headers={**tool, **replay_first}).status_code == 409
        assert head.status_calls == 2


def test_tool_receipt_uses_monotonic_clock_immune_to_wall_steps(
    settings, tokens, monkeypatch,
):
    """Wall-clock forward/backward jumps neither break fresh receipts nor revive expired ones."""
    class Clock:
        def __init__(self):
            self.mono_ns = 50_000_000_000
            self.wall_ns = 1_700_000_000_000_000_000

        def monotonic(self) -> float:
            return self.mono_ns / 1_000_000_000

        def monotonic_ns(self) -> int:
            return self.mono_ns

        def time_ns(self) -> int:
            return self.wall_ns

    clock = Clock()
    app, robot_id, speech_token, _hub, head = _receipt_app_setup(
        settings, monkeypatch, clock=clock,
    )
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    url = f"/v1/robots/{robot_id}/status"

    # Load desk_robot_tools helper with stub bridge/plugins dependencies to verify signer clock.
    bridge_stub = types.ModuleType("desk_robot_bridge")
    bridge_stub.connections = {}
    bridge_stub.robot_for_device = lambda _d: "robot-01"
    plugins_pkg = types.ModuleType("plugins_func")
    plugins_reg = types.ModuleType("plugins_func.register")
    plugins_reg.Action = SimpleNamespace(REQLLM=3, NONE=1)
    plugins_reg.ActionResponse = SimpleNamespace
    plugins_reg.ToolType = SimpleNamespace(IOT_CTL=5)
    plugins_reg.register_function = lambda *a, **kw: (lambda fn: fn)
    monkeypatch.setitem(sys.modules, "desk_robot_bridge", bridge_stub)
    monkeypatch.setitem(sys.modules, "plugins_func", plugins_pkg)
    monkeypatch.setitem(sys.modules, "plugins_func.register", plugins_reg)
    spec = importlib.util.spec_from_file_location("test_tools_clock", TOOLS_PATH)
    assert spec and spec.loader
    tools_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tools_mod)
    monkeypatch.setattr(tools_mod.time, "monotonic_ns", clock.monotonic_ns)
    monkeypatch.setattr(tools_mod.time, "time_ns", clock.time_ns)

    with TestClient(app) as client:
        # 1. Large forward wall-clock step between issue and verify still succeeds.
        hdrs1 = tools_mod._receipt_headers(
            speech_token, robot_id, "mac-01", 7, "GET", url,
        )
        clock.wall_ns += 3_600_000_000_000  # +1 hour NTP step
        clock.mono_ns += 100_000_000        # +0.1s monotonic
        assert client.get(url, headers={**tool, **hdrs1}).status_code == 200
        assert head.status_calls == 1

        # 2. After 10s replay TTL expires, a backward wall-clock jump CANNOT revive hdrs1.
        clock.mono_ns += 11_000_000_000     # +11s monotonic (replay entry expired)
        clock.wall_ns -= 7_200_000_000_000  # -2 hour NTP step backward
        assert client.get(url, headers={**tool, **hdrs1}).status_code == 409
        assert head.status_calls == 1

        # 3. Future monotonic stamp fails closed even after wall backward step.
        future = _signed_headers(
            speech_token,
            robot_id=robot_id,
            device_id="mac-01",
            generation=7,
            method="GET",
            path=url,
            receipt_id="f" * 32,
            issued_us=clock.monotonic_ns() // 1000 + 1_000_000,
        )
        assert client.get(url, headers={**tool, **future}).status_code == 409
        assert head.status_calls == 1


def test_cli_run_uvicorn_registers_and_restores_sighup(monkeypatch):
    """Unit check: _run_uvicorn_server wires SIGHUP to server.handle_exit and restores it."""
    if not hasattr(signal, "SIGHUP"):
        pytest.skip("SIGHUP not available on this platform")
    registered: dict[int, object] = {}
    calls: list[str] = []

    class FakeServer:
        def __init__(self, config):
            self.config = config

        def handle_exit(self, _sig, _frame):
            calls.append("handle_exit")

        def run(self):
            handler = signal.getsignal(signal.SIGHUP)
            registered["inside"] = handler
            assert callable(handler)
            handler(signal.SIGHUP, None)

    monkeypatch.setattr("uvicorn.Config", lambda app, **kw: SimpleNamespace(app=app, **kw))
    monkeypatch.setattr("uvicorn.Server", FakeServer)
    before = signal.getsignal(signal.SIGHUP)
    _run_uvicorn_server(object(), host="127.0.0.1", port=0)
    after = signal.getsignal(signal.SIGHUP)
    assert calls == ["handle_exit"]
    assert after == before


def test_cli_serve_sighup_runs_lifespan_shutdown_in_subprocess(tmp_path):
    """Subprocess SIGHUP check: FastAPI lifespan teardown completes instead of abrupt death."""
    if not hasattr(signal, "SIGHUP"):
        pytest.skip("SIGHUP not available on this platform")
    marker = tmp_path / "shutdown_marker.txt"
    ready_file = tmp_path / "ready.txt"
    script = tmp_path / "run_sighup_server.py"
    script.write_text(
        f"""
import contextlib
import pathlib
import uvicorn
from fastapi import FastAPI
from desk_robot.cli import _run_uvicorn_server

marker = pathlib.Path({str(marker)!r})
ready = pathlib.Path({str(ready_file)!r})

@contextlib.asynccontextmanager
async def lifespan(_app):
    ready.write_text("ready", encoding="utf-8")
    try:
        yield
    finally:
        marker.write_text("lifespan_clean_shutdown", encoding="utf-8")

app = FastAPI(lifespan=lifespan)
_run_uvicorn_server(app, host="127.0.0.1", port=0)
""",
        encoding="utf-8",
    )
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        env={**os.environ, "PYTHONPATH": str(CODE / "laptop/src")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10.0
        while not ready_file.exists() and time.monotonic() < deadline:
            assert proc.poll() is None, proc.stderr.read()
            time.sleep(0.05)
        assert ready_file.exists(), "Subprocess test server failed to become ready"
        os.kill(proc.pid, signal.SIGHUP)
        rc = proc.wait(timeout=10.0)
        assert rc == 0, f"Unexpected exit code {rc}: {proc.stderr.read()}"
        assert marker.read_text(encoding="utf-8") == "lifespan_clean_shutdown"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5.0)


def test_pet_typing_annotations_and_nfc_impossible_forward_jump(settings, tmp_path):
    """Verify explicit Pet annotations and NFC fence quarantine on impossible event jumps."""
    annotations = {f.name: f.type for f in fields(PetState)}
    assert "asyncio.Task[dict[str, Any]]" in str(annotations["aux_read_task"])
    assert PeerBatchResult == (bool | BaseException)

    settings.mode = "hardware"
    settings.robots[0].nfc_interactions_qualified = True
    rid = settings.robots[0].id
    mem = MemoryStore(tmp_path / "memory", [r.id for r in settings.robots])
    pet = PetController(
        settings,
        {rid: SimpleNamespace()},
        SimpleNamespace(active=None),
        mem,
        SimpleNamespace(),
    )
    state = pet.states[rid]
    state.enabled, state.generation = True, 14

    def aux_report(events: int, token: int, *, seq: int) -> dict[str, object]:
        return {
            "robot_id": rid,
            "pulse": {
                "present": False, "valid": False, "part_id": 0,
                "red": 0, "ir": 0, "age_ms": 0, "bpm": None, "medical": False,
            },
            "angles": {
                "raw": [0, 0, 0], "present_mask": 0,
                "valid_mask": 0, "magnet": [0, 0, 0],
            },
            "force": {
                "adc": [0, 0], "jaw_seq": 0,
                "valid": False, "calibrated": False, "boot_id": 5,
            },
            "climate": {"temp_centi": 0, "rh_centi": 0, "valid": False},
            "power": {
                "cell_mv": 0, "soc_centi": 0, "bus_mv": 0,
                "shunt_uv": 0, "fuel_valid": False,
                "monitor_valid": False, "current_calibrated": False,
            },
            "proximity": {
                "raw": 0, "valid": False, "gesture": 0,
                "gesture_events": 0, "physically_qualified": False, "boot_id": 5,
            },
            "nfc": {"v": True, "t": token, "e": events, "s": seq},
        }

    async def exercise():
        try:
            await pet._observe_aux(rid, state.generation, aux_report(20, 0, seq=100))
            assert (state.last_nfc_scan_seq, state.last_nfc_events) == (100, 20)

            # Impossible jump: scan advanced by 1, event jumped by 4 -> quarantine both fences.
            changes_before = mem.count(rid)
            await pet._observe_aux(rid, state.generation, aux_report(24, 0x12345678, seq=101))
            assert (state.last_nfc_scan_seq, state.last_nfc_events) == (100, 20)
            assert mem.count(rid) == changes_before

            # Normal unchanged scan advances scan fence cleanly without bogus emission.
            await pet._observe_aux(rid, state.generation, aux_report(20, 0, seq=102))
            assert (state.last_nfc_scan_seq, state.last_nfc_events) == (102, 20)
            assert mem.count(rid) == changes_before

            # Truthful next arrival emits once and advances fences.
            await pet._observe_aux(rid, state.generation, aux_report(21, 0x12345678, seq=103))
            assert (state.last_nfc_scan_seq, state.last_nfc_events) == (103, 21)
            assert mem.count(rid) == changes_before + 1
        finally:
            await pet.close()

    asyncio.run(exercise())


def test_memory_check_to_open_directory_swap_fails_closed(tmp_path, monkeypatch):
    """A root swap between validation and sqlite3.connect must fail before any query."""
    orig_dir = tmp_path / "memory"
    orig_dir.mkdir(mode=0o700)
    swap_dir = tmp_path / "swapped"
    swap_dir.mkdir(mode=0o700)
    store = MemoryStore(orig_dir, ["robot-01"])
    store.remember(
        "robot-01", "evt-1", "real eyewitness",
        kind="object", source_robot="robot-01", witnessed=True,
    )

    # Pre-seed an evil DB in swap_dir with valid identity so ONLY our inode guard catches it.
    evil_store = MemoryStore(swap_dir, ["robot-01"])
    evil_store.remember(
        "robot-01", "evt-evil", "poisoned swap",
        kind="object", source_robot="robot-01", witnessed=True,
    )

    real_connect = sqlite3.connect
    executed_on_swapped = False

    def racing_connect(database, *args, **kwargs):
        # Swap orig_dir -> swap_dir right before SQLite opens the URI path.
        tmp_hold = tmp_path / "old_orig"
        orig_dir.rename(tmp_hold)
        swap_dir.rename(orig_dir)
        conn = real_connect(database, *args, **kwargs)
        # Ensure caller never runs a single SQL query against the swapped handle.
        orig_execute = conn.execute

        class GuardedConn:
            def __getattr__(self, name):
                if name == "execute":
                    def checked_execute(*a, **kw):
                        nonlocal executed_on_swapped
                        executed_on_swapped = True
                        return orig_execute(*a, **kw)

                    return checked_execute
                return getattr(conn, name)

        return GuardedConn()

    monkeypatch.setattr("desk_robot.memory.sqlite3.connect", racing_connect)
    with pytest.raises(PermissionError, match="changed during SQLite open"):
        store.count("robot-01")
    assert executed_on_swapped is False


def test_validate_private_directory_ancestry_rejects_unsticky_world_writable(tmp_path):
    """Non-sticky 0o777 ancestor directories are rejected."""
    open_parent = tmp_path / "open_parent"
    open_parent.mkdir()
    os.chmod(open_parent, 0o777)
    try:
        if os.stat(open_parent).st_mode & 0o002:
            with pytest.raises(PermissionError, match="non-sticky world-writable"):
                validate_private_directory_ancestry(open_parent / "memory")
    finally:
        os.chmod(open_parent, 0o700)


def test_controller_repeated_cancel_during_halt_retains_owner_until_recovery(settings):
    """Double cancellation during blocked HALT retains fleet owner until explicit recovery STOP."""
    robot_id = settings.robots[0].id
    settings.robots[0].motion_enabled = True
    halt_entered = asyncio.Event()
    halt_release = asyncio.Event()
    halt_calls = 0

    class Head:
        async def status(self):
            return {
                "robot_id": robot_id,
                "armed": False,
                "safety": {"fault": "none", "cliff_clear": True},
            }

        async def command(self, cmd: str):
            nonlocal halt_calls
            if cmd == "halt":
                halt_calls += 1
                if halt_calls == 1:
                    halt_entered.set()
                    await halt_release.wait()
                return {"ok": True, "robot_id": robot_id, "reply": "OK halt"}
            if cmd == "arm":
                return {"ok": True, "robot_id": robot_id, "reply": "OK arm"}
            if cmd == "keepalive":
                return {"ok": True, "robot_id": robot_id, "reply": "OK keepalive"}
            return {"ok": True, "robot_id": robot_id, "reply": f"OK {cmd}"}

    async def scenario():
        ctrl = Coordinator(settings, {robot_id: Head()}, None)
        ctrl.permits[robot_id] = time.monotonic() + 5.0
        work_started = asyncio.Event()

        async def long_work(_job):
            work_started.set()
            await asyncio.Event().wait()
            return {"ok": True}

        job = ctrl._submit(robot_id, "manual", long_work)
        task = ctrl.tasks[job.id]
        await asyncio.wait_for(work_started.wait(), timeout=2.0)

        # First cancellation enters finally -> blocks inside _bounded_body_stop("halt").
        task.cancel()
        await asyncio.wait_for(halt_entered.wait(), timeout=2.0)

        # Second cancellation arrives while HALT is still blocked!
        task.cancel()
        await asyncio.wait_for(task, timeout=4.0)

        assert job.state == "failed"
        assert not any("stop acknowledged" in ev for ev in job.events)
        assert ctrl._fleet_motion_owner == job.id
        assert job.id in ctrl._motion_children
        # New motion must still be blocked while previous owner STOP is unconfirmed.
        ctrl.permits[robot_id] = time.monotonic() + 5.0
        with pytest.raises(OperationError):
            ctrl.manual(robot_id, "drive 20 20 100")

        # Now release blocked transport and issue explicit recovery STOP.
        halt_release.set()
        receipt = await ctrl.stop(robot_id)
        assert receipt["reply"] == "OK halt"
        assert ctrl._fleet_motion_owner is None
        assert job.id not in ctrl._motion_children

    asyncio.run(scenario())


def test_trials_file_wired_into_doctor_and_check_trials(tmp_path):
    """settings.trials_file points to CSV and feeds both doctor and check_trials --config."""
    loaded = load_settings(CODE / "config/robots.example.toml")
    assert loaded.trials_file.name == "physical-trials.csv"
    assert loaded.trials_file.is_file()

    with ExitStack():
        report = _doctor_report(
            SimpleNamespace(live=False, look=None, robot=None, url="http://127.0.0.1:8765"),
            loaded,
        )
    assert report["trials_file"] == str(loaded.trials_file)
    assert report["trials_file_present"] is True

    proc = subprocess.run(
        [
            sys.executable,
            str(CODE / "scripts/check_trials.py"),
            "--config",
            str(CODE / "config/robots.example.toml"),
        ],
        cwd=str(CODE),
        env={**os.environ, "PYTHONPATH": str(CODE / "laptop/src")},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["physical_trial_count"] == 0
    assert payload["evidence_status"] == "HOLD"
