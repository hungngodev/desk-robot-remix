"""Actual pinned Xiaozhi PCM/Opus integration tests using a loopback model fake.

These are full async socket tests of the adapter, not claims about the
head's physical audio DAC, AEC, realtime model quality or charging.
"""
import asyncio
import base64
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def native(monkeypatch):
    fake_bridge = SimpleNamespace(
        connections={},
        robot_for_device=lambda dev: "robot-01" if dev == "mac-01" else None,
        lease_stopping=False, lease_ids=frozenset(), lease_until=0.0,
        human_speech_active=lambda: False,
    )
    monkeypatch.setitem(sys.modules, "desk_robot_bridge", fake_bridge)
    spec = importlib.util.spec_from_file_location(
        "desk_robot_native_omni",
        ROOT / "laptop/server/overlay/desk_robot_native_omni.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "desk_robot_native_omni", module)
    spec.loader.exec_module(module)
    return module, fake_bridge


def healthy_session(model="openbmb/MiniCPM-o-4_5"):
    # Match the published vLLM-Omni session.created capability contract,
    # not an artificially permissive fake backend.
    return {
        "type": "session.created",
        "session": {
            "model": model, "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "audio": {
                "input": {"sample_rate_hz": 16000},
                "output": {"format": {"type": "audio/pcm", "rate": 24000}},
            },
            "capabilities": {
                "implementation_level": "model_native_duplex",
                "supports_input_append": True,
                "supports_barge_in": True,
                "chunk_period_ms": 1000,
            },
        },
    }


def connection():
    sent = []

    class DeviceSocket:
        async def send(self, packet):
            sent.append(packet)

    conn = SimpleNamespace(
        device_id="mac-01",
        client_listen_mode="realtime",
        conn_from_mqtt_gateway=False,
        client_is_speaking=False,
        client_abort=False,
        websocket=DeviceSocket(),
        session_id="real-head-session",
    )
    return conn, sent


def test_native_backend_has_explicit_opt_in_and_tls_only_for_remote_audio(native, monkeypatch):
    module, bridge = native
    conn, sent = connection()
    bridge.connections["mac-01"] = conn
    assert module.route_audio(conn, b"\x00" * 1920, True) is False
    assert not module.active("mac-01")
    for url in (
        "ws://192.168.0.5/v1/realtime?duplex=1",
        "http://127.0.0.1:8099/v1/realtime?duplex=1",
        "ws://attacker@127.0.0.1:8099/v1/realtime?duplex=1",
        "ws://127.0.0.1:8099/v1/not-realtime?duplex=1",
    ):
        with pytest.raises(ValueError):
            module.approved_backend_url(url)
    assert module.approved_backend_url(
        "ws://127.0.0.1:8099/v1/realtime?duplex=1"
    )
    monkeypatch.setenv("DESK_ROBOT_OMNI_ROBOTS", "robot-01")
    # Missing backend or token fails closed; it must NOT fall back to a
    # second LLM/TTS while the private operator explicitly enabled native.
    assert module.route_audio(conn, b"\x00" * 1920, True) is True
    assert module.status("mac-01")["native_backend_connected"] is False
    assert sent == []


