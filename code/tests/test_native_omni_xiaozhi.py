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
    # Match the pinned installer layout: the pure read-only intent parser
    # sits beside the native transport adapter, not in the Mac package.
    monkeypatch.syspath_prepend(str(ROOT / "laptop/server/overlay"))
    spec = importlib.util.spec_from_file_location(
        "desk_robot_native_omni",
        ROOT / "laptop/server/overlay/desk_robot_native_omni.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "desk_robot_native_omni", module)
    spec.loader.exec_module(module)
    # Existing media/speaker unit tests simulate a pet whose operator
    # explicitly enabled autonomy. Production defaults remain fail closed
    # until Mac's authenticated pet policy is fetched.
    actual_session = module.NativeOmniSession

    class ConsentfulFakeSession(actual_session):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # The loopback fake grants what the real Mac endpoint must grant
            # on every native startup, without ever authenticating production.
            self._mac_context_verified = True
            self._last_authenticated_mac_at = module.time.monotonic()
            self._pet_autonomy_enabled = True

    module.NativeOmniSession = ConsentfulFakeSession
    return module, fake_bridge


def test_native_voice_intents_are_one_pure_shared_module(native):
    """The pinned session aliases one read-only router; no duplicated grammar."""
    module, _bridge = native
    import desk_robot_voice_intents as intents

    assert module.native_readonly_request is intents.native_readonly_request
    assert module.native_readonly_requests is intents.native_readonly_requests
    assert module.native_grounded_fact is intents.native_grounded_fact
    assert module._advice_only_request is intents._advice_only_request
    assert module.native_readonly_request("How do I charge a battery?") is None
    assert module.native_readonly_request("Check your battery") == (
        "power-status", {},
    )
    assert module.native_readonly_request("What color is this mug?")[0] == "look"
    assert set(route for route, _ in module.native_readonly_requests(
        "Look at my desk, and check your battery"
    )) == {"look", "power-status"}


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


def test_native_audiovisual_readiness_requires_live_mic_and_fresh_selected_video(
    native,
):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    module._sessions["mac-01"] = session
    try:
        first = module.status("mac-01")
        assert first["continuous_av_input_receiving"] is False
        assert first["microphone_last_frame_age_ms"] is None
        session.connected = True
        session._camera_stream_connected = True
        session.wire.frames_sent = 1
        session._last_video_selected_at = module.time.monotonic()
        assert module.status("mac-01")["continuous_av_input_receiving"] is False
        session.queue_mic(b"\0" * 3200, False)  # actual quiet-room PCM
        ready = module.status("mac-01")
        assert ready["continuous_av_input_receiving"] is True
        assert 0 <= ready["microphone_last_frame_age_ms"] <= 200
        session._last_mic_received_at -= 3
        assert module.status("mac-01")["continuous_av_input_receiving"] is False
        session._last_mic_received_at = module.time.monotonic()
        session._last_video_selected_at -= 5
        assert module.status("mac-01")["continuous_av_input_receiving"] is False
        session._last_video_selected_at = module.time.monotonic()
        session._camera_stream_connected = False
        assert module.status("mac-01")["continuous_av_input_receiving"] is False
    finally:
        session.closed = True


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


async def test_native_audio_refused_by_mac_speaker_never_sends_stop_or_records_history(
    native, monkeypatch,
):
    """A refused TTS START cannot become delivered speech or stop Mac TTS."""
    module, bridge = native
    conn, sent = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._external_speech_active = True
    conn.client_is_speaking = True  # This belongs to the Mac lease, not native.
    session._tool_audio_response_id = "tool_unclaimed"
    session._tool_reply_pending["tool_unclaimed"] = (
        0, "Where is my key?", "I can see a key.",
    )

    class Encoder:
        def __init__(self, rate, channels, mode):
            assert (rate, channels, mode) == (16000, 1, "audio")
        def encode(self, pcm, samples):
            raise AssertionError("Blocked native reply must never encode speaker PCM")

    monkeypatch.setitem(sys.modules, "opuslib_next", SimpleNamespace(
        Encoder=Encoder, APPLICATION_AUDIO="audio",
    ))
    session.outgoing.put_nowait(("tool_unclaimed", bytes(9600)))
    session.outgoing.put_nowait(("tool_unclaimed", bytes(9600)))
    session.outgoing.put_nowait(("tool_unclaimed", None))
    playback = asyncio.create_task(session._play())
    try:
        async with asyncio.timeout(1):
            while not session.outgoing.empty():
                await asyncio.sleep(.005)
        await asyncio.sleep(.005)
        assert sent == []  # No native TTS START, STOP or PCM may leak.
        assert conn.client_is_speaking is True
        assert session.native_tool_audio_sent == 0
        assert not session._tool_dialogue
        assert "tool_unclaimed" in session._tool_reply_pending
    finally:
        session.closed = True
        playback.cancel()
        await asyncio.gather(playback, return_exceptions=True)


@pytest.mark.parametrize("cancel_mode", ["raised", "task_cancel"])
async def test_cancelled_proactive_handoff_releases_fleet_speaker_lease(
    native, cancel_mode,
):
    """No leaked exclusive XIAO speaker lease after native task cancellation."""
    module, bridge = native
    conn, _sent = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    module._sessions["mac-01"] = session
    entered = asyncio.Event()

    async def interrupted_cutover():
        entered.set()
        if cancel_mode == "raised":
            raise asyncio.CancelledError()
        await asyncio.sleep(100)

    session._invalidate_head_first = interrupted_cutover
    session._schedule_remote_cancel = lambda events: None
    pending = asyncio.create_task(module.begin_external_speech(conn))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        if cancel_mode == "task_cancel":
            pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert module._external_speaker_owner is None
        assert module._external_speaker_connection is None
        assert session._external_speech_active is False
    finally:
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await module.end_external_speech(conn)
        module._sessions.clear()


@pytest.mark.parametrize("lease_owner", ["same_head", "another_head"])
async def test_native_output_refuses_external_mac_speaker_without_pcm_or_delivery(
    native, monkeypatch, lease_owner,
):
    """A denied TTS START must return False, never None.

    The playback worker compares START with False specifically. An implicit
    None previously let a model response enter the Opus loop despite losing
    the one physical Xiaozhi speaker lease.
    """
    module, bridge = native
    conn, sent = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._tool_speech_turn = (0, 0)
    session._tool_audio_response_id = "tool_refused"
    if lease_owner == "same_head":
        session._external_speech_active = True
    else:
        module._external_speaker_owner = "mac-02"
        module._external_speaker_connection = object()
    class Encoder:
        def __init__(self, *args):
            pass
        def encode(self, data, frame_size):
            return b"unwanted_opus"
    monkeypatch.setitem(sys.modules, "opuslib_next", SimpleNamespace(
        Encoder=Encoder, APPLICATION_AUDIO="audio",
    ))
    session.outgoing.put_nowait(("tool_refused", bytes(9600)))
    session.outgoing.put_nowait(("tool_refused", None))
    player = None
    try:
        assert await session._send_device_state("start", 0) is False
        player = asyncio.create_task(session._play())
        async with asyncio.timeout(1):
            while not session.outgoing.empty():
                await asyncio.sleep(0.005)
        await asyncio.sleep(0)
        assert sent == []
        assert session.head_packets == 0
        assert session.native_tool_audio_sent == 0
        assert session._tool_speech_turn == (0, 0)
        assert not session._tool_dialogue
    finally:
        session.closed = True
        if player is not None:
            player.cancel()
            await asyncio.gather(player, return_exceptions=True)
        module._external_speaker_owner = None
        module._external_speaker_connection = None


async def test_proactive_mac_and_native_voice_share_one_interruptible_speaker_lease(
    native,
):
    module, bridge = native
    conn, sent = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    module._sessions["mac-01"] = session
    events = []
    session._schedule_remote_cancel = lambda batch: events.extend(batch)
    try:
        session._tool_speech_turn = (0, 0)
        assert not await module.begin_external_speech(conn)
        session._tool_speech_turn = None
        session._pending_audio_commits.append((0, 0))
        assert not await module.begin_external_speech(conn)
        session._pending_audio_commits.clear()
        session._asr_item_turns["live_human_question"] = (0, 0)
        assert not await module.begin_external_speech(conn)
        session._asr_item_turns.clear()
        assert await module.begin_external_speech(conn)
        assert session._external_speech_active
        assert module._external_speaker_owner == "mac-01"
        assert not await module.claim_speaker(session)
        assert events and events[0]["type"] == "response.cancel"
        assert not await module.begin_external_speech(conn)
        # Native output cannot invalidate the current Mac TTS decoder.
        await session._send_device_state("start", session._generation)
        assert not sent
        await module.end_external_speech(conn)
        assert not session._external_speech_active
        assert module._external_speaker_owner is None
        assert await module.claim_speaker(session)
    finally:
        await module.end_external_speech(conn)
        module._sessions.clear()
        module._output_owner = None


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


async def test_native_proactive_model_sees_video_while_microphone_reports_no_speech(
    native,
):
    """One persistent Mac media subscription + real silent PCM unit.

    The test fails if either native video or the MiniCPM append gate still
    depends on _user_was_talking or VAD-positive microphone frames.
    """
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    service = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    observed = []

    class ModelSocket:
        async def send_json(self, packet):
            observed.append(packet)

    jpeg = b"\xff\xd8" + b"new mug on the desk" + b"\xff\xd9"
    payload = (json.dumps({
        "robot_id": "robot-01", "source": "proactive",
        "camera_age_ms": 2,
        "camera_receipt_us": round(module.time.monotonic() * 1_000_000),
        "motion_ppm": 30000,
        "jpeg_base64": base64.b64encode(jpeg).decode("ascii"),
        "motor_authorized": False, "charging_authorized": False,
    }) + "\n").encode("ascii")

    class Chunks:
        async def iter_chunked(self, count):
            assert count >= 1024
            for chunk in (payload[:5], payload[5:37], payload[37:]):
                yield chunk
            # A genuine persistent feed stays open between camera frames.
            await asyncio.Event().wait()

    class StreamReply:
        status = 200
        headers = {
            "X-Desk-Robot-Id": "robot-01",
            "Content-Type": "application/x-ndjson",
        }
        content = Chunks()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    class MacHTTP:
        def __init__(self):
            self.calls = 0

        def get(self, address, **kwargs):
            self.calls += 1
            assert address.endswith("/v1/pet/robot-01/omni-stream")
            assert kwargs["headers"]["Authorization"] == "Bearer " + "p" * 32
            return StreamReply()

    service._socket = ModelSocket()
    mac = MacHTTP()
    video = asyncio.create_task(service._camera_stream(mac))
    mic = asyncio.create_task(service._send_mic())
    try:
        async with asyncio.timeout(1):
            while service.video_frames_selected < 1:
                await asyncio.sleep(.001)
        assert not service._user_was_talking
        for _ in range(10):
            service.queue_mic(b"\0" * 3200, False)
        async with asyncio.timeout(1):
            while len([e for e in observed
                       if e["type"] == "input_audio_buffer.append"]) < 10:
                await asyncio.sleep(.001)
        appends = [e for e in observed
                   if e["type"] == "input_audio_buffer.append"]
        video_packets = [e for e in appends if e.get("video_frames")]
        assert len(video_packets) == 1
        assert video_packets[0]["is_speech"] is False
        assert base64.b64decode(video_packets[0]["video_frames"][0]) == jpeg
        assert service.wire.frames_sent == 1
        assert not service._user_was_talking
        assert mac.calls == 1  # No repeated /omni-frame GET requests.
    finally:
        service.closed = True
        for task in (video, mic):
            task.cancel()
        await asyncio.gather(video, mic, return_exceptions=True)




async def test_native_proactive_stream_rejects_delayed_and_future_receipts(native):
    """Mac and Xiaozhi share a monotonic clock, not producer-side age trust."""
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    service = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    original_us = round(module.time.monotonic() * 1_000_000)
    jpeg = b"\xff\xd8" + b"camera source verified" + b"\xff\xd9"

    def frame(receipt):
        return (json.dumps({
            "robot_id": "robot-01", "source": "proactive",
            # A compromised / buffered producer could falsely claim age=0.
            "camera_age_ms": 0, "camera_receipt_us": receipt,
            "motion_ppm": 30000,
            "jpeg_base64": base64.b64encode(jpeg).decode("ascii"),
            "motor_authorized": False, "charging_authorized": False,
        }) + "\n").encode("ascii")

    batch = (
        frame(original_us - 3_000_000)
        + frame(original_us + 3_000_000)
        + frame(original_us)
    )

    class Chunks:
        async def iter_chunked(self, _):
            yield batch[:43]
            yield batch[43:]
            await asyncio.Event().wait()

    class Reply:
        status = 200
        headers = {
            "X-Desk-Robot-Id": "robot-01",
            "Content-Type": "application/x-ndjson",
        }
        content = Chunks()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    class Mac:
        calls = 0

        def get(self, *_args, **_kwargs):
            self.calls += 1
            return Reply()

    mac = Mac()
    worker = asyncio.create_task(service._camera_stream(mac))
    try:
        async with asyncio.timeout(1):
            while service.video_frames_selected == 0:
                await asyncio.sleep(.005)
        assert service.video_frames_skipped_stale == 2
        assert service.video_frames_selected == 1
        assert service.latest_jpeg == jpeg
        assert abs(service.latest_frame_time - original_us / 1_000_000) < .00001
        assert service._camera_stream_connected is True
        assert mac.calls == 1  # dropped frames do not cause HTTP reconnect
    finally:
        service.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)



