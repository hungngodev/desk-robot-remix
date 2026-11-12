"""Opt-in REAL device PCM <-> MiniCPM-o realtime duplex server adapter.

Runs inside the existing pinned Xiaozhi backend. The same websocket continues
to own the physical microphone and speaker. The official vLLM-Omni WebSocket
owns model inference; no invented audio backend and no second device client.
Enable per robot via DESK_ROBOT_OMNI_ROBOTS and DESK_ROBOT_OMNI_URL only after
deploying the actual compatible upstream service. Default is disabled.

Physical AEC, playback timing, audible barge-in, camera exposure sync, native
model performance and continuous long-session stability remain UNVERIFIED.
"""
from __future__ import annotations

import asyncio
import audioop
import hashlib
import ipaddress
import json
import os
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

import aiohttp

# The host test environment installs the Mac package; the isolated pinned
# Xiaozhi server instead receives desk_robot_omni_wire.py from install_overlay.
try:
    from desk_robot.realtime_omni_protocol import OmniDuplexWire, verify_native_server
except ModuleNotFoundError:
    from desk_robot_omni_wire import OmniDuplexWire, verify_native_server

_sessions: dict[str, "NativeOmniSession"] = {}
_output_owner: str | None = None
_output_owner_lock = asyncio.Lock()
# Keep only bounded error diagnostics, never PCM/video or recovered transcripts.
_terminal_errors: dict[str, str] = {}
_retry_after: dict[str, float] = {}


def approved_backend_url(url: str) -> str:
    """No microphone plaintext may leave this Mac over an arbitrary LAN URL."""
    value = urlsplit(url)
    if (value.scheme not in ("ws", "wss") or not value.hostname
            or value.username or value.password or value.fragment
            or value.path != "/v1/realtime" or value.query != "duplex=1"):
        raise ValueError("Use the official realtime /v1/realtime?duplex=1 URL")
    if value.scheme == "ws":
        if value.hostname != "localhost":
            try:
                if not ipaddress.ip_address(value.hostname).is_loopback:
                    raise ValueError("Mic traffic over LAN requires wss://")
            except ValueError as exc:
                raise ValueError("Mic traffic requires loopback ws or secure wss") from exc
    return url


def opted_in(conn) -> bool:
    robot = _robot_id(conn)
    selected = {
        name.strip() for name in
        os.environ.get("DESK_ROBOT_OMNI_ROBOTS", "").split(",")
        if name.strip()
    }
    return robot is not None and robot in selected


def _robot_id(conn) -> str | None:
    # Load only the actual current, registered Xiaozhi websocket identity.
    import desk_robot_bridge as bridge
    if bridge.connections.get(getattr(conn, "device_id", None)) is not conn:
        return None
    return bridge.robot_for_device(conn.device_id)


def active(device: str) -> bool:
    s = _sessions.get(device)
    # A connecting native backend already owns the audio route. Do not
    # grant a competing Mac Kokoro speaker lease during its handshake.
    return s is not None and not s.closed


def status(device: str) -> dict:
    s = _sessions.get(device)
    if s is None:
        return {"native_omni_enabled": device in _terminal_errors,
                "native_backend_connected": False,
                "retry_delay_seconds": round(max(
                    0.0, _retry_after.get(device, 0) - time.monotonic()), 2),
                "last_error": _terminal_errors.get(device),
                "head_audio_playback_acknowledged": False,
                "audio_video_latency_physically_measured": False}
    return {
        "native_omni_enabled": True,
        "native_backend_connected": s.connected and not s.closed,
        "head_audio_playback_acknowledged": False,
        "audio_video_latency_physically_measured": False,
        "mic_frames_forwarded": s.audio_frames,
        "jpeg_frames_forwarded": s.wire.frames_sent,
        "camera_frames_selected": s.video_frames_selected,
        "camera_frames_skipped_static": s.video_frames_skipped_static,
        "camera_frames_skipped_duplicate": s.video_frames_skipped_duplicate,
        "heard_memories_stored": s.heard_memories_stored,
        "heard_memories_dropped": s.heard_memories_dropped,
        "transcript_memory_enabled": s._transcript_memory_enabled,
        "model_pcm_chunks_received": s.model_chunks,
        "model_opus_packets_sent_to_head": s.head_packets,
        "last_error": s.last_error,
    }


