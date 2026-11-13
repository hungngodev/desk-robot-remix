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
    service._user_was_talking = True
    service._video_turn = 3
    service.latest_jpeg = b"old-frame"
    service._latest_frame_receipt_us = 123
    await service.barge()
    assert service._generation == 1
    assert service._video_turn == 4
    assert service.latest_jpeg is None
    assert service._latest_frame_receipt_us is None
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
        assert module.route_audio(conn, b"\0" * 3200, True)
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


async def test_native_completed_audio_transcript_has_opt_in_bounded_private_memory(
    native,
):
    """Only completed model ASR is stored, in chunks, never PCM or video."""
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    service = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    transcript = " ".join(["I noticed a red key on the desk"] * 21)
    event = {
        "type": "conversation.item.input_audio_transcription.completed",
        "item_id": "item_from_model_7",
        "transcript": transcript,
    }
    service._accept_heard_transcript(event)
    assert service._heard_queue.empty()  # separate consent defaults OFF
    service._transcript_memory_enabled = True
    service._accept_heard_transcript(event)
    count = service._heard_queue.qsize()
    assert 2 <= count <= 10
    service._accept_heard_transcript(event)  # backend event replay
    assert service._heard_queue.qsize() == count
    stored = []

    class Reply:
        status = 200

        def __init__(self, request):
            self.request = request

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def json(self):
            return {
                "robot_id": "robot-01", "stored": True,
                "source": "model_estimated_xiaozhi_audio_transcription",
            }

    class FakeMac:
        def post(self, url, **kwargs):
            assert url.endswith("/v1/pet/robot-01/omni-heard")
            assert kwargs["headers"]["Authorization"] == "Bearer " + "p" * 32
            request = kwargs["json"]
            assert 1 <= len(request["transcript"]) <= 240
            assert request["event_id"].startswith("omni_")
            stored.append(request)
            return Reply(request)

    worker = asyncio.create_task(service._persist_heard(FakeMac()))
    try:
        async with asyncio.timeout(2):
            while service.heard_memories_stored < count:
                await asyncio.sleep(.001)
        assert len(stored) == count
        assert len({x["event_id"] for x in stored}) == count
        assert " ".join(x["transcript"] for x in stored) == transcript
        assert service.heard_memories_dropped == 0
    finally:
        service.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.parametrize(
    ("spoken", "route"),
    [
        ("What do you see on the desk?", "look"),
        ("Please look at this object", "look"),
        ("What am I holding?", "look"),
        ("Can you tell me what you see?", "look"),
        ("Hey Pip, can you look around?", "look"),
        ("What's on my desk?", "look"),
        ("Do you see my keyboard?", "look"),
        ("Describe what you see.", "look"),
        ("Check your battery status", "status"),
        ("Could you check your battery status?", "status"),
        ("How much battery is left?", "status"),
        ("What's your power level?", "status"),
        ("Is the pickup job done?", "latest-pickup"),
        ("Did you pick up the key already?", "latest-pickup"),
        ("Can you check the pickup job status?", "latest-pickup"),
        ("What just happened?", "interaction-context"),
        ("What did you just notice?", "interaction-context"),
        ("Could you tell me what just happened?", "interaction-context"),
        ("Move forward", None),
        ("Pick up this key", None),
        ("Start the charger", None),
        ("I heard somebody say look at this", None),
        ("I can see a key", None),
        ("Can you pick up this key?", None),
        ("Please start charging now", None),
        ("Stop your motors now", None),
        ("Do you remember yesterday?", "voice-context"),
        ("What did I tell you about my key?", "voice-context"),
        ("Can you recall what we discussed?", "voice-context"),
        ("Have we talked about the keyboard?", "voice-context"),
    ],
)
def test_native_speech_tools_allow_only_explicit_readonly_requests(
    native, spoken, route,
):
    module, _ = native
    request = module.native_readonly_request(spoken)
    assert (request[0] if request else None) == route
    if request:
        assert request[0] in {
            "look", "status", "latest-pickup", "interaction-context",
            "voice-context",
        }


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("Do you remember anything?", {}),
        ("Do you remember yesterday?", {}),
        ("What do you remember?", {}),
        ("Tell me what you remember", {}),
        ("What did I tell you about the green mug?", {
            "question": "What did I tell you about the green mug?",
        }),
        ("Remind me about my key", {
            "question": "Remind me about my key",
        }),
    ],
)
def test_native_memory_request_chooses_recent_or_topic_query(
    native, spoken, expected,
):
    module, _ = native
    route, payload = module.native_readonly_request(spoken)
    assert route == "voice-context"
    assert payload == expected