async def test_new_vad_turn_rejects_recent_but_pre_turn_video(native):
    """A late NDJSON frame from prior silence cannot enter a new human turn."""
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    service = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )

    class ModelSocket:
        async def send_json(self, packet):
            assert packet["type"] == "input_audio_buffer.append"

    service._socket = ModelSocket()
    captured_before_vad = module.time.monotonic_ns() // 1000
    mic = asyncio.create_task(service._send_mic())
    video = None
    try:
        service.queue_mic(b"\x00" * 3200, True)
        async with asyncio.timeout(1):
            while not service._user_was_talking:
                await asyncio.sleep(.001)
        assert service._video_turn_started_us > captured_before_vad
        fresh_receipt = module.time.monotonic_ns() // 1000
        jpeg = b"\xff\xd8" + b"fresh actual frame" + b"\xff\xd9"

        def event(receipt):
            return (json.dumps({
                "robot_id": "robot-01", "source": "proactive",
                "camera_age_ms": 0, "camera_receipt_us": receipt,
                "motion_ppm": 20000,
                "jpeg_base64": base64.b64encode(jpeg).decode("ascii"),
                "motor_authorized": False, "charging_authorized": False,
            }) + "\n").encode("ascii")

        class Chunks:
            async def iter_chunked(self, _):
                payload = event(captured_before_vad) + event(fresh_receipt)
                yield payload[:17]
                yield payload[17:]
                await asyncio.Event().wait()

        class Reply:
            status = 200
            headers = {
                "X-Desk-Robot-Id": "robot-01",
                "Content-Type": "application/x-ndjson",
            }
            content = Chunks()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_):
                return False

        class Mac:
            def get(self, *_args, **_kwargs):
                return Reply()

        video = asyncio.create_task(service._camera_stream(Mac()))
        async with asyncio.timeout(1):
            while service.video_frames_selected < 1:
                await asyncio.sleep(.001)
        assert service.video_frames_skipped_stale == 1
        assert service.latest_jpeg == jpeg
        assert service._latest_frame_receipt_us == fresh_receipt
    finally:
        service.closed = True
        mic.cancel()
        if video is not None:
            video.cancel()
        await asyncio.gather(
            *(t for t in (mic, video) if t is not None),
            return_exceptions=True,
        )


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
        ("Can you see the blue mug?", "look"),
        ("Can you identify this part?", "look"),
        ("Where is my red key?", "look"),
        ("What is in the picture?", "look"),
        ("Check your battery status", "power-status"),
        ("Could you check your battery status?", "power-status"),
        ("How much battery is left?", "power-status"),
        ("What's your power level?", "power-status"),
        ("Check your temperature", "aux-status"),
        ("What is your humidity reading?", "aux-status"),
        ("Show sensor readings", "aux-status"),
        ("Read your BMP280 pressure", "aux-status"),
        ("What is the NFC sensor reading?", "aux-status"),
        ("What is a temperature sensor?", None),
        ("How does a proximity sensor work?", None),
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
            "look", "status", "power-status", "aux-status",
            "latest-pickup", "interaction-context", "voice-context",
        }


@pytest.mark.parametrize(
    ("spoken", "route"),
    [
        ("What color is the mug?", "look"),
        ("What shape is the key?", "look"),
        ("What size is the box?", "look"),
        ("How many keys are on the desk?", "look"),
        ("Is there a blue mug on the table?", "look"),
        ("Is the red key next to the mug?", "look"),
        ("Does the screen say READY?", "look"),
        ("Could you tell me what color is the mug?", "look"),
        ("Can you count the screws on the desk?", "look"),
        ("Is there a way to charge the battery on the desk?", None),
        ("How do I replace my battery?", None),
        ("What is the best way to charge my battery?", None),
        ("How can I see what the camera captures?", None),
        ("How many batteries are left?", None),
        ("Is the charger ready?", None),
        ("Pick up the red key next to the mug", None),
        ("I can see the red key on the table", None),
        ("What color did I say the mug was?", None),
        ("Does the battery say 80%?", None),
        ("Can you move next to the mug?", None),
    ],
)
def test_native_explicit_scene_questions_use_existing_camera_authority(
    native, spoken, route,
):
    module, _ = native
    result = module.native_readonly_request(spoken)
    assert (result[0] if result else None) == route
    if result:
        assert result[1] == {"question": spoken}


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
            ("look", "power-status"),
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
            ("look", "power-status", "interaction-context"),
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


@pytest.mark.parametrize(
    ("spoken", "routes", "visual_question"),
    [
        (
            "Look at the key and the mug and check your battery status?",
            ("look", "power-status"),
            "Look at the key and the mug",
        ),
        (
            "Can you look at the red key and the blue cup and check the battery?",
            ("look", "power-status"),
            "Can you look at the red key and the blue cup",
        ),
        (
            "Do you remember the key and the mug?",
            ("voice-context",),
            None,
        ),
        (
            "Look at the mug, check your battery status",
            ("look", "power-status"),
            "Look at the mug",
        ),
        (
            "Please look at the key; what just happened",
            ("look", "interaction-context"),
            "Please look at the key",
        ),
        (
            "Look at the key, the mug, and the cube; check your battery",
            ("look", "power-status"),
            "Look at the key, the mug, and the cube",
        ),
        (
            "Pick up the key, check your battery",
            ("power-status",),
            None,
        ),
        (
            "Look around and then please tell me what happened",
            ("look", "interaction-context"),
            "Look around",
        ),
    ],
)
def test_native_compound_clauses_preserve_multi_object_questions(
    native, spoken, routes, visual_question,
):
    module, _ = native
    requests = module.native_readonly_requests(spoken)
    assert tuple(route for route, _ in requests) == routes
    if visual_question is not None:
        assert requests[0][1]["question"] == visual_question


