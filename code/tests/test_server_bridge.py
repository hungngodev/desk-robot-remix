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



async def test_authenticated_realtime_voice_readiness_is_live_not_invented(bridge):
    connection = conn("mac-01")
    connection.client_listen_mode = "auto"
    bridge.register(connection)
    headers = {"Authorization": "Bearer " + "s" * 40}
    async with TestClient(TestServer(bridge.create_app())) as client:
        path = "/voice-readiness?device_id=mac-01"
        assert (await client.get(path)).status == 401
        response = await client.get(path, headers=headers)
        assert response.status == 200
        state = await response.json()
        assert state["connected"] and state["reported_listen_mode"] == "auto"
        assert not state["realtime_audio_path_available"]
        assert not state["natural_barge_in_certified"]
        connection.client_listen_mode = "realtime"
        voice = await (await client.get(path, headers=headers)).json()
        assert voice["realtime_audio_path_available"]
        assert voice["reported_listen_mode"] == "realtime"
        assert not voice["device_aec_measured"]
        assert not voice["audible_flush_measured"]
        assert (await client.get("/voice-readiness?device_id=unknown", headers=headers)).status == 400
        bridge.unregister(connection)
        missing = await (await client.get(path, headers=headers)).json()
        assert not missing["connected"]
        assert not missing["realtime_audio_path_available"]

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
    assert len(changes) == 11
    assert "core/handle/intentHandler.py" in changes
    guarded = changes["core/handle/intentHandler.py"]
    assert "expected_generation=_desk_generation" in guarded
    assert "if not current_utterance():" in guarded
    assert "if response and current_utterance():" in guarded
    assert "if current_utterance():" in guarded
    assert "core/providers/tools/unified_tool_handler.py" in changes
    multi = changes["core/providers/tools/unified_tool_handler.py"]
    assert "getattr(response, 'result', None)" in multi
    assert "response.content" not in multi.split("def _combine_responses", 1)[1]
    assert "core/providers/tools/server_plugins/plugin_executor.py" in changes
    plugin = changes["core/providers/tools/server_plugins/plugin_executor.py"]
    assert "_PLUGIN_SLOTS = threading.BoundedSemaphore(8)" in plugin
    assert "native = _PLUGIN_POOL.submit(call)" in plugin
    assert "native.add_done_callback(finished)" in plugin
    assert "result = await asyncio.wrap_future(native)" in plugin
    assert "Synchronous plugin capacity exhausted" in plugin
    assert "desk_robot_native_omni.py" in changes
    assert "desk_robot_omni_wire.py" in changes
    patched_audio = changes["core/handle/receiveAudioHandle.py"]
    assert "desk_robot_native_omni.route_audio" in patched_audio
    # The actual pinned upstream contains only the AEC comment, NOT our
    # native route. VAD and emergency speaker preemption must run first,
    # then exactly one native PCM route may bypass legacy ASR.
    assert patched_audio.count("desk_robot_native_omni.route_audio") == 1
    assert patched_audio.index("interrupt_for_user_voice") < patched_audio.index(
        "desk_robot_native_omni.route_audio"
    )
    assert patched_audio.index("interrupt_for_normal_voice") < patched_audio.index(
        "desk_robot_native_omni.route_audio"
    )
    assert patched_audio.index("observe_idle_human_voice") < patched_audio.index(
        "desk_robot_native_omni.route_audio"
    )
    assert patched_audio.index("desk_robot_native_omni.route_audio") < patched_audio.index(
        "await conn.asr.receive_audio"
    )
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