@pytest.mark.parametrize(
    ("spoken", "routes"),
    [
        (
            "Can you look around and check your battery status?",
            ("look", "status"),
        ),
        (
            "What do you see and did you pick up the key already?",
            ("look", "latest-pickup"),
        ),
        (
            "Do you remember the key and the mug?",
            ("voice-context",),
        ),
        (
            "Please pick up the key and look around",
            ("look",),
        ),
        (
            "Drive forward and start charging",
            (),
        ),
        (
            "Look at the desk then check your battery status also what just happened?",
            ("look", "status", "interaction-context"),
        ),
    ],
)
def test_native_compound_speech_dispatches_only_explicit_readonly_tools(
    native, spoken, routes,
):
    module, _ = native
    selected = module.native_readonly_requests(spoken)
    assert tuple(route for route, _ in selected) == routes
    assert len(selected) <= 3
    assert all(route not in ("pickup", "stop", "move", "charge") for route in routes)


def test_native_compound_asr_queues_distinct_tools_once_per_real_audio_item(native):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session._live_transcript_enabled = True
    original = {
        "item_id": "compound_1",
        "transcript": "Look at the desk and check your battery status",
    }
    session._queue_readonly_tool(original)
    session._queue_readonly_tool(original)
    session._queue_readonly_tool({
        "item_id": "compound_2", "transcript": original["transcript"],
    })
    assert session._readonly_queue.qsize() == 2
    first = session._readonly_queue.get_nowait()
    second = session._readonly_queue.get_nowait()
    assert (first[0], second[0]) == ("look", "status")
    assert first[2:] == second[2:]
    assert first[3] == session._readonly_turn


@pytest.mark.parametrize("superseded_by", [
    "new_human_turn", "barge_generation", "active_new_speech",
])
def test_native_completed_asr_rejects_older_committed_audio_item(
    native, superseded_by,
):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._readonly_turn = 1
    session._pending_audio_commits.append((0, 1))
    if superseded_by == "new_human_turn":
        session._readonly_turn += 1
    elif superseded_by == "barge_generation":
        session._generation += 1
    else:
        session._user_was_talking = True
    session._bind_native_audio_commit({
        "type": "input_audio_buffer.committed",
        "item_id": "old_audio_item",
        "event": {"turn_id": 14},
    })
    assert not session._accept_current_audio_item({
        "type": "conversation.item.input_audio_transcription.completed",
        "item_id": "old_audio_item",
        "transcript": "What do you see on the desk?",
    })
    assert session.native_readonly_tools_dropped == 1
    assert not session.closed


def test_native_only_current_committed_audio_can_enter_tools_and_memory(native):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True
    session._readonly_turn = 4
    event = {
        "type": "conversation.item.input_audio_transcription.completed",
        "item_id": "verified_input_item",
        "transcript": "Check your battery status",
    }
    assert not session._accept_current_audio_item(event)
    assert session._readonly_queue.empty()
    assert session._heard_queue.empty()
    session._pending_audio_commits.append((0, 4))
    session._bind_native_audio_commit({
        "type": "input_audio_buffer.committed",
        "item_id": "verified_input_item",
        "event": {"turn_id": 42},
    })
    assert session._accept_current_audio_item(event)
    session._accept_heard_transcript(event)
    session._queue_readonly_tool(event)
    assert session._readonly_queue.get_nowait()[0] == "status"
    assert session._heard_queue.qsize() == 1
    assert not session._accept_current_audio_item(event)  # replay
    assert session.native_readonly_tools_dropped == 2


def test_native_model_reordered_input_commits_fail_closed(native):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._pending_audio_commits.extend([(0, 0), (0, 0)])
    session._bind_native_audio_commit({
        "type": "input_audio_buffer.committed",
        "item_id": "first", "event": {"turn_id": 88},
    })
    session._bind_native_audio_commit({
        "type": "input_audio_buffer.committed",
        "item_id": "reordered", "event": {"turn_id": 90},
    })
    assert session.closed
    assert session.last_error == "Native model audio commit sequence inconsistent"


@pytest.mark.parametrize("invalid", [
    {"item_id": "", "event": {"turn_id": 1}},
    {"item_id": "nonascii_\u00f1", "event": {"turn_id": 1}},
    {"item_id": "safe", "event": {"turn_id": True}},
    {"item_id": "safe", "event": {"turn_id": "1"}},
    {"item_id": "safe"},
])
def test_native_audio_commit_rejects_bad_identity_without_consuming_local_turn(
    native, invalid,
):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session._pending_audio_commits.append((0, 0))
    session._bind_native_audio_commit({
        "type": "input_audio_buffer.committed", **invalid,
    })
    assert len(session._pending_audio_commits) == 1
    assert not session._asr_item_turns
    assert session.native_readonly_tools_dropped == 1


