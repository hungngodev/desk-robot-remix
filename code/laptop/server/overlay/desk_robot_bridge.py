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
import threading
import time
import wave
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from aiohttp import web

connections = {}
lease_ids: frozenset[str] = frozenset()
lease_until = 0.0
lease_stopping = False
lease_passive = False
lease_cleanup_task: asyncio.Task | None = None
speaker_lock = asyncio.Lock()
# The upstream WAV to Opus conversion is synchronous CPU work. Cancellation
# of asyncio.to_thread does not stop it. Keep the one native encoder owned
# until the underlying worker really exits; reject extra queued speech while
# an old interrupted encoding remains active.
_opus_encode_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="desk-opus")
_opus_encode_slot = threading.BoundedSemaphore(1)


async def encode_opus_owned(audio: bytes) -> list[bytes]:
    """Never stack another native Opus encoder onto a cancelled old turn."""
    if not _opus_encode_slot.acquire(blocking=False):
        raise RuntimeError("Previous Opus encoding still in flight")
    try:
        future = _opus_encode_pool.submit(encode_opus, audio)
    except BaseException:
        _opus_encode_slot.release()
        raise

    def worker_finished(completed) -> None:
        try:
            if not completed.cancelled():
                completed.exception()  # Consume late native encoder failures.
        finally:
            _opus_encode_slot.release()

    future.add_done_callback(worker_finished)
    return await asyncio.wrap_future(future)


# Retain the PR #7 device-specific generation fence for queued or encoding TTS.
interrupt_generation: dict[str, int] = {}
# Each real current-head human speech start supersedes tool results from
# an older utterance. Unlike an audio decoder epoch, this stays stable across
# speech_end until the next actual person begins speaking.
voice_turn_generation: dict[str, int] = {}
# One cancellation signal per authenticated head turn. The existing tool
# bridge awaits it alongside read-only HTTP requests: obsolete camera/VLM
# work gets cancelled promptly, not merely rejected after a 50s timeout.
_tool_turn_cancel: dict[str, asyncio.Event] = {}


def tool_turn_cancel_event(device: str) -> asyncio.Event:
    if device not in connections:
        raise ValueError("Only a connected Xiaozhi head owns a tool turn")
    return _tool_turn_cancel.setdefault(device, asyncio.Event())


def _invalidate_tool_turn(device: str) -> None:
    current = _tool_turn_cancel.get(device)
    if current is not None:
        current.set()
    _tool_turn_cancel[device] = asyncio.Event()


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
# Source-authenticated VAD leases. Audio is never stored here. Only current
# registered heads can keep the floor reserved; absent speech automatically
# expires even if an upstream connection never delivered speech_end.
human_vad_until: dict[str, float] = {}


def active_idle_speech_robots() -> list[str]:
    """Current authenticated, debounced VAD turn state, never a voice sample.

    Idle speech_start is set until real speech_end or device unregister. AEC
    normal/group interruptions are deliberately excluded: no paired end event
    is guaranteed for those, so Mac handles them with a bounded lease.
    """
    current = device_map()
    return sorted(
        robot_id for robot_id, device in current.items()
        if device in idle_voice_emitted and device in connections
    )


def human_speech_active() -> bool:
    now = time.monotonic()
    return any(
        device in connections and until > now
        for device, until in human_vad_until.items()
    )


