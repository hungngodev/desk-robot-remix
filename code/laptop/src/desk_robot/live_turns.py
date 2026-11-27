"""Offline state for a future real-time voice/video transport, one event-loop owner.

Google's Live example clears playback on ``server_content.interrupted``:
https://github.com/google-gemini/cookbook/blob/main/quickstarts/Get_started_LiveAPI.py
Its robotics guidance uses latest-frame observation prompts only between turns:
https://ai.google.dev/gemini-api/docs/robotics-streaming

This is original transport-independent code, not a Google SDK client or an AEC
implementation. An adapter must retain the epoch belonging to each producer or
request; stamping delayed old callbacks with the *current* epoch defeats the guard.
It must also send every FlushPlayback to the device and cancel obsolete network
work, including ``ObservationRequest.flush`` before dispatching that request.
Clearing this local queue cannot stop PCM already buffered by an ESP32/DMA driver.
Capture callbacks retain a separate connection_epoch, which survives normal turns
but changes across reconnects. Lifecycle methods are for the authoritative session
owner; an old socket must not call them after its replacement has connected.

All methods are synchronous and must be called on the same event loop. Off-thread
capture/codec callbacks must be marshalled to that owner before calling this API.
Times are explicit finite monotonic seconds; nothing here starts timers or I/O.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class PlaybackChunk:
    epoch: int
    pcm: bytes


@dataclass(frozen=True)
class FlushPlayback:
    """Directive for the adapter: flush device playback and cancel older work."""

    epoch: int
    reason: str
    discarded_bytes: int


@dataclass(frozen=True)
class VideoFrame:
    jpeg: bytes
    captured_at: float
    connection_epoch: int


@dataclass(frozen=True)
class ObservationRequest:
    """Deliver flush before dispatching this request or any of its audio.

    Recheck ``is_current(epoch)`` after awaiting external delivery; another event
    may have interrupted the request while the adapter was suspended.
    """

    flush: FlushPlayback
    jpeg: bytes
    captured_at: float
    prompt: str

    @property
    def epoch(self) -> int:
        return self.flush.epoch


def _seconds(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Use finite monotonic seconds")
    # A huge Python int can OverflowError during float/isfinite conversion.
    # Untrusted capture timestamps must fail as validation, not crash the
    # owning event loop while a newer frame is waiting.
    try:
        seconds = float(value)
    except OverflowError as exc:
        raise ValueError("Use finite monotonic seconds") from exc
    if not math.isfinite(seconds):
        raise ValueError("Use finite monotonic seconds")
    return seconds


class LiveTurns:
    """Bounded media and opt-in observations; no motion or network authority.

    Default audio capacity is 200ms of mono 16-bit PCM at 24kHz. For another
    format, set the byte limit accordingly; this core does not resample audio.
    Keep ``model`` busy through generation AND actual device playback completion.
    Stopping a tool or capture is external work; interruption never clears those
    busy flags on an adapter's behalf. Reconcile retained busy flags explicitly
    with the current epoch after reconnect, once old work has actually stopped.
    Quiet mode cancels spontaneous replies; user-requested turns remain available.
    """

    def __init__(
        self,
        *,
        max_audio_bytes: int = 9600,
        max_jpeg_bytes: int = 512_000,
        frame_interval: float = 1.0,
        frame_max_age: float = 2.0,
        heartbeat_interval: float = 30.0,
    ) -> None:
        for limit in (max_audio_bytes, max_jpeg_bytes):
            if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
                raise ValueError("Media byte limits must be positive integers")
        for interval in (frame_interval, frame_max_age, heartbeat_interval):
            if _seconds(interval) <= 0:
                raise ValueError("Intervals must be positive")
        self.max_audio_bytes = max_audio_bytes
        self.max_jpeg_bytes = max_jpeg_bytes
        self.frame_interval = float(frame_interval)
        self.frame_max_age = float(frame_max_age)
        self.heartbeat_interval = float(heartbeat_interval)
        self._epoch = 0
        self._connection_epoch = 0
        self._connected = False
        self._quiet = False
        self._busy = {"user": False, "model": False, "tool": False}
        self._audio: deque[PlaybackChunk] = deque()
        self._audio_bytes = 0
        self._frame: VideoFrame | None = None
        self._frame_serial = 0
        self._sent_frame_serial = 0
        self._last_frame_sent = -math.inf
        self._proactive = False
        self._last_observation: float | None = None
        self._pending_observation: int | None = None
        self._spontaneous_epoch: int | None = None

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def queued_audio_bytes(self) -> int:
        return self._audio_bytes

    @property
    def connection_epoch(self) -> int:
        """Capture once per camera producer; do not retag a delayed old callback."""
        return self._connection_epoch

    def is_connection_current(self, connection_epoch: int) -> bool:
        """Recheck popped frames before sending to an external video transport."""
        return (self._connected and type(connection_epoch) is int
                and connection_epoch == self._connection_epoch)

    def is_current(self, epoch: int) -> bool:
        """Recheck popped chunks before sending; a device flush is still required."""
        return self._connected and type(epoch) is int and epoch == self._epoch

    def _invalidate(self, reason: str) -> FlushPlayback:
        discarded = self._audio_bytes
        self._audio.clear()
        self._audio_bytes = 0
        self._epoch += 1
        self._pending_observation = None
        self._spontaneous_epoch = None
        return FlushPlayback(self._epoch, reason, discarded)

    def set_connected(self, connected: bool) -> FlushPlayback | None:
        if type(connected) is not bool:
            raise ValueError("Connection state must be a boolean")
        if connected == self._connected:
            return None
        self._connected = connected
        self._connection_epoch += 1
        self._frame = None
        self._last_frame_sent = -math.inf
        self._proactive = False  # Reconnection never silently restarts observation prompts.
        self._last_observation = None
        return self._invalidate("connected" if connected else "disconnected")

    def begin_turn(self) -> FlushPlayback:
        """Start a new manually requested model turn and invalidate its predecessor."""
        if not self._connected:
            raise RuntimeError("A turn requires a connected session")
        return self._invalidate("new_turn")

    def interrupt(self) -> FlushPlayback:
        """Handle the Live API interrupted signal, retaining external busy state."""
        return self._invalidate("interrupted")

    def queue_audio(self, epoch: int, pcm: bytes | bytearray | memoryview) -> bool:
        if not self.is_current(epoch):
            return False
        if not isinstance(pcm, (bytes, bytearray, memoryview)):
            raise TypeError("PCM must be a bytes-like buffer")
        size = memoryview(pcm).nbytes
        if size % 2:
            raise ValueError("PCM must contain complete 16-bit samples")
        if not size:
            return False
        if self._audio_bytes + size > self.max_audio_bytes:
            raise BufferError("Playback capacity exceeded; drain or explicitly cancel the turn")
        self._audio.append(PlaybackChunk(epoch, bytes(pcm)))
        self._audio_bytes += size
        return True

    def pop_audio(self) -> PlaybackChunk | None:
        if not self._audio:
            return None
        chunk = self._audio.popleft()
        self._audio_bytes -= len(chunk.pcm)
        return chunk

    def offer_frame(
        self, jpeg: bytes, *, captured_at: float, now: float, connection_epoch: int
    ) -> bool:
        """Keep the latest usable capture; timestamps share the owner's clock."""
        # Retired producers cannot surface payload errors in the new session.
        if not self.is_connection_current(connection_epoch):
            return False
        captured_at = _seconds(captured_at)
        now = _seconds(now)
        if not 0 <= now - captured_at <= self.frame_max_age:
            return False
        if not isinstance(jpeg, bytes) or not jpeg:
            raise ValueError("Supply nonempty JPEG bytes from a validated capture source")
        if len(jpeg) > self.max_jpeg_bytes:
            raise BufferError("JPEG slot capacity exceeded")
        if self._frame is not None and captured_at < self._frame.captured_at:
            return False
        self._frame = VideoFrame(jpeg, captured_at, connection_epoch)
        self._frame_serial += 1
        return True

    def _fresh_frame(self, now: float) -> VideoFrame | None:
        if self._frame is None or not 0 <= now - self._frame.captured_at <= self.frame_max_age:
            return None
        return self._frame

    def take_video_frame(self, *, now: float) -> VideoFrame | None:
        now = _seconds(now)
        frame = self._fresh_frame(now)
        if (
            not self._connected
            or frame is None
            or self._frame_serial == self._sent_frame_serial
            or now - self._last_frame_sent < self.frame_interval
        ):
            return None
        self._sent_frame_serial = self._frame_serial
        self._last_frame_sent = now
        return frame

    def set_busy(
        self,
        epoch: int,
        *,
        user: bool | None = None,
        model: bool | None = None,
        tool: bool | None = None,
    ) -> bool:
        """Reject old turn completions instead of marking a newer turn idle."""
        if not self.is_current(epoch):
            return False
        if any(value is not None and type(value) is not bool
               for value in (user, model, tool)):
            raise ValueError("Busy ownership flags must be booleans")
        for role, value in (("user", user), ("model", model), ("tool", tool)):
            if value is not None:
                self._busy[role] = value
        return True

    def set_quiet(self, quiet: bool) -> FlushPlayback | None:
        if type(quiet) is not bool:
            raise ValueError("Quiet mode must be a boolean")
        self._quiet = quiet
        if quiet and self._spontaneous_epoch is not None:
            return self._invalidate("quiet")
        return None

    def enable_proactivity(self, *, now: float) -> None:
        now = _seconds(now)
        if not self._connected:
            raise RuntimeError("Proactivity requires a connected session")
        self._proactive = True
        self._last_observation = now

    def disable_proactivity(self) -> FlushPlayback | None:
        self._proactive = False
        if self._spontaneous_epoch is not None:
            return self._invalidate("proactivity_disabled")
        return None

    def poll_observation(self, *, now: float) -> ObservationRequest | None:
        now = _seconds(now)
        frame = self._fresh_frame(now)
        if (
            not self._connected
            or not self._proactive
            or self._quiet
            or any(self._busy.values())
            or self._audio_bytes
            or self._pending_observation is not None
            or self._last_observation is None
            or now - self._last_observation < self.heartbeat_interval
            or frame is None
        ):
            return None
        flush = self._invalidate("observation")  # Distinct token rejects old completions.
        self._pending_observation = self._epoch
        self._spontaneous_epoch = self._epoch
        self._last_observation = now
        return ObservationRequest(
            flush,
            frame.jpeg,
            frame.captured_at,
            "Observe the current scene briefly. Stay silent unless a useful change warrants "
            "a short comment. This observation grants no movement permission.",
        )

    def finish_observation(self, epoch: int) -> bool:
        """Release the generation slot, retaining its quiet-cancellable audio origin.

        The adapter must keep model busy until playback is complete. This method
        alone does not mark generation or device playback idle.
        """
        # is_current already rejects non-integer epochs and disconnected sessions.
        if not self.is_current(epoch) or epoch != self._pending_observation:
            return False
        self._pending_observation = None
        return True