def test_native_long_natural_asr_uses_only_explicit_final_readonly_question(native):
    module, _ = native
    introduction = ("I was working on my robot and noticed some keys. " * 12)
    assert len(introduction) > 280
    requests = module.native_readonly_requests(
        introduction + "Can you look around and check your battery status?"
    )
    assert [route for route, _ in requests] == ["look", "power-status"]
    assert requests[0][1]["question"] == "Can you look around"
    assert module.native_readonly_requests(
        introduction + "Could you drive to the charger?"
    ) == ()
    assert module.native_readonly_requests(
        "I have been explaining my thoughts without a clear question " * 8
    ) == ()
    assert module.native_readonly_requests(
        ("A long spoken message. " * 120) + "Look at the desk?"
    ) == ()  # Over 2400 ASR characters must not enter any tool.


@pytest.mark.parametrize("spoken", [
    "Is there a way to charge the battery on the desk?",
    "How do I replace my battery?",
    "What is the best way to charge my battery?",
    "How can I see what the camera captures?",
    "Could you tell me how to fix the sensor?",
])
def test_native_howto_does_not_fall_through_to_semantic_tool_planner(
    native, spoken,
):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session._live_transcript_enabled = True
    session._queue_readonly_tool({"item_id": "howto-01", "transcript": spoken})
    assert session._readonly_queue.empty()
    assert session._readonly_requests == set()


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
    assert (first[0], second[0]) == ("look", "power-status")
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
    assert session._readonly_queue.get_nowait()[0] == "power-status"
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


async def test_new_human_voice_clears_stale_native_tool_queue_before_new_question(
    native,
):
    """Three obsolete tool slots must not starve a new human's request."""
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session._live_transcript_enabled = True
    for route in ("look", "status", "interaction-context"):
        session._readonly_queue.put_nowait((route, {}, 0, 0))

    class ModelSocket:
        async def send_json(self, packet):
            assert packet["type"] == "input_audio_buffer.append"

    session._socket = ModelSocket()
    worker = asyncio.create_task(session._send_mic())
    try:
        session.queue_mic(b"\x00" * 3200, True)
        async with asyncio.timeout(1):
            while session._readonly_turn == 0:
                await asyncio.sleep(.005)
        assert session._readonly_queue.empty()
        assert session._context_update_unsupported is True
        assert session.native_readonly_tools_dropped == 3
        session._queue_readonly_tool({
            "item_id": "fresh_human_vision",
            "transcript": "What do you see on the desk?",
        })
        selected = session._readonly_queue.get_nowait()
        assert selected[0] == "look"
        assert selected[2:] == (session._generation, session._readonly_turn)
        assert session.native_readonly_tools_dropped == 3
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_native_barge_drops_old_queued_tools_without_physical_retry(native):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session._live_transcript_enabled = True
    session._readonly_queue.put_nowait(("look", {}, 0, 0))
    session._readonly_queue.put_nowait(("power-status", {}, 0, 0))
    await session.barge()
    assert session._readonly_queue.empty()
    assert session.native_readonly_tools_dropped == 2
    assert session._generation == 1 and session._readonly_turn == 1
    session._queue_readonly_tool({
        "item_id": "post_barge_tool",
        "transcript": "Check your battery status",
    })
    assert session._readonly_queue.get_nowait()[0] == "power-status"


@pytest.mark.parametrize(
    ("route", "response", "expected"),
    [
        ("look", {"source": "authenticated_xiao_camera_and_local_vlm",
                   "answer": "Maybe a blue mug"},
         "local_camera_model_guess"),
        ("look", {"source": "fabricated", "answer": "Definitely a mug"}, None),
        ("power-status", {"source": "wroom_aux_fuel_gauge_raw_unqualified",
                          "gauge_available": False}, "wroom_fuel_gauge"),
        ("power-status", {"source": "wroom_aux_fuel_gauge_raw_unqualified",
                          "gauge_available": True, "reported_soc_centi": 5000,
                          "reported_cell_mv": 3700}, "unqualified_wroom_gauge"),
        ("power-status", {"source": "wroom_aux_fuel_gauge_raw_unqualified",
                          "gauge_available": True, "reported_soc_centi": "99",
                          "reported_cell_mv": 3700}, None),
        ("aux-status", {"robot_id": "robot-01", "climate": {
            "valid": True, "temp_centi": 2150, "rh_centi": 4400
        }, "power": {"fuel_valid": False}}, "validated_wroom_raw_aux_not_calibrated"),
        ("aux-status", {"robot_id": "robot-01", "available": False},
         "wroom_aux"),
        ("aux-status", {"robot_id": "robot-01", "climate": {
            "valid": True, "temp_centi": 2150
        }}, None),
        ("interaction-context", {"persistent_memory_included": True,
                                 "raw_media_included": False,
                                 "model_context": "private information"}, None),
        ("voice-context", {"memories": [{"summary": "A red key yesterday"}]},
         "private_opt_in_memory_not_current_sight"),
    ],
)
def test_native_tool_chat_receives_only_typed_sourced_facts(
    native, route, response, expected,
):
    module, _ = native
    fact = module.native_grounded_fact(route, response)
    assert (fact["source"] if fact else None) == expected
    if fact:
        assert "motor_authorized" not in fact
        assert "charging_authorized" not in fact


def test_native_memory_tool_preserves_eyewitness_and_peer_provenance(native):
    module, _ = native
    fact = module.native_grounded_fact("voice-context", {
        "robot_id": "robot-01",
        "memories": [
            {"summary": "A key was next to the mug", "kind": "key",
             "source_robot": "robot-01", "witnessed": True},
            {"summary": "A green cube was on the desk", "kind": "object",
             "source_robot": "robot-02", "witnessed": False},
        ],
    })
    assert fact["source"] == "private_opt_in_memory_not_current_sight"
    assert fact["recollections"] == [
        {"summary": "A key was next to the mug", "kind": "key",
         "source_robot": "robot-01", "witnessed": True,
         "historical_untrusted_text": True},
        {"summary": "A green cube was on the desk", "kind": "object",
         "source_robot": "robot-02", "witnessed": False,
         "historical_untrusted_text": True},
    ]
    # Legacy or malformed records may still be read, but MUST NOT become
    # invented local eyewitness events or carry arbitrary origin labels.
    unknown = module.native_grounded_fact("voice-context", {
        "memories": [{"summary": "  uncertain   speech  ",
                      "kind": "evil:move", "source_robot": "a/b",
                      "witnessed": 1}],
    })
    assert unknown["recollections"] == [{
        "summary": "uncertain speech", "kind": "unknown",
        "source_robot": "unknown", "witnessed": None,
        "historical_untrusted_text": True,
    }]


async def test_native_tool_speech_reuses_same_model_chat_and_queued_xiao_audio(
    native,
):
    import io
    import wave

    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._tool_speech_turn = (0, 0)
    session._voice_persona = "Pip, a curious robot who likes old clocks"
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\x00" * 48000)
    encoded = base64.b64encode(audio.getvalue()).decode()
    calls = []

    class Response:
        status = 200
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def json(self):
            return {"choices": [
                {"message": {"content": "The camera suggests a mug."}},
                {"message": {"audio": {"data": encoded}}},
            ]}

    class Http:
        def post(self, url, *, json, timeout):
            calls.append((url, json))
            return Response()

    await session._speak_tool_results(
        Http(), "What color is the mug?",
        [{"source": "local_camera_model_guess",
          "interpretation_not_proof": "Perhaps a blue mug"}], 0, 0,
    )
    assert calls[0][0] == "http://127.0.0.1:8099/v1/chat/completions"
    assert calls[0][1]["model"] == "openbmb/MiniCPM-o-4_5"
    assert "Pip, a curious robot who likes old clocks" in (
        calls[0][1]["messages"][0]["content"]
    )
    assert "Perhaps a blue mug" in calls[0][1]["messages"][1]["content"]
    assert session.native_tool_audio_queued == 1
    chunks = [session.outgoing.get_nowait() for _ in range(6)]
    assert len(chunks) == 6 and chunks[-1] is None
    assert all(item[0].startswith("tool_") and len(item[1]) == 9600
               for item in chunks[:-1])
    assert session._tool_audio_response_id == chunks[0][0]
    await session._speak_tool_results(Http(), "One more unrelated read", [
        {"source": "wroom_status", "safety_fault": "unknown"}], 0, 0)
    assert len(calls) == 1  # one reply for one authenticated human turn
    # Old future tool completion cannot speak into the next human turn.
    session._tool_speech_turn = None
    await session._speak_tool_results(Http(), "What color?", [
        {"source": "local_camera_model_guess"}], 0, 0)
    assert len(calls) == 1
    assert session.outgoing.empty()