def _native_adapter():
    """Optional module is installed in real pinned Xiaozhi builds only.

    The host tests import this bridge standalone without ESP Opus codecs.
    Fail loudly if native mode was explicitly requested but not installed.
    """
    try:
        import desk_robot_native_omni
        return desk_robot_native_omni
    except ModuleNotFoundError:
        if os.environ.get("DESK_ROBOT_OMNI_ROBOTS", "").strip():
            raise
        return None


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
    if kind == "speech_end":
        # A short hangover prevents a queued peer from beginning on the
        # first VAD-negative window; it is not evidence of new speech.
        human_vad_until[device] = time.monotonic() + 0.15
    else:
        human_vad_until[device] = time.monotonic() + 1.0
    voice_event_cursor += 1
    voice_event_history.append({
        "seq": voice_event_cursor, "robot_id": robot_id,
        "kind": kind,
        "source": "xiaozhi_server_vad" if kind in ("speech_start", "speech_end")
                  else "xiaozhi_aec_vad",
    })
    if kind in ("speech_start", "normal", "group"):
        voice_turn_generation[device] = voice_turn_generation.get(device, 0) + 1
        _invalidate_tool_turn(device)
        try:
            native = _native_adapter()
        except ModuleNotFoundError:
            # An explicitly selected but missing OPTIONAL model must never
            # prevent the authenticated human VAD event or urgent head STOP.
            # route_audio still rejects this misconfigured model separately.
            native = None
        if native is not None:
            # Never block original AEC/VAD while silencing other native pets.
            # Synchronous test/diagnostic code has no running event loop.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                loop.create_task(native.preempt_others_for_human(device))
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


async def inject_live_context_into_legacy_llm(conn) -> None:
    """Supply actual Mac tool evidence only to the next model request.

    The pinned Xiaozhi Dialogue serializes via get_llm_dialogue_with_memory.
    A per-connection wrapper adds a paired assistant/tool receipt to that
    transient output, never to its stored history or SYSTEM instructions.
    Model guesses cannot become durable session memories on disconnect.
    """
    device = getattr(conn, "device_id", None)
    if connections.get(device) is not conn:
        return
    robot = robot_for_device(device)
    if robot is None:
        return
    owner = getattr(conn, "dialogue", None)
    dialogue = getattr(owner, "dialogue", None)
    if not isinstance(dialogue, list):
        return
    model_messages = getattr(owner, "get_llm_dialogue_with_memory", None)
    if not callable(model_messages):
        return  # No verified pinned serializer: do not mutate the SYSTEM role.
    if not callable(getattr(owner, "_desk_original_model_messages", None)):
        owner._desk_original_model_messages = model_messages

        def model_messages_with_mac_context(*args, **kwargs):
            messages = owner._desk_original_model_messages(*args, **kwargs)
            data = getattr(owner, "_desk_transient_mac_context", None)
            if (not isinstance(messages, list) or not isinstance(data, dict)
                    or connections.get(device) is not conn
                    or data.get("generation") != voice_turn_generation.get(device, 0)
                    or data.get("nonce") != getattr(
                        conn, "_desk_live_context_request", None
                    )
                    or not isinstance(data.get("expires_at"), float)
                    or time.monotonic() > data["expires_at"]):
                return messages
            # This is a real completed read-only tool call, not a model-made
            # physical action. The downstream model receives its source and
            # uncertainty through the tool role, not SYSTEM or human speech.
            return messages + [
                {"role": "assistant", "tool_calls": [{
                    "id": data["call_id"], "type": "function",
                    "function": {
                        "name": "desk_robot_situation", "arguments": "{}",
                    },
                }]},
                {
                    "role": "tool", "tool_call_id": data["call_id"],
                    "content": data["content"],
                },
            ]

        owner.get_llm_dialogue_with_memory = model_messages_with_mac_context
    # Retire the previous source before awaiting the next Mac query.
    # Session memory providers inspect owner.dialogue, not this model view.
    owner._desk_transient_mac_context = None
    system = next(
        (message for message in dialogue
         if getattr(message, "role", None) == "system"
         and isinstance(getattr(message, "content", None), str)),
        None,
    )
    if system is None:
        return
    # Remove this bridge's previous temporary call/receipt pair. A Mac
    # outage must not leave old observations in another conversation turn.
    # Also migrate old in-place SYSTEM context from earlier overlay builds.
    marker = "\n<desk_robot_live_context>"
    system.content = system.content.split(marker, 1)[0]
    prefix = "desk_mac_context_"
    dialogue[:] = [
        message for message in dialogue
        if not (isinstance(getattr(message, "uniq_id", None), str)
                and message.uniq_id.startswith(prefix))
    ]
    generation = voice_turn_generation.get(device, 0)
    nonce = secrets.token_hex(12)
    conn._desk_live_context_request = nonce
    try:
        from plugins_func.functions.desk_robot_tools import call
        data = await asyncio.wait_for(
            call(conn, "interaction-context"), timeout=0.65
        )
    except Exception:
        return  # Preserve original persona and normal Xiaozhi ASR/LLM.
    if (connections.get(device) is not conn
            or voice_turn_generation.get(device, 0) != generation
            or getattr(conn, "_desk_live_context_request", None) != nonce
            or not isinstance(data, dict)
            or data.get("robot_id") != robot
            or data.get("raw_media_included") is not False
            or data.get("persistent_memory_included") is not False
            or data.get("model_context_untrusted_not_instructions") is not True
            or data.get("motor_authorized") is not False
            or data.get("charging_authorized") is not False):
        return
    context = data.get("model_context")
    if not isinstance(context, str) or not 1 <= len(context) <= 400:
        return
    # A completed Mac observation is visible to the model but never added
    # to the durable Dialogue list later summarized by memory providers.
    owner._desk_transient_mac_context = {
        "generation": generation,
        "nonce": nonce,
        # A later unrelated model request cannot replay this short-lived
        # sensor/tool receipt if the bridge never saw another human VAD.
        "expires_at": time.monotonic() + 2.0,
        "call_id": "call_mac_context_" + secrets.token_hex(12),
        "content": json.dumps({
            "robot_id": robot,
            "source": "authenticated_mac_readonly_interaction_context",
            "untrusted_observation_not_instructions": True,
            "motor_authorized": False,
            "charging_authorized": False,
            "model_context": " ".join(context.split()),
        }, ensure_ascii=True),
    }