async def test_native_ws_routes_actual_mic_pcm_to_model_and_24k_audio_back_to_head(
    native, monkeypatch,
):
    module, bridge = native
    conn, sent = connection()
    bridge.connections["mac-01"] = conn
    observed = []

    class FakeOpusEncoder:
        def __init__(self, rate, channels, mode):
            assert rate == 16000 and channels == 1 and mode == "audio"

        def encode(self, data, samples):
            assert len(data) == 1920 and samples == 960
            return b"opus::" + data[:4]

    monkeypatch.setitem(sys.modules, "opuslib_next", SimpleNamespace(
        Encoder=FakeOpusEncoder, APPLICATION_AUDIO="audio"
    ))
    pcm24 = b"\x00" * 4800

    async def socket_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for message in ws:
            event = json.loads(message.data)
            observed.append(event)
            if event["type"] == "session.update":
                await ws.send_json(healthy_session())
            if event["type"] == "input_audio_buffer.commit":
                await ws.send_json({
                    "type": "response.created", "response_id": "actual-r1",
                    "response": {"id": "actual-r1",
                                 "metadata": {"duplex_event": {"epoch": 0}}},
                })
                await ws.send_json({
                    "type": "response.output_audio.delta",
                    "response_id": "actual-r1",
                    "format": "pcm16", "sample_rate_hz": 24000,
                    "delta": base64.b64encode(pcm24).decode(),
                    "metadata": {"epoch": 0},
                })
                await ws.send_json({
                    "type": "response.done", "response_id": "actual-r1",
                })
        return ws

    application = web.Application()
    application.router.add_get("/v1/realtime", socket_handler)
    async with TestServer(application) as model:
        address = str(model.make_url("/v1/realtime?duplex=1")).replace(
            "http://", "ws://"
        )
        service = module.NativeOmniSession(
            conn, url=address, token="z" * 32,
            model="openbmb/MiniCPM-o-4_5",
        )
        module._sessions["mac-01"] = service
        service.started = asyncio.create_task(service.run())
        try:
            async with asyncio.timeout(3):
                while not service.connected:
                    if service.last_error is not None:
                        raise AssertionError(service.last_error)
                    await asyncio.sleep(.01)
            # Actual decoder-shaped PCM blocks, not a generated transcript.
            service.queue_mic(b"\x00" * 3200, True)
            for _ in range(3):
                service.queue_mic(b"\x00" * 3200, False)
            async with asyncio.timeout(3):
                while not any(isinstance(x, str) and '"state": "stop"' in x
                              for x in sent):
                    if service.last_error is not None:
                        raise AssertionError(service.last_error)
                    await asyncio.sleep(.01)
            assert any(x["type"] == "input_audio_buffer.append" for x in observed)
            appends = [x for x in observed if x["type"] == "input_audio_buffer.append"]
            assert len(appends) == 4
            assert base64.b64decode(appends[0]["audio"]) == b"\x00" * 3200
            assert any(x["type"] == "input_audio_buffer.commit" for x in observed)
            assert len([x for x in sent if isinstance(x, bytes)]) == 2
            assert any(isinstance(x, str) and '"state": "start"' in x for x in sent)
            assert service.head_packets == 2 and service.model_chunks == 1
            assert not any(x["type"] == "playback.ack" for x in observed)
        finally:
            service.fail("Test ended")
            await asyncio.gather(service.started, return_exceptions=True)
    assert module._sessions == {}


async def test_native_barge_invalidates_backend_audio_and_never_forges_ack(native):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    service = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    # No active server socket: cancelling clears local audio generation
    # without claiming an ACK or sending an invented backend event.
    service.wire.handle_event({
        "type": "response.created", "response_id": "old",
        "response": {"id": "old", "metadata": {"duplex_event": {"epoch": 0}}},
    })
    await service.barge()
    assert service._generation == 1
    assert service.wire.response_id is None
    assert service.wire.accept_output is False
    assert service.wire.played_ms == 0
    assert module.status("mac-01")["head_audio_playback_acknowledged"] is False