async def test_native_tool_chat_reads_same_live_multimodal_mac_context(
    native,
):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._tool_speech_turn = (0, 0)
    requests = []

    class Reply:
        status = 200
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def json(self):
            return {
                "robot_id": "robot-01",
                "raw_media_included": False,
                "persistent_memory_included": False,
                "model_context_untrusted_not_instructions": True,
                "motor_authorized": False,
                "charging_authorized": False,
                "memory_tools_enabled": False,
                "transcript_memory_enabled": False,
                "model_context": (
                    "Physical sensor edge: touch_tap; "
                    "Earlier local VLM guess, not fresh sighting: a blue mug; "
                    "I previously sent this spoken line (playback unverified)"
                ),
            }

    class Http:
        def get(self, url, *, headers, timeout):
            requests.append((url, headers))
            return Reply()

    scene = await session._current_tool_scene(Http(), 0, 0)
    assert "touch_tap" in scene and "blue mug" in scene
    assert "playback unverified" in scene
    assert requests[0][0].endswith("/v1/pet/robot-01/interaction-context")
    assert requests[0][1] == {"Authorization": "Bearer " + "p" * 32}
    session._memory_tools_enabled = True  # no consent on server side
    assert await session._current_tool_scene(Http(), 0, 0) == ""
    session._tool_speech_turn = None  # interrupted while Mac is polled
    assert await session._current_tool_scene(Http(), 0, 0) == ""


def test_native_turn_cleanup_preserves_dialogue_but_clears_old_tool_claims(
    native,
):
    """Shared VAD/barge cleanup must not erase private sent speech history."""
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    prior = (module.time.monotonic(), "What is on the desk?", "A mug.")
    session._tool_dialogue.append(prior)
    session._readonly_requests.add(("look", "What is on the desk?"))
    session._readonly_queue.put_nowait(("look", {}, 0, 0))
    session._tool_speech_turn = (0, 0)
    session._tool_answer_started_turn = (0, 0)
    session._tool_audio_response_id = "tool_previous"
    session._tool_reply_pending["tool_previous"] = (0, "Q", "A")
    session._native_output_words["native_previous"] = {"spoken": "A mug."}
    session._last_human_transcript = "What is on the desk?"
    session._tool_question = "What is on the desk?"
    session.latest_jpeg = b"existing_frame"
    session.outgoing.put_nowait(("native_previous", b"old audio"))
    session.outgoing.put_nowait(("native_previous", None))
    session._clear_obsolete_tool_turn()
    assert session.outgoing.empty()
    # A repeated human VAD must remain idempotent; it must never recurse.
    session._clear_obsolete_tool_turn()
    assert session._tool_speech_turn is None
    assert session._tool_answer_started_turn is None
    assert session._tool_audio_response_id is None
    assert session._readonly_queue.empty()
    assert not session._readonly_requests
    assert not session._tool_reply_pending
    assert not session._native_output_words
    assert session._last_human_transcript == ""
    assert session._tool_question == ""
    assert list(session._tool_dialogue) == [prior]
    # Camera invalidation belongs to each VAD/video callsite, not this helper.
    assert session.latest_jpeg == b"existing_frame"


@pytest.mark.parametrize("facts,audio_enqueued", [
    (False, False), (True, False), (True, True),
])
async def test_native_tool_worker_releases_speaker_if_no_audio_was_queued(
    native, facts, audio_enqueued,
):
    """A failed read-only tool/model must not strand the future speaker lease."""
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._tool_speech_turn = (0, 0)
    session._tool_question = "Look at the mug"
    spoken = asyncio.Event()

    async def read(batch):
        return [{"source": "authenticated_xiao_camera_and_local_vlm",
                 "observed": "blue mug"}] if facts else []

    async def say(http, transcript, results, epoch, turn):
        assert results and transcript == "Look at the mug"
        if audio_enqueued:
            session._tool_audio_response_id = "tool_actual_audio"
        spoken.set()

    session._run_readonly_batch = read
    session._speak_tool_results = say
    session._readonly_queue.put_nowait(("look", {}, 0, 0))
    worker = asyncio.create_task(session._readonly_tool_worker())
    try:
        if facts:
            await asyncio.wait_for(spoken.wait(), timeout=2)
        else:
            async with asyncio.timeout(2):
                while session._tool_speech_turn is not None:
                    await asyncio.sleep(.005)
        # Worker cleanup runs synchronously after successful audio queuing.
        await asyncio.sleep(.02)
        if audio_enqueued:
            assert session._tool_speech_turn == (0, 0)
            assert session._tool_audio_response_id == "tool_actual_audio"
        else:
            assert session._tool_speech_turn is None
            assert session._tool_question == ""
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_stale_response_done_does_not_split_new_grounded_tool_speech(
    native, monkeypatch,
):
    """Tool response B can continue across a delayed native A completion.

    A previous response.done used a global None sentinel, and falsely
    stopped whichever response happened to own the physical speaker.
    """
    module, bridge = native
    conn, sent = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._tool_speech_turn = (0, 0)
    session._tool_audio_response_id = "tool_new"
    session._tool_reply_pending["tool_new"] = (
        0, "What color is the mug?", "The mug appears blue.",
    )

    class Encoder:
        def __init__(self, *args):
            pass

        def encode(self, pcm, frame_size):
            assert len(pcm) == 1920 and frame_size == 960
            return b"opus"

    monkeypatch.setitem(sys.modules, "opuslib_next", SimpleNamespace(
        Encoder=Encoder, APPLICATION_AUDIO="audio",
    ))
    states, encoded = [], []
    done = asyncio.Event()

    async def send_state(state, generation):
        states.append(state)
        if state == "stop":
            done.set()
        return True

    async def send_opus(packet, generation):
        encoded.append(packet)

    session._send_device_state = send_state
    session._send_device_opus = send_opus

    session.outgoing.put_nowait(("tool_new", bytes(9600)))
    session.outgoing.put_nowait(("native_old", None))
    session.outgoing.put_nowait(("tool_new", bytes(9600)))
    session.outgoing.put_nowait(("tool_new", None))
    worker = asyncio.create_task(session._play())
    try:
        await asyncio.wait_for(done.wait(), timeout=1)
        await asyncio.sleep(0)
        assert states == ["start", "stop"]
        assert encoded and len(encoded) >= 4
        assert session.native_tool_audio_sent == 1
        assert len(session._tool_dialogue) == 1
        assert "mug appears blue" in session._tool_dialogue[-1][2]
        assert not sent  # Fake head transport was never used.
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)



async def test_new_native_response_stops_old_decoder_before_next_start(
    native, monkeypatch,
):
    """Two valid response IDs must never overlap at the physical XIAO."""
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session.wire.response_id = "native_prior"
    session._native_output_words["native_prior"] = {
        "spoken": "Old interrupted answer",
    }
    session._tool_speech_turn = (0, 0)
    session._tool_audio_response_id = "tool_next"
    session._tool_reply_pending["tool_next"] = (
        0, "What is on the desk?", "A blue mug appears on the desk.",
    )

    class Encoder:
        def __init__(self, *args):
            pass

        def encode(self, pcm, frame_size):
            assert len(pcm) == 1920 and frame_size == 960
            return b"opus"

    monkeypatch.setitem(sys.modules, "opuslib_next", SimpleNamespace(
        Encoder=Encoder, APPLICATION_AUDIO="audio",
    ))
    states, encoded = [], []

    async def send_state(state, generation):
        states.append((state, generation))
        return True

    async def send_opus(packet, generation):
        encoded.append((packet, generation))

    session._send_device_state = send_state
    session._send_device_opus = send_opus
    session.outgoing.put_nowait(("native_prior", bytes(9600)))
    session.outgoing.put_nowait(("tool_next", bytes(9600)))
    session.outgoing.put_nowait(("native_prior", None))
    session.outgoing.put_nowait(("tool_next", None))
    worker = asyncio.create_task(session._play())
    try:
        async with asyncio.timeout(1):
            while len(states) < 4:
                await asyncio.sleep(0.005)
        assert [state for state, _ in states] == [
            "start", "stop", "start", "stop",
        ]
        assert encoded
        assert session.native_tool_audio_sent == 1
        assert "native_prior" not in session._native_output_words
        assert len(session._tool_dialogue) == 1
        assert session._tool_dialogue[-1][2] == (
            "A blue mug appears on the desk."
        )
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_new_native_response_refuses_start_when_prior_stop_failed(
    native, monkeypatch,
):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session.wire.response_id = "native_prior"
    session._tool_audio_response_id = "tool_next"
    session._tool_reply_pending["tool_next"] = (
        0, "What color is it?", "Probably blue.",
    )

    class Encoder:
        def __init__(self, *args):
            pass
        def encode(self, pcm, frame_size):
            return b"opus"

    monkeypatch.setitem(sys.modules, "opuslib_next", SimpleNamespace(
        Encoder=Encoder, APPLICATION_AUDIO="audio",
    ))
    states, encoded = [], []

    async def send_state(state, generation):
        states.append(state)
        return state != "stop"

    async def send_opus(packet, generation):
        encoded.append(packet)

    session._send_device_state = send_state
    session._send_device_opus = send_opus
    session.outgoing.put_nowait(("native_prior", bytes(9600)))
    session.outgoing.put_nowait(("tool_next", bytes(9600)))
    session.outgoing.put_nowait(("tool_next", None))
    worker = asyncio.create_task(session._play())
    try:
        async with asyncio.timeout(1):
            while len(states) < 2:
                await asyncio.sleep(0.005)
        await asyncio.sleep(0)
        assert states == ["start", "stop"]
        assert session.native_tool_audio_sent == 0
        assert not session._tool_dialogue
        assert session._tool_audio_response_id == "tool_next"
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)