def register(conn):
    if conn.device_id in device_map().values():
        # Reject duplicate identities instead of sending a robot's audio elsewhere.
        existing = connections.get(conn.device_id)
        if existing is not None and existing is not conn:
            raise RuntimeError("Duplicate live Xiaozhi device identity")
        connections[conn.device_id] = conn


def unregister(conn):
    if connections.get(conn.device_id) is conn:
        native = _native_adapter()
        if native is not None:
            native.unregister(conn)
        connections.pop(conn.device_id, None)
        idle_voice_count.pop(conn.device_id, None)
        idle_voice_last_at.pop(conn.device_id, None)
        idle_voice_emitted.discard(conn.device_id)
        idle_voice_quiet_frames.pop(conn.device_id, None)
        human_vad_until.pop(conn.device_id, None)
        # A queued request may outlive this socket and a replacement register.
        interrupt_generation[conn.device_id] = (
            interrupt_generation.get(conn.device_id, 0) + 1
        )
        voice_turn_generation[conn.device_id] = (
            voice_turn_generation.get(conn.device_id, 0) + 1
        )
        # No memory, camera or status tool from the detached socket may
        # continue waiting on the old turn. A new connection gets its own
        # current signal, preserving the existing identity generation.
        pending_tool = _tool_turn_cancel.pop(conn.device_id, None)
        if pending_tool is not None:
            pending_tool.set()


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
        # Real VAD continues to sustain this current human turn. Do not let
        # the floor expire during a sentence longer than one second.
        if connections.get(device) is conn:
            human_vad_until[device] = time.monotonic() + 1.0
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
        global lease_ids, lease_until, lease_stopping, active_device_id, lease_passive
        async with speaker_lock:
            lease_until = 0
            lease_ids = frozenset()
            lease_stopping = False
            lease_passive = False
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
    # Record authenticated VAD before awaiting a possibly disconnected
    # head, so Mac and other pets can preempt independently of this STOP.
    record_human_voice(conn, "normal")
    try:
        native = _native_adapter()
    except ModuleNotFoundError:
        native = None  # Physical STOP never waits for optional inference.
    urgent = getattr(native, "send_external_urgent_stop", None)
    stop_sent = False
    try:
        if callable(urgent):
            # Use the same device lock as a currently transmitted Mac Opus
            # frame. STOP must follow it, never get overtaken by old audio.
            await urgent(conn)
        else:
            await asyncio.wait_for(
                conn.websocket.send(json.dumps({
                    "type": "tts", "state": "stop",
                    "session_id": conn.session_id, "flush": True,
                })), timeout=0.4,
            )
        stop_sent = True
    finally:
        if stop_sent:
            conn.clearSpeakStatus()
        # Failure or cancellation must not pretend the decoder stopped.
        # Native generation invalidation still happens on real user VAD,
        # even when the first urgent STOP failed.
        voice_frames.pop(device, None)
        voice_last_frame_at.pop(device, None)
        if native is not None:
            try:
                await asyncio.wait_for(native.on_barge(conn), timeout=0.5)
            except (Exception, asyncio.CancelledError):
                pass
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
    # The human VAD event and Mac sender-generation abort must survive a
    # stalled physical STOP, not disappear behind a head WebSocket timeout.
    record_human_voice(conn, "group")
    await asyncio.wait_for(conn.websocket.send(json.dumps({
        "type": "tts", "state": "stop", "session_id": conn.session_id,
        "flush": True,
    })), timeout=0.4)
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


