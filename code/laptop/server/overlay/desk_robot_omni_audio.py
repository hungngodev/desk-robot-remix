"""PCM framing and transport pacing for the existing Xiaozhi Opus path."""
from __future__ import annotations

from collections.abc import Callable

HEAD_SAMPLE_RATE = 16000
MODEL_SAMPLE_RATE = 24000
FRAME_SECONDS = 0.060
FRAME_SAMPLES = 960
FRAME_BYTES = FRAME_SAMPLES * 2
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
        pcm16k, self._resample_state = self._ratecv(
            pcm24k, 2, 1, MODEL_SAMPLE_RATE, HEAD_SAMPLE_RATE, self._resample_state
        )
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
        return bytes(self._pending).ljust(FRAME_BYTES, b"\0") if self._pending else b""


def remaining_packet_delay(started: float, now: float) -> float:
    """Charge socket send time against one frame, without catch-up debt."""
    return max(0.0, FRAME_SECONDS - (now - started))