async def test_brief_human_barge_during_old_stop_cannot_restart_stale_tool_audio(
    native, monkeypatch,
):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session.wire.response_id = "native_prior"
    session._tool_audio_response_id = "tool_obsolete"

    class Encoder:
        def __init__(self, *args):
            pass

        def encode(self, pcm, frame_size):
            assert len(pcm) == 1920 and frame_size == 960
            return b"opus"

    monkeypatch.setitem(sys.modules, "opuslib_next", SimpleNamespace(
        Encoder=Encoder, APPLICATION_AUDIO="audio",
    ))
    states, encoded = [], []

    async def send_state(state, generation):
        states.append((state, generation))
        if state == "stop":
            # The human spoke and stopped again within the awaited send.
            # An obsolete tool answer still has a queued PCM chunk.
            session._generation += 1
            session._tool_audio_response_id = None
        return True

    async def send_opus(packet, generation):
        encoded.append((packet, generation))

    session._send_device_state = send_state
    session._send_device_opus = send_opus
    session.outgoing.put_nowait(("native_prior", bytes(9600)))
    session.outgoing.put_nowait(("tool_obsolete", bytes(9600)))
    session.outgoing.put_nowait(("tool_obsolete", None))
    worker = asyncio.create_task(session._play())
    try:
        async with asyncio.timeout(1):
            while len(states) < 2:
                await asyncio.sleep(0.005)
        await asyncio.sleep(0)
        assert [state for state, _ in states] == ["start", "stop"]
        assert session.native_tool_audio_sent == 0
        assert not session._tool_dialogue
        assert not [p for p, gen in encoded if gen == session._generation]
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_native_tool_dialogue_only_remembers_sent_uninterrupted_audio(
    native, monkeypatch,
):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    class Encoder:
        def __init__(self, rate, channels, mode):
            assert (rate, channels, mode) == (16000, 1, "audio")
        def encode(self, data, frame_size):
            assert len(data) == 1920 and frame_size == 960
            return b"fake_opus"

    monkeypatch.setitem(sys.modules, "opuslib_next", SimpleNamespace(
        Encoder=Encoder, APPLICATION_AUDIO="audio",
    ))
    session._tool_audio_response_id = "tool_verified_send"
    session._tool_reply_pending["tool_verified_send"] = (
        0, "Where is the blue mug?", "I think it is beside the key.",
    )
    sent_states = []
    opus_sent = []

    async def state(name, gen):
        sent_states.append((name, gen))
    async def opus(data, gen):
        opus_sent.append((data, gen))

    session._send_device_state = state
    session._send_device_opus = opus
    session.outgoing.put_nowait(("tool_verified_send", bytes(9600)))
    session.outgoing.put_nowait(("tool_verified_send", None))
    play = asyncio.create_task(session._play())
    try:
        async with asyncio.timeout(1):
            while not session._tool_dialogue:
                await asyncio.sleep(.005)
        assert sent_states == [("start", 0), ("stop", 0)]
        assert opus_sent
        assert "Where is the blue mug?" in session._tool_dialogue_context(
            module.time.monotonic()
        )
        assert "playback unverified" in session._tool_dialogue_context(
            module.time.monotonic()
        )
    finally:
        session.closed = True
        play.cancel()
        await asyncio.gather(play, return_exceptions=True)

    # A pending reply interrupted before its TTS STOP cannot become history.
    session._tool_reply_pending["tool_interrupted"] = (
        0, "What happened?", "I saw something.",
    )
    session._generation += 1
    session._tool_audio_sent("tool_interrupted", 0)
    assert len(session._tool_dialogue) == 1


async def test_native_duplex_speech_text_enters_dialogue_only_after_opus_stop(
    native, monkeypatch,
):
    """Real upstream text events + audio delivery give next turn continuity."""
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._last_human_transcript = "Tell me something interesting"
    class Encoder:
        def __init__(self, rate, ch, mode):
            assert (rate, ch, mode) == (16000, 1, "audio")
        def encode(self, pcm, samples):
            return b"opus"
    monkeypatch.setitem(sys.modules, "opuslib_next", SimpleNamespace(
        Encoder=Encoder, APPLICATION_AUDIO="audio",
    ))
    states = []
    packets = []
    async def state(name, gen):
        states.append(name)
    async def send_opus(chunk, gen):
        packets.append(chunk)
    session._send_device_state = state
    session._send_device_opus = send_opus

    pcm = base64.b64encode(bytes(4800)).decode()
    events = [
        {"type": "response.created", "response_id": "native_1",
         "response": {"id": "native_1",
                      "metadata": {"duplex_event": {"epoch": 0}}}},
        {"type": "response.output_text.delta", "response_id": "native_1",
         "delta": "Model text guess"},
        {"type": "response.output_audio_transcript.delta",
         "response_id": "native_1", "delta": "Hello from the robot."},
        {"type": "response.output_audio.delta", "response_id": "native_1",
         "format": "pcm16", "sample_rate_hz": 24000,
         "delta": pcm, "metadata": {"epoch": 0}},
        {"type": "response.done", "response_id": "native_1"},
    ]
    class ModelSocket:
        def __aiter__(self):
            async def incoming():
                for event in events:
                    yield SimpleNamespace(
                        type=module.aiohttp.WSMsgType.TEXT,
                        data=json.dumps(event),
                    )
            return incoming()
    session._socket = ModelSocket()
    await session._receive_model()
    assert not session._tool_dialogue
    playing = asyncio.create_task(session._play())
    try:
        async with asyncio.timeout(1):
            while not session._tool_dialogue:
                await asyncio.sleep(.005)
        assert states == ["start", "stop"]
        assert packets
        message = session._tool_dialogue_context(module.time.monotonic())
        assert "Tell me something interesting" in message
        assert "Hello from the robot." in message
        assert "Model text guess" not in message
    finally:
        session.closed = True
        playing.cancel()
        await asyncio.gather(playing, return_exceptions=True)


async def test_second_asr_clause_same_human_turn_survives_native_audio_fence(
    native,
):
    """Tool speech cancellation must not invalidate the human's next ASR item."""
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True
    session._asr_item_turns["first"] = (0, 0)
    session._asr_item_turns["second"] = (0, 0)
    first = {
        "item_id": "first", "transcript": "What color is the mug?",
    }
    second = {
        "item_id": "second", "transcript": "Check your battery status",
    }
    assert session._accept_current_audio_item(first)
    assert session._queue_readonly_tool(first)
    assert session._readonly_queue.qsize() == 1
    session._schedule_remote_cancel = lambda events: None
    await session._reserve_tool_speech()
    assert session._generation == 1 and session._input_generation == 0
    assert session._accept_current_audio_item(second)
    assert session._queue_readonly_tool(second)
    await session._reserve_tool_speech()  # same human, do not bump generation
    assert session._generation == 1
    assert session._readonly_turn == 0
    assert {session._readonly_queue.get_nowait()[0] for _ in range(2)} == {
        "look", "power-status",
    }
    session._asr_item_turns["stale"] = (0, 0)
    session._input_generation += 1
    session._readonly_turn += 1
    assert not session._accept_current_audio_item({
        "item_id": "stale", "transcript": "Old question",
    })