async def test_normal_xiaozhi_realtime_listening_barges_into_its_own_tts(bridge):
    sent, cleared = [], []

    class Socket:
        async def send(self, frame):
            sent.append(json.loads(frame))

    one = conn("mac-01")
    one.client_listen_mode = "realtime"
    one.client_is_speaking = True
    one.session_id = "head-user-dialogue"
    one.websocket = Socket()
    one.clear_queues = lambda: cleared.append("queues")
    one.clearSpeakStatus = lambda: (
        cleared.append("speaker"),
        setattr(one, "client_is_speaking", False),
    )
    assert not await bridge.interrupt_for_normal_voice(one, False)
    assert not await bridge.interrupt_for_normal_voice(one, True)
    assert sent == []
    assert await bridge.interrupt_for_normal_voice(one, True)
    assert one.client_abort and not one.client_is_speaking
    assert cleared == ["queues", "speaker"]
    assert sent == [{
        "type": "tts", "state": "stop",
        "session_id": "head-user-dialogue", "flush": True,
    }]
    assert not await bridge.interrupt_for_normal_voice(one, True)


async def test_normal_barge_in_does_not_cut_off_auto_or_peer_speech(bridge):
    first = conn("mac-01")
    first.client_is_speaking = True
    first.client_listen_mode = "auto"
    for _ in range(3):
        assert not await bridge.interrupt_for_normal_voice(first, True)
    first.client_listen_mode = "realtime"
    bridge.lease_ids = frozenset(["mac-01", "mac-02"])
    bridge.lease_until = time.monotonic() + 10
    assert not await bridge.interrupt_for_normal_voice(first, True)
    assert bridge.voice_frames.get("mac-01") is None


def test_sustained_voice_resets_after_gap_and_silence(bridge, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(bridge.time, "monotonic", lambda: clock[0])
    assert not bridge.sustained_voice("mac-01", True)
    clock[0] += 0.5
    assert not bridge.sustained_voice("mac-01", True)
    clock[0] += 0.05
    assert bridge.sustained_voice("mac-01", True)
    assert not bridge.sustained_voice("mac-01", False)
    assert bridge.voice_frames.get("mac-01") is None


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
    assert "await desk_robot_bridge.interrupt_for_normal_voice(conn, have_voice)" in audio
    assert audio.index("await desk_robot_bridge.interrupt_for_user_voice") < audio.index(
        "await conn.asr.receive_audio"
    )
    assert "and not desk_robot_bridge.was_interrupted_by_human" in audio
    assert '"flush": True' in (
        ROOT / "laptop/server/overlay/desk_robot_bridge.py"
    ).read_text()


async def test_installed_pinned_audio_function_delivers_vad_before_native_pcm(
    monkeypatch,
):
    """Execute the real overlaid upstream audio handler, not a mock copy."""
    import ast
    import types

    spec = importlib.util.spec_from_file_location(
        "real_upstream_audio_overlay", ROOT / "laptop/server/install_overlay.py"
    )
    overlay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(overlay)
    files = overlay.files(
        ROOT / "upstream/xiaozhi-esp32-server/main/xiaozhi-server"
    )
    tree = ast.parse(files["core/handle/receiveAudioHandle.py"])
    handler = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "handleAudioMessage"
    )
    calls = []
    native_enabled = [True]

    async def interrupt_user(conn, voice):
        calls.append("group_stop")

    async def interrupt_normal(conn, voice):
        calls.append("head_stop")

    def observe_idle(conn, voice):
        calls.append("authenticated_vad")

    def native_route(conn, pcm, voice):
        calls.append("native_pcm")
        return native_enabled[0]

    async def no_voice(conn, voice):
        calls.append("legacy_idle")

    class ASR:
        async def receive_audio(self, conn, pcm, voice):
            calls.append("legacy_asr")

    monkeypatch.setitem(sys.modules, "desk_robot_bridge", types.SimpleNamespace(
        interrupt_for_user_voice=interrupt_user,
        interrupt_for_normal_voice=interrupt_normal,
        observe_idle_human_voice=observe_idle,
    ))
    monkeypatch.setitem(sys.modules, "desk_robot_native_omni",
                        types.SimpleNamespace(route_audio=native_route))
    namespace = {
        "asyncio": asyncio,
        "no_voice_close_connect": no_voice,
    }
    isolated = ast.Module(body=[handler], type_ignores=[])
    exec(compile(isolated, "actual_pinned_audio_handler.py", "exec"), namespace)
    conn = types.SimpleNamespace(
        vad=types.SimpleNamespace(is_vad=lambda conn, pcm: True),
        client_aec=False, just_woken_up=False, asr=ASR(),
    )
    await namespace["handleAudioMessage"](conn, b"actual_decoded_pcm")
    assert calls == [
        "group_stop", "head_stop", "authenticated_vad", "native_pcm"
    ]
    calls.clear()
    native_enabled[0] = False
    await namespace["handleAudioMessage"](conn, b"actual_decoded_pcm")
    assert calls == [
        "group_stop", "head_stop", "authenticated_vad",
        "native_pcm", "legacy_idle", "legacy_asr"
    ]


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