async def transmit(conn, text, frames, *, passive: bool = False):
    from core.handle.sendAudioHandle import send_tts_message

    global active_device_id
    if type(passive) is not bool:
        raise ValueError("Passive speech flag must be a boolean")
    if conn.conn_from_mqtt_gateway:
        raise ValueError("Speech bridge currently requires direct Xiaozhi WebSocket transport")
    # This is the SAME physical decoder used by native MiniCPM. Preserve
    # Mac proactive and social pet speech, but never let it overlap a human
    # voice/tool answer or a peer robot's already claimed speech.
    # The human generation must be captured BEFORE yielding to the async
    # native speaker lease. Otherwise a VAD race can reset client_abort and
    # accidentally restart a superseded proactive remark.
    generation = interrupt_generation.get(conn.device_id, 0)
    native = _native_adapter()
    begin = getattr(native, "begin_external_speech", None)
    leased = False
    if callable(begin):
        leased = await begin(conn, passive=True) if passive else await begin(conn)
        if not leased:
            raise RuntimeError("Live human/native tool speech owns the Xiaozhi speaker")
    if (generation != interrupt_generation.get(conn.device_id, 0)
            or human_speech_active()):
        # The lease succeeded, but a real human started speaking while
        # awaiting it. Release it BEFORE raising; never reset that abort.
        if leased:
            await native.end_external_speech(conn)
        raise RuntimeError("Speech interrupted before the speaker lease started")
    active_device_id = conn.device_id
    voice_frames.pop(conn.device_id, None)
    voice_last_frame_at.pop(conn.device_id, None)
    # The speaker lock and callers serialize transmission, but cancellation
    # does not wait for that lock. Capture generation before clearing stale
    # abort state; once interrupted this exact transmission cannot restart.
    conn.client_abort = False
    conn.client_is_speaking = True
    control = getattr(native, "send_external_tts_control", None)
    async def send_control(state: str, content: str | None = None) -> None:
        async def deliver():
            if content is None:
                await send_tts_message(conn, state)
            else:
                await send_tts_message(conn, state, content)
        if leased and callable(control):
            await control(conn, generation, deliver)
        else:
            await deliver()

    try:
        await send_control("start")
        if passive:
            record_passive = getattr(native, "record_external_passive_start", None)
            if not leased or not callable(record_passive):
                raise RuntimeError(
                    "Native adapter cannot account for passive fleet speech"
                )
            await record_passive(conn)
        # The real microphone may have interrupted during the async START.
        # Never publish even the old caption or subsequent Opus in that case.
        if (conn.client_abort
                or generation != interrupt_generation.get(conn.device_id, 0)
                or not muted(conn.device_id) or human_speech_active()):
            raise RuntimeError("Speech interrupted before the first sentence")
        await send_control("sentence_start", text)
        for packet in frames:
            if (conn.client_abort
                    or generation != interrupt_generation.get(conn.device_id, 0)
                    or not muted(conn.device_id) or human_speech_active()):
                raise RuntimeError("Speech interrupted or session expired")
            # Reuse the firmware's existing 16 kHz mono, 60 ms Opus
            # framing. The native adapter already owns the device send lock:
            # a human STOP must not race past an in-flight Mac Opus packet.
            send_native = getattr(native, "send_external_opus", None)
            if leased and callable(send_native):
                await send_native(conn, packet, generation)
            else:
                await conn.websocket.send(packet)
            conn.last_activity_time = time.time() * 1000
            await asyncio.sleep(0.06)
        await asyncio.sleep(0.24)  # estimated buffer tail; no physical playback acknowledgement
        if (conn.client_abort
                or generation != interrupt_generation.get(conn.device_id, 0)
                or human_speech_active()):
            raise RuntimeError("Speech interrupted during playback tail")
    finally:
        stop_confirmed = False
        try:
            async def send_stop():
                if (conn.client_abort
                        or generation != interrupt_generation.get(conn.device_id, 0)
                        or human_speech_active()):
                    # Bypass upstream normal stop's wait-for-all-audio behavior.
                    if hasattr(conn, "websocket") and conn.websocket is not None:
                        await conn.websocket.send(json.dumps({
                            "type": "tts", "state": "stop",
                            "session_id": getattr(conn, "session_id", None), "flush": True,
                        }))
                    else:
                        await send_tts_message(conn, "stop")
                elif leased and callable(control):
                    # Pinned Xiaozhi's normal stop waits for its own TTS
                    # audio-rate queue, not Mac's separately sent Opus.
                    # The Mac sender has already paced its packets and tail.
                    # Send the SAME upstream control envelope directly while
                    # owning the device lock; no acoustic ACK is fabricated.
                    if hasattr(conn, "websocket") and conn.websocket is not None:
                        await conn.websocket.send(json.dumps({
                            "type": "tts", "state": "stop",
                            "session_id": getattr(conn, "session_id", None),
                        }))
                    else:
                        await send_tts_message(conn, "stop")
                else:
                    await send_tts_message(conn, "stop")
            if leased and callable(control):
                await control(conn, generation, send_stop, terminal=True)
            else:
                await send_stop()
            # A sent transport command is not an acoustic playback ACK,
            # but a failed send must never release the five-pet speaker.
            stop_confirmed = True
        finally:
            try:
                conn.clearSpeakStatus()
            finally:
                if active_device_id == conn.device_id:
                    active_device_id = None
                if leased:
                    if stop_confirmed:
                        await native.end_external_speech(conn)
                    else:
                        await native.end_external_speech(
                            conn, stop_confirmed=False,
                        )


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
        global lease_passive
        body = await request.json()
        ids = body.get("device_ids")
        passive = body.get("passive", False)
        if type(passive) is not bool:
            raise ValueError("passive must be a boolean")
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
            if passive and len(selected) != 1:
                raise ValueError("Passive initiative must own exactly one robot")
            native = _native_adapter()
            if native is not None and any(
                native.active(device) for device in device_map().values()
            ):
                raise RuntimeError("Native realtime model owns the shared fleet speech floor")
            if passive:
                allowed = getattr(native, "passive_speech_allowed", None)
                if not callable(allowed):
                    raise RuntimeError(
                        "Native adapter lacks the shared passive speech budget"
                    )
                if not allowed():
                    raise RuntimeError("Passive fleet speech cooldown is active")
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
            lease_passive = passive
        elif body.get("enabled") is False:
            if lease_ids and lease_ids != selected:
                raise RuntimeError("Session identities differ")
            if lease_ids and passive is not lease_passive:
                raise RuntimeError("Session passive mode differs")
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
        response = {
            "device_ids": sorted(selected),
            "enabled": body["enabled"],
            "expires_in_seconds": 305 if body["enabled"] else 0,
        }
        if passive:
            response["passive"] = True
        return web.json_response(response)

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
                frames = await encode_opus_owned(audio)
                if (lease_stopping or not muted(device) or connections.get(device) is not connection
                        or generation != interrupt_generation.get(device, 0)):
                    raise RuntimeError("Coordinated session stopped, interrupted or robot disconnected")
                if lease_passive:
                    await transmit(connection, text, frames, passive=True)
                else:
                    await transmit(connection, text, frames)
        return web.json_response({
            "device_id": device, "transmitted": True,
            "physical_playback_verified": False,
        })

    async def interrupt(request):
        """Immediate authenticated head DMA flush without awaiting speaker_lock.

        Only the specified registered device is canceled. The generation bump
        fences previously queued, encoding and transmitting requests. A returned
        result acknowledges the request to flush, not audible completion.
        """
        body = await request.json()
        device = body.get("device_id") if isinstance(body, dict) else None
        revoke = body.get("revoke_initiative", False) if isinstance(body, dict) else False
        monitor_lost = body.get("monitor_unavailable", False) if isinstance(body, dict) else False
        if type(revoke) is not bool or type(monitor_lost) is not bool or (revoke and monitor_lost):
            raise ValueError("Exactly one valid operator or monitor interruption reason required")
        if not isinstance(device, str) or device not in device_map().values():
            raise ValueError("Known device_id required")
        connection = connections.get(device)
        if connection is None:
            raise RuntimeError("Robot is offline")
        interrupt_generation[device] = interrupt_generation.get(device, 0) + 1
        connection.client_abort = True
        # A normal VAD barge cancels just this response generation. An
        # operator explicitly revokes future unsolicited initiative. These
        # intents must never share a hidden quiet-mode side effect.
        stopped_native = False
        native = None
        try:
            native = _native_adapter()
            if native is not None:
                action = getattr(
                    native,
                    "suspend_proactive_for_operator" if revoke else
                    "suspend_proactive_for_monitor_loss" if monitor_lost else
                    "on_barge",
                    None,
                )
                if callable(action):
                    stopped_native = await action(connection) is True
        except Exception:
            # An unavailable native module, broken model connection or
            # failed remote cancel is NEVER allowed to suppress the physical
            # XIAO STOP fallback. Sending STOP twice is safer than sending
            # none; its decoder flush is an idempotent safety action.
            stopped_native = False
        if not stopped_native:
            # A Mac Opus packet can still be in flight when the native model
            # session is absent. Use its shared physical device lock before
            # requesting DMA flush, not an unordered direct WebSocket STOP.
            urgent = getattr(native, "send_external_urgent_stop", None)
            if callable(urgent):
                await urgent(connection)
            else:
                await asyncio.wait_for(
                    connection.websocket.send(json.dumps({
                        "type": "tts", "state": "stop",
                        "session_id": connection.session_id, "flush": True,
                    })), timeout=0.4,
                )
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
            "native_omni": (
                native.status(device) if (native := _native_adapter()) is not None
                else {"native_backend_connected": False,
                      "head_audio_playback_acknowledged": False}
            ),
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
                "active_human_robots": active_idle_speech_robots(),
            })
        if after > voice_event_cursor:
            return web.json_response({
                "cursor": voice_event_cursor, "events": [],
                "reset": True, "lost": False,
                "active_human_robots": active_idle_speech_robots(),
            })
        earliest = voice_event_history[0]["seq"] if voice_event_history else voice_event_cursor + 1
        return web.json_response({
            "cursor": voice_event_cursor,
            "events": [item for item in voice_event_history if item["seq"] > after],
            "reset": False, "lost": after < earliest - 1,
            "active_human_robots": active_idle_speech_robots(),
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