async def test_native_asr_camera_and_battery_clauses_are_spoken_together(
    native, monkeypatch,
):
    """A delayed camera lookup must not cause two disconnected replies."""
    import io
    import wave
    import types

    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._tool_speech_turn = (0, 0)
    session._tool_question = "Look at the mug and check your battery"
    waiting, release = asyncio.Event(), asyncio.Event()
    requests = []
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(bytes(48000))
    encoded = base64.b64encode(audio.getvalue()).decode()

    async def call(current, route, payload):
        if route == "look":
            waiting.set()
            await release.wait()
            return {
                "robot_id": "robot-01",
                "source": "authenticated_xiao_camera_and_local_vlm",
                "answer": "Probably a BLUE_MUG", "frames_used": 1,
                "motor_authorized": False, "charging_authorized": False,
            }
        assert route == "power-status"
        return {
            "robot_id": "robot-01",
            "source": "wroom_aux_fuel_gauge_raw_unqualified",
            "gauge_available": True, "reported_soc_centi": 5200,
            "reported_cell_mv": 3670, "charging_authorized": False,
            "motor_authorized": False,
        }

    pkg = types.ModuleType("plugins_func")
    pkg.__path__ = []
    funcs = types.ModuleType("plugins_func.functions")
    funcs.__path__ = []
    tools = types.ModuleType("plugins_func.functions.desk_robot_tools")
    tools.call = call
    for name, mod in (
        ("plugins_func", pkg),
        ("plugins_func.functions", funcs),
        ("plugins_func.functions.desk_robot_tools", tools),
    ):
        monkeypatch.setitem(sys.modules, name, mod)

    class Response:
        status = 200
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def json(self):
            return {"choices": [
                {"message": {"content": "The mug looks blue, battery about 52%"}},
                {"message": {"audio": {"data": encoded}}},
            ]}

    class Http:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        def post(self, url, *, json, timeout):
            requests.append(json)
            return Response()

    monkeypatch.setattr(module.aiohttp, "ClientSession", Http)
    session._readonly_queue.put_nowait(("look", {}, 0, 0))
    worker = asyncio.create_task(session._readonly_tool_worker())
    try:
        await asyncio.wait_for(waiting.wait(), timeout=1)
        session._readonly_queue.put_nowait(("power-status", {}, 0, 0))
        release.set()
        async with asyncio.timeout(3):
            while not session.native_tool_audio_queued:
                await asyncio.sleep(.01)
        assert len(requests) == 1
        message = requests[0]["messages"][1]["content"]
        assert "BLUE_MUG" in message
        assert "52" in message
        assert session.native_readonly_tools_completed == 2
        assert session.native_tool_audio_queued == 1
    finally:
        session.closed = True
        release.set()
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_new_human_tool_turn_cancels_stalled_old_model_speech_http(
    native, monkeypatch,
):
    """A wedged tool answer must not monopolize next user's tool worker."""
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._tool_speech_turn = (0, 0)
    entered_chat, next_tool = asyncio.Event(), asyncio.Event()
    cancelled = []

    async def fake_read_batch(entries):
        if entries[0][2:] == (1, 1):
            next_tool.set()
        return [{"source": "mac_readonly", "route": entries[0][0]}]

    async def fake_speech(http, question, facts, epoch, request_turn):
        if (epoch, request_turn) == (0, 0):
            entered_chat.set()
            try:
                await asyncio.Event().wait()  # Stalled old MiniCPM HTTP
            except asyncio.CancelledError:
                cancelled.append((epoch, request_turn))
                raise

    class HTTP:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(module.aiohttp, "ClientSession", HTTP)
    session._run_readonly_batch = fake_read_batch
    session._speak_tool_results = fake_speech
    session._readonly_queue.put_nowait(("look", {}, 0, 0))
    worker = asyncio.create_task(session._readonly_tool_worker())
    try:
        await asyncio.wait_for(entered_chat.wait(), timeout=1)
        assert session._readonly_inflight is not None
        session._generation += 1
        session._readonly_turn += 1
        session._tool_speech_turn = (1, 1)
        session._readonly_inflight.cancel()  # same human VAD cancel path
        session._readonly_queue.put_nowait(("power-status", {}, 1, 1))
        await asyncio.wait_for(next_tool.wait(), timeout=1)
        assert cancelled == [(0, 0)]
        assert not worker.done()
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_failed_tool_speech_releases_native_floor_without_duplicate(
    native,
):
    """A backend HTTP 503 cannot lock out all future proactive pet speech."""
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True
    session._tool_speech_turn = (0, 0)
    async def scene(http, epoch, turn):
        return "One uncertain touch event"
    session._current_tool_scene = scene

    class ErrorResult:
        status = 503
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
    class Http:
        def post(self, *args, **kwargs):
            return ErrorResult()

    await session._speak_tool_results(
        Http(), "What is on my desk?",
        [{"source": "local_camera_model_guess",
          "interpretation_not_proof": "Possibly a mug"}],
        0, 0,
    )
    assert session.native_tool_speech_errors == 1
    assert session._tool_speech_turn is None
    assert session._tool_answer_started_turn == (0, 0)
    assert session.outgoing.empty()
    assert not session._queue_readonly_tool({
        "item_id": "late_item", "transcript": "Check the battery",
    })

    module._sessions["mac-01"] = session
    session._schedule_remote_cancel = lambda events: None
    try:
        assert await module.begin_external_speech(conn)
    finally:
        await module.end_external_speech(conn)
        module._sessions.clear()


@pytest.mark.parametrize(
    "previous_question,seconds_old,followup,expected",
    [
        ("Look at the mug on my desk", 5, "What about the one beside it?", True),
        ("Look at the mug on my desk", 5, "And the other one?", True),
        ("Look at the mug on my desk", 5, "What about that?", True),
        ("Look at the mug on my desk", 5, "Can you drive over there?", False),
        ("Look at the mug on my desk", 60, "What about the one beside it?", False),
        ("Check your battery", 5, "What about the one beside it?", False),
        ("", 0, "What about the one beside it?", False),
    ],
)
def test_native_visual_followup_uses_only_prior_real_sent_visual_question(
    native, previous_question, seconds_old, followup, expected,
):
    """Resolve object anaphora only through the current pet's recent speech."""
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True
    if previous_question:
        session._tool_dialogue.append((
            module.time.monotonic() - seconds_old,
            previous_question, "",  # valid audio sent, no returned text
        ))
    event = {
        "item_id": "fresh_second_turn",
        "transcript": followup,
    }
    assert session._queue_readonly_tool(event) is expected
    if expected:
        route, payload, epoch, turn = session._readonly_queue.get_nowait()
        assert route == "look"
        assert "Prior completed user visual question:" in payload["question"]
        assert "Look at the mug" in payload["question"]
        assert followup in payload["question"]
        assert epoch == session._generation and turn == session._readonly_turn
        assert len(payload["question"]) <= 280
    else:
        assert session._readonly_queue.empty()


def test_audio_only_tool_reply_retains_question_without_faking_spoken_words(native):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session._tool_reply_pending["tool_audio_only"] = (
        0, "Look at the blue mug", "",
    )
    session._tool_audio_sent("tool_audio_only", 0)
    context = session._tool_dialogue_context(module.time.monotonic())
    assert "Look at the blue mug" in context
    assert "no matching spoken transcript" in context
    assert len(session._tool_dialogue) == 1
    assert session._tool_dialogue[0][2] == ""
    session._tool_audio_sent("tool_audio_only", 0)
    assert len(session._tool_dialogue) == 1


async def test_native_tool_chat_finishing_after_barge_cannot_queue_speech(native):
    import io
    import wave

    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._tool_speech_turn = (2, 5)
    arrived, release = asyncio.Event(), asyncio.Event()
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(bytes(48000))
    blob = base64.b64encode(audio.getvalue()).decode()

    class Response:
        status = 200
        async def __aenter__(self):
            arrived.set()
            await release.wait()
            return self
        async def __aexit__(self, *args):
            return None
        async def json(self):
            return {"choices": [{"message": {"audio": {"data": blob}}}]}

    class Http:
        def post(self, url, *, json, timeout):
            return Response()

    task = asyncio.create_task(session._speak_tool_results(
        Http(), "Where is my key?",
        [{"source": "local_camera_model_guess",
          "interpretation_not_proof": "Near a cup"}], 2, 5,
    ))
    try:
        await asyncio.wait_for(arrived.wait(), timeout=1)
        session._tool_speech_turn = None  # new actual human voice owns output
        release.set()
        await asyncio.wait_for(task, timeout=1)
        assert session.outgoing.empty()
        assert session._tool_audio_response_id is None
        assert session.native_tool_audio_queued == 0
        assert session.native_tool_speech_errors == 0
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_two_completed_asr_clauses_keep_whole_question_and_one_reply(
    native,
):
    """Two model ASR items from one actual human turn are not two speakers."""
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True
    session._schedule_remote_cancel = lambda events: None
    session._pending_audio_commits.extend(((0, 0), (0, 0)))
    events = [
        {"type": "input_audio_buffer.committed", "item_id": "first",
         "event": {"turn_id": 0}},
        {"type": "conversation.item.input_audio_transcription.completed",
         "item_id": "first", "transcript": "Look at the mug"},
        {"type": "input_audio_buffer.committed", "item_id": "second",
         "event": {"turn_id": 1}},
        {"type": "conversation.item.input_audio_transcription.completed",
         "item_id": "second", "transcript": "Check your battery level"},
    ]
    class ModelSocket:
        def __aiter__(self):
            async def reader():
                for event in events:
                    yield SimpleNamespace(
                        type=module.aiohttp.WSMsgType.TEXT,
                        data=json.dumps(event),
                    )
            return reader()
    session._socket = ModelSocket()
    await session._receive_model()
    assert "Look at the mug" in session._tool_question
    assert "Check your battery level" in session._tool_question
    assert session._tool_question.count("Look at the mug") == 1
    assert session._generation == 1
    assert session._readonly_turn == 0
    assert {session._readonly_queue.get_nowait()[0] for _ in range(2)} == {
        "look", "power-status",
    }

    # The first combined answer was transmitted. A delayed third ASR item
    # from this very human turn may not initiate another spoken tool answer.
    session._tool_answer_started_turn = (1, 0)
    session._tool_speech_turn = None
    session._asr_item_turns["late"] = (0, 0)
    late = {"item_id": "late", "transcript": "Check your battery"}
    assert session._accept_current_audio_item(late)
    assert not session._queue_readonly_tool(late)
    assert session._readonly_queue.empty()


async def test_native_tool_reservation_fences_model_pcm_without_dropping_tools(
    native,
):
    module, bridge = native
    conn, sent = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._readonly_queue.put_nowait(("look", {"question": "What color?"}, 0, 0))
    session.outgoing.put_nowait(("old_audio", b"stale"))
    cancelled = []
    session._schedule_remote_cancel = lambda events: cancelled.extend(events)
    await session._reserve_tool_speech()
    assert session._generation == 1
    assert session._readonly_turn == 0
    assert session._tool_speech_turn == (1, 0)
    assert session.outgoing.empty()
    assert session._readonly_queue.get_nowait()[2:] == (1, 0)
    assert cancelled and cancelled[0]["type"] == "response.cancel"
    assert sent == []  # no speaker was active; not a fake playback ack


