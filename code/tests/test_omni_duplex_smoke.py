"""Offline native video/audio probe checks; no service or robot required."""
import asyncio
import importlib.util
import json
import wave
from pathlib import Path

import pytest
from desk_robot.config import load_settings

ROOT = Path(__file__).resolve().parents[1]


def smoke_module():
    spec = importlib.util.spec_from_file_location(
        "omni_duplex_smoke", ROOT / "scripts/omni_duplex_smoke.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_native_audio_probe_rejects_unencrypted_remote_voice_urls():
    probe = smoke_module()
    assert probe.server_url(
        "ws://127.0.0.1:8099/v1/realtime?duplex=1"
    ).startswith("ws://")
    assert probe.server_url(
        "wss://private.example.org/v1/realtime?duplex=1"
    ).startswith("wss://")
    for url in (
        "ws://192.168.1.10/v1/realtime?duplex=1",
        "http://127.0.0.1:8099/v1/realtime?duplex=1",
        "ws://user:secret@127.0.0.1/v1/realtime?duplex=1",
        "ws://127.0.0.1:8099/not-a-model",
    ):
        with pytest.raises(ValueError):
            probe.server_url(url)


def test_native_probe_only_accepts_real_16khz_mono_pcm(tmp_path):
    probe = smoke_module()
    path = tmp_path / "voice.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0" * 3200)
    assert len(probe.read_wav(path)) == 3200
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0" * 3200)
    with pytest.raises(ValueError):
        probe.read_wav(path)


def test_full_hardware_fleet_example_is_valid_and_disarmed():
    settings = load_settings(ROOT / "config/fleet.hardware.example.toml")
    assert settings.mode == "hardware"
    assert len(settings.robots) == 5
    assert not settings.voice_vision_tools_enabled
    assert not settings.voice_memory_tools_enabled
    assert not settings.fleet_text_sharing_enabled
    assert len({robot.id for robot in settings.robots}) == 5
    for robot in settings.robots:
        assert not robot.motion_enabled
        assert not robot.dock_motion_qualified
        assert not robot.exploration_qualified
        assert not robot.gesture_interactions_qualified


def test_legacy_hardware_example_does_not_contain_removed_unknown_flags():
    settings = load_settings(ROOT / "config/robots.example.toml")
    assert settings.mode == "hardware"
    assert settings.vision_model == ""
    assert not settings.voice_vision_tools_enabled