async def test_fleet_native_speaker_claim_flushes_old_pet_before_second_pet_talks(native):
    module, bridge = native
    first, sent = connection()
    bridge.connections["mac-01"] = first
    second = SimpleNamespace(
        device_id="mac-02",
        conn_from_mqtt_gateway=False, client_listen_mode="realtime",
        client_is_speaking=False, client_abort=False,
        session_id="second-session", websocket=first.websocket,
    )
    bridge.connections["mac-02"] = second
    bridge.robot_for_device = lambda dev: {
        "mac-01": "robot-01", "mac-02": "robot-02"
    }.get(dev)
    previous = module.NativeOmniSession(
        first, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    newer = module.NativeOmniSession(
        second, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    module._sessions.update({"mac-01": previous, "mac-02": newer})
    module._output_owner = "mac-01"
    first.client_is_speaking = True
    await module.claim_speaker(newer)
    assert previous._generation == 1
    assert first.client_is_speaking is False
    assert any(isinstance(x, str) and '"flush": true' in x for x in sent)
    assert module._output_owner == "mac-02"
    newer.conn.client_is_speaking = True
    await module.preempt_others_for_human("mac-01")
    assert newer._generation == 1
    assert newer.conn.client_is_speaking is False


async def test_native_cutover_flushes_pending_xiaozhi_legacy_speech_first(native):
    from queue import Queue

    module, bridge = native
    conn, sent = connection()
    conn.client_is_speaking = True
    pending_audio = Queue()
    pending_audio.put(b"legacy opus")
    conn.tts = SimpleNamespace(tts_audio_queue=pending_audio, tts_text_queue=Queue())
    cleared = []

    def clear_queues():
        cleared.append(True)
        while not pending_audio.empty():
            pending_audio.get_nowait()

    conn.clear_queues = clear_queues
    bridge.connections["mac-01"] = conn
    service = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    await service._retire_legacy_audio()
    assert cleared == [True]
    assert conn.client_is_speaking is False
    assert conn.client_abort is True
    assert any(isinstance(packet, str)
               and '"flush": true' in packet for packet in sent)
    # No second stop packet or legacy queue replay on repeated checks.
    await service._retire_legacy_audio()
    assert len(sent) == 1


@pytest.mark.parametrize("mutation", [
    ("session", "model", "wrong-model"),
    ("session", "input_audio_format", "g711_ulaw"),
    ("session", "output_audio_format", "mp3"),
    ("capabilities", "supports_input_append", False),
    ("capabilities", "supports_barge_in", False),
    ("capabilities", "chunk_period_ms", 80),
    ("capabilities", "implementation_level", "turn_based"),
])
def test_native_adapter_rejects_incompatible_realtime_server_before_mic_transfer(
    native, mutation,
):
    module, _ = native
    greeting = healthy_session()
    block, key, value = mutation
    if block == "session":
        greeting["session"][key] = value
    else:
        greeting["session"]["capabilities"][key] = value
    with pytest.raises(RuntimeError):
        module.verify_native_server(greeting, "openbmb/MiniCPM-o-4_5")


@pytest.mark.parametrize("input_rate,output_rate", [
    (8000, 24000), (16000, 16000), (48000, 24000),
])
def test_native_adapter_refuses_unexpected_model_pcm_rates(native, input_rate, output_rate):
    module, _ = native
    greeting = healthy_session()
    greeting["session"]["audio"]["input"]["sample_rate_hz"] = input_rate
    greeting["session"]["audio"]["output"]["format"]["rate"] = output_rate
    with pytest.raises(RuntimeError):
        module.verify_native_server(greeting, "openbmb/MiniCPM-o-4_5")


def test_native_adapter_accepts_published_upstream_duplex_capabilities(native):
    module, _ = native
    assert module.verify_native_server(healthy_session(), "openbmb/MiniCPM-o-4_5") is None


def test_native_configuration_error_preserved_and_retries_throttled(native, monkeypatch):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    monkeypatch.setenv("DESK_ROBOT_OMNI_ROBOTS", "robot-01")
    monkeypatch.delenv("DESK_ROBOT_OMNI_URL", raising=False)
    monkeypatch.delenv("DESK_ROBOT_TOOL_TOKEN", raising=False)
    for _ in range(25):
        assert module.route_audio(conn, b"\\0" * 3200, True)
    assert module._sessions == {}
    assert module.status("mac-01")["native_backend_connected"] is False
    assert module.status("mac-01")["retry_delay_seconds"] > 0
    assert module.status("mac-01")["last_error"] is not None
    assert module.status("mac-01")["head_audio_playback_acknowledged"] is False


async def test_human_voice_flushes_physical_head_before_slow_remote_cancel(native):
    module, bridge = native
    conn, sent = connection()
    bridge.connections["mac-01"] = conn
    conn.client_is_speaking = True
    service = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    service.wire.handle_event({
        "type": "response.created",
        "response_id": "old-response",
        "response": {"id": "old-response",
                     "metadata": {"duplex_event": {"epoch": 0}}},
    })
    entered_remote_cancel = asyncio.Event()
    release_remote_cancel = asyncio.Event()
    remote_events = []

    class SlowModelSocket:
        async def send_json(self, payload):
            remote_events.append(payload)
            entered_remote_cancel.set()
            await release_remote_cancel.wait()

    service._socket = SlowModelSocket()
    service.connected = True
    task = asyncio.create_task(service.barge())
    try:
        async with asyncio.timeout(1):
            await entered_remote_cancel.wait()
        # The remote model is still blocked. Physical stop must already have
        # reached the registered XIAO and all old Opus sends are invalid.
        assert not task.done()
        assert service._generation == 1
        assert service.wire.response_id is None
        assert service.wire.played_ms == 0
        assert conn.client_is_speaking is False
        assert any(isinstance(item, str) and '"flush": true' in item
                   for item in sent)
        assert remote_events[0]["type"] == "response.cancel"
    finally:
        release_remote_cancel.set()
        await task
    assert any(x["type"] == "output_audio_buffer.clear" for x in remote_events)
    assert module.status("mac-01")["head_audio_playback_acknowledged"] is False


async def test_native_audio_cannot_start_during_other_robots_authenticated_human_vad(
    native,
):
    module, bridge = native
    first, sent = connection()
    bridge.connections["mac-01"] = first
    service = module.NativeOmniSession(
        first, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    module._sessions["mac-01"] = service
    bridge.human_speech_active = lambda: True
    await service._send_device_state("start", service._generation)
    assert first.client_is_speaking is False
    assert service._generation == 1  # stale generated Opus invalidated
    assert service.wire.accept_output is False
    assert sent == []
    assert module._output_owner is None
    assert module.status("mac-01")["head_audio_playback_acknowledged"] is False


async def test_native_audio_racing_with_new_human_vad_refuses_tts_start(native):
    module, bridge = native
    conn, sent = connection()
    bridge.connections["mac-01"] = conn
    service = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    module._sessions["mac-01"] = service
    # First speaker-floor read is clear. The second read, while awaiting
    # physical device send, detects speech from a newly registered peer.
    check_count = 0

    def human_active():
        nonlocal check_count
        check_count += 1
        return check_count >= 2

    bridge.human_speech_active = human_active
    await service._send_device_state("start", service._generation)
    assert check_count >= 2
    assert conn.client_is_speaking is False
    assert service.wire.response_id is None
    assert service._generation == 1
    assert sent == []
    assert module._output_owner is None


async def test_native_opus_packet_checks_live_human_floor_even_after_reply_started(
    native,
):
    module, bridge = native
    conn, sent = connection()
    bridge.connections["mac-01"] = conn
    service = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    module._sessions["mac-01"] = service
    conn.client_is_speaking = True
    module._output_owner = "mac-01"
    bridge.human_speech_active = lambda: True
    await service._send_device_opus(b"encoded-opus-packet", service._generation)
    assert not any(isinstance(item, bytes) for item in sent)
    assert any(isinstance(item, str) and '"flush": true' in item for item in sent)
    assert not conn.client_is_speaking
    assert service._generation == 1
    assert service.wire.accept_output is False
    assert service.head_packets == 0
    assert module._output_owner is None
    assert module.status("mac-01")["head_audio_playback_acknowledged"] is False


async def test_native_voice_sends_one_video_frame_per_camera_receipt(native):
    """Audio stays live, but an unchanged JPEG is never replayed each second."""
    module, bridge = native
    conn, _sent = connection()
    bridge.connections["mac-01"] = conn
    service = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    observed = []

    class ModelSocket:
        async def send_json(self, packet):
            observed.append(packet)

    service._socket = ModelSocket()
    worker = asyncio.create_task(service._send_mic())
    try:
        service.queue_mic(b"\0" * 3200, True)
        await asyncio.wait_for(service._camera_wakeup.wait(), timeout=1)
        assert service._user_was_talking
        jpeg = b"\xff\xd8" + b"live camera" + b"\xff\xd9"
        service.latest_jpeg = jpeg
        service.latest_frame_time = module.time.monotonic()
        service._latest_frame_receipt_us = 125_678
        for _ in range(19):
            service.queue_mic(b"\0" * 3200, True)
        for _ in range(3):
            service.queue_mic(b"\0" * 3200, False)
        async with asyncio.timeout(2):
            while len([x for x in observed if
                       x["type"] == "input_audio_buffer.append"]) < 23:
                await asyncio.sleep(.001)
        appends = [x for x in observed if
                   x["type"] == "input_audio_buffer.append"]
        image_events = [x for x in appends if x.get("video_frames")]
        assert len(image_events) == 1
        assert base64.b64decode(image_events[0]["video_frames"][0]) == jpeg
        assert service.wire.frames_sent == 1
        assert service._last_video_sent_receipt_us == 125_678
        assert service._user_was_talking is False
        assert service.latest_jpeg is None
        # Another spoken turn cannot inherit that now-expired visual context.
        service.queue_mic(b"\0" * 3200, True)
        async with asyncio.timeout(1):
            while len([x for x in observed if
                       x["type"] == "input_audio_buffer.append"]) < 24:
                await asyncio.sleep(.001)
        assert service.latest_jpeg is None
        assert service._last_video_sent_receipt_us is None
    finally:
        service.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_native_camera_selects_keyframe_motion_and_static_refresh(native):
    """Use the Mac motion estimate; do not decode JPEG again on the server."""
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    service = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    service._user_was_talking = True
    service._video_turn = 1
    calls = []

    class FrameReply:
        status = 200

        def __init__(self, index):
            self.index = index
            self.headers = {
                "X-Desk-Robot-Id": "robot-01",
                "Content-Type": "image/jpeg",
                "X-Desk-Camera-Age-Ms": "0",
                "X-Desk-Camera-Receipt-Us": str([501, 502, 503, 503][index]),
                "X-Desk-Frame-Motion-Ppm": str([0, 0, 25_000, 25_000][index]),
            }

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def read(self):
            return b"\xff\xd8" + bytes([65 + self.index]) * 20 + b"\xff\xd9"

    class MacHTTP:
        def get(self, *_args, **_kwargs):
            index = min(len(calls), 3)
            calls.append(index)
            return FrameReply(index)

    worker = asyncio.create_task(service._camera(MacHTTP()))
    try:
        async with asyncio.timeout(2):
            while service.video_frames_selected < 1:
                await asyncio.sleep(.001)
        assert service._latest_frame_receipt_us == 501
        service._camera_wakeup.set()
        async with asyncio.timeout(2):
            while service.video_frames_skipped_static < 1:
                await asyncio.sleep(.001)
        assert service._latest_frame_receipt_us == 501
        service._camera_wakeup.set()
        async with asyncio.timeout(2):
            while service.video_frames_selected < 2:
                await asyncio.sleep(.001)
        assert service._latest_frame_receipt_us == 503
        service._camera_wakeup.set()
        async with asyncio.timeout(2):
            while service.video_frames_skipped_duplicate < 1:
                await asyncio.sleep(.001)
        assert service.video_frames_selected == 2
        assert service.video_frames_skipped_static == 1
        assert service.video_frames_skipped_duplicate == 1
    finally:
        service.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_native_camera_rejects_late_jpeg_from_previous_vad_turn(native):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    service = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    service._user_was_talking = True
    service._video_turn = 10
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowReply:
        status = 200
        headers = {
            "X-Desk-Robot-Id": "robot-01",
            "Content-Type": "image/jpeg",
            "X-Desk-Camera-Age-Ms": "0",
            "X-Desk-Camera-Receipt-Us": "7654321",
            "X-Desk-Frame-Motion-Ppm": "75000",
        }

        async def __aenter__(self):
            entered.set()
            await release.wait()
            return self

        async def __aexit__(self, *_):
            return False

        async def read(self):
            return b"\xff\xd8" + b"delayed JPEG" + b"\xff\xd9"

    class SlowHTTP:
        def get(self, *_args, **_kwargs):
            return SlowReply()

    worker = asyncio.create_task(service._camera(SlowHTTP()))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        service._user_was_talking = False
        service._video_turn += 1
        release.set()
        await asyncio.sleep(.03)
        assert service.latest_jpeg is None
        assert service.video_frames_selected == 0
    finally:
        release.set()
        service.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