async def test_native_speech_tool_uses_pinned_mac_bridge_once_per_asr_item(
    native, monkeypatch,
):
    import types

    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True
    calls = []

    async def call(current, route, payload):
        calls.append((current, route, payload))
        return {"robot_id": "robot-01", "answer": "Maybe a key"}

    pkg = types.ModuleType("plugins_func")
    pkg.__path__ = []
    funcs = types.ModuleType("plugins_func.functions")
    funcs.__path__ = []
    tools = types.ModuleType("plugins_func.functions.desk_robot_tools")
    tools.call = call
    for key, val in (
        ("plugins_func", pkg),
        ("plugins_func.functions", funcs),
        ("plugins_func.functions.desk_robot_tools", tools),
    ):
        monkeypatch.setitem(sys.modules, key, val)
    transcript = {
        "item_id": "model_item_1",
        "transcript": "What do you see near me?",
    }
    session._queue_readonly_tool(transcript)
    session._queue_readonly_tool(transcript)
    # Different model ASR item IDs may replay the exact same request.
    session._queue_readonly_tool({
        "item_id": "model_item_1b", "transcript": transcript["transcript"],
    })
    assert session._readonly_queue.qsize() == 1
    # A complete spoken sentence closes its VIDEO turn before a slow
    # read-only lookup finishes. That must not revoke the same human request.
    human_request = session._readonly_turn
    session._video_turn += 1
    assert session._readonly_turn == human_request
    task = asyncio.create_task(session._readonly_tool_worker())
    try:
        async with asyncio.timeout(1):
            while session.native_readonly_tools_completed < 1:
                await asyncio.sleep(.005)
        assert calls == [(conn, "look", {"question": transcript["transcript"]})]
        assert session._context_wakeup.is_set()
        assert session.native_readonly_tools_dropped == 0
    finally:
        session.closed = True
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "result",
    [
        {"robot_id": "robot-02", "answer": "Other pet private data"},
        {"robot_id": "robot-01", "motor_authorized": True},
        {"robot_id": "robot-01", "charging_authorized": True},
        {"answer": "Unidentified head response"},
    ],
)
async def test_native_voice_tool_rejects_wrong_pet_and_action_permissions(
    native, monkeypatch, result,
):
    import types

    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True

    async def call(current, route, payload):
        return result

    pkg = types.ModuleType("plugins_func")
    pkg.__path__ = []
    funcs = types.ModuleType("plugins_func.functions")
    funcs.__path__ = []
    tools = types.ModuleType("plugins_func.functions.desk_robot_tools")
    tools.call = call
    for key, val in (
        ("plugins_func", pkg),
        ("plugins_func.functions", funcs),
        ("plugins_func.functions.desk_robot_tools", tools),
    ):
        monkeypatch.setitem(sys.modules, key, val)
    session._queue_readonly_tool({
        "item_id": "native_wrong_owner",
        "transcript": "Check your battery status",
    })
    worker = asyncio.create_task(session._readonly_tool_worker())
    try:
        async with asyncio.timeout(1):
            while session.native_readonly_tools_dropped < 1:
                await asyncio.sleep(.005)
        assert session.native_readonly_tools_completed == 0
        assert not session._context_wakeup.is_set()
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_compound_native_tool_worker_executes_two_existing_mac_readonly_routes(
    native, monkeypatch,
):
    import types

    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True
    received = []

    async def call(current, route, payload):
        assert current is conn
        received.append((route, payload))
        await asyncio.sleep(0)
        return {
            "robot_id": "robot-01", "motor_authorized": False,
            "charging_authorized": False,
        }

    pkg = types.ModuleType("plugins_func")
    pkg.__path__ = []
    funcs = types.ModuleType("plugins_func.functions")
    funcs.__path__ = []
    tools = types.ModuleType("plugins_func.functions.desk_robot_tools")
    tools.call = call
    for key, val in (
        ("plugins_func", pkg),
        ("plugins_func.functions", funcs),
        ("plugins_func.functions.desk_robot_tools", tools),
    ):
        monkeypatch.setitem(sys.modules, key, val)
    transcript = {
        "item_id": "two_tools_one_turn",
        "transcript": "Can you look around and check your battery status?",
    }
    session._queue_readonly_tool(transcript)
    session._queue_readonly_tool({
        "item_id": "two_tools_duplicate", "transcript": transcript["transcript"],
    })
    assert session._readonly_queue.qsize() == 2
    worker = asyncio.create_task(session._readonly_tool_worker())
    try:
        async with asyncio.timeout(1):
            while session.native_readonly_tools_completed < 2:
                await asyncio.sleep(.005)
        assert [route for route, _ in received] == ["look", "status"]
        assert session._context_wakeup.is_set()
        assert session.native_readonly_tools_dropped == 0
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_native_fast_battery_context_before_slow_vision_completes(
    native, monkeypatch,
):
    """Compound status must not sit behind a 24 second VLM."""
    import types

    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True
    started, release = asyncio.Event(), asyncio.Event()

    async def call(current, route, payload):
        assert current is conn
        if route == "look":
            started.set()
            await release.wait()
        return {"robot_id": "robot-01", "motor_authorized": False}

    pkg = types.ModuleType("plugins_func")
    pkg.__path__ = []
    funcs = types.ModuleType("plugins_func.functions")
    funcs.__path__ = []
    tools = types.ModuleType("plugins_func.functions.desk_robot_tools")
    tools.call = call
    for key, val in (
        ("plugins_func", pkg),
        ("plugins_func.functions", funcs),
        ("plugins_func.functions.desk_robot_tools", tools),
    ):
        monkeypatch.setitem(sys.modules, key, val)
    session._queue_readonly_tool({
        "item_id": "compound_slow_look",
        "transcript": "Look at the desk and check your battery status",
    })
    worker = asyncio.create_task(session._readonly_tool_worker())
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        async with asyncio.timeout(.8):
            while session.native_readonly_tools_completed < 1:
                await asyncio.sleep(.005)
        assert not release.is_set()
        assert session._context_wakeup.is_set()
        release.set()
        async with asyncio.timeout(.8):
            while session.native_readonly_tools_completed < 2:
                await asyncio.sleep(.005)
    finally:
        release.set()
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_native_barge_cancels_entire_inflight_compound_tool_batch(
    native, monkeypatch,
):
    import types

    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True
    started, cancelled = set(), set()
    both_started = asyncio.Event()

    async def call(current, route, payload):
        started.add(route)
        if len(started) == 2:
            both_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.add(route)

    pkg = types.ModuleType("plugins_func")
    pkg.__path__ = []
    funcs = types.ModuleType("plugins_func.functions")
    funcs.__path__ = []
    tools = types.ModuleType("plugins_func.functions.desk_robot_tools")
    tools.call = call
    for key, val in (
        ("plugins_func", pkg),
        ("plugins_func.functions", funcs),
        ("plugins_func.functions.desk_robot_tools", tools),
    ):
        monkeypatch.setitem(sys.modules, key, val)
    session._queue_readonly_tool({
        "item_id": "compound_interrupt",
        "transcript": "Look at the desk and check your battery status",
    })
    worker = asyncio.create_task(session._readonly_tool_worker())
    try:
        await asyncio.wait_for(both_started.wait(), timeout=1)
        session._readonly_turn += 1
        session._readonly_inflight.cancel()
        async with asyncio.timeout(.8):
            while session._readonly_inflight is not None:
                await asyncio.sleep(.005)
        assert cancelled == {"look", "status"}
        assert session.native_readonly_tools_completed == 0
        assert not session._context_wakeup.is_set()
        assert not worker.done()
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.parametrize("invalid", [
    {"robot_id": "robot-01", "motor_authorized": "false"},
    {"robot_id": "robot-01", "charging_authorized": 0},
    {"robot_id": "robot-02", "charging_authorized": False},
])
async def test_native_batch_refuses_malformed_authority_and_cross_pet(
    native, monkeypatch, invalid,
):
    import types

    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True

    async def call(current, route, payload):
        return invalid

    pkg = types.ModuleType("plugins_func")
    pkg.__path__ = []
    funcs = types.ModuleType("plugins_func.functions")
    funcs.__path__ = []
    tools = types.ModuleType("plugins_func.functions.desk_robot_tools")
    tools.call = call
    for key, val in (
        ("plugins_func", pkg),
        ("plugins_func.functions", funcs),
        ("plugins_func.functions.desk_robot_tools", tools),
    ):
        monkeypatch.setitem(sys.modules, key, val)
    session._queue_readonly_tool({
        "item_id": "malformed_receipt",
        "transcript": "Check your battery status",
    })
    worker = asyncio.create_task(session._readonly_tool_worker())
    try:
        async with asyncio.timeout(.8):
            while session.native_readonly_tools_dropped < 1:
                await asyncio.sleep(.005)
        assert session.native_readonly_tools_completed == 0
        assert not session._context_wakeup.is_set()
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_ambiguous_completed_asr_uses_existing_mac_planner_then_two_real_tools(
    native, monkeypatch,
):
    import types

    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True
    question = "Could you tell me whether the object is still there?"
    calls = []

    async def call(current, route, payload):
        assert current is conn
        calls.append((route, payload))
        if route == "plan-readonly":
            assert payload["transcript"] == question
            return {
                "robot_id": "robot-01",
                "source": "existing_mac_ollama_readonly_route_selection",
                "untrusted_model_selection": True,
                "model_can_arm_motors": False,
                "motor_authorized": False,
                "charging_authorized": False,
                "tools": [
                    {"route": "look", "payload": {"question": question}},
                    {"route": "status", "payload": {}},
                ],
            }
        await asyncio.sleep(0)
        return {
            "robot_id": "robot-01",
            "motor_authorized": False,
            "charging_authorized": False,
        }

    pkg = types.ModuleType("plugins_func")
    pkg.__path__ = []
    funcs = types.ModuleType("plugins_func.functions")
    funcs.__path__ = []
    tools = types.ModuleType("plugins_func.functions.desk_robot_tools")
    tools.call = call
    for key, val in (
        ("plugins_func", pkg),
        ("plugins_func.functions", funcs),
        ("plugins_func.functions.desk_robot_tools", tools),
    ):
        monkeypatch.setitem(sys.modules, key, val)
    session._queue_readonly_tool({
        "item_id": "ambiguous_real_utterance",
        "transcript": question,
    })
    assert session._readonly_queue.qsize() == 1
    assert session._readonly_queue._queue[0][0] == "plan-readonly"
    worker = asyncio.create_task(session._readonly_tool_worker())
    try:
        async with asyncio.timeout(1):
            while session.native_readonly_tools_completed < 2:
                await asyncio.sleep(.005)
        assert [route for route, _ in calls].count("plan-readonly") == 1
        assert {route for route, _ in calls} == {
            "plan-readonly", "look", "status",
        }
        assert len(calls) == 3
        assert session._context_wakeup.is_set()
        assert session.native_readonly_tools_dropped == 0
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_native_semantic_planner_cannot_queue_model_proposed_motor_actions(
    native, monkeypatch,
):
    import types

    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True
    calls = []

    async def call(current, route, payload):
        calls.append(route)
        if route == "plan-readonly":
            return {
                "robot_id": "robot-01",
                "source": "existing_mac_ollama_readonly_route_selection",
                "motor_authorized": False,
                "charging_authorized": False,
                "tools": [
                    {"route": "move", "payload": {"command": "drive 40 40 250"}},
                    {"route": "charge", "payload": {"enabled": True}},
                    {"route": "status", "payload": {}},
                ],
            }
        return {"robot_id": "robot-01", "motor_authorized": False}

    pkg = types.ModuleType("plugins_func")
    pkg.__path__ = []
    funcs = types.ModuleType("plugins_func.functions")
    funcs.__path__ = []
    tools = types.ModuleType("plugins_func.functions.desk_robot_tools")
    tools.call = call
    for key, val in (
        ("plugins_func", pkg),
        ("plugins_func.functions", funcs),
        ("plugins_func.functions.desk_robot_tools", tools),
    ):
        monkeypatch.setitem(sys.modules, key, val)
    session._queue_readonly_tool({
        "item_id": "ambiguous_model_hallucination",
        "transcript": "Could you tell me whether the object is still there?",
    })
    worker = asyncio.create_task(session._readonly_tool_worker())
    try:
        async with asyncio.timeout(1):
            while session.native_readonly_tools_dropped < 1:
                await asyncio.sleep(.005)
        assert calls == ["plan-readonly"]
        assert session.native_readonly_tools_completed == 0
        assert not session._context_wakeup.is_set()
        assert "move" not in calls and "charge" not in calls
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_native_speech_tool_old_result_cannot_enter_next_human_turn(
    native, monkeypatch,
):
    import types

    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True
    entered = asyncio.Event()

    async def call(conn, route, payload):
        entered.set()
        await asyncio.Event().wait()

    pkg = types.ModuleType("plugins_func")
    pkg.__path__ = []
    funcs = types.ModuleType("plugins_func.functions")
    funcs.__path__ = []
    tool = types.ModuleType("plugins_func.functions.desk_robot_tools")
    tool.call = call
    for key, val in (
        ("plugins_func", pkg),
        ("plugins_func.functions", funcs),
        ("plugins_func.functions.desk_robot_tools", tool),
    ):
        monkeypatch.setitem(sys.modules, key, val)
    session._queue_readonly_tool({
        "item_id": "model_item_2", "transcript": "Check your battery status"
    })
    worker = asyncio.create_task(session._readonly_tool_worker())
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        session._video_turn += 1
        session._readonly_turn += 1  # A genuinely NEW human request.
        session._readonly_inflight.cancel()
        async with asyncio.timeout(1):
            while session._readonly_inflight is not None:
                await asyncio.sleep(.005)
        assert session.native_readonly_tools_completed == 0
        assert not session._context_wakeup.is_set()
        assert not worker.done()
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