async def test_live_stream_interrupt_fences_remaining_opus_packets(bridge, monkeypatch):
    sent = []
    cleared = []
    connection = conn("mac-01")
    connection.conn_from_mqtt_gateway = False
    connection.session_id = "session"
    connection.last_activity_time = 0
    connection.clearSpeakStatus = lambda: cleared.append(True)

    class Socket:
        async def send(self, frame):
            sent.append(frame)

    connection.websocket = Socket()
    bridge.register(connection)
    bridge.lease_ids = frozenset({"mac-01"})
    bridge.lease_until = time.monotonic() + 20

    async def send_tts(c, state, text=None):
        sent.append(state)

    monkeypatch.setitem(
        sys.modules, "core.handle.sendAudioHandle",
        SimpleNamespace(send_tts_message=send_tts),
    )
    handlers = {
        route.resource.canonical: route.handler
        for route in bridge.create_app().router.routes()
    }
    task = asyncio.create_task(
        bridge.transmit(connection, "old reply", [b"first", b"second", b"third"])
    )
    async with asyncio.timeout(2):
        while b"first" not in sent:
            await asyncio.sleep(.001)
    response = await handlers["/interrupt"](
        body_request({"device_id": "mac-01"})
    )
    assert response.status == 200
    with pytest.raises(RuntimeError, match="interrupted"):
        await task
    assert b"second" not in sent and b"third" not in sent
    assert any(
        isinstance(frame, str) and '"flush": true' in frame for frame in sent
    )
    assert cleared == [True]

async def test_real_xiaozhi_voice_events_are_authenticated_replayable_metadata(bridge):
    one = conn("mac-01")
    bridge.register(one)
    assert bridge.record_human_voice(one, "normal")
    assert bridge.record_human_voice(one, "group")
    bridge.unregister(one)
    assert not bridge.record_human_voice(one, "normal")
    headers = {"Authorization": "Bearer " + "s" * 40}
    async with TestClient(TestServer(bridge.create_app())) as client:
        assert (await client.get("/events?after=0")).status == 401
        boot = await client.get("/events?after=0&bootstrap=1", headers=headers)
        assert await boot.json() == {
            "cursor": 2, "events": [], "lost": False, "reset": False,
            "active_human_robots": [],
        }
        result = await client.get("/events?after=0", headers=headers)
        data = await result.json()
        assert data["cursor"] == 2 and not data["lost"]
        assert [e["kind"] for e in data["events"]] == ["normal", "group"]
        assert all(e["robot_id"] == "robot-01" for e in data["events"])
        assert all("audio" not in e and "transcript" not in e for e in data["events"])
        result = await client.get("/events?after=1", headers=headers)
        assert [e["seq"] for e in (await result.json())["events"]] == [2]
        result = await client.get("/events?after=900", headers=headers)
        assert (await result.json())["reset"] is True
        assert (await client.get("/events?after=-1", headers=headers)).status == 400