async def test_native_completed_audio_tool_result_reaches_same_model_audio_queue(
    native, monkeypatch,
):
    """Actual ASR receipt -> Mac look -> chat audio; old native PCM discarded."""
    import io
    import wave
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
    session._pending_audio_commits.append((0, 0))
    session.outgoing.put_nowait(("stale_native_audio", b"old PCM"))
    seen = []
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(bytes(48000))
    wav64 = base64.b64encode(audio.getvalue()).decode()

    class ChatResult:
        status = 200
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def json(self):
            return {"choices": [{"message": {"audio": {"data": wav64}}}]}

    class ChatHttp:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        def post(self, url, *, json, timeout):
            seen.append((url, json))
            return ChatResult()

    monkeypatch.setattr(module.aiohttp, "ClientSession", ChatHttp)
    async def call(current, route, payload):
        assert current is conn and route == "look"
        return {"robot_id": "robot-01",
                "source": "authenticated_xiao_camera_and_local_vlm",
                "answer": "Possibly a blue cup in this camera frame",
                "frames_used": 1, "motor_authorized": False,
                "charging_authorized": False}

    pkg = types.ModuleType("plugins_func")
    pkg.__path__ = []
    funcs = types.ModuleType("plugins_func.functions")
    funcs.__path__ = []
    tools = types.ModuleType("plugins_func.functions.desk_robot_tools")
    tools.call = call
    for name, mod in (
        ("plugins_func", pkg),
        ("plugins_func.functions", funcs),
        ("plugins_func.functions.desk_robot_tools", tools),
    ):
        monkeypatch.setitem(sys.modules, name, mod)
    events = [
        {"type": "input_audio_buffer.committed", "item_id": "heard_item",
         "event": {"turn_id": 0}},
        {"type": "conversation.item.input_audio_transcription.completed",
         "item_id": "heard_item", "transcript": "What color is the cup?"},
        {"type": "response.created", "response_id": "stale_model",
         "response": {"id": "stale_model",
                      "metadata": {"duplex_event": {"epoch": 0}}}},
    ]

    class ModelSocket:
        async def send_json(self, event):
            seen.append(("model_event", event))
        def __aiter__(self):
            async def iterator():
                for event in events:
                    yield SimpleNamespace(
                        type=module.aiohttp.WSMsgType.TEXT,
                        data=json.dumps(event),
                    )
            return iterator()

    session._socket = ModelSocket()
    worker = asyncio.create_task(session._readonly_tool_worker())
    try:
        await session._receive_model()
        async with asyncio.timeout(2):
            while not session.native_tool_audio_queued:
                await asyncio.sleep(.005)
        assert session._generation == 1
        assert session._tool_speech_turn == (1, 0)
        assert session.native_readonly_tools_completed == 1
        assert seen and any("/v1/chat/completions" in str(x[0])
                            for x in seen)
        packets = list(session.outgoing._queue)
        assert packets[-1] is None
        assert packets[0][0].startswith("tool_")
        assert b"old PCM" not in [packet[1] for packet in packets[:-1]]
        assert session.wire.response_id != "stale_model"
        assert session.head_packets == 0  # no physical playback claim
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        for task in list(session._pending_cancels):
            task.cancel()
        await asyncio.gather(*session._pending_cancels,
                             return_exceptions=True)


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
        assert [route for route, _ in received] == ["look", "power-status"]
        assert session._context_wakeup.is_set()
        assert session.native_readonly_tools_dropped == 0
    finally:
        session.closed = True
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_native_parallel_tool_results_keep_human_clause_order(native, monkeypatch):
    """The faster battery receipt must not reorder 'look, then check battery'."""
    import types

    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    camera_started, battery_done, release_camera = (
        asyncio.Event(), asyncio.Event(), asyncio.Event()
    )

    async def call(current, route, payload):
        assert current is conn
        if route == "look":
            camera_started.set()
            await release_camera.wait()
            return {"robot_id": "robot-01",
                    "source": "authenticated_xiao_camera_and_local_vlm",
                    "answer": "Possibly a red key", "motor_authorized": False}
        assert route == "power-status"
        battery_done.set()
        return {"robot_id": "robot-01",
                "source": "wroom_aux_fuel_gauge_raw_unqualified",
                "gauge_available": False, "motor_authorized": False}

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

    pending = asyncio.create_task(session._run_readonly_batch([
        ("look", {"question": "Look at my desk"}, 0, 0),
        ("power-status", {}, 0, 0),
    ]))
    try:
        await asyncio.wait_for(camera_started.wait(), timeout=1)
        await asyncio.wait_for(battery_done.wait(), timeout=1)
        assert not pending.done()  # independent concurrent battery finished
        release_camera.set()
        facts = await asyncio.wait_for(pending, timeout=1)
        assert [fact["source"] for fact in facts] == [
            "local_camera_model_guess", "wroom_fuel_gauge",
        ]
        assert session.native_readonly_tools_completed == 2
    finally:
        release_camera.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


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


async def test_one_cancelled_native_tool_does_not_discard_other_observation(
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
        if route == "look":
            raise asyncio.CancelledError
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
        "item_id": "partial_optional_failure",
        "transcript": "Look at the desk and check your battery status",
    })
    worker = asyncio.create_task(session._readonly_tool_worker())
    try:
        async with asyncio.timeout(1):
            while (session.native_readonly_tools_dropped < 1
                   or session.native_readonly_tools_completed < 1):
                await asyncio.sleep(.005)
        assert set(calls) == {"look", "power-status"}
        assert session._context_wakeup.is_set()
        assert not worker.done()
    finally:
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
        assert cancelled == {"look", "power-status"}
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


@pytest.mark.parametrize("defect", [
    "duplicate_route", "missing_provenance", "claimed_model_motor_authority",
    "nonstring_route",
])
async def test_native_model_plan_rejects_duplicate_or_untrusted_routes(
    native, monkeypatch, defect,
):
    """No malformed model plan can queue even an otherwise valid Mac tool."""
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
    plan = {
        "robot_id": "robot-01",
        "source": "existing_mac_ollama_readonly_route_selection",
        "untrusted_model_selection": True,
        "model_can_arm_motors": False,
        "motor_authorized": False,
        "charging_authorized": False,
        "tools": [
            {"route": "look", "payload": {"question": "Where is the key?"}},
            {"route": "status", "payload": {}},
        ],
    }
    if defect == "duplicate_route":
        plan["tools"][1]["route"] = "look"
    elif defect == "missing_provenance":
        plan.pop("untrusted_model_selection")
    elif defect == "nonstring_route":
        plan["tools"][0]["route"] = ["look"]
    else:
        plan["model_can_arm_motors"] = True

    async def call(current, route, payload):
        calls.append(route)
        return plan

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
    await session._run_readonly_batch([
        ("plan-readonly", {}, session._generation, session._readonly_turn),
    ])
    assert calls == ["plan-readonly"]
    assert session._readonly_queue.empty()
    assert session.native_readonly_tools_completed == 0
    assert session.native_readonly_tools_dropped == 1
    assert not session._context_wakeup.is_set()


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


async def test_native_minicpm_context_update_rejection_keeps_actual_audio_session(
    native,
):
    """Official MiniCPM backend rejects late instructions, not PCM traffic."""
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    session._live_transcript_enabled = True
    session._context_update_attempted = True
    session._context_pending = "New live camera evidence"
    session._context_ack.clear()

    class Socket:
        async def __aiter__(self):
            yield SimpleNamespace(
                type=module.aiohttp.WSMsgType.TEXT,
                data=json.dumps({
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "code": "instructions_update_unsupported",
                        "message": "Native context locked after first audio",
                    },
                }),
            )
            yield SimpleNamespace(
                type=module.aiohttp.WSMsgType.TEXT,
                data=json.dumps({"type": "response.done", "response_id": "old"}),
            )

    session._socket = Socket()
    await session._receive_model()
    assert session.connected and not session.closed
    assert session._context_update_unsupported is True
    assert session._context_ack.is_set()
    module._sessions["mac-01"] = session
    assert module.status("mac-01")["native_context_model_application_verified"] is False
    assert module.status("mac-01")["native_context_instruction_updates_unsupported"] is True


async def test_native_unsupported_context_keeps_polling_mac_consent_without_sending(
    native,
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
    session._context_update_unsupported = True
    session._context_instructions = session._base_instructions
    sent = []
    checks = []
    async def send(event):
        sent.append(event)
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
                "model_context": "Recent tool: likely red key",
                "persistent_memory_included": False,
                "raw_media_included": False,
                "model_context_untrusted_not_instructions": True,
                "memory_tools_enabled": False,
                "transcript_memory_enabled": False,
            }
    class Mac:
        def get(self, url, **kwargs):
            checks.append(url)
            return Reply()

    worker = asyncio.create_task(session._refresh_live_context(Mac()))
    try:
        session._context_wakeup.set()
        async with asyncio.timeout(1):
            while not checks:
                await asyncio.sleep(.005)
        await asyncio.sleep(.01)
        assert sent == []  # No impossible MiniCPM instruction change.
        assert session.native_context_updates == 0
        assert session.connected and not session.closed
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
                "persona": "Pip, a curious desk robot",
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
    assert session._voice_persona == "Pip, a curious desk robot"


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