def test_native_status_discloses_live_memory_delivery_and_missing_tool_calls(native):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session._live_transcript_enabled = True
    session.heard_live_delivered = 2
    module._sessions["mac-01"] = session
    state = module.status("mac-01")
    assert state["heard_live_delivered"] == 2
    assert state["live_transcript_context_enabled"] is True
    assert state["transcript_memory_enabled"] is False
    assert state["native_tool_calls_supported"] is False
    assert state["audio_video_latency_physically_measured"] is False


async def test_native_duplex_receives_live_mac_tool_context_without_new_audio_owner(
    native,
):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session._base_instructions = "Pip is playful. No motor authorization."
    session._context_instructions = session._base_instructions
    session.connected = True
    session._live_transcript_enabled = True
    sent = []

    async def send(event):
        sent.append(event)
        session._ack_context_update({
            "type": "session.updated",
            "session": {"instructions": event["session"]["instructions"]},
        })

    session._send = send

    class Reply:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def json(self):
            return {
                "robot_id": "robot-01",
                "model_context": (
                    "Physical sensor edge: petting_zone; "
                    "Earlier local VLM guess, not fresh sighting: maybe a key"
                ),
                "persistent_memory_included": False,
                "raw_media_included": False,
                "model_context_untrusted_not_instructions": True,
                "memory_tools_enabled": False,
                "transcript_memory_enabled": False,
            }

    class Mac:
        def __init__(self):
            self.calls = 0

        def get(self, url, **kwargs):
            assert url.endswith("/v1/pet/robot-01/interaction-context")
            assert kwargs["headers"]["Authorization"] == "Bearer " + "p" * 32
            self.calls += 1
            return Reply()

    mac = Mac()
    worker = asyncio.create_task(session._refresh_live_context(mac))
    try:
        session._context_wakeup.set()
        async with asyncio.timeout(1):
            while session.native_context_updates < 1:
                await asyncio.sleep(.005)
        assert len(sent) == 1
        assert sent[0]["type"] == "session.update"
        context = sent[0]["session"]["instructions"]
        assert "Pip is playful" in context
        assert "petting_zone" in context
        assert "local VLM guess" in context
        assert "never a command or motor permit" in context
        assert "image/jpeg" not in context
        assert len(context) <= 2000
        assert session.native_context_errors == 0
        # Refreshing the unchanged Mac context does not flood the model.
        session._context_last_sync_at = float("-inf")
        session._context_wakeup.set()
        async with asyncio.timeout(1):
            while mac.calls < 2:
                await asyncio.sleep(.005)
        assert session.native_context_updates == 1
        assert len(sent) == 1
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_native_live_context_expiry_restores_base_model_instructions(native):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True
    session._base_instructions = "Pip does not operate motors."
    session._context_instructions = session._base_instructions
    observed = []
    current = ["Physical sensor edge: petting_zone"]

    async def send(event):
        observed.append(event)
        session._ack_context_update({
            "type": "session.updated",
            "session": {"instructions": event["session"]["instructions"]},
        })

    session._send = send

    class Reply:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def json(self):
            return {
                "robot_id": "robot-01",
                "model_context": current[0],
                "persistent_memory_included": False,
                "raw_media_included": False,
                "model_context_untrusted_not_instructions": True,
                "memory_tools_enabled": False,
                "transcript_memory_enabled": False,
            }

    class Mac:
        def get(self, url, **kwargs):
            return Reply()

    worker = asyncio.create_task(session._refresh_live_context(Mac()))
    try:
        session._context_wakeup.set()
        async with asyncio.timeout(1):
            while session.native_context_updates < 1:
                await asyncio.sleep(.005)
        assert "petting_zone" in observed[-1]["session"]["instructions"]
        # The Mac's 30s TTL has expired; the model must no longer retain
        # a previously truthful but now stale situational instruction.
        current[0] = ""
        session._context_last_sync_at = float("-inf")
        session._context_wakeup.set()
        async with asyncio.timeout(1):
            while session.native_context_updates < 2:
                await asyncio.sleep(.005)
        assert observed[-1]["session"]["instructions"] == (
            session._base_instructions
        )
        assert session.native_context_errors == 0
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_native_context_send_is_not_counted_without_backend_ack(native):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True
    sent = []

    async def send(event):
        sent.append(event)
        # A stale server acknowledgement must not certify new context.
        session._ack_context_update({
            "type": "session.updated",
            "session": {"instructions": "older unrelated turn"},
        })

    session._send = send

    class Reply:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def json(self):
            return {
                "robot_id": "robot-01",
                "model_context": "Physical sensor edge: touch_tap",
                "persistent_memory_included": False,
                "raw_media_included": False,
                "model_context_untrusted_not_instructions": True,
                "memory_tools_enabled": False,
                "transcript_memory_enabled": False,
            }

    class Mac:
        def get(self, url, **kwargs):
            return Reply()

    worker = asyncio.create_task(session._refresh_live_context(Mac()))
    try:
        session._context_wakeup.set()
        async with asyncio.timeout(2):
            while session.native_context_errors < 1:
                await asyncio.sleep(.01)
        assert len(sent) == 1
        assert session.native_context_updates == 0
        assert session._context_pending is None
        assert session._context_instructions == session.wire.instructions
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_native_live_context_refuses_cross_robot_and_stale_turn_data(native):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True
    entered = asyncio.Event()
    release = asyncio.Event()
    sent = []

    async def send(event):
        sent.append(event)

    session._send = send

    class Reply:
        status = 200

        async def __aenter__(self):
            entered.set()
            await release.wait()
            return self

        async def __aexit__(self, *_):
            return False

        async def json(self):
            return {
                "robot_id": "robot-01",
                "model_context": "An old camera guesses a red toy",
                "persistent_memory_included": False,
                "raw_media_included": False,
                "model_context_untrusted_not_instructions": True,
                "memory_tools_enabled": False,
                "transcript_memory_enabled": False,
            }

    class Mac:
        def get(self, url, **kwargs):
            return Reply()

    worker = asyncio.create_task(session._refresh_live_context(Mac()))
    try:
        session._context_wakeup.set()
        await asyncio.wait_for(entered.wait(), timeout=1)
        session._video_turn += 1  # real new human voice while HTTP is pending
        release.set()
        await asyncio.sleep(.02)
        assert sent == []
        assert session.native_context_updates == 0
    finally:
        session.closed = True
        release.set()
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.parametrize("revoked", ["private_memory", "transcript_memory"])
async def test_native_consent_toggle_retires_model_with_old_private_context(
    native, revoked,
):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True
    if revoked == "private_memory":
        session._memory_tools_enabled = True
    else:
        session._transcript_memory_enabled = True

    class Reply:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def json(self):
            return {
                "robot_id": "robot-01",
                "model_context": "Physical sensor edge: petting_zone",
                "persistent_memory_included": False,
                "raw_media_included": False,
                "model_context_untrusted_not_instructions": True,
                "memory_tools_enabled": False,
                "transcript_memory_enabled": False,
            }

    class Mac:
        def get(self, url, **kwargs):
            return Reply()

    task = asyncio.create_task(session._refresh_live_context(Mac()))
    session._context_wakeup.set()
    await asyncio.wait_for(task, timeout=1)
    assert session.closed
    assert session.last_error == (
        "Mac private memory consent changed; native session must restart"
    )
    assert session.native_context_updates == 0


