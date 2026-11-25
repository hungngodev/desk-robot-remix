"""Bounded, volatile habituation for optional initiative and context only.

The existing camera policy is a sliding inactivity window: a repeat renews
its last-seen time, and habituation expires at exactly window_s of silence.
This is a candidate software policy, not a learned sensory or safety model.
"""
from __future__ import annotations

import math
from typing import Generic, Hashable, TypeVar

K = TypeVar("K", bound=Hashable)


def _finite_time(value: float) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


class HabituationWindow(Generic[K]):
    """One owner, one monotonic time domain, no I/O or motor authority."""

    def __init__(self, window_s: float = 900.0, capacity: int = 64) -> None:
        if not _finite_time(window_s) or window_s <= 0:
            raise ValueError("habituation window must be finite and positive")
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("habituation capacity must be a positive integer")
        self._window_s = float(window_s)
        self._capacity = capacity
        self._entries: dict[K, tuple[float, int]] = {}
        self._epoch: tuple[int, int | None] | None = None

    def reset(self) -> None:
        self._entries.clear()
        self._epoch = None

    def begin_epoch(self, epoch: tuple[int, int | None]) -> None:
        if self._epoch != epoch:
            self.reset()
            self._epoch = epoch

    def record(self, key: K, now: float) -> bool:
        """Record an admitted observation; reject invalid or regressing time."""
        if not _finite_time(now):
            return False
        previous = self._entries.get(key)
        if previous is not None and now < previous[0]:
            return False
        count = 1
        if previous is not None and now - previous[0] < self._window_s:
            count = previous[1] + 1
        self._entries.pop(key, None)
        if len(self._entries) >= self._capacity:
            del self._entries[next(iter(self._entries))]
        self._entries[key] = (now, count)
        return True

    def refresh_if_repeated(self, key: K, now: float) -> bool:
        """Suppress a repeat, without admitting a new stimulus prematurely."""
        if not _finite_time(now):
            return True  # Invalid time cannot justify optional initiative.
        previous = self._entries.get(key)
        if previous is None:
            return False
        if now < previous[0]:
            return True  # Do not rewind or refresh from a regressing clock.
        if now - previous[0] >= self._window_s:
            del self._entries[key]
            return False
        self.record(key, now)
        return True

    def recent_repeats(self, now: float) -> dict[K, int]:
        """Current burst counts, not lifetime frequencies or verified actions."""
        if not _finite_time(now):
            return {}
        return {
            key: count for key, (seen, count) in self._entries.items()
            if count >= 2 and 0 <= now - seen < self._window_s
        }