async def test_events_snapshot_recovers_missed_active_vad_and_cleans_up(bridge):
    first = conn("mac-01")
    first.client_listen_mode = "realtime"
    bridge.register(first)
    assert bridge.observe_idle_human_voice(first, True) is False
    assert bridge.observe_idle_human_voice(first, True) is True
    assert bridge.active_idle_speech_robots() == ["robot-01"]
    headers = {"Authorization": "Bearer " + "s" * 40}
    async with TestClient(TestServer(bridge.create_app())) as client:
        snapshot = await client.get("/events?after=0&bootstrap=1", headers=headers)
        payload = await snapshot.json()
        assert payload["active_human_robots"] == ["robot-01"]
        assert payload["events"] == []  # Live state even without replay.
        assert not bridge.observe_idle_human_voice(first, False)
        assert not bridge.observe_idle_human_voice(first, False)
        ended = await client.get("/events?after=1", headers=headers)
        assert (await ended.json())["active_human_robots"] == []
    bridge.unregister(first)
    assert bridge.active_idle_speech_robots() == []


async def test_real_voice_event_ring_overflow_detected(bridge):
    one = conn("mac-01")
    bridge.register(one)
    for _ in range(135):
        assert bridge.record_human_voice(one, "normal")
    async with TestClient(TestServer(bridge.create_app())) as client:
        result = await client.get("/events?after=1", headers={
            "Authorization": "Bearer " + "s" * 40,
        })
        data = await result.json()
        assert data["cursor"] == 135
        assert data["lost"] is True
        assert len(data["events"]) == 128
        assert data["events"][0]["seq"] == 8



async def test_physical_normal_barge_in_emits_only_from_live_registered_connection(bridge):
    sent = []

    class Socket:
        async def send(self, frame):
            sent.append(json.loads(frame))

    one = conn("mac-01")
    one.client_listen_mode = "realtime"
    one.client_is_speaking = True
    one.session_id = "live-device"
    one.websocket = Socket()
    one.clear_queues = lambda: None
    one.clearSpeakStatus = lambda: setattr(one, "client_is_speaking", False)
    bridge.register(one)
    assert not await bridge.interrupt_for_normal_voice(one, True)
    assert bridge.voice_event_cursor == 0
    assert await bridge.interrupt_for_normal_voice(one, True)
    assert bridge.voice_event_cursor == 1
    assert list(bridge.voice_event_history) == [{
        "seq": 1, "robot_id": "robot-01",
        "kind": "normal", "source": "xiaozhi_aec_vad",
    }]
    assert sent == [{
        "type": "tts", "state": "stop", "session_id": "live-device", "flush": True,
    }]
    assert not await bridge.interrupt_for_normal_voice(one, True)
    assert bridge.voice_event_cursor == 1
    bridge.unregister(one)
    assert not bridge.record_human_voice(one, "normal")


def test_idle_real_human_vad_queues_one_voice_video_hint_per_utterance(bridge):
    one = conn("mac-01")
    one.client_listen_mode = "auto"
    bridge.register(one)
    assert not bridge.observe_idle_human_voice(one, False)
    assert not bridge.observe_idle_human_voice(one, True)
    assert bridge.observe_idle_human_voice(one, True)
    assert not bridge.observe_idle_human_voice(one, True)
    assert len(bridge.voice_event_history) == 1
    first = bridge.voice_event_history[-1]
    assert first["kind"] == "speech_start"
    assert first["source"] == "xiaozhi_server_vad"
    assert first["robot_id"] == "robot-01"
    assert not bridge.observe_idle_human_voice(one, False)
    # A single momentary silent VAD frame must NOT end a live phrase.
    assert not bridge.observe_idle_human_voice(one, True)
    assert not bridge.observe_idle_human_voice(one, True)
    assert len(bridge.voice_event_history) == 1
    assert not bridge.observe_idle_human_voice(one, False)
    assert not bridge.observe_idle_human_voice(one, False)
    assert bridge.voice_event_history[-1]["kind"] == "speech_end"
    assert bridge.voice_event_history[-1]["source"] == "xiaozhi_server_vad"
    assert not bridge.observe_idle_human_voice(one, True)
    assert bridge.observe_idle_human_voice(one, True)
    assert len(bridge.voice_event_history) == 3
    one.client_is_speaking = True
    bridge.observe_idle_human_voice(one, False)
    assert not bridge.observe_idle_human_voice(one, True)
    assert len(bridge.voice_event_history) == 3
    bridge.unregister(one)