async def test_native_context_revocation_closes_model_session_not_just_cache(native):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True

    class Reply:
        status = 403

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    class Mac:
        def get(self, url, **kwargs):
            return Reply()

    task = asyncio.create_task(session._refresh_live_context(Mac()))
    session._context_wakeup.set()
    await asyncio.wait_for(task, timeout=1)
    assert session.closed
    assert session.last_error == "Mac live context permission revoked"
    assert session.native_context_updates == 0


async def test_native_persona_negotiates_live_asr_without_disk_permission(native):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )

    class Reply:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def json(self):
            return {
                "robot_id": "robot-01", "instructions": "Be kind and concise.",
                "model_can_arm_motors": False,
                "live_transcript_context_enabled": True,
                "transcript_memory_enabled": False,
            }

    class Mac:
        def get(self, url, **kwargs):
            assert url.endswith("/v1/pet/robot-01/omni-context")
            return Reply()

    await session._load_private_persona(Mac())
    assert session._live_transcript_enabled is True
    assert session._transcript_memory_enabled is False
    assert session.wire.instructions == "Be kind and concise."


async def test_native_asr_live_only_context_does_not_count_as_saved_memory(native):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session._live_transcript_enabled = True
    assert session._transcript_memory_enabled is False
    event = {"item_id": "asr1", "transcript": "That little key moved"}
    session._accept_heard_transcript(event)
    session._accept_heard_transcript(event)
    assert session._heard_queue.qsize() == 1
    delivered = []

    class Reply:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def json(self):
            return {
                "robot_id": "robot-01", "stored": False,
                "ephemeral_context_added": True,
                "source": "model_estimated_xiaozhi_audio_transcription",
            }

    class Mac:
        def post(self, url, **kwargs):
            delivered.append(kwargs["json"])
            assert url.endswith("/v1/pet/robot-01/omni-heard")
            return Reply()

    worker = asyncio.create_task(session._persist_heard(Mac()))
    try:
        async with asyncio.timeout(1):
            while session.heard_live_delivered < 1:
                await asyncio.sleep(.001)
        assert len(delivered) == 1
        assert delivered[0]["transcript"] == "That little key moved"
        assert session.heard_memories_stored == 0
        assert session.heard_memories_dropped == 0
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_first_human_camera_wake_does_not_double_fetch_on_esp32(native):
    """The initial VAD event is consumed before the first Mac camera HTTP."""
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    service = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    service._user_was_talking = True
    service._video_turn = 1
    service._camera_wakeup.set()
    calls = []
    seen = asyncio.Event()

    class CameraReply:
        status = 503
        headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    class CameraHTTP:
        def get(self, *_args, **_kwargs):
            calls.append(1)
            seen.set()
            return CameraReply()

    worker = asyncio.create_task(service._camera(CameraHTTP()))
    try:
        await asyncio.wait_for(seen.wait(), timeout=1)
        await asyncio.sleep(.04)  # much shorter than the 800ms idle cadence
        assert len(calls) == 1
        service._camera_wakeup.set()  # new independent VAD/motion wake
        async with asyncio.timeout(1):
            while len(calls) < 2:
                await asyncio.sleep(.001)
        assert len(calls) == 2
    finally:
        service.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_human_fleet_preemption_cancels_idle_queued_audio_while_peer_head_hangs(
    native,
):
    """A slow physical head must not hold up other independent STOPs."""
    module, _bridge = native
    slow_entered, slow_release, fast_stopped = (
        asyncio.Event(), asyncio.Event(), asyncio.Event()
    )
    stopped = []

    class Peer:
        def __init__(self, device, slow=False, speaking=False):
            self.device = device
            self.closed = False
            self.conn = SimpleNamespace(client_is_speaking=speaking)
            self.slow = slow

        async def _invalidate_head_first(self):
            stopped.append(self.device)
            if self.slow:
                slow_entered.set()
                await slow_release.wait()
            else:
                fast_stopped.set()
            return ({"type": "response.cancel"},)

        def _schedule_remote_cancel(self, events):
            assert events[0]["type"] == "response.cancel"

    module._sessions = {
        "mac-01": Peer("mac-01"),
        "mac-02": Peer("mac-02", slow=True, speaking=True),
        # This model has queued sound but has not issued TTS START yet.
        "mac-03": Peer("mac-03", slow=False, speaking=False),
    }
    module._output_owner = "mac-02"
    task = asyncio.create_task(module.preempt_others_for_human("mac-01"))
    try:
        await asyncio.wait_for(slow_entered.wait(), timeout=1)
        await asyncio.wait_for(fast_stopped.wait(), timeout=1)
        assert "mac-03" in stopped  # queued silent response invalidated
        assert "mac-02" in stopped
        assert module._output_owner == "mac-02"  # no false physical flush ACK
        assert not task.done()
    finally:
        slow_release.set()
        await asyncio.wait_for(task, timeout=1)
    assert module._output_owner is None
    assert "mac-01" not in stopped


async def test_human_fleet_failed_head_flush_keeps_audio_owner_blocked(native):
    module, _bridge = native
    invalidated = []

    class Broken:
        closed = False
        conn = SimpleNamespace(client_is_speaking=True)

        async def _invalidate_head_first(self):
            raise OSError("head send did not complete")

        def _schedule_remote_cancel(self, events):
            raise AssertionError("Failed head cannot report physical flush")

    class Healthy:
        closed = False
        conn = SimpleNamespace(client_is_speaking=False)

        async def _invalidate_head_first(self):
            invalidated.append("queued model cancelled")
            return ({"type": "response.cancel"},)

        def _schedule_remote_cancel(self, events):
            assert events[0]["type"] == "response.cancel"

    module._sessions = {
        "mac-01": Healthy(), "mac-02": Broken(), "mac-03": Healthy()
    }
    module._output_owner = "mac-02"
    await module.preempt_others_for_human("mac-01")
    assert invalidated == ["queued model cancelled"]
    assert module._output_owner == "mac-02"
