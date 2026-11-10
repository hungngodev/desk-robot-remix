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


def test_only_current_duplex_speaker_passes_microphone_while_group_talks(bridge):
    one, two = conn("mac-01"), conn("mac-02")
    one.client_listen_mode = "realtime"
    two.client_listen_mode = "realtime"
    bridge.lease_ids = frozenset(["mac-01", "mac-02"])
    bridge.lease_until = time.monotonic() + 20
    bridge.active_device_id = "mac-01"
    assert not bridge.suppress_message(one, b"live clean microphone PCM")
    assert bridge.suppress_message(two, b"the other robot heard robot 1")
    assert bridge.suppress_message(one, '{"type":"listen","state":"start"}')
    one.client_listen_mode = "auto"  # no confirmed head AEC: fail closed
    assert bridge.suppress_message(one, b"echo-only unclean PCM")


async def test_real_time_user_double_talk_aborts_peer_speech_with_immediate_dma_flush(bridge):
    sent = []

    class Websocket:
        async def send(self, content):
            sent.append(json.loads(content))

    first, second = conn("mac-01"), conn("mac-02")
    first.websocket = Websocket()
    first.session_id = "private-session"
    first.clearSpeakStatus = lambda: None
    first.client_listen_mode = "realtime"
    second.client_listen_mode = "realtime"
    bridge.register(first)
    bridge.register(second)
    bridge.lease_ids = frozenset(["mac-01", "mac-02"])
    bridge.lease_until = time.monotonic() + 20
    bridge.active_device_id = "mac-01"
    await bridge.speaker_lock.acquire()
    try:
        assert not await bridge.interrupt_for_user_voice(first, False)
        assert not await bridge.interrupt_for_user_voice(first, True)
        assert not await bridge.interrupt_for_user_voice(second, True)
        assert not sent
        assert await bridge.interrupt_for_user_voice(first, True)
        assert first.client_abort is True
        assert bridge.was_interrupted_by_human("mac-01")
        assert bridge.lease_stopping
        assert sent == [
            {
                "type": "tts", "state": "stop", "flush": True,
                "session_id": "private-session",
            }
        ]
        assert not await bridge.interrupt_for_user_voice(first, True)
    finally:
        bridge.speaker_lock.release()
    await bridge.lease_cleanup_task
    assert bridge.lease_ids == frozenset()
    assert not bridge.lease_stopping
    assert not bridge.was_interrupted_by_human("mac-01")