def test_idle_voice_must_come_from_current_registered_head_and_listen_mode(bridge):
    first = conn("mac-01")
    first.client_listen_mode = "auto"
    forgery = conn("mac-01")
    forgery.client_listen_mode = "realtime"
    bridge.register(first)
    assert not bridge.observe_idle_human_voice(forgery, True)
    assert not bridge.observe_idle_human_voice(forgery, True)
    first.client_listen_mode = "manual"
    assert not bridge.observe_idle_human_voice(first, True)
    first.client_listen_mode = "realtime"
    assert not bridge.observe_idle_human_voice(first, True)
    assert bridge.observe_idle_human_voice(first, True)
    assert len(bridge.voice_event_history) == 1
    bridge.unregister(first)
    assert not bridge.observe_idle_human_voice(first, True)


def test_human_speaker_floor_requires_authenticated_live_vad_and_cleans_up(bridge):
    first, second, forged = conn("mac-01"), conn("mac-02"), conn("mac-01")
    first.client_listen_mode = "realtime"
    second.client_listen_mode = "realtime"
    bridge.register(first)
    bridge.register(second)
    assert bridge.human_speech_active() is False
    assert bridge.record_human_voice(forged, "speech_start") is False
    assert bridge.human_speech_active() is False
    assert bridge.record_human_voice(first, "speech_start") is True
    assert bridge.human_speech_active() is True
    assert bridge.record_human_voice(first, "speech_end") is True
    assert bridge.human_speech_active() is True  # brief word pause
    bridge.human_vad_until["mac-01"] = time.monotonic() - 1
    assert bridge.human_speech_active() is False
    assert bridge.record_human_voice(second, "group") is True
    assert bridge.human_speech_active() is True
    bridge.unregister(second)
    assert bridge.human_speech_active() is False
    bridge.unregister(first)


def test_ongoing_voice_refreshes_floor_without_replaying_speech_start(bridge):
    head = conn("mac-01")
    head.client_listen_mode = "realtime"
    bridge.register(head)
    assert bridge.observe_idle_human_voice(head, True) is False
    assert bridge.observe_idle_human_voice(head, True) is True
    assert bridge.voice_event_cursor == 1
    bridge.human_vad_until["mac-01"] = time.monotonic() - 1
    assert bridge.human_speech_active() is False
    assert bridge.observe_idle_human_voice(head, True) is False
    assert bridge.voice_event_cursor == 1
    assert bridge.human_speech_active() is True
    assert not bridge.observe_idle_human_voice(head, False)
    assert not bridge.observe_idle_human_voice(head, False)
    assert bridge.voice_event_history[-1]["kind"] == "speech_end"
    bridge.unregister(head)
    assert bridge.human_speech_active() is False


def test_authenticated_vad_invalidates_old_tool_requests_but_not_speech_end(bridge):
    head = conn("mac-01")
    bridge.register(head)
    first = bridge.tool_turn_cancel_event("mac-01")
    assert not first.is_set()
    assert bridge.record_human_voice(head, "speech_start")
    assert first.is_set()
    second = bridge.tool_turn_cancel_event("mac-01")
    assert second is not first and not second.is_set()
    assert bridge.record_human_voice(head, "speech_end")
    assert not second.is_set()  # Still the same user turn.
    assert bridge.record_human_voice(head, "normal")
    assert second.is_set()
    third = bridge.tool_turn_cancel_event("mac-01")
    assert not third.is_set()
    bridge.unregister(head)
    assert third.is_set()
    with pytest.raises(ValueError, match="connected"):
        bridge.tool_turn_cancel_event("mac-01")
