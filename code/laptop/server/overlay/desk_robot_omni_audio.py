"""PCM framing and transport pacing for the existing Xiaozhi Opus path."""
from __future__ import annotations

import math
from collections.abc import Callable

HEAD_SAMPLE_RATE = 16000
MODEL_SAMPLE_RATE = 24000
FRAME_SECONDS = 0.060
FRAME_SAMPLES = 960
FRAME_BYTES = FRAME_SAMPLES * 2
# Match the wire protocol's two-second maximum PCM16 model delta.
MAX_MODEL_CHUNK_BYTES = MODEL_SAMPLE_RATE * 2 * 2
MAX_RESAMPLED_CHUNK_BYTES = HEAD_SAMPLE_RATE * 2 * 2
RatecvState = tuple[int, tuple[tuple[int, int], ...]] | None
Ratecv = Callable[[bytes, int, int, int, int, RatecvState], tuple[bytes, RatecvState]]


class PcmOpusFramer:
    """Own one response's PCM tail and streaming resampler state."""

    def __init__(self, ratecv: Ratecv) -> None:
        self._ratecv = ratecv
        self._pending = bytearray()
        self._resample_state: RatecvState = None

    def reset(self) -> None:
        self._pending.clear()
        self._resample_state = None

    def append(self, pcm24k: bytes) -> None:
        if type(pcm24k) is not bytes:
            raise ValueError("Model PCM chunk must be bytes")
        if not pcm24k:
            return
        if len(pcm24k) % 2 or len(pcm24k) > MAX_MODEL_CHUNK_BYTES:
            raise ValueError("Malformed or oversized model PCM chunk")
        if self.has_frame():
            raise ValueError("Drain complete Opus frames before appending PCM")
        pcm16k, next_state = self._ratecv(
            pcm24k, 2, 1, MODEL_SAMPLE_RATE, HEAD_SAMPLE_RATE, self._resample_state
        )
        if (type(pcm16k) is not bytes or len(pcm16k) % 2
                or len(pcm16k) > MAX_RESAMPLED_CHUNK_BYTES):
            raise ValueError("Malformed or oversized resampled PCM chunk")
        self._resample_state = next_state
        self._pending.extend(pcm16k)

    def has_frame(self) -> bool:
        return len(self._pending) >= FRAME_BYTES

    def pop_frame(self) -> bytes:
        if not self.has_frame():
            raise ValueError("Incomplete Opus frame")
        frame = bytes(self._pending[:FRAME_BYTES])
        del self._pending[:FRAME_BYTES]
        return frame

    def padded_tail(self) -> bytes:
        """Return the terminal tail without discarding state before STOP."""
        if self.has_frame():
            raise ValueError("Drain complete Opus frames before padding tail")
        return bytes(self._pending).ljust(FRAME_BYTES, b"\0") if self._pending else b""


def remaining_packet_delay(started: float, now: float) -> float:
    """Charge socket send time against one frame, without catch-up debt."""
    if type(started) not in (int, float) or type(now) not in (int, float):
        raise ValueError("Invalid packet clock")
    try:
        elapsed = now - started
        if not (math.isfinite(started) and math.isfinite(now)
                and math.isfinite(elapsed) and elapsed >= 0):
            raise ValueError("Invalid packet clock")
    except OverflowError:
        raise ValueError("Invalid packet clock") from None
    return max(0.0, FRAME_SECONDS - elapsed)