@dataclass(frozen=True)
class MicFrame:
    pcm16k: bytes
    speech: bool


class NativeOmniSession:
    """One robot audio route. Full model turn-taking with bounded media queues."""

    def __init__(self, conn, *, url: str, model: str, token: str):
        if _robot_id(conn) is None or len(token) < 24:
            raise ValueError("Current mapped Xiaozhi head and tool secret required")
        if getattr(conn, "client_listen_mode", "") != "realtime":
            raise ValueError("Native voice needs Xiaozhi realtime mode")
        if getattr(conn, "conn_from_mqtt_gateway", False):
            raise ValueError("Native adapter requires direct Xiaozhi WebSocket")
        self.conn = conn
        self.device = conn.device_id
        self.robot = _robot_id(conn)
        self.url = approved_backend_url(url)
        self.token = token
        self.wire = OmniDuplexWire(model=model)
        self.incoming: asyncio.Queue[MicFrame] = asyncio.Queue(maxsize=50)
        self.outgoing: asyncio.Queue[tuple[str, bytes] | None] = asyncio.Queue(maxsize=40)
        self.started: asyncio.Task | None = None
        self.connected = False
        self.closed = False
        self.last_error: str | None = None
        self.audio_frames = 0
        self.model_chunks = 0
        self.head_packets = 0
        self.latest_jpeg: bytes | None = None
        self.latest_frame_time = 0.0
        self._tasks: list[asyncio.Task] = []
        self._pending_cancels: set[asyncio.Task] = set()
        self._socket = None
        self._socket_lock = asyncio.Lock()
        self._device_send_lock = asyncio.Lock()
        self._generation = 0
        self._user_was_talking = False
        self._silent_frames = 0
        self._playback_generation = -1
        # Consent comes from THIS pet's authenticated Mac context. Never
        # persist a microphone transcript unless separately enabled there.
        self._transcript_memory_enabled = False
        self._heard_session = uuid.uuid4().hex[:12]
        self._heard_queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=12)
        self._heard_seen: set[str] = set()
        self.heard_memories_stored = 0
        self.heard_memories_dropped = 0
        # One selected frame per real camera receipt, not one copy per
        # outgoing audio unit. A new VAD turn invalidates old JPEGs.
        self._video_turn = 0
        self._camera_wakeup = asyncio.Event()
        self._latest_frame_receipt_us: int | None = None
        self._last_video_sent_receipt_us: int | None = None
        self._last_video_selected_at = float("-inf")
        self.video_frames_selected = 0
        self.video_frames_skipped_static = 0
        self.video_frames_skipped_duplicate = 0

    def queue_mic(self, pcm: bytes, speech: bool) -> None:
        """Return immediately to the upstream VAD/audio callback."""
        if self.closed:
            return
        if (type(speech) is not bool or not isinstance(pcm, bytes)
                or not 32 <= len(pcm) <= 32000 or len(pcm) % 32):
            self.fail("Unexpected 16k PCM shape from Xiaozhi Opus decoder")
            return
        try:
            self.incoming.put_nowait(MicFrame(pcm, speech))
        except asyncio.QueueFull:
            # Never quietly drop a block of live speech and then hallucinate
            # that the model heard the complete utterance.
            self.fail("Microphone backlog overflow; native stream stopped")

    def fail(self, reason: str) -> None:
        self.last_error = reason[:140]
        self.closed = True
        task = self.started
        if task is not None and not task.done():
            task.cancel()

    async def _send(self, event: dict) -> None:
        if self._socket is None or self.closed:
            raise RuntimeError("Native realtime socket unavailable")
        async with self._socket_lock:
            await self._socket.send_json(event)

    async def _retire_legacy_audio(self) -> None:
        """Clear any previous Xiaozhi welcome/TTS before native model output.

        Only one voice provider may own the head decoder. This is a requested
        firmware flush, NOT an ACK of physically completed I2S playback.
        """
        speaking = bool(getattr(self.conn, "client_is_speaking", False))
        tts = getattr(self.conn, "tts", None)
        pending = False
        if tts is not None:
            for name in ("tts_text_queue", "tts_audio_queue"):
                queue = getattr(tts, name, None)
                if queue is not None and callable(getattr(queue, "empty", None)):
                    pending = pending or not queue.empty()
        if speaking or pending:
            self.conn.client_abort = True
            clear = getattr(self.conn, "clear_queues", None)
            if callable(clear):
                clear()
            async with self._device_send_lock:
                await self.conn.websocket.send(json.dumps({
                    "type": "tts", "state": "stop", "flush": True,
                    "session_id": self.conn.session_id,
                }))
            self.conn.client_is_speaking = False

    async def _load_private_persona(self, http: aiohttp.ClientSession) -> None:
        """Ask the existing Mac authority for THIS robot's voice style.

        Old memories are only included when the operator separately enabled
        voice memory tools in local.toml. Backend failure keeps a safe generic
        persona and does not change the native/legacy audio route.
        """
        url = f"http://127.0.0.1:8765/v1/pet/{self.robot}/omni-context"
        try:
            async with http.get(
                url, headers={"Authorization": f"Bearer {self.token}"},
                timeout=aiohttp.ClientTimeout(total=1.5),
            ) as reply:
                if reply.status != 200:
                    return
                data = await reply.json()
                instructions = data.get("instructions")
                if (data.get("robot_id") == self.robot
                        and isinstance(instructions, str)
                        and 1 <= len(instructions) <= 2000
                        and data.get("model_can_arm_motors") is False):
                    self.wire.instructions = instructions
                    self._transcript_memory_enabled = (
                        data.get("transcript_memory_enabled") is True
                    )
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return

    async def _camera(self, http: aiohttp.ClientSession) -> None:
        """Select real JPEG receipts independently from realtime microphone I/O.

        Mac owns camera capture, grayscale motion and the shared VAD sampler.
        This worker forwards an initial keyframe, meaningful scene changes,
        or a periodic static refresh while this head's user is speaking.
        Optional camera HTTP never blocks a microphone or cancellation packet.
        """
        address = f"http://127.0.0.1:8765/v1/pet/{self.robot}/omni-frame"
        while not self.closed:
            if not self._user_was_talking:
                await self._camera_wakeup.wait()
                self._camera_wakeup.clear()
                continue
            turn = self._video_turn
            try:
                async with http.get(
                    address,
                    headers={"Authorization": f"Bearer {self.token}"},
                    timeout=aiohttp.ClientTimeout(total=1.8),
                ) as response:
                    if (response.status == 200
                            and response.headers.get("X-Desk-Robot-Id") == self.robot
                            and response.headers.get("Content-Type", "").startswith("image/jpeg")):
                        raw = await response.read()
                        age = response.headers.get("X-Desk-Camera-Age-Ms", "")
                        receipt = response.headers.get("X-Desk-Camera-Receipt-Us", "")
                        motion = response.headers.get("X-Desk-Frame-Motion-Ppm", "")
                        if (age.isascii() and age.isdecimal()
                                and receipt.isascii() and receipt.isdecimal()
                                and motion.isascii() and motion.isdecimal()
                                and 0 <= int(age) <= 1000
                                and 0 < int(receipt) < 0x7fffffffffffffff
                                and 0 <= int(motion) <= 1_000_000
                                and 10 <= len(raw) <= 1_000_000
                                and raw.startswith(b"\xff\xd8")
                                and raw.endswith(b"\xff\xd9")
                                and self._user_was_talking
                                and self._video_turn == turn):
                            now = time.monotonic()
                            ident = int(receipt)
                            if ident == self._latest_frame_receipt_us:
                                self.video_frames_skipped_duplicate += 1
                            elif (self._latest_frame_receipt_us is None
                                  or int(motion) >= 15_000
                                  or now - self._last_video_selected_at >= 2.5):
                                self.latest_jpeg = raw
                                self.latest_frame_time = now - int(age) / 1000
                                self._latest_frame_receipt_us = ident
                                self._last_video_selected_at = now
                                self.video_frames_selected += 1
                            else:
                                self.video_frames_skipped_static += 1
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                # A failed optional camera NEVER blocks actual human speech.
                self.latest_jpeg = None
                self._latest_frame_receipt_us = None
            try:
                await asyncio.wait_for(self._camera_wakeup.wait(), timeout=0.8)
            except TimeoutError:
                pass
            self._camera_wakeup.clear()

    async def _send_mic(self) -> None:
        while not self.closed:
            packet = await self.incoming.get()
            self.audio_frames += 1
            was_talking = self._user_was_talking
            if packet.speech:
                self._user_was_talking = True
                if not was_talking:
                    # No image from the preceding spoken turn may be sent
                    # with this voice. Wake the camera without HTTP in VAD.
                    self._video_turn += 1
                    self.latest_jpeg = None
                    self._latest_frame_receipt_us = None
                    self._last_video_sent_receipt_us = None
                    self._last_video_selected_at = float("-inf")
                    self._camera_wakeup.set()
            jpeg, age, receipt = None, None, None
            if (self._user_was_talking and self.latest_jpeg is not None
                    and self._latest_frame_receipt_us
                    != self._last_video_sent_receipt_us):
                candidate_age = round(
                    (time.monotonic() - self.latest_frame_time) * 1000
                )
                if 0 <= candidate_age <= 1000:
                    jpeg, age = self.latest_jpeg, candidate_age
                    receipt = self._latest_frame_receipt_us
            event = self.wire.append_audio(
                packet.pcm16k, speech=packet.speech, jpeg=jpeg,
                camera_age_ms=age,
            )
            await self._send(event)
            # The pinned duplex wire selects at most one JPEG on each
            # one-second audio unit; do not offer the same receipt again.
            if event.get("video_frames"):
                self._last_video_sent_receipt_us = receipt
            if packet.speech:
                self._silent_frames = 0
            elif was_talking:
                self._silent_frames += 1
                if self._silent_frames >= 3:
                    await self._send(self.wire.commit(final=True))
                    self._silent_frames = 0
                    self._user_was_talking = False
                    self._video_turn += 1
                    self.latest_jpeg = None
                    self._latest_frame_receipt_us = None

    async def _receive_model(self) -> None:
        async for message in self._socket:
            if self.closed:
                break
            if message.type != aiohttp.WSMsgType.TEXT:
                raise RuntimeError("Unexpected native omni media frame")
            event = json.loads(message.data)
            kind = event.get("type")
            # A model response may be interrupted at any time. Use a bounded
            # FIFO and response identity, never detached unbounded audio tasks.
            pcm = self.wire.handle_event(event)
            if kind == "response.output_audio.delta" and pcm is not None:
                self.model_chunks += 1
                try:
                    self.outgoing.put_nowait((pcm.response_id, pcm.pcm24k))
                except asyncio.QueueFull as exc:
                    raise RuntimeError("Model audio too fast for XIAO speaker") from exc
            elif (kind == "response.done"
                  and event.get("response_id") == self.wire.response_id):
                await self.outgoing.put(None)

    async def _play(self) -> None:
        """24k model PCM to the SAME Xiaozhi 16k Opus speaker.

        No fabricated playback. A queued/sent packet does not mean the
        transducer has finished playing it, so playback.ack is NEVER sent.
        """
        import opuslib_next  # available in pinned Xiaozhi, not needed for host-only tests
        encoder = opuslib_next.Encoder(
            16000, 1, opuslib_next.APPLICATION_AUDIO
        )
        pending = bytearray()
        resample_state = None
        current_response: str | None = None
        generation = -1
        while not self.closed:
            item = await self.outgoing.get()
            if item is None:
                if current_response is not None and generation == self._generation:
                    if pending:
                        tail = bytes(pending).ljust(1920, b"\0")
                        await self._send_device_opus(encoder.encode(tail, 960), generation)
                    await self._send_device_state("stop", generation)
                pending.clear()
                resample_state = None
                current_response = None
                continue
            response_id, chunk24k = item
            if (self.wire.response_id != response_id
                    or self.closed):
                continue
            if current_response != response_id or generation != self._generation:
                pending.clear()
                resample_state = None
                current_response = response_id
                generation = self._generation
                await self._send_device_state("start", generation)
            pcm16k, resample_state = audioop.ratecv(
                chunk24k, 2, 1, 24000, 16000, resample_state
            )
            pending.extend(pcm16k)
            while len(pending) >= 1920 and generation == self._generation:
                frame = bytes(pending[:1920])
                del pending[:1920]
                await self._send_device_opus(encoder.encode(frame, 960), generation)

    async def _send_device_state(self, state: str, generation: int) -> None:
        global _output_owner
        if self.closed or generation != self._generation:
            return
        import desk_robot_bridge as bridge
        if bridge.connections.get(self.device) is not self.conn:
            raise RuntimeError("Physical robot identity changed during native speech")
        if state == "start":
            # Source-authenticated human VAD has priority even if this model
            # response was already queued. Never speak over another pet's user.
            if not await claim_speaker(self):
                events = await self._invalidate_head_first()
                self._schedule_remote_cancel(events)
                return
            if self.closed or generation != self._generation:
                return
        speech_raced = False
        async with self._device_send_lock:
            if self.closed or generation != self._generation:
                return
            # VAD may start between claim_speaker and acquiring the device
            # send lock. Suppress the TTS START packet in that case.
            if state == "start" and bridge.human_speech_active():
                speech_raced = True
            else:
                if state == "start":
                    self.conn.client_abort = False
                    self.conn.client_is_speaking = True
                await self.conn.websocket.send(json.dumps({
                    "type": "tts", "state": state, "session_id": self.conn.session_id,
                }))
        if speech_raced:
            events = await self._invalidate_head_first()
            self._schedule_remote_cancel(events)
            async with _output_owner_lock:
                if _output_owner == self.device:
                    _output_owner = None
            return
        if state == "stop":
            self.conn.client_is_speaking = False
            async with _output_owner_lock:
                if _output_owner == self.device:
                    _output_owner = None

    async def _send_device_opus(self, packet: bytes, generation: int) -> None:
        global _output_owner
        if self.closed or generation != self._generation:
            return
        import desk_robot_bridge as bridge
        if bridge.connections.get(self.device) is not self.conn:
            raise RuntimeError("Physical robot identity changed")
        blocked_by_human = False
        async with self._device_send_lock:
            # Human VAD can begin AFTER a reply already started, before the
            # queued cross-pet preemption task runs. Check real floor state
            # before every 60 ms packet, not just the TTS START frame.
            if self.closed or generation != self._generation:
                return
            if bridge.human_speech_active():
                blocked_by_human = True
            else:
                await self.conn.websocket.send(packet)
                self.head_packets += 1
        if blocked_by_human:
            events = await self._invalidate_head_first()
            self._schedule_remote_cancel(events)
            async with _output_owner_lock:
                if _output_owner == self.device:
                    _output_owner = None
            return
        # 60ms Opus audio pacing, not an acoustic playback confirmation.
        await asyncio.sleep(0.060)

    async def _invalidate_head_first(self) -> tuple[dict, ...]:
        """Local audio generation, queued PCM and actual head flush first."""
        self._generation += 1
        # A barge-in invalidates both obsolete robot audio and visual
        # context. A camera fetch already in flight must not reintroduce
        # old-turn JPEGs after the head's audio has been flushed.
        self._video_turn += 1
        self.latest_jpeg = None
        self._latest_frame_receipt_us = None
        self._last_video_sent_receipt_us = None
        self._last_video_selected_at = float("-inf")
        if self._user_was_talking:
            self._camera_wakeup.set()
        while not self.outgoing.empty():
            try:
                self.outgoing.get_nowait()
            except asyncio.QueueEmpty:
                break
        events = self.wire.interrupt()  # even without a connected backend
        await flush_head(self)
        return events

    async def _cancel_remote(self, events: tuple[dict, ...]) -> None:
        if self.connected and not self.closed:
            try:
                for event in events:
                    # A wedged model must not delay or repeatedly restart
                    # audio. Source owner remains the registered XIAO head.
                    await asyncio.wait_for(self._send(event), timeout=0.8)
            except (asyncio.TimeoutError, aiohttp.ClientError, RuntimeError) as exc:
                self.fail(f"Native model interrupt failed: {type(exc).__name__}")

    def _schedule_remote_cancel(self, events: tuple[dict, ...]) -> None:
        """After physical flush, free the shared five pet audio floor fast."""
        if not self.connected or self.closed:
            return
        if len(self._pending_cancels) >= 3:
            self.fail("Native cancellation queue overloaded")
            return
        task = asyncio.create_task(self._cancel_remote(events))
        self._pending_cancels.add(task)
        task.add_done_callback(self._pending_cancels.discard)

    async def barge(self) -> None:
        """The actual XIAO gets its flush before remote model cancellation."""
        events = await self._invalidate_head_first()
        await self._cancel_remote(events)

    async def run(self) -> None:
        try:
            await self._retire_legacy_audio()
            async with aiohttp.ClientSession() as http:
                await self._load_private_persona(http)
                async with http.ws_connect(
                    self.url, heartbeat=20, max_msg_size=2_000_000,
                    timeout=8,
                ) as ws:
                    self._socket = ws
                    await self._send(self.wire.session_update())
                    greeting = await ws.receive_json(timeout=8)
                    verify_native_server(greeting, self.wire.model)
                    self.wire.handle_event(greeting)
                    self.connected = True
                    _terminal_errors.pop(self.device, None)
                    _retry_after.pop(self.device, None)
                    self._tasks = [
                        asyncio.create_task(self._send_mic()),
                        asyncio.create_task(self._receive_model()),
                        asyncio.create_task(self._play()),
                        asyncio.create_task(self._camera(http)),
                    ]
                    done, _pending = await asyncio.wait(
                        self._tasks, return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in done:
                        exc = task.exception() if not task.cancelled() else None
                        if exc:
                            raise exc
                    raise RuntimeError("Native realtime worker exited unexpectedly")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {str(exc)[:115]}"
        finally:
            self.connected = False
            self.closed = True
            self._generation += 1
            for task in (*self._tasks, *self._pending_cancels):
                task.cancel()
            if self._tasks or self._pending_cancels:
                await asyncio.gather(
                    *self._tasks, *self._pending_cancels,
                    return_exceptions=True,
                )
            try:
                if self.conn.client_is_speaking:
                    await self.conn.websocket.send(json.dumps({
                        "type": "tts", "state": "stop",
                        "session_id": self.conn.session_id, "flush": True,
                    }))
                    self.conn.client_is_speaking = False
            except Exception:
                pass
            if _sessions.get(self.device) is self:
                _sessions.pop(self.device, None)
                _terminal_errors[self.device] = (
                    self.last_error or "Native model session ended without clean shutdown"
                )[:140]
                _retry_after[self.device] = time.monotonic() + 15.0
            global _output_owner
            async with _output_owner_lock:
                if _output_owner == self.device:
                    _output_owner = None


async def claim_speaker(session: NativeOmniSession) -> bool:
    """One native speaker owner, and NO new reply during human speech."""
    global _output_owner
    import desk_robot_bridge as bridge
    async with _output_owner_lock:
        if bridge.human_speech_active():
            return False
        other_id = _output_owner
        if other_id is not None and other_id != session.device:
            previous = _sessions.get(other_id)
            if previous is not None and not previous.closed:
                # Do not hold the shared five-pet speaker lock while the
                # previous robot's remote model is slow to cancel.
                events = await previous._invalidate_head_first()
                previous._schedule_remote_cancel(events)
        _output_owner = session.device
        return True


async def flush_head(session: NativeOmniSession) -> None:
    """Urgent decoder reset request, NOT an acoustic DMA completion ACK."""
    if session.conn.client_is_speaking:
        async with session._device_send_lock:
            await session.conn.websocket.send(json.dumps({
                "type": "tts", "state": "stop", "flush": True,
                "session_id": session.conn.session_id,
            }))
            session.conn.client_is_speaking = False


async def preempt_others_for_human(source_device: str) -> None:
    """Human conversation takes priority over every native-model pet."""
    global _output_owner
    for device, session in list(_sessions.items()):
        if device != source_device and session.conn.client_is_speaking:
            events = await session._invalidate_head_first()
            session._schedule_remote_cancel(events)
    async with _output_owner_lock:
        # A previous model speaker must not remain recorded as the owner
        # after its audio was stopped for a new human voice.
        if _output_owner is not None and _output_owner != source_device:
            _output_owner = None


def route_audio(conn, pcm_frame: bytes, have_voice: bool) -> bool:
    """Opted-in real PCM bypasses legacy Xiaozhi ASR/LLM/TTS, not in parallel."""
    if not opted_in(conn):
        return False
    import desk_robot_bridge as bridge
    device = conn.device_id
    # Never make a second audio owner while group/peer speech has the
    # exclusive existing Xiaozhi lease. The real VAD still interrupts it.
    if (bridge.lease_stopping
            or (bridge.lease_ids and time.monotonic() < bridge.lease_until)):
        return True
    if time.monotonic() < _retry_after.get(device, 0.0):
        return True  # fail closed during reconnect cooldown, no flood
    session = _sessions.get(device)
    if session is None:
        try:
            token = os.environ.get("DESK_ROBOT_TOOL_TOKEN", "")
            session = NativeOmniSession(
                conn,
                url=os.environ.get("DESK_ROBOT_OMNI_URL", ""),
                model=os.environ.get(
                    "DESK_ROBOT_OMNI_MODEL", "openbmb/MiniCPM-o-4_5"
                ),
                token=token,
            )
            _sessions[device] = session
            session.started = asyncio.create_task(session.run())
        except ValueError as exc:
            # Explicit opt-in means fail closed; never send the same voice
            # unexpectedly to another provider or synthesize old responses.
            _terminal_errors[device] = str(exc)[:140]
            _retry_after[device] = time.monotonic() + 15.0
            return True
    if session.conn is not conn or session.closed:
        return True
    session.queue_mic(pcm_frame, have_voice)
    return True


async def on_barge(conn) -> None:
    session = _sessions.get(getattr(conn, "device_id", None))
    if session is not None and session.conn is conn:
        await session.barge()


def unregister(conn) -> None:
    session = _sessions.get(getattr(conn, "device_id", None))
    if session is not None and session.conn is conn:
        session.fail("Xiaozhi head disconnected")