async def test_fleet_vad_aborts_mac_speaker_before_waiting_on_output_lock(
    native,
):
    """The human's STOP priority cannot depend on a held shared audio lock."""
    module, bridge = native
    conn, _ = connection()
    conn.device_id = "mac-02"
    bridge.connections["mac-02"] = conn
    bridge.interrupt_generation = {"mac-02": 4}
    module._external_speaker_owner = "mac-02"
    module._external_speaker_connection = conn
    conn.client_is_speaking = True

    await module._output_owner_lock.acquire()
    preempt = asyncio.create_task(module.preempt_others_for_human("mac-01"))
    try:
        async with asyncio.timeout(1):
            while not conn.client_abort:
                await asyncio.sleep(.005)
        assert bridge.interrupt_generation["mac-02"] == 5
        assert not preempt.done()  # owner lock still held
    finally:
        module._output_owner_lock.release()
        await asyncio.wait_for(preempt, timeout=1)
        module._external_speaker_owner = None
        module._external_speaker_connection = None


async def test_delayed_mac_opus_is_serialized_before_fleet_human_stop(native):
    """No asynchronous Mac Opus send may complete AFTER a human STOP."""
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    bridge.interrupt_generation = {"mac-01": 5}
    module._external_speaker_owner = "mac-01"
    module._external_speaker_connection = conn
    first_started, unblock = asyncio.Event(), asyncio.Event()
    emitted = []

    class SlowSocket:
        async def send(self, packet):
            if packet == b"opus_before_stop":
                first_started.set()
                await unblock.wait()
            emitted.append(packet)
    conn.websocket = SlowSocket()
    conn.client_is_speaking = True
    first = asyncio.create_task(
        module.send_external_opus(conn, b"opus_before_stop", 5)
    )
    stopper = None
    try:
        await asyncio.wait_for(first_started.wait(), timeout=1)
        stopper = asyncio.create_task(
            module.preempt_others_for_human("mac-02")
        )
        async with asyncio.timeout(1):
            while not conn.client_abort:
                await asyncio.sleep(.005)
        assert emitted == []
        unblock.set()
        await asyncio.wait_for(
            asyncio.gather(first, stopper), timeout=1,
        )
        assert emitted[0] == b"opus_before_stop"
        stop = json.loads(emitted[1])
        assert stop["type"] == "tts"
        assert stop["state"] == "stop" and stop["flush"] is True
        assert len(emitted) == 2
        assert bridge.interrupt_generation["mac-01"] == 6
        with pytest.raises(RuntimeError, match="Mac speech interrupted"):
            await module.send_external_opus(conn, b"opus_after_stop", 5)
        assert len(emitted) == 2
    finally:
        unblock.set()
        first.cancel()
        if stopper is not None:
            stopper.cancel()
        await asyncio.gather(
            first, *( [stopper] if stopper is not None else [] ),
            return_exceptions=True,
        )
        module._external_speaker_owner = None
        module._external_speaker_connection = None


@pytest.mark.parametrize("has_native_session", [False, True])
async def test_human_on_one_robot_interrupts_other_mac_proactive_sender(
    native, has_native_session,
):
    """A physical STOP alone cannot stop the Mac's subsequent Opus packets.

    An authenticated human VAD on A must invalidate B's generation before
    flushing B, even when B's external Mac TTS holds the speaker lease and
    B's optional native model is absent.
    """
    module, bridge = native
    head_a, _ = connection()
    head_b, sent = connection()
    head_b.device_id = "mac-02"
    bridge.connections.update({"mac-01": head_a, "mac-02": head_b})
    bridge.interrupt_generation = {"mac-01": 0, "mac-02": 5}
    module._external_speaker_owner = "mac-02"
    module._external_speaker_connection = head_b
    head_b.client_is_speaking = True
    if has_native_session:
        class Session:
            closed = False
            async def _invalidate_head_first(self):
                await head_b.websocket.send(json.dumps({
                    "type": "tts", "state": "stop", "flush": True,
                    "session_id": head_b.session_id,
                }))
                return ({"type": "response.cancel"},)
            def _schedule_remote_cancel(self, events):
                assert events[0]["type"] == "response.cancel"
        module._sessions["mac-02"] = Session()

    started = asyncio.Event()
    release = asyncio.Event()

    async def previous_mac_utterance():
        generation = bridge.interrupt_generation["mac-02"]
        for index in range(4):
            if (head_b.client_abort
                    or generation != bridge.interrupt_generation["mac-02"]):
                return
            await head_b.websocket.send(b"opus")
            if index == 0:
                started.set()
                await release.wait()

    mac = asyncio.create_task(previous_mac_utterance())
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        await module.preempt_others_for_human("mac-01")
        release.set()
        await asyncio.wait_for(mac, timeout=1)
        assert head_b.client_abort is True
        assert bridge.interrupt_generation["mac-02"] == 6
        assert sent.count(b"opus") == 1
        assert any(
            isinstance(message, str)
            and json.loads(message).get("type") == "tts"
            and json.loads(message).get("flush") is True
            for message in sent
        )
        # Do not release the lease before the Mac transmitter's own finally.
        assert module._external_speaker_owner == "mac-02"
    finally:
        release.set()
        mac.cancel()
        await asyncio.gather(mac, return_exceptions=True)
        module._external_speaker_owner = None
        module._external_speaker_connection = None
        module._sessions.clear()


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


async def test_native_respects_operator_quiet_and_paused_direct_human_voice(native):
    module, bridge = native
    conn, sent = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    module._sessions["mac-01"] = session
    try:
        session._pet_quiet = True
        assert await session._send_device_state("start", session._generation) is False
        assert not sent

        session._pet_quiet = False
        session._pet_autonomy_enabled = False
        assert await session._send_device_state("start", session._generation) is False
        assert not sent  # Paused pet cannot initiate by itself.

        # Direct authenticated human speech is still answerable in pause,
        # provided quiet mode was not selected by the operator.
        session._last_human_speech_at = module.time.monotonic()
        assert await session._send_device_state("start", session._generation)
        assert any(isinstance(message, str) and '"state": "start"' in message
                   for message in sent)
        await session._send_device_state("stop", session._generation)
        session._pet_quiet = True
        assert await session._send_device_state("start", session._generation) is False
    finally:
        session.closed = True
        module._sessions.clear()
        module._output_owner = None


async def test_native_operator_stop_revokes_model_and_flushes_real_head(native):
    module, bridge = native
    conn, sent = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    module._sessions["mac-01"] = session
    conn.client_is_speaking = True
    session._last_human_speech_at = module.time.monotonic()
    commands = []
    session._schedule_remote_cancel = lambda events: commands.extend(
        event["type"] for event in events
    )
    try:
        assert await module.suspend_proactive_for_operator(conn) is True
        assert session._pet_quiet is True
        assert session._pet_autonomy_enabled is False
        assert session._generation == 1
        assert conn.client_is_speaking is False
        assert any(isinstance(message, str) and '"flush": true' in message
                   for message in sent)
        assert commands and "response.cancel" in commands
        assert await session._send_device_state("start", session._generation) is False
    finally:
        session.closed = True
        module._sessions.clear()


async def test_native_expired_mac_authorization_stops_private_media_without_tools(
    native,
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
    session._last_authenticated_mac_at = module.time.monotonic() - 12

    class NoMacCall:
        def get(self, *args, **kwargs):
            raise AssertionError(
                "Expired Mac authorization must block a new media/tool poll"
            )

    session._context_wakeup.set()
    await asyncio.wait_for(
        session._refresh_live_context(NoMacCall()), timeout=1,
    )
    assert session.closed
    assert "authorization expired" in session.last_error
    assert session._pet_autonomy_enabled is True  # fake opt in is not an ACK
    assert module.status("mac-01")["native_backend_connected"] is False


async def test_native_model_connection_never_opens_without_current_mac_consent(
    native, monkeypatch,
):
    module, bridge = native
    conn, sent = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session._mac_context_verified = False
    attempts = []

    async def denied(http):
        attempts.append("mac_auth_denied")
        session._mac_context_verified = False

    session._load_private_persona = denied

    class FakeHTTP:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        def ws_connect(self, *args, **kwargs):
            raise AssertionError("Private media reached model without Mac grant")

    monkeypatch.setattr(module.aiohttp, "ClientSession", FakeHTTP)
    await asyncio.wait_for(session.run(), timeout=2)
    assert attempts == ["mac_auth_denied"]
    assert session.closed and not session.connected
    assert "Mac permission required" in session.last_error
    assert not any(isinstance(item, bytes) for item in sent)


async def test_operator_quiet_never_blocks_emergency_native_stop(native):
    module, bridge = native
    conn, sent = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    module._sessions["mac-01"] = session
    session._pet_quiet = True
    conn.client_is_speaking = True
    module._output_owner = "mac-01"
    try:
        assert await session._send_device_state("start", 0) is False
        assert await session._send_device_state("stop", 0) is True
        assert conn.client_is_speaking is False
        assert module._output_owner is None
        assert sent == [json.dumps({
            "type": "tts", "state": "stop",
            "session_id": conn.session_id,
        })]
        await session._send_device_opus(b"do_not_play", 0)
        assert not any(isinstance(data, bytes) for data in sent)
    finally:
        session.closed = True
        module._sessions.clear()
        module._output_owner = None
