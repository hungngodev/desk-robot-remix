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
from io import BytesIO

from aiohttp import web

connections = {}
lease_ids: frozenset[str] = frozenset()
lease_until = 0.0
lease_stopping = False
lease_cleanup_task: asyncio.Task | None = None
speaker_lock = asyncio.Lock()
interrupt_generation: dict[str, int] = {}


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


def muted(device_id):
    return device_id in lease_ids and time.monotonic() < lease_until


def suppress_message(conn, message):
    if not muted(conn.device_id):
        return False
    if isinstance(message, bytes):
        return True
    try:
        data = json.loads(message)
        return isinstance(data, dict) and data.get("type") == "listen"
    except (ValueError, TypeError):
        return False


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

    if conn.conn_from_mqtt_gateway:
        raise ValueError("Speech bridge currently requires direct Xiaozhi WebSocket transport")
    # A previous user's explicit interrupt must not be lost when an old
    # provider finishes encoding and tries to begin output.
    generation = interrupt_generation.get(conn.device_id, 0)
    conn.client_abort = False
    conn.client_is_speaking = True
    try:
        await send_tts_message(conn, "start")
        await send_tts_message(conn, "sentence_start", text)
        for packet in frames:
            if conn.client_abort or generation != interrupt_generation.get(conn.device_id, 0) or not muted(conn.device_id):
                raise RuntimeError("Speech interrupted or session expired")
            # Reuse the firmware's existing 16 kHz mono, 60 ms Opus framing.
            await conn.websocket.send(packet)
            conn.last_activity_time = time.time() * 1000
            await asyncio.sleep(0.06)
        await asyncio.sleep(0.24)  # estimated buffer tail; no physical playback acknowledgement
    finally:
        try:
            await send_tts_message(conn, "stop")
        finally:
            conn.clearSpeakStatus()


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
                lease_stopping = True
                for device in lease_ids:
                    if device in connections:
                        connections[device].client_abort = True

                async def finish_stop():
                    global lease_ids, lease_until, lease_stopping
                    # Keep microphones muted until transmission has exited, even if
                    # the caller disconnects while this stop waits for the lock.
                    async with speaker_lock:
                        lease_until = 0
                        lease_ids = frozenset()
                        lease_stopping = False

                lease_cleanup_task = asyncio.create_task(finish_stop())
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
        async with speaker_lock:
            # A queued request may outlive a stop or a device disconnect.
            if lease_stopping or not muted(device) or connections.get(device) is not connection:
                raise RuntimeError("Coordinated session stopped or robot disconnected")
            async with asyncio.timeout(40):
                frames = await asyncio.to_thread(encode_opus, audio)
                if lease_stopping or not muted(device) or connections.get(device) is not connection:
                    raise RuntimeError("Coordinated session stopped or robot disconnected")
                await transmit(connection, text, frames)
        return web.json_response({"transmitted": True, "physical_playback_verified": False})

    async def interrupt(request):
        """Authenticated, immediate cancellation, including queued audio.

        This endpoint does not detect human speech. VAD/AEC must call it on a
        genuine user interruption; server cancellation is not yet audible A2.
        The custom device 'tts abort' branch is installed by the Sense overlay.
        """
        body = await request.json()
        device = body.get("device_id")
        if not isinstance(device, str) or device not in device_map().values():
            raise ValueError("Known device_id required")
        connection = connections.get(device)
        if connection is None:
            raise RuntimeError("Robot is offline")
        interrupt_generation[device] = interrupt_generation.get(device, 0) + 1
        connection.client_abort = True
        # Never wait on speaker_lock here: an active stream may be sleeping
        # under that lock and must be notified immediately.
        await connection.websocket.send(
            json.dumps({"type": "tts", "state": "abort", "session_id": connection.session_id})
        )
        return web.json_response({
            "interrupted": True,
            "device_id": device,
            "head_flush_requested": True,
            "head_flush_acknowledged": False,
            "audible_stop_verified": False,
        })

    app.router.add_post("/session", session)
    app.router.add_post("/interrupt", interrupt)
    app.router.add_post("/speak", speak)
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