@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled", "closed"])
async def test_native_probe_sends_one_real_av_unit_with_distinct_jpeg_receipt(
    terminal,
):
    """Loopback MiniCPM wire exercises JPEG + 16k PCM before real GPU testing."""
    import asyncio
    import base64
    import json

    from aiohttp import web
    from aiohttp.test_utils import TestServer

    smoke = smoke_module()
    received = []

    async def model_socket(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        async for message in socket:
            event = json.loads(message.data)
            received.append(event)
            if event["type"] == "session.update":
                await socket.send_json({
                    "type": "session.created",
                    "session": {
                        "model": "openbmb/MiniCPM-o-4_5",
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm16",
                        "audio": {
                            "input": {"sample_rate_hz": 16000},
                            "output": {"format": {
                                "type": "audio/pcm", "rate": 24000,
                            }},
                        },
                        "capabilities": {
                            "implementation_level": "model_native_duplex",
                            "supports_input_append": True,
                            "supports_barge_in": True,
                            "chunk_period_ms": 1000,
                        },
                    },
                })
            elif event["type"] == "input_audio_buffer.commit":
                if terminal == "closed":
                    await socket.close()
                    continue
                await socket.send_json({
                    "type": "response.created", "response_id": "real-turn-1",
                    "response": {
                        "id": "real-turn-1",
                        "metadata": {"duplex_event": {"epoch": 0}},
                    },
                })
                await socket.send_json({
                    "type": "response.output_audio.delta",
                    "response_id": "real-turn-1",
                    "format": "pcm16", "sample_rate_hz": 24000,
                    "delta": base64.b64encode(b"\0" * 4800).decode("ascii"),
                    "metadata": {"epoch": 0},
                })
                await socket.send_json({
                    "type": "response.done", "response_id": "real-turn-1",
                    "response": {
                        "id": "real-turn-1", "status": terminal,
                    },
                })
        return socket

    app = web.Application()
    app.router.add_get("/v1/realtime", model_socket)
    jpeg = b"\xff\xd8" + b"camera frame" + b"\xff\xd9"
    async with TestServer(app) as server:
        url = str(server.make_url("/v1/realtime?duplex=1")).replace(
            "http://", "ws://"
        )
        request = smoke.probe(
            url, "openbmb/MiniCPM-o-4_5",
            b"\0" * 32000, jpeg, deadline=5,
        )
        if terminal == "completed":
            output, report = await asyncio.wait_for(request, timeout=8)
        else:
            with pytest.raises(RuntimeError, match=(
                "failed, cancelled or malformed"
                if terminal != "closed" else "ended before response.done"
            )):
                await asyncio.wait_for(request, timeout=8)
            output, report = None, None
    appends = [
        event for event in received
        if event["type"] == "input_audio_buffer.append"
    ]
    assert len(appends) == 10
    assert sum(len(event.get("video_frames", [])) for event in appends) == 1
    assert base64.b64decode(appends[-1]["video_frames"][0]) == jpeg
    if terminal == "completed":
        assert report["video_frames_sent"] == 1
        assert report["head_speaker_connected"] is False
        assert report["actual_playback_acknowledged"] is False
        assert len(output) == 4800
    else:
        assert output is None and report is None



def test_native_probe_rejects_truncated_jpeg_before_opening_model(tmp_path):
    smoke = smoke_module()
    path = tmp_path / "truncated.jpg"
    path.write_bytes(b"\xff\xd8" + b"truncated camera image")
    with pytest.raises(ValueError, match="complete"):
        smoke.read_jpeg(path)


@pytest.mark.asyncio
async def test_native_video_probe_refuses_partial_audio_unit_before_network():
    smoke = smoke_module()
    jpeg = b"\xff\xd8" + b"test camera image" + b"\xff\xd9"
    with pytest.raises(ValueError, match="at least one second"):
        await smoke.probe(
            "ws://127.0.0.1:8099/v1/realtime?duplex=1",
            "openbmb/MiniCPM-o-4_5",
            b"\0" * 3200, jpeg, deadline=5,
        )



@pytest.mark.asyncio
async def test_five_pet_backend_preflight_opens_all_sessions_before_streaming(
    monkeypatch,
):
    """Every real probe waits for all five authenticated model sessions."""
    import asyncio

    smoke = smoke_module()
    entered = set()
    completed = []

    async def admitted_probe(url, model, pcm, jpeg, *, deadline, barrier, quiet_input):
        number = len(entered)
        entered.add(number)
        assert barrier.parties == 5
        await asyncio.wait_for(barrier.wait(), timeout=1)
        assert len(entered) == 5
        completed.append(number)
        return b"opus_conversion_candidate", {
            "native_backend_protocol_only": True,
            "head_speaker_connected": False,
        }

    monkeypatch.setattr(smoke, "probe", admitted_probe)
    responses = await asyncio.wait_for(smoke.probe_fleet(
        "ws://127.0.0.1:8099/v1/realtime?duplex=1",
        "openbmb/MiniCPM-o-4_5", b"pcm", None,
        deadline=5, count=5,
    ), timeout=2)
    assert len(responses) == 5
    assert sorted(completed) == list(range(5))
    assert all(audio for audio, _ in responses)
    for count in (0, 6, True):
        with pytest.raises(ValueError, match="one to five"):
            await smoke.probe_fleet(
                "ws://127.0.0.1:8099/v1/realtime?duplex=1",
                "openbmb/MiniCPM-o-4_5", b"pcm", None,
                deadline=5, count=count,
            )


@pytest.mark.asyncio
async def test_failed_five_pet_backend_preflight_cancels_other_live_sessions(
    monkeypatch,
):
    import asyncio

    smoke = smoke_module()
    release = asyncio.Event()
    cancelled = []

    async def failing_probe(url, model, pcm, jpeg, *, deadline, barrier, quiet_input):
        await barrier.wait()
        if asyncio.current_task().get_name() == "Task-does-not-exist":
            raise AssertionError("unreachable")
        # One real model refuses a session while other models are still
        # producing audio. The fleet smoke must cancel remaining sessions.
        if not release.is_set():
            release.set()
            raise RuntimeError("backend session admission failed")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    monkeypatch.setattr(smoke, "probe", failing_probe)
    with pytest.raises(RuntimeError, match="admission failed"):
        await asyncio.wait_for(smoke.probe_fleet(
            "ws://127.0.0.1:8099/v1/realtime?duplex=1",
            "openbmb/MiniCPM-o-4_5", b"pcm", None,
            deadline=5, count=5,
        ), timeout=2)
    assert cancelled



@pytest.mark.asyncio
async def test_native_av_smoke_propagates_backend_error_during_input_pacing():
    """A bad backend must not consume a minute of prerecorded microphone PCM."""
    import asyncio
    import json

    from aiohttp import web
    from aiohttp.test_utils import TestServer

    smoke = smoke_module()
    appends = []

    async def fail_socket(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        async for message in socket:
            event = json.loads(message.data)
            if event["type"] == "session.update":
                await socket.send_json({
                    "type": "session.created",
                    "session": {
                        "model": "openbmb/MiniCPM-o-4_5",
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm16",
                        "audio": {
                            "input": {"sample_rate_hz": 16000},
                            "output": {"format": {
                                "type": "audio/pcm", "rate": 24000,
                            }},
                        },
                        "capabilities": {
                            "implementation_level": "model_native_duplex",
                            "supports_input_append": True,
                            "supports_barge_in": True,
                            "chunk_period_ms": 1000,
                        },
                    },
                })
            if event["type"] == "input_audio_buffer.append":
                appends.append(event)
                await socket.send_json({
                    "type": "error",
                    "error": {"type": "server_error", "code": "test_failure"},
                })
        return socket

    app = web.Application()
    app.router.add_get("/v1/realtime", fail_socket)
    async with TestServer(app) as server:
        url = str(server.make_url("/v1/realtime?duplex=1")).replace(
            "http://", "ws://"
        )
        with pytest.raises(RuntimeError, match="protocol error"):
            await asyncio.wait_for(
                smoke.probe(url, "openbmb/MiniCPM-o-4_5",
                            b"\0" * (32000 * 20), None, deadline=5),
                timeout=2,
            )
    assert 1 <= len(appends) <= 3



@pytest.mark.asyncio
async def test_real_five_concurrent_websocket_av_sessions_use_independent_receipts():
    """Five actual protocol sockets, not five mocked Python probe calls."""
    import asyncio
    import base64
    import json

    from aiohttp import web
    from aiohttp.test_utils import TestServer

    smoke = smoke_module()
    sessions = []
    appends = []

    async def realtime(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        session_id = len(sessions)
        sessions.append(session_id)
        async for msg in socket:
            event = json.loads(msg.data)
            if event["type"] == "session.update":
                await socket.send_json({
                    "type": "session.created",
                    "session": {
                        "model": "openbmb/MiniCPM-o-4_5",
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm16",
                        "audio": {
                            "input": {"sample_rate_hz": 16000},
                            "output": {"format": {
                                "type": "audio/pcm", "rate": 24000,
                            }},
                        },
                        "capabilities": {
                            "implementation_level": "model_native_duplex",
                            "supports_input_append": True,
                            "supports_barge_in": True,
                            "chunk_period_ms": 1000,
                        },
                    },
                })
            elif event["type"] == "input_audio_buffer.append":
                # The shared preflight barrier must open all five authenticated
                # sessions before ANY model receives its first audio chunk.
                assert len(sessions) == 5
                appends.append((session_id, event))
            elif event["type"] == "input_audio_buffer.commit":
                response_id = f"resp_{session_id}"
                await socket.send_json({
                    "type": "response.created",
                    "response_id": response_id,
                    "response": {"id": response_id,
                                 "metadata": {"duplex_event": {"epoch": 0}}},
                })
                await socket.send_json({
                    "type": "response.output_audio.delta",
                    "response_id": response_id,
                    "format": "pcm16", "sample_rate_hz": 24000,
                    "metadata": {"epoch": 0},
                    "delta": base64.b64encode(bytes(4800)).decode("ascii"),
                })
                await socket.send_json({
                    "type": "response.done",
                    "response_id": response_id,
                    "response": {"id": response_id, "status": "completed"},
                })
        return socket

    app = web.Application()
    app.router.add_get("/v1/realtime", realtime)
    jpeg = bytes((0xff, 0xd8)) + b"one captured frame" + bytes((0xff, 0xd9))
    async with TestServer(app) as server:
        url = str(server.make_url("/v1/realtime?duplex=1")).replace(
            "http://", "ws://",
        )
        result = await asyncio.wait_for(smoke.probe_fleet(
            url, "openbmb/MiniCPM-o-4_5", bytes(32000), jpeg,
            deadline=5, count=5,
        ), timeout=8)
    assert len(result) == 5
    assert len(sessions) == 5
    assert len(appends) == 50
    for session_id in sessions:
        events = [item for owner, item in appends if owner == session_id]
        assert len(events) == 10
        assert sum(len(item.get("video_frames", [])) for item in events) == 1
        assert base64.b64decode(events[-1]["video_frames"][0]) == jpeg
    assert all(len(audio) == 4800 for audio, _ in result)
    assert all(stats["video_frames_sent"] == 1 for _, stats in result)
    assert all(
        stats["head_speaker_connected"] is False
        and stats["actual_playback_acknowledged"] is False
        for _, stats in result
    )



@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["listen", "speak"])
async def test_quiet_mic_video_unit_accepts_intentional_listen_or_real_speech(
    decision,
):
    """Quiet PCM plus a real JPEG reaches native duplex without forged VAD."""
    import asyncio
    import base64
    import json

    from aiohttp import web
    from aiohttp.test_utils import TestServer

    smoke = smoke_module()
    input_events = []
    jpeg = bytes((0xff, 0xd8)) + b"quiet desk scene" + bytes((0xff, 0xd9))

    async def model_socket(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        async for message in socket:
            event = json.loads(message.data)
            if event["type"] == "session.update":
                await socket.send_json({
                    "type": "session.created",
                    "session": {
                        "model": "openbmb/MiniCPM-o-4_5",
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm16",
                        "audio": {
                            "input": {"sample_rate_hz": 16000},
                            "output": {"format": {
                                "type": "audio/pcm", "rate": 24000,
                            }},
                        },
                        "capabilities": {
                            "implementation_level": "model_native_duplex",
                            "supports_input_append": True,
                            "supports_barge_in": True,
                            "chunk_period_ms": 1000,
                        },
                    },
                })
            elif event["type"] == "input_audio_buffer.append":
                input_events.append(event)
                if event.get("video_frames"):
                    if decision == "listen":
                        await socket.send_json({
                            "type": "response.listen",
                            "session_id": "quiet_test",
                            "epoch": 0,
                            "response": {"status": "listening"},
                        })
                    else:
                        await socket.send_json({
                            "type": "response.created", "response_id": "q1",
                            "response": {
                                "id": "q1",
                                "metadata": {"duplex_event": {"epoch": 0}},
                            },
                        })
                        await socket.send_json({
                            "type": "response.output_audio.delta",
                            "response_id": "q1", "format": "pcm16",
                            "sample_rate_hz": 24000,
                            "metadata": {"epoch": 0},
                            "delta": base64.b64encode(bytes(4800)).decode("ascii"),
                        })
                        await socket.send_json({
                            "type": "response.done", "response_id": "q1",
                            "response": {"id": "q1", "status": "completed"},
                        })
        return socket

    app = web.Application()
    app.router.add_get("/v1/realtime", model_socket)
    async with TestServer(app) as server:
        url = str(server.make_url("/v1/realtime?duplex=1")).replace(
            "http://", "ws://",
        )
        result = await asyncio.wait_for(smoke.probe_fleet(
            url, "openbmb/MiniCPM-o-4_5", bytes(32000), jpeg,
            deadline=5, count=1, quiet_input=True,
        ), timeout=8)
    assert len(input_events) == 10
    assert all(item["is_speech"] is False for item in input_events)
    assert input_events[-1]["video_frames"] == [
        base64.b64encode(jpeg).decode("ascii")
    ]
    audio, stats = result[0]
    assert stats["input_mode"] == "quiet_mic"
    assert stats["input_duration_ms"] == 1000
    assert stats["video_frames_sent"] == 1
    assert stats["model_decision"] == decision
    assert stats["input_output_overlap_observed"] is False
    assert stats["input_appends_after_first_audio"] == 0
    assert len(audio) == (0 if decision == "listen" else 4800)
    assert stats["actual_playback_acknowledged"] is False




async def test_native_av_smoke_refuses_empty_completed_response_as_speech():
    """The backend must emit actual PCM or an intentional model listen event."""
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    smoke = smoke_module()

    async def server_socket(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        async for msg in socket:
            event = json.loads(msg.data)
            if event["type"] == "session.update":
                await socket.send_json({
                    "type": "session.created",
                    "session": {
                        "model": "openbmb/MiniCPM-o-4_5",
                        "input_audio_format": "pcm16",
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
                })
            elif (event["type"] == "input_audio_buffer.append"
                  and event.get("video_frames")):
                await socket.send_json({
                    "type": "response.created", "response_id": "empty1",
                    "response": {
                        "id": "empty1",
                        "metadata": {"duplex_event": {"epoch": 0}},
                    },
                })
                await socket.send_json({
                    "type": "response.done", "response_id": "empty1",
                    "response": {"id": "empty1", "status": "completed"},
                })
        return socket

    app = web.Application()
    app.router.add_get("/v1/realtime", server_socket)
    jpeg = b"\xff\xd8" + b"synthetic-frame" + b"\xff\xd9"
    async with TestServer(app) as server:
        url = str(server.make_url("/v1/realtime?duplex=1")).replace(
            "http://", "ws://",
        )
        with pytest.raises(RuntimeError, match="without generated speech"):
            await asyncio.wait_for(
                smoke.probe(
                    url, "openbmb/MiniCPM-o-4_5",
                    bytes(32000), jpeg, deadline=5,
                ),
                timeout=8,
            )

@pytest.mark.asyncio
@pytest.mark.parametrize("quiet_input", [False, True])
async def test_smoke_ignores_superseded_completion_and_stale_listen(quiet_input):
    import asyncio
    import base64
    import json

    from aiohttp import web
    from aiohttp.test_utils import TestServer

    smoke = smoke_module()
    appends = []
    old_audio = bytes(4800)
    new_audio = b"\x01\x00" * 2400

    async def model_socket(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        async for msg in socket:
            event = json.loads(msg.data)
            if event["type"] == "session.update":
                await socket.send_json({
                    "type": "session.created",
                    "session": {
                        "model": "openbmb/MiniCPM-o-4_5", "epoch": 3,
                        "input_audio_format": "pcm16",
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
                })
            elif event["type"] == "input_audio_buffer.append":
                appends.append(event)
                if len(appends) == 1 and quiet_input:
                    await socket.send_json({"type": "response.listen", "epoch": 2})
                if len(appends) != 10:
                    continue
                if quiet_input:
                    await socket.send_json({"type": "response.listen", "epoch": 3})
                    continue

                async def created(response_id):
                    await socket.send_json({
                        "type": "response.created", "response_id": response_id,
                        "response": {"id": response_id, "metadata": {
                            "duplex_event": {"epoch": 3},
                        }},
                    })

                async def audio(response_id, pcm):
                    await socket.send_json({
                        "type": "response.output_audio.delta",
                        "response_id": response_id, "format": "pcm16",
                        "sample_rate_hz": 24000, "metadata": {"epoch": 3},
                        "delta": base64.b64encode(pcm).decode("ascii"),
                    })

                async def done(response_id):
                    await socket.send_json({
                        "type": "response.done", "response_id": response_id,
                        "response": {"id": response_id, "status": "completed"},
                    })

                await created("old")
                await audio("old", old_audio)
                await created("new")
                await done("old")
                await audio("new", new_audio)
                await done("new")
        return socket

    app = web.Application()
    app.router.add_get("/v1/realtime", model_socket)
    async with TestServer(app) as server:
        url = str(server.make_url("/v1/realtime?duplex=1")).replace(
            "http://", "ws://",
        )
        audio, stats = await asyncio.wait_for(smoke.probe(
            url, "openbmb/MiniCPM-o-4_5", bytes(32000), None,
            deadline=5, quiet_input=quiet_input,
        ), timeout=8)
    assert len(appends) == 10
    assert stats["input_duration_ms"] == 1000
    assert stats["model_decision"] == ("listen" if quiet_input else "speak")
    assert audio == (b"" if quiet_input else new_audio)


@pytest.mark.asyncio
@pytest.mark.parametrize("stall", ["greeting", "input"])
async def test_probe_deadline_covers_negotiation_and_paced_input(stall):
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    smoke = smoke_module()
    input_events = []
    commits = []

    async def model_socket(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        async for msg in socket:
            event = json.loads(msg.data)
            if event["type"] == "session.update" and stall == "input":
                await socket.send_json({
                    "type": "session.created",
                    "session": {
                        "model": "openbmb/MiniCPM-o-4_5",
                        "input_audio_format": "pcm16",
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
                })
            elif event["type"] == "input_audio_buffer.append":
                input_events.append(event)
            elif event["type"] == "input_audio_buffer.commit":
                commits.append(event)
        return socket

    app = web.Application()
    app.router.add_get("/v1/realtime", model_socket)
    async with TestServer(app) as server:
        url = str(server.make_url("/v1/realtime?duplex=1")).replace("http://", "ws://")
        # The outer wait only observes termination, never manufactures a
        # TimeoutError that could be mistaken for the probe's own deadline.
        task = asyncio.create_task(smoke.probe(
            url, "openbmb/MiniCPM-o-4_5", bytes(32000 * 20), None,
            deadline=5,
        ))
        try:
            done, _ = await asyncio.wait({task}, timeout=8)
            assert task in done, "Probe ignored its total communication deadline"
            with pytest.raises(TimeoutError):
                await task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert not commits
    if stall == "greeting":
        assert not input_events
    else:
        assert 0 < len(input_events) < 200


def test_declared_wav_frames_must_actually_exist(tmp_path):
    smoke = smoke_module()
    path = tmp_path / "truncated.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(bytes(3200))
    # Keep the declared frame count intact but remove real samples.
    path.write_bytes(path.read_bytes()[:-2])
    with pytest.raises(ValueError, match="Truncated PCM16 WAV data"):
        smoke.read_wav(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("pcm", [b"", b"\x01", bytes(32000 * 60 + 2), bytearray(32)])
async def test_direct_probe_rejects_invalid_pcm_before_network(monkeypatch, pcm):
    smoke = smoke_module()

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid PCM must never open a WebSocket client")

    monkeypatch.setattr(smoke.aiohttp, "ClientSession", forbidden)
    with pytest.raises(ValueError, match="complete PCM16 samples"):
        await smoke.probe(
            "ws://127.0.0.1:8099/v1/realtime?duplex=1",
            "openbmb/MiniCPM-o-4_5", pcm, None, deadline=5,
        )


def test_read_jpeg_enforces_bounded_file_read(tmp_path):
    smoke = smoke_module()
    path = tmp_path / "oversized.jpg"
    path.write_bytes(b"\xff\xd8" + bytes(1_000_000) + b"\xff\xd9")
    with pytest.raises(ValueError, match="complete <=1MB JPEG"):
        smoke.read_jpeg(path)


@pytest.mark.asyncio
async def test_direct_probe_rejects_invalid_jpeg_before_network(monkeypatch):
    smoke = smoke_module()

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid JPEG must never open a WebSocket client")

    monkeypatch.setattr(smoke.aiohttp, "ClientSession", forbidden)
    with pytest.raises(ValueError, match="complete <=1MB JPEG"):
        await smoke.probe(
            "ws://127.0.0.1:8099/v1/realtime?duplex=1",
            "openbmb/MiniCPM-o-4_5", bytes(32000), b"not a JPEG", deadline=5,
        )


@pytest.mark.asyncio
async def test_probe_observes_actual_overlapping_input_and_output():
    import base64

    from aiohttp import web
    from aiohttp.test_utils import TestServer

    smoke = smoke_module()
    appends = []
    pcm = b"\x01\x00" * 2400

    async def model_socket(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        async for msg in socket:
            event = json.loads(msg.data)
            if event["type"] == "session.update":
                await socket.send_json({
                    "type": "session.created",
                    "session": {
                        "model": "openbmb/MiniCPM-o-4_5",
                        "input_audio_format": "pcm16",
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
                })
            elif event["type"] == "input_audio_buffer.append":
                appends.append(event)
                if len(appends) == 1:
                    await socket.send_json({
                        "type": "response.created", "response_id": "overlap",
                        "response": {"id": "overlap", "metadata": {
                            "duplex_event": {"epoch": 0},
                        }},
                    })
                    await socket.send_json({
                        "type": "response.output_audio.delta",
                        "response_id": "overlap", "format": "pcm16",
                        "sample_rate_hz": 24000, "metadata": {"epoch": 0},
                        "delta": base64.b64encode(pcm).decode("ascii"),
                    })
                elif len(appends) == 10:
                    await socket.send_json({
                        "type": "response.done", "response_id": "overlap",
                        "response": {"id": "overlap", "status": "completed"},
                    })
        return socket

    app = web.Application()
    app.router.add_get("/v1/realtime", model_socket)
    async with TestServer(app) as server:
        url = str(server.make_url("/v1/realtime?duplex=1")).replace("http://", "ws://")
        audio, stats = await smoke.probe(
            url, "openbmb/MiniCPM-o-4_5", bytes(32000), None,
            deadline=5,
        )
    assert len(appends) == 10
    assert audio == pcm
    assert stats["input_output_overlap_observed"] is True
    assert 1 <= stats["input_appends_after_first_audio"] <= 9
    assert stats["actual_playback_acknowledged"] is False


def test_fleet_cli_does_not_label_audio_only_turns_as_full_av(monkeypatch, tmp_path, capsys):
    import sys

    smoke = smoke_module()
    monkeypatch.setattr(smoke, "read_wav", lambda path: bytes(32000))

    async def audio_only(*args, **kwargs):
        return [
            (bytes(4800), {
                "video_frames_sent": 0, "input_output_overlap_observed": False,
            }),
            (bytes(4800), {
                "video_frames_sent": 0, "input_output_overlap_observed": True,
            }),
        ]

    monkeypatch.setattr(smoke, "probe_fleet", audio_only)
    monkeypatch.setattr(sys, "argv", [
        "omni_duplex_smoke.py", "--input-wav", str(tmp_path / "input.wav"),
        "--output-wav", str(tmp_path / "output.wav"), "--fleet-sessions", "2",
    ])
    smoke.main()
    report = json.loads(capsys.readouterr().out)
    assert report["backend_turns_completed"] == 2
    assert report["full_av_turns_completed"] == 0
    assert report["input_output_overlap_sessions"] == 1
    assert report["five_physical_robots_verified"] is False
