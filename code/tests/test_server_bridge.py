import asyncio
import base64
import importlib.util
import json
import sys
import threading
import time
import wave
from io import BytesIO
from pathlib import Path
from queue import Queue
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bridge(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "test_desk_bridge", ROOT / "laptop/server/overlay/desk_robot_bridge.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("DESK_ROBOT_SPEECH_TOKEN", "s" * 40)
    monkeypatch.setenv(
        "DESK_ROBOT_DEVICE_MAP", json.dumps({"robot-01": "mac-01", "robot-02": "mac-02"})
    )
    return module


def conn(device):
    return SimpleNamespace(
        device_id=device,
        client_is_speaking=False,
        calling=False,
        tts=SimpleNamespace(tts_text_queue=Queue(), tts_audio_queue=Queue()),
        client_abort=False,
    )


def test_device_registry_and_expiring_mute(bridge):
    first, second = conn("mac-01"), conn("mac-02")
    bridge.register(first)
    with pytest.raises(RuntimeError, match="Duplicate"):
        bridge.register(conn("mac-01"))
    bridge.lease_ids = frozenset(["mac-01"])
    bridge.lease_until = time.monotonic() + 10
    assert bridge.suppress_message(first, b"microphone")
    assert not bridge.suppress_message(second, b"microphone")
    assert bridge.suppress_message(first, '{"type":"listen"}')
    assert not bridge.suppress_message(first, '{"type":"abort"}')
    assert not bridge.suppress_message(first, '{"type":"mcp"}')
    bridge.lease_until = time.monotonic() - 1
    assert not bridge.suppress_message(first, b"microphone")
    bridge.unregister(second)
    assert "mac-01" in bridge.connections
    bridge.unregister(first)
    assert not bridge.connections


def test_wav_bounded_and_real_pcm(bridge):
    with pytest.raises(ValueError):
        bridge.wav_audio("!notbase64")
    buffer = BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0" * 3200)
    encoded = base64.b64encode(buffer.getvalue()).decode()
    assert bridge.wav_audio(encoded).startswith(b"RIFF")


async def test_bridge_auth_identity_and_lease_cleanup(bridge):
    bridge.register(conn("mac-01"))
    bridge.register(conn("mac-02"))
    async with TestClient(TestServer(bridge.create_app())) as client:
        assert (await client.post("/session", json={})).status == 401
        headers = {"Authorization": "Bearer " + "s" * 40}
        request = {"device_ids": ["mac-01", "mac-02"], "enabled": True}
        assert (await client.post("/session", headers=headers, json=request)).status == 200
        assert bridge.muted("mac-01") and bridge.muted("mac-02")
        assert (await client.post("/session", headers=headers, json=request)).status == 409
        assert (
            await client.post(
                "/speak", headers=headers, json={"device_id": "wrong", "text": "hello"}
            )
        ).status == 409
        request["enabled"] = False
        assert (await client.post("/session", headers=headers, json=request)).status == 200
        assert not bridge.muted("mac-01")


def test_overlay_targets_pinned_server_and_compiles():
    spec = importlib.util.spec_from_file_location(
        "server_overlay", ROOT / "laptop/server/install_overlay.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    changes = module.files(ROOT / "upstream/xiaozhi-esp32-server/main/xiaozhi-server")
    assert len(changes) == 6
    assert "desk_robot_bridge.register(self)" in changes["core/connection.py"]
    assert "desk_robot_bridge.unregister(handler)" in changes["core/websocket_server.py"]
    for path, source in changes.items():
        compile(source, path, "exec")


def fleet_handlers(bridge, monkeypatch):
    ids = [f"mac-{index:02}" for index in range(1, 6)]
    monkeypatch.setenv(
        "DESK_ROBOT_DEVICE_MAP",
        json.dumps({f"robot-{index:02}": device for index, device in enumerate(ids, 1)}),
    )
    for device in ids:
        bridge.register(conn(device))
    app = bridge.create_app()
    handlers = {route.resource.canonical: route.handler for route in app.router.routes()}
    return ids, handlers


def body_request(body):
    async def json_body():
        return body

    return SimpleNamespace(json=json_body)


async def test_five_bridge_devices_muted_and_speech_serialized(bridge, monkeypatch):
    ids, handlers = fleet_handlers(bridge, monkeypatch)
    session = handlers["/session"]
    await session(body_request({"device_ids": ids, "enabled": True}))
    active, maximum, spoken = 0, 0, []

    async def transmit(connection, text, frames):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        assert all(bridge.muted(device) for device in ids)
        await asyncio.sleep(0.01)
        spoken.append(connection.device_id)
        active -= 1

    monkeypatch.setattr(bridge, "wav_audio", lambda encoded: b"RIFF")
    monkeypatch.setattr(bridge, "encode_opus", lambda audio: [b"opus"])
    monkeypatch.setattr(bridge, "transmit", transmit)
    await asyncio.gather(
        *(
            handlers["/speak"](
                body_request({"device_id": device, "text": "hello", "wav_base64": ""})
            )
            for device in ids
        )
    )
    assert maximum == 1 and spoken == ids
    await session(body_request({"device_ids": ids, "enabled": False}))
    assert not bridge.lease_ids and not bridge.lease_stopping
    assert all(not bridge.muted(device) for device in ids)
    assert all(connection.client_abort for connection in bridge.connections.values())


async def test_bridge_stop_rejects_queued_speech_and_unmutes_all_five(bridge, monkeypatch):
    ids, handlers = fleet_handlers(bridge, monkeypatch)
    await handlers["/session"](body_request({"device_ids": ids, "enabled": True}))
    monkeypatch.setattr(bridge, "wav_audio", lambda encoded: b"RIFF")
    await bridge.speaker_lock.acquire()
    queued = asyncio.create_task(
        handlers["/speak"](body_request({"device_id": ids[0], "text": "hello", "wav_base64": ""}))
    )
    await asyncio.sleep(0)
    stopping = asyncio.create_task(
        handlers["/session"](body_request({"device_ids": ids, "enabled": False}))
    )
    await asyncio.sleep(0)
    assert bridge.lease_stopping and all(bridge.muted(device) for device in ids)
    bridge.speaker_lock.release()
    with pytest.raises(RuntimeError, match="stopped"):
        await queued
    await stopping
    assert not bridge.lease_ids and not bridge.lease_stopping


async def test_cancelled_bridge_stop_still_completes_cleanup(bridge, monkeypatch):
    ids, handlers = fleet_handlers(bridge, monkeypatch)
    await handlers["/session"](body_request({"device_ids": ids, "enabled": True}))
    await bridge.speaker_lock.acquire()
    stopping = asyncio.create_task(
        handlers["/session"](body_request({"device_ids": ids, "enabled": False}))
    )
    await asyncio.sleep(0)
    stopping.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    assert bridge.lease_stopping and all(bridge.muted(device) for device in ids)
    bridge.speaker_lock.release()
    await bridge.lease_cleanup_task
    assert not bridge.lease_stopping and not bridge.lease_ids
    await handlers["/session"](body_request({"device_ids": ids, "enabled": True}))
    await handlers["/session"](body_request({"device_ids": ids, "enabled": False}))


@pytest.mark.parametrize("replacement", [False, True])
async def test_queued_speech_rejects_disconnected_or_replaced_head(
    bridge, monkeypatch, replacement
):
    ids, handlers = fleet_handlers(bridge, monkeypatch)
    await handlers["/session"](body_request({"device_ids": ids, "enabled": True}))
    monkeypatch.setattr(bridge, "wav_audio", lambda encoded: b"RIFF")
    await bridge.speaker_lock.acquire()
    queued = asyncio.create_task(
        handlers["/speak"](body_request({"device_id": ids[0], "text": "hello", "wav_base64": ""}))
    )
    await asyncio.sleep(0)
    bridge.unregister(bridge.connections[ids[0]])
    if replacement:
        bridge.register(conn(ids[0]))
    bridge.speaker_lock.release()
    with pytest.raises(RuntimeError, match="disconnected"):
        await queued
    await handlers["/session"](body_request({"device_ids": ids, "enabled": False}))


async def test_stop_during_encoding_does_not_start_transmission(bridge, monkeypatch):
    ids, handlers = fleet_handlers(bridge, monkeypatch)
    await handlers["/session"](body_request({"device_ids": ids, "enabled": True}))
    entered, release = threading.Event(), threading.Event()

    def encode(audio):
        entered.set()
        assert release.wait(5)
        return [b"opus"]

    monkeypatch.setattr(bridge, "wav_audio", lambda encoded: b"RIFF")
    monkeypatch.setattr(bridge, "encode_opus", encode)
    speaking = asyncio.create_task(
        handlers["/speak"](body_request({"device_id": ids[0], "text": "hello", "wav_base64": ""}))
    )
    assert await asyncio.to_thread(entered.wait, 5)
    stopping = asyncio.create_task(
        handlers["/session"](body_request({"device_ids": ids, "enabled": False}))
    )
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(RuntimeError, match="stopped"):
        await speaking
    await stopping
    assert not bridge.lease_ids


async def test_transmit_clears_speaking_status_when_final_stop_fails(bridge, monkeypatch):
    async def send(connection, state, text=None):
        if state == "stop":
            raise RuntimeError("socket disconnected")

    monkeypatch.setitem(
        sys.modules, "core.handle.sendAudioHandle", SimpleNamespace(send_tts_message=send)
    )
    connection = conn("mac-01")
    connection.conn_from_mqtt_gateway = False
    cleared = []
    connection.clearSpeakStatus = lambda: cleared.append(True)
    with pytest.raises(RuntimeError, match="disconnected"):
        await bridge.transmit(connection, "hello", [])
    assert cleared == [True]



async def test_authenticated_interrupt_requests_head_abort_without_waiting_on_speech_lock(bridge):
    connection = conn("mac-01")
    sent = []

    class Socket:
        async def send(self, data):
            sent.append(json.loads(data))

    connection.websocket = Socket()
    connection.session_id = "socket-session-1"
    bridge.register(connection)
    async with TestClient(TestServer(bridge.create_app())) as client:
        auth = {"Authorization": "Bearer " + "s" * 40}
        assert (await client.post("/interrupt", json={"device_id": "mac-01"})).status == 401
        assert (await client.post(
            "/interrupt", headers=auth, json={"device_id": "foreign"}
        )).status == 400
        await bridge.speaker_lock.acquire()
        try:
            result = await asyncio.wait_for(
                client.post("/interrupt", headers=auth, json={"device_id": "mac-01"}),
                1,
            )
            assert result.status == 200
            data = await result.json()
            assert data["head_flush_requested"] is True
            assert data["head_flush_acknowledged"] is False
            assert data["audible_stop_verified"] is False
            assert connection.client_abort is True
            assert bridge.interrupt_generation["mac-01"] == 1
            assert sent == [{
                "type": "tts", "state": "abort", "session_id": "socket-session-1"
            }]
        finally:
            bridge.speaker_lock.release()


async def test_interrupt_fences_inflight_and_queued_speech(bridge, monkeypatch):
    device = "mac-01"
    connection = conn(device)
    connection.session_id = "listen"
    sent = []

    class Socket:
        async def send(self, payload):
            sent.append(payload)

    connection.websocket = Socket()
    bridge.register(connection)
    bridge.lease_ids = frozenset([device])
    bridge.lease_until = time.monotonic() + 10
    handlers = {route.resource.canonical: route.handler for route in bridge.create_app().router.routes()}
    monkeypatch.setattr(bridge, "wav_audio", lambda _: b"RIFF")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_encode(_):
        entered.set()
        await release.wait()
        return [b"opus"]

    # Replace asyncio.to_thread only locally to hold the encode boundary.
    # Abort must invalidate the generation before any packet is transmitted.
    async def to_thread_(_func, _arg):
        return await blocked_encode(_arg)

    monkeypatch.setattr(bridge.asyncio, "to_thread", to_thread_)
    pending = asyncio.create_task(
        handlers["/speak"](
            body_request({"device_id": device, "text": "Old speech", "wav_base64": ""})
        )
    )
    await entered.wait()
    await handlers["/interrupt"](body_request({"device_id": device}))
    release.set()
    with pytest.raises(RuntimeError, match="stopped"):
        await pending
    assert len(sent) == 1
    assert json.loads(sent[0])["state"] == "abort"