async def test_server_overlay_routes_actual_double_talk_audio_to_guard(bridge):
    spec = importlib.util.spec_from_file_location(
        "real_upstream_overlay", ROOT / "laptop/server/install_overlay.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    files = module.files(ROOT / "upstream/xiaozhi-esp32-server/main/xiaozhi-server")
    audio = files["core/handle/receiveAudioHandle.py"]
    assert "await desk_robot_bridge.interrupt_for_user_voice(conn, have_voice)" in audio
    assert audio.index("await desk_robot_bridge.interrupt_for_user_voice") < audio.index(
        "await conn.asr.receive_audio"
    )
    assert "and not desk_robot_bridge.was_interrupted_by_human" in audio
    assert '"flush": True' in (
        ROOT / "laptop/server/overlay/desk_robot_bridge.py"
    ).read_text()


async def test_stop_during_group_playback_marks_urgent_flush(bridge, monkeypatch):
    sent = []

    class Socket:
        async def send(self, frame):
            sent.append(frame)

    connection = conn("mac-01")
    connection.conn_from_mqtt_gateway = False
    connection.websocket = Socket()
    connection.session_id = "session"
    connection.last_activity_time = 0
    connection.clearSpeakStatus = lambda: None
    bridge.lease_ids = frozenset(["mac-01"])
    bridge.lease_until = time.monotonic() + 30
    bridge.active_device_id = "mac-01"

    async def send_tts(connection, state, text=None):
        sent.append(state)

    monkeypatch.setitem(
        sys.modules, "core.handle.sendAudioHandle",
        SimpleNamespace(send_tts_message=send_tts)
    )

    async def abort_midplayback():
        await asyncio.sleep(0)
        connection.client_abort = True

    kill = asyncio.create_task(abort_midplayback())
    with pytest.raises(RuntimeError, match="interrupted"):
        await bridge.transmit(connection, "short greeting", [b"one", b"two"])
    await kill
    assert "start" in sent
    assert any(
        isinstance(value, str) and '"flush": true' in value for value in sent
    )


async def test_authenticated_device_interrupt_restored_from_pr7(bridge):
    sent = []

    class Websocket:
        async def send(self, frame):
            sent.append(json.loads(frame))

    first = conn("mac-01")
    first.websocket = Websocket()
    first.session_id = "private-01"
    bridge.register(first)
    async with TestClient(TestServer(bridge.create_app())) as client:
        payload = {"device_id": "mac-01"}
        assert (await client.post("/interrupt", json=payload)).status == 401
        headers = {"Authorization": "Bearer " + "s" * 40}
        assert (await client.post(
            "/interrupt", headers=headers, json={"device_id": "unknown"}
        )).status == 400
        assert (await client.post(
            "/interrupt", headers=headers, json={"device_id": "mac-02"}
        )).status == 409
        response = await client.post("/interrupt", headers=headers, json=payload)
        assert response.status == 200
        data = await response.json()
        assert data["interrupted"] is True
        assert data["head_flush_requested"] is True
        assert data["head_flush_acknowledged"] is False
        assert data["audible_stop_verified"] is False
    assert bridge.interrupt_generation["mac-01"] == 1
    assert first.client_abort is True
    assert sent == [{
        "type": "tts", "state": "stop", "session_id": "private-01",
        "flush": True,
    }]


async def test_interrupt_fences_previously_queued_speech_without_waiting_for_lock(
    bridge, monkeypatch
):
    ids, handlers = fleet_handlers(bridge, monkeypatch)
    first = bridge.connections[ids[0]]
    sent, delivered = [], []

    class Websocket:
        async def send(self, frame):
            sent.append(json.loads(frame))

    first.websocket = Websocket()
    first.session_id = "session"
    monkeypatch.setattr(bridge, "wav_audio", lambda value: b"RIFF")
    monkeypatch.setattr(bridge, "encode_opus", lambda audio: [b"opus"])

    async def record_transmission(connection, text, frames):
        delivered.append(connection.device_id)

    monkeypatch.setattr(bridge, "transmit", record_transmission)
    await handlers["/session"](
        body_request({"device_ids": ids, "enabled": True})
    )
    await bridge.speaker_lock.acquire()
    queued = asyncio.create_task(handlers["/speak"](body_request({
        "device_id": ids[0], "text": "old sentence", "wav_base64": ""
    })))
    await asyncio.sleep(0)
    try:
        interrupt = await asyncio.wait_for(
            handlers["/interrupt"](body_request({"device_id": ids[0]})),
            timeout=0.5,
        )
        assert interrupt.status == 200
        assert first.client_abort is True
        assert bridge.interrupt_generation[ids[0]] == 1
        assert not bridge.connections[ids[1]].client_abort
        assert sent == [{
            "type": "tts", "state": "stop",
            "session_id": "session", "flush": True,
        }]
    finally:
        bridge.speaker_lock.release()
    with pytest.raises(RuntimeError, match="interrupted"):
        await queued
    assert delivered == []
    # A different robot keeps its own generation and can still transmit.
    await handlers["/speak"](body_request({
        "device_id": ids[1], "text": "new sentence", "wav_base64": ""
    }))
    assert delivered == [ids[1]]
    await handlers["/session"](
        body_request({"device_ids": ids, "enabled": False})
    )


async def test_interrupt_while_opus_encoding_cannot_resurrect_obsolete_tts(
    bridge, monkeypatch
):
    ids, handlers = fleet_handlers(bridge, monkeypatch)
    first = bridge.connections[ids[0]]
    sent, delivered = [], []
    entered, release = threading.Event(), threading.Event()

    class Websocket:
        async def send(self, frame):
            sent.append(json.loads(frame))

    first.websocket = Websocket()
    first.session_id = "session"
    monkeypatch.setattr(bridge, "wav_audio", lambda value: b"RIFF")

    def slow_encode(audio):
        entered.set()
        assert release.wait(5)
        return [b"opus"]

    async def record_transmission(connection, text, frames):
        delivered.append(connection.device_id)

    monkeypatch.setattr(bridge, "encode_opus", slow_encode)
    monkeypatch.setattr(bridge, "transmit", record_transmission)
    await handlers["/session"](
        body_request({"device_ids": ids, "enabled": True})
    )
    old = asyncio.create_task(handlers["/speak"](body_request({
        "device_id": ids[0], "text": "still encoding", "wav_base64": ""
    })))
    assert await asyncio.to_thread(entered.wait, 5)
    try:
        result = await asyncio.wait_for(
            handlers["/interrupt"](body_request({"device_id": ids[0]})),
            timeout=0.5,
        )
        assert result.status == 200
        assert first.client_abort
        assert sent[0]["flush"] is True
    finally:
        release.set()
    with pytest.raises(RuntimeError, match="interrupted"):
        await old
    assert delivered == []
    await handlers["/session"](
        body_request({"device_ids": ids, "enabled": False})
    )
