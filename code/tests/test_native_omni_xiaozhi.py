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
    fake_bridge = SimpleNamespace(connections={}, robot_for_device=lambda dev:
                                  "robot-01" if dev == "mac-01" else None)
    monkeypatch.setitem(sys.modules, "desk_robot_bridge", fake_bridge)
    spec = importlib.util.spec_from_file_location(
        "desk_robot_native_omni",
        ROOT / "laptop/server/overlay/desk_robot_native_omni.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "desk_robot_native_omni", module)
    spec.loader.exec_module(module)
    return module, fake_bridge


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
                await ws.send_json({"type": "session.created"})
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
