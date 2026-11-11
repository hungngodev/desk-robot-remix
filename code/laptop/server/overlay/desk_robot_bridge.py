"""Local Xiaozhi speech adapter. Device audio uses upstream conversion and protocol.

This module is copied into the pinned server build, never into its upstream source.
No microphone recording or WebSocket traffic is sent to another robot. A short
lease suppresses ASR during coordinated speech; the transcript travels digitally.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import time
import wave
from collections import deque
from io import BytesIO

from aiohttp import web

connections = {}
lease_ids: frozenset[str] = frozenset()
lease_until = 0.0
lease_stopping = False
lease_cleanup_task: asyncio.Task | None = None
speaker_lock = asyncio.Lock()
# Retain the PR #7 device-specific generation fence for queued or encoding TTS.
interrupt_generation: dict[str, int] = {}
# Never allow one robot to cancel another's reply based on hearing its speaker.
# Only the current device may contribute AEC-cleaned voice during group speech.
active_device_id: str | None = None
voice_frames: dict[str, int] = {}
voice_last_frame_at: dict[str, float] = {}
human_interrupted_devices: set[str] = set()
# Authenticated, bounded, text-only events for the Mac cancellation owner.
# PCM, transcripts, images and bearer tokens never enter this replay buffer.
voice_event_cursor = 0
voice_event_history: deque[dict] = deque(maxlen=128)
# Independent idle-speech start gate, not shared with double-talk counters.
idle_voice_count: dict[str, int] = {}
idle_voice_last_at: dict[str, float] = {}
idle_voice_emitted: set[str] = set()
idle_voice_quiet_frames: dict[str, int] = {}


def record_human_voice(conn, kind: str) -> bool:
    """Only a CURRENT authenticated Xiaozhi websocket can publish human VAD."""
    global voice_event_cursor
    if kind not in ("normal", "group", "speech_start", "speech_end"):
        raise ValueError("Unknown interruption class")
    device = getattr(conn, "device_id", None)
    if connections.get(device) is not conn:
        return False
    robot_id = robot_for_device(device)
    if robot_id is None:
        return False
    voice_event_cursor += 1
    voice_event_history.append({
        "seq": voice_event_cursor, "robot_id": robot_id,
        "kind": kind,
        "source": "xiaozhi_server_vad" if kind in ("speech_start", "speech_end")
                  else "xiaozhi_aec_vad",
    })
    return True



def device_map():
    mapping = json.loads(os.environ.get("DESK_ROBOT_DEVICE_MAP", "{}"))
    if not isinstance(mapping, dict) or not mapping or len(set(mapping.values())) != len(mapping):
        raise ValueError("Configure a unique robot ID -> Xiaozhi device ID mapping")
    if not all(isinstance(k, str) and isinstance(v, str) and k and v for k, v in mapping.items()):
        raise ValueError("Device IDs must be nonempty strings")
    return mapping


def robot_for_device(device_id):
    return next((robot for robot, device in device_map().items() if device == device_id), None)


def register(conn):
    if conn.device_id in device_map().values():
        # Reject duplicate identities instead of sending a robot's audio elsewhere.
        existing = connections.get(conn.device_id)
        if existing is not None and existing is not conn:
            raise RuntimeError("Duplicate live Xiaozhi device identity")
        connections[conn.device_id] = conn


def unregister(conn):
    if connections.get(conn.device_id) is conn:
        connections.pop(conn.device_id, None)
        idle_voice_count.pop(conn.device_id, None)
        idle_voice_last_at.pop(conn.device_id, None)
        idle_voice_emitted.discard(conn.device_id)
        idle_voice_quiet_frames.pop(conn.device_id, None)
        # A queued request may outlive this socket and a replacement register.
        interrupt_generation[conn.device_id] = (
            interrupt_generation.get(conn.device_id, 0) + 1
        )


def muted(device_id):
    return device_id in lease_ids and time.monotonic() < lease_until


def duplex_available(conn) -> bool:
    """Only a real device AEC/realtime session may stream double-talk audio.

    If actual head AEC is disabled or misconfigured, retain the old safe
    suppression rather than creating endless self-triggered conversations.
    A successful physical A2 trial is still required.
    """
    return getattr(conn, "client_listen_mode", "") == "realtime"


def observe_idle_human_voice(conn, have_voice: bool) -> bool:
    """Emit real human VAD START while Xiaozhi is listening and not talking.

    Native Xiaozhi ASR still receives every original audio packet. This
    function never stops device speech, changes ASR, or manufactures a
    transcript. Double-talk is handled by the existing separate AEC path.
    """
    device = getattr(conn, "device_id", None)
    if not have_voice:
        idle_voice_count.pop(device, None)
        idle_voice_last_at.pop(device, None)
        if device in idle_voice_emitted:
            quiet = idle_voice_quiet_frames.get(device, 0) + 1
            idle_voice_quiet_frames[device] = quiet
            if quiet >= 2:
                # Two genuine VAD-negative calls end the user turn. A brief
                # pause inside a word/phrase does not terminate video early.
                # The original Xiaozhi ASR/speaker state stays untouched.
                if connections.get(device) is conn:
                    record_human_voice(conn, "speech_end")
                idle_voice_emitted.discard(device)
                idle_voice_quiet_frames.pop(device, None)
        return False
    if (connections.get(device) is not conn
            or muted(device) or lease_stopping
            or getattr(conn, "client_is_speaking", False)
            or getattr(conn, "client_abort", False)
            or getattr(conn, "client_listen_mode", "") not in ("auto", "realtime")):
        idle_voice_count.pop(device, None)
        idle_voice_last_at.pop(device, None)
        return False
    idle_voice_quiet_frames.pop(device, None)
    if device in idle_voice_emitted:
        return False
    now = time.monotonic()
    gap = now - idle_voice_last_at.get(device, -1e9)
    count = idle_voice_count.get(device, 0) + 1 if 0 <= gap <= 0.3 else 1
    idle_voice_count[device] = min(count, 2)
    idle_voice_last_at[device] = now
    if count < 2:
        return False
    if not record_human_voice(conn, "speech_start"):
        return False
    idle_voice_emitted.add(device)
    return True


def was_interrupted_by_human(device_id):
    return device_id in human_interrupted_devices


def suppress_message(conn, message):
    if not muted(conn.device_id):
        return False
    if isinstance(message, bytes):
        return not (conn.device_id == active_device_id and duplex_available(conn))
    try:
        data = json.loads(message)
        # The existing listener setup is established before the speaker lease.
        # A fresh listen request during group playback cannot reset ASR state.
        return isinstance(data, dict) and data.get("type") == "listen"
    except (ValueError, TypeError):
        return False


def _start_lease_cleanup() -> None:
    """Complete cleanup even when the HTTP caller disappears mid-abort."""
    global lease_stopping, lease_cleanup_task
    if lease_cleanup_task is not None and not lease_cleanup_task.done():
        return
    lease_stopping = True

    async def finish_stop():
        global lease_ids, lease_until, lease_stopping, active_device_id
        async with speaker_lock:
            lease_until = 0
            lease_ids = frozenset()
            lease_stopping = False
            active_device_id = None
            voice_frames.clear()
            voice_last_frame_at.clear()
            human_interrupted_devices.clear()

    lease_cleanup_task = asyncio.create_task(finish_stop())



def sustained_voice(device_id: str, have_voice: bool) -> bool:
    """Keep two consecutive VAD-positive real PCM frames within 300ms.

    Missing frames or idle gaps reset confirmation. The first human frames are
    still forwarded to ASR independently, never lost to this decision gate.
    """
    if not have_voice:
        voice_frames.pop(device_id, None)
        voice_last_frame_at.pop(device_id, None)
        return False
    now = time.monotonic()
    previous = voice_last_frame_at.get(device_id, 0)
    count = voice_frames.get(device_id, 0) if 0 <= now - previous <= 0.3 else 0
    voice_frames[device_id] = min(count + 1, 2)
    voice_last_frame_at[device_id] = now
    return voice_frames[device_id] >= 2


async def interrupt_for_normal_voice(conn, have_voice: bool) -> bool:
    """Barge in during ordinary Xiaozhi speech, not only group speech.

    Reuses upstream abort semantics (queue invalidation) with our Sense
    urgent flush extension. Device AEC + realtime listen mode is mandatory.
    This does not claim unmeasured acoustic double-talk performance.
    """
    device = conn.device_id
    if muted(device) or lease_stopping:
        return False  # Coordinated sessions have their own interrupt path.
    if (getattr(conn, "client_listen_mode", "") != "realtime"
            or not getattr(conn, "client_is_speaking", False)):
        voice_frames.pop(device, None)
        voice_last_frame_at.pop(device, None)
        return False
    if not sustained_voice(device, have_voice):
        return False
    # Mirrored from the pinned upstream handleAbortMessage except the stop
    # includes flush:true to discard old decoder PCM and speaker DMA.
    conn.close_after_chat = False
    conn.client_abort = True
    conn.clear_queues()
    interrupt_generation[device] = interrupt_generation.get(device, 0) + 1
    try:
        await conn.websocket.send(json.dumps({
            "type": "tts", "state": "stop",
            "session_id": conn.session_id, "flush": True,
        }))
    finally:
        conn.clearSpeakStatus()
        voice_frames.pop(device, None)
        voice_last_frame_at.pop(device, None)
    record_human_voice(conn, "normal")
    return True


async def interrupt_for_user_voice(conn, have_voice: bool) -> bool:
    """Adapt upstream Xiaozhi VAD with a minimal two-frame double-talk gate.

    The mic PCM passes through to upstream ASR throughout; nothing is clipped
    waiting for the decision. The first two real voice frames are retained.
    """
    global lease_stopping
    device = conn.device_id
    if (
        not muted(device) or active_device_id != device
        or not duplex_available(conn) or lease_stopping
    ):
        voice_frames.pop(device, None)
        return False
    if not sustained_voice(device, have_voice):
        return False
    # Never let an old unsolicited TTS resume after detecting human speech.
    human_interrupted_devices.add(device)
    interrupt_generation[device] = interrupt_generation.get(device, 0) + 1
    conn.client_abort = True
    conn.close_after_chat = False
    _start_lease_cleanup()
    # A normal Xiaozhi 'tts stop' waits for its queued stream and does not
    # empty I2S DMA. This explicit stop extension is handled by Sense firmware.
    await conn.websocket.send(json.dumps({
        "type": "tts", "state": "stop", "session_id": conn.session_id,
        "flush": True,
    }))
    record_human_voice(conn, "group")
    return True


def wav_audio(encoded):
    if not isinstance(encoded, str) or len(encoded) > 5_600_000:
        raise ValueError("WAV payload exceeds limit")
    audio = base64.b64decode(encoded, validate=True)
    if len(audio) > 4_000_000:
        raise ValueError("WAV payload exceeds limit")
    with wave.open(BytesIO(audio), "rb") as wav:
        duration = wav.getnframes() / wav.getframerate()
        if (
            not 0 < duration <= 30
            or wav.getnchannels() not in (1, 2)
            or not (8000 <= wav.getframerate() <= 48000)
            or wav.getsampwidth() != 2
        ):
            raise ValueError("Expected 16-bit mono/stereo PCM WAV up to 30 seconds")
    return audio


def encode_opus(audio):
    from core.utils.util import audio_bytes_to_data_stream

    frames = []
    audio_bytes_to_data_stream(audio, "wav", True, frames.append, sample_rate=16000)
    if not frames or len(frames) > 501:
        raise ValueError("Opus duration exceeds limit")
    return frames


async def transmit(conn, text, frames):
    from core.handle.sendAudioHandle import send_tts_message

    global active_device_id
    active_device_id = conn.device_id
    voice_frames.pop(conn.device_id, None)
    voice_last_frame_at.pop(conn.device_id, None)
    if conn.conn_from_mqtt_gateway:
        raise ValueError("Speech bridge currently requires direct Xiaozhi WebSocket transport")
    # The speaker lock and callers serialize transmission, but cancellation
    # does not wait for that lock. Capture generation before clearing stale
    # abort state; once interrupted this exact transmission cannot restart.
    generation = interrupt_generation.get(conn.device_id, 0)
    conn.client_abort = False
    conn.client_is_speaking = True
    try:
        await send_tts_message(conn, "start")
        await send_tts_message(conn, "sentence_start", text)
        for packet in frames:
            if (conn.client_abort
                    or generation != interrupt_generation.get(conn.device_id, 0)
                    or not muted(conn.device_id)):
                raise RuntimeError("Speech interrupted or session expired")
            # Reuse the firmware's existing 16 kHz mono, 60 ms Opus framing.
            await conn.websocket.send(packet)
            conn.last_activity_time = time.time() * 1000
            await asyncio.sleep(0.06)
        await asyncio.sleep(0.24)  # estimated buffer tail; no physical playback acknowledgement
        if conn.client_abort or generation != interrupt_generation.get(conn.device_id, 0):
            raise RuntimeError("Speech interrupted during playback tail")
    finally:
        try:
            if (conn.client_abort
                    or generation != interrupt_generation.get(conn.device_id, 0)):
                # Bypass upstream normal stop's wait-for-all-audio behavior.
                await conn.websocket.send(json.dumps({
                    "type": "tts", "state": "stop",
                    "session_id": conn.session_id, "flush": True,
                }))
            else:
                await send_tts_message(conn, "stop")
        finally:
            conn.clearSpeakStatus()
            if active_device_id == conn.device_id:
                active_device_id = None


def create_app():
    token = os.environ.get("DESK_ROBOT_SPEECH_TOKEN", "")
    if len(token) < 24:
        raise ValueError("Set private DESK_ROBOT_SPEECH_TOKEN before starting server")
    device_map()

    @web.middleware
    async def auth(request, handler):
        if not secrets.compare_digest(request.headers.get("Authorization", ""), f"Bearer {token}"):
            raise web.HTTPUnauthorized()
        try:
            return await handler(request)
        except (ValueError, wave.Error) as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        except RuntimeError as exc:
            raise web.HTTPConflict(text=str(exc)) from exc

    app = web.Application(middlewares=[auth], client_max_size=5_700_000)

    async def session(request):
        global lease_ids, lease_until, lease_stopping, lease_cleanup_task
        body = await request.json()
        ids = body.get("device_ids")
        if (
            not isinstance(ids, list)
            or not ids
            or len(ids) > 5
            or not all(isinstance(i, str) for i in ids)
        ):
            raise ValueError("Choose one to five device IDs")
        selected = frozenset(ids)
        if len(selected) != len(ids) or not selected.issubset(set(device_map().values())):
            raise ValueError("Unknown or duplicate device identity")
        if body.get("enabled") is True:
            if lease_stopping or time.monotonic() < lease_until:
                raise RuntimeError("A coordinated session is already active")
            for device in selected:
                conn = connections.get(device)
                if conn is None or conn.tts is None:
                    raise RuntimeError("Selected robot is offline or audio is not ready")
                if (
                    conn.client_is_speaking
                    or conn.calling
                    or not conn.tts.tts_text_queue.empty()
                    or not conn.tts.tts_audio_queue.empty()
                ):
                    raise RuntimeError("Wait for the current robot speech to finish")
            lease_ids, lease_until = selected, time.monotonic() + 305
        elif body.get("enabled") is False:
            if lease_ids and lease_ids != selected:
                raise RuntimeError("Session identities differ")
            if not lease_stopping:
                for device in lease_ids:
                    interrupt_generation[device] = interrupt_generation.get(device, 0) + 1
                    if device in connections and device not in human_interrupted_devices:
                        connections[device].client_abort = True
                _start_lease_cleanup()
            if lease_cleanup_task is not None:
                await asyncio.shield(lease_cleanup_task)
        else:
            raise ValueError("enabled must be a boolean")
        return web.json_response(
            {"enabled": body["enabled"], "expires_in_seconds": 305 if body["enabled"] else 0}
        )

    async def speak(request):
        body = await request.json()
        device, text = body.get("device_id"), body.get("text")
        connection = connections.get(device) if isinstance(device, str) else None
        if connection is None or lease_stopping or not muted(device):
            raise RuntimeError("No active coordinated session for this robot")
        if not isinstance(text, str) or not 1 <= len(text) <= 2000:
            raise ValueError("Speech text must be 1..2000 characters")
        audio = wav_audio(body.get("wav_base64"))
        # Snapshot before the potentially long speaker queue and Opus encoding.
        # Never clear a more recent interrupt by beginning an obsolete request.
        generation = interrupt_generation.get(device, 0)
        async with speaker_lock:
            if (lease_stopping or not muted(device) or connections.get(device) is not connection
                    or generation != interrupt_generation.get(device, 0)):
                raise RuntimeError("Coordinated session stopped, interrupted or robot disconnected")
            async with asyncio.timeout(40):
                frames = await asyncio.to_thread(encode_opus, audio)
                if (lease_stopping or not muted(device) or connections.get(device) is not connection
                        or generation != interrupt_generation.get(device, 0)):
                    raise RuntimeError("Coordinated session stopped, interrupted or robot disconnected")
                await transmit(connection, text, frames)
        return web.json_response({"transmitted": True, "physical_playback_verified": False})

    async def interrupt(request):
        """Immediate authenticated head DMA flush without awaiting speaker_lock.

        Only the specified registered device is canceled. The generation bump
        fences previously queued, encoding and transmitting requests. A returned
        result acknowledges the request to flush, not audible completion.
        """
        body = await request.json()
        device = body.get("device_id") if isinstance(body, dict) else None
        if not isinstance(device, str) or device not in device_map().values():
            raise ValueError("Known device_id required")
        connection = connections.get(device)
        if connection is None:
            raise RuntimeError("Robot is offline")
        interrupt_generation[device] = interrupt_generation.get(device, 0) + 1
        connection.client_abort = True
        # Device firmware expects a stop with flush=True, not PR #7's earlier
        # abort frame. The actual Sense overlay handles the decoder/DMA reset.
        await connection.websocket.send(json.dumps({
            "type": "tts", "state": "stop",
            "session_id": connection.session_id, "flush": True,
        }))
        return web.json_response({
            "interrupted": True,
            "device_id": device,
            "head_flush_requested": True,
            "head_flush_acknowledged": False,
            "audible_stop_verified": False,
        })

    async def voice_readiness(request):
        """Read the actual connected Xiaozhi session, not a stored configuration.

        The server cannot verify analog acoustic AEC performance or audible
        cancellation. Preserve these false flags until measured WAV trials.
        """
        device = request.query.get("device_id")
        if device not in device_map().values():
            raise ValueError("Known device_id required")
        conn = connections.get(device)
        connected = conn is not None
        mode = getattr(conn, "client_listen_mode", None) if connected else None
        if mode not in ("auto", "manual", "realtime"):
            mode = None
        return web.json_response({
            "device_id": device,
            "connected": connected,
            "reported_listen_mode": mode,
            "realtime_audio_path_available": connected and mode == "realtime",
            "speaking": bool(getattr(conn, "client_is_speaking", False)) if connected else False,
            "device_aec_measured": False,
            "microphone_double_talk_measured": False,
            "audible_flush_measured": False,
            "natural_barge_in_certified": False,
        })

    async def voice_events(request):
        """Replay actual interruption metadata without raw voice or model text."""
        raw = request.query.get("after", "0")
        if not raw.isascii() or not raw.isdecimal() or len(raw) > 19:
            raise ValueError("Invalid voice event cursor")
        after = int(raw)
        if after > 0x7fffffffffffffff:
            raise ValueError("Voice event cursor out of range")
        if request.query.get("bootstrap") == "1":
            return web.json_response({
                "cursor": voice_event_cursor, "events": [],
                "reset": False, "lost": False,
            })
        if after > voice_event_cursor:
            return web.json_response({
                "cursor": voice_event_cursor, "events": [],
                "reset": True, "lost": False,
            })
        earliest = voice_event_history[0]["seq"] if voice_event_history else voice_event_cursor + 1
        return web.json_response({
            "cursor": voice_event_cursor,
            "events": [item for item in voice_event_history if item["seq"] > after],
            "reset": False, "lost": after < earliest - 1,
        })

    app.router.add_get("/events", voice_events)
    app.router.add_post("/session", session)
    app.router.add_post("/speak", speak)
    app.router.add_post("/interrupt", interrupt)
    app.router.add_get("/voice-readiness", voice_readiness)
    return app


async def start():
    runner = web.AppRunner(create_app())
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 8766).start()
    except BaseException:
        await runner.cleanup()
        raise
    return runner
