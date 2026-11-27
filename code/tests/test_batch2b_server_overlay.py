"""Batch 2B regression tests for Xiaozhi server overlay and installer parity."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
import types
from pathlib import Path
from queue import Queue
from types import ModuleType, SimpleNamespace

import httpx
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def native(monkeypatch):
    fake_bridge = SimpleNamespace(
        connections={},
        robot_for_device=lambda dev: "robot-01" if dev == "mac-01" else None,
        lease_stopping=False,
        lease_ids=frozenset(),
        lease_until=0.0,
        speaker_lock=asyncio.Lock(),
        human_speech_active=lambda: False,
    )
    monkeypatch.setitem(sys.modules, "desk_robot_bridge", fake_bridge)
    monkeypatch.syspath_prepend(str(ROOT / "laptop/server/overlay"))
    spec = importlib.util.spec_from_file_location(
        "desk_robot_native_omni",
        ROOT / "laptop/server/overlay/desk_robot_native_omni.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "desk_robot_native_omni", module)
    spec.loader.exec_module(module)
    return module, fake_bridge


@pytest.fixture
def bridge_only(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "test_desk_bridge_b2b",
        ROOT / "laptop/server/overlay/desk_robot_bridge.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, "desk_robot_bridge", module)
    monkeypatch.setenv("DESK_ROBOT_SPEECH_TOKEN", "s" * 40)
    monkeypatch.setenv(
        "DESK_ROBOT_DEVICE_MAP", json.dumps({"robot-01": "mac-01"})
    )
    core = types.ModuleType("core")
    core.__path__ = []
    utils = types.ModuleType("core.utils")
    utils.__path__ = []
    dialogue = types.ModuleType("core.utils.dialogue")
    dialogue.Message = lambda role, content=None, **kw: SimpleNamespace(
        role=role, content=content, **kw
    )
    for name, stub in (
        ("core", core),
        ("core.utils", utils),
        ("core.utils.dialogue", dialogue),
    ):
        monkeypatch.setitem(sys.modules, name, stub)
    return module


@pytest.fixture
def bridge_tools(monkeypatch):
    bridge = ModuleType("desk_robot_bridge")
    bridge.robot_for_device = (
        lambda device: "robot-01" if device == "mac-head-01" else None
    )
    registered = SimpleNamespace(device_id="mac-head-01")
    bridge.connections = {"mac-head-01": registered}
    registry = ModuleType("plugins_func.register")
    registry.Action = SimpleNamespace(REQLLM=3, NONE=1)
    registry.ToolType = SimpleNamespace(IOT_CTL=5)
    registry.ActionResponse = lambda action, result=None, response=None: SimpleNamespace(
        action=action, result=result, response=response
    )
    registry.register_function = lambda *args, **kwargs: lambda fn: fn
    monkeypatch.setitem(sys.modules, "desk_robot_bridge", bridge)
    monkeypatch.setitem(sys.modules, "plugins_func", ModuleType("plugins_func"))
    monkeypatch.setitem(sys.modules, "plugins_func.register", registry)
    spec = importlib.util.spec_from_file_location(
        "desk_tools_b2b",
        ROOT / "laptop/server/overlay/desk_robot_tools.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("DESK_ROBOT_TOOL_TOKEN", "s" * 40)
    monkeypatch.setenv("DESK_ROBOT_SPEECH_TOKEN", "r" * 40)
    module.registered_head = registered
    return module


def _make_conn(device="mac-01"):
    sent = []

    async def ws_send(payload):
        sent.append(payload)

    conn = SimpleNamespace(
        device_id=device,
        session_id=f"sess-{device}",
        client_listen_mode="realtime",
        conn_from_mqtt_gateway=False,
        client_is_speaking=False,
        client_abort=False,
        calling=False,
        device_aec_measured=True,
        last_activity_time=0.0,
        tts=SimpleNamespace(tts_text_queue=Queue(), tts_audio_queue=Queue()),
        websocket=SimpleNamespace(send=ws_send),
    )
    return conn, sent


@pytest.mark.parametrize(
    "case,expected_invalidated",
    [
        ("active_direct", False),
        ("pending_direct", False),
        ("unsolicited", True),
        ("expired_direct", True),
        ("monitor_loss", True),
    ],
)
async def test_quiet_transition_preserves_direct_reply_but_cancels_autonomy(
    native, monkeypatch, case, expected_invalidated,
):
    """868V7w7: quiet toggle preserves bounded direct reply; monitor loss always cancels."""
    module, fake_bridge = native
    conn, _sent = _make_conn()
    fake_bridge.connections[conn.device_id] = conn
    monkeypatch.setenv("DESK_ROBOT_TOOL_TOKEN", "t" * 32)
    monkeypatch.setenv("DESK_ROBOT_OMNI_URL", "ws://127.0.0.1:9999/v1/realtime?duplex=1")
    monkeypatch.setenv("DESK_ROBOT_OMNI_MODEL", "openbmb/MiniCPM-o-4_5")

    context_count = 0
    ctx_done = asyncio.Event()

    async def handle_ctx(_request):
        nonlocal context_count
        context_count += 1
        body = {
            "robot_id": "robot-01",
            "model_context": "desk quiet",
            "active_activity": "",
            "persistent_memory_included": False,
            "raw_media_included": False,
            "model_context_untrusted_not_instructions": True,
            "memory_tools_enabled": False,
            "transcript_memory_enabled": False,
            "pet_quiet": True,
            "pet_autonomy_enabled": False,
            "voice_monitor_ready": case != "monitor_loss",
        }
        ctx_done.set()
        return web.json_response(body)

    app = web.Application()
    app.router.add_get("/v1/pet/robot-01/interaction-context", handle_ctx)
    async with TestServer(app) as server:
        monkeypatch.setattr(
            module,
            "_pet_coordinator_url",
            lambda _robot, ep: str(server.make_url(f"/v1/pet/robot-01/{ep}")),
        )
        session = module.NativeOmniSession(
            conn, url="ws://127.0.0.1:9999/v1/realtime?duplex=1",
            model="openbmb/MiniCPM-o-4_5", token="t" * 32,
        )
        session.connected = True
        session._live_transcript_enabled = True
        session._pet_quiet = False
        session._pet_autonomy_enabled = True
        now = time.monotonic()
        session._context_last_sync_at = now - 5.0
        session._last_authenticated_mac_at = now - 2.0
        if case == "active_direct":
            session._direct_reply_active = True
            session._last_human_speech_at = now
        elif case == "pending_direct":
            session._direct_reply_available = True
            session._last_human_speech_at = now
        elif case == "expired_direct":
            session._direct_reply_available = True
            session._last_human_speech_at = now - 20.0
        else:
            session._direct_reply_active = case == "monitor_loss"
            session._last_human_speech_at = now - 20.0

        invalidated = []

        async def track_invalidate(*, force_flush=False):
            invalidated.append(force_flush)
            session._direct_reply_active = False
            session._direct_reply_available = False
            return ()

        session._invalidate_head_first = track_invalidate
        session._schedule_remote_cancel = lambda _events: None
        session._context_wakeup.set()

        import aiohttp
        async with aiohttp.ClientSession() as http:
            task = asyncio.create_task(session._refresh_live_context(http))
            await asyncio.wait_for(ctx_done.wait(), timeout=1.0)
            await asyncio.sleep(0.05)
            session.closed = True
            session._context_wakeup.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        assert context_count >= 1
        assert bool(invalidated) is expected_invalidated


async def test_response_replacement_stop_carries_flush_and_blocks_old_i2s(
    native, monkeypatch,
):
    """868mx6o: response-replacement STOP includes flush=true and clears old playback."""
    module, fake_bridge = native
    conn, sent = _make_conn()
    fake_bridge.connections[conn.device_id] = conn
    monkeypatch.setenv("DESK_ROBOT_TOOL_TOKEN", "t" * 32)
    monkeypatch.setattr(
        module.opuslib_next if hasattr(module, "opuslib_next") else module,
        "Encoder",
        SimpleNamespace,
        raising=False,
    )

    class Encoder:
        def __init__(self, *_a):
            pass

        def encode(self, *_a):
            return b"opus"

    monkeypatch.setitem(
        sys.modules,
        "opuslib_next",
        SimpleNamespace(Encoder=Encoder, APPLICATION_AUDIO="audio"),
    )

    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:9999/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="t" * 32,
    )
    session.connected = True
    session._mac_context_verified = True
    session._last_authenticated_mac_at = time.monotonic()
    session._pet_autonomy_enabled = True
    session.wire.response_id = "resp-1"
    pid1 = session._begin_head_playback("resp-1", session._generation)
    assert pid1 > 0
    assert session._head_playback_current(session._generation)

    conn.client_is_speaking = True
    session.wire.response_id = "resp-2"
    session.outgoing.put_nowait(("resp-1", bytes(9600)))
    session.outgoing.put_nowait(("resp-2", bytes(9600)))
    session.outgoing.put_nowait(("resp-2", None))

    worker = asyncio.create_task(session._play())
    try:
        # Let _play start resp-1 or transition straight to resp-2.
        await asyncio.sleep(0.05)
        stopped = await session._send_replacement_stop_state(session._generation)
        assert stopped is True
        stop_msgs = [
            json.loads(m) for m in sent
            if isinstance(m, str) and json.loads(m).get("state") == "stop"
        ]
        assert any(m.get("flush") is True for m in stop_msgs)
        assert not session.accept_head_i2s_progress({
            "type": "desk_robot_i2s_progress",
            "session_id": conn.session_id,
            "playback_id": pid1,
            "committed_ms": 120,
        })
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_live_opt_out_retires_session_and_confirms_stop_before_legacy(
    native, monkeypatch,
):
    """868h9Sm: removing allowlist keeps consuming frames until native STOP completes."""
    module, fake_bridge = native
    conn, sent = _make_conn()
    fake_bridge.connections[conn.device_id] = conn
    monkeypatch.setenv("DESK_ROBOT_TOOL_TOKEN", "t" * 32)
    monkeypatch.setenv("DESK_ROBOT_OMNI_URL", "ws://127.0.0.1:9999/v1/realtime?duplex=1")
    monkeypatch.setenv("DESK_ROBOT_OMNI_ROBOTS", "robot-01")
    monkeypatch.setenv("DESK_ROBOT_OMNI_MODEL", "openbmb/MiniCPM-o-4_5")

    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:9999/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="t" * 32,
    )
    conn.client_is_speaking = True
    module._sessions[conn.device_id] = session

    # Disable opt-in live: route_audio must NOT fall back to legacy False yet.
    monkeypatch.setenv("DESK_ROBOT_OMNI_ROBOTS", "")
    assert module.route_audio(conn, b"\x00" * 1920, True) is True
    assert session.closed is True
    assert module.route_audio(conn, b"\x00" * 1920, True) is True

    # Once retirement task runs and confirms STOP, legacy routing may resume.
    await asyncio.sleep(0.05)
    stop_msgs = [json.loads(m) for m in sent if isinstance(m, str)]
    assert any(m.get("state") == "stop" and m.get("flush") is True for m in stop_msgs)
    assert module.route_audio(conn, b"\x00" * 1920, True) is False


async def test_bridge_fallback_orders_urgent_stop_behind_inflight_raw_opus(
    bridge_only, monkeypatch,
):
    """868Yibt: fallback without native adapter still serializes Opus and urgent STOP."""
    conn, _sent = _make_conn()
    conn.device_aec_measured = True
    conn.client_listen_mode = "realtime"
    bridge_only.connections["mac-01"] = conn
    monkeypatch.setattr(bridge_only, "_native_adapter", lambda: None)

    entered_opus = asyncio.Event()
    release_opus = asyncio.Event()
    order = []

    async def ws_send(payload):
        if isinstance(payload, (bytes, bytearray)):
            order.append("opus_start")
            entered_opus.set()
            await release_opus.wait()
            order.append("opus_end")
        else:
            order.append("stop")

    conn.websocket = SimpleNamespace(send=ws_send)

    async def send_raw_opus():
        async with bridge_only._fallback_device_send_lock(conn.device_id):
            await conn.websocket.send(b"raw-opus")

    opus_task = asyncio.create_task(send_raw_opus())
    await asyncio.wait_for(entered_opus.wait(), timeout=1.0)
    bridge_only.lease_ids = frozenset(["mac-01"])
    bridge_only.lease_until = time.monotonic() + 5.0
    bridge_only.active_device_id = "mac-01"
    monkeypatch.setattr(bridge_only, "sustained_voice", lambda _d, _v: True)
    stop_task = asyncio.create_task(bridge_only.interrupt_for_user_voice(conn, True))
    await asyncio.sleep(0.03)
    assert order == ["opus_start"]
    release_opus.set()
    await asyncio.gather(opus_task, stop_task)
    assert order == ["opus_start", "opus_end", "stop"]


@pytest.mark.parametrize(
    "route,bad_payload",
    [
        ("stop", {"robot_id": "robot-01", "physical_stop_verified": True}),
        ("stop", {"robot_id": "robot-01", "stopped": "yes"}),
        ("pickup", {"robot_id": "robot-01", "physical_grasp_verified": True}),
        ("pickup", {"robot_id": "robot-01", "target": "coin"}),
        ("status", {"robot_id": "robot-01", "armed": "false"}),
        ("power-status", {"robot_id": "robot-01", "power": "high"}),
        ("aux-status", {"robot_id": "robot-01", "force": []}),
        ("interaction-context", {"robot_id": "robot-01", "current_interaction_timeline": "bad"}),
        ("voice-context", {"robot_id": "robot-01", "memories": ["not-a-dict"]}),
    ],
)
async def test_tools_reject_wrong_type_and_fabricated_physical_receipts(
    bridge_tools, monkeypatch, route, bad_payload,
):
    """868T2l1: reject malformed per-route tool responses and fabricated physical claims."""
    original = httpx.AsyncClient
    monkeypatch.setattr(
        bridge_tools.httpx,
        "AsyncClient",
        lambda *a, **kw: original(
            *a,
            transport=httpx.MockTransport(
                lambda _req: httpx.Response(200, json=bad_payload)
            ),
            **kw,
        ),
    )
    req_payload = {"target": "key"} if route == "pickup" else None
    result = await bridge_tools.call(bridge_tools.registered_head, route, req_payload)
    assert "error" in result and result["retried"] is False


async def test_tools_reject_oversized_response_before_json_decode(
    bridge_tools, monkeypatch,
):
    """868T2l1: HTTP 200 payload exceeding size cap is rejected before JSON decoding."""
    original = httpx.AsyncClient
    huge = json.dumps({"robot_id": "robot-01", "blob": "x" * 70000}).encode("utf-8")
    monkeypatch.setattr(
        bridge_tools.httpx,
        "AsyncClient",
        lambda *a, **kw: original(
            *a,
            transport=httpx.MockTransport(
                lambda _req: httpx.Response(200, content=huge)
            ),
            **kw,
        ),
    )
    result = await bridge_tools.call(bridge_tools.registered_head, "status")
    assert result == {
        "error": "Robot Mac tool response exceeds size limit",
        "retried": False,
    }


def test_install_overlay_generates_exact_omni_wire_parity():
    """868cq0w: generated desk_robot_omni_wire.py matches canonical source bytes."""
    import hashlib

    spec = importlib.util.spec_from_file_location(
        "server_overlay_b2b",
        ROOT / "laptop/server/install_overlay.py",
    )
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    server_root = ROOT / "upstream/xiaozhi-esp32-server/main/xiaozhi-server"
    changes = installer.files(server_root)
    canonical = (
        ROOT / "laptop/src/desk_robot/realtime_omni_protocol.py"
    ).read_bytes()
    assert "desk_robot_omni_wire.py" in changes
    generated = changes["desk_robot_omni_wire.py"].encode("utf-8")
    assert generated == canonical
    manifest_digest = hashlib.sha256(generated).hexdigest()
    assert manifest_digest == hashlib.sha256(canonical).hexdigest()
