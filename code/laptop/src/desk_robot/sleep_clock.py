"""Sleep-aware monotonic timing helpers for Mac hardware deadlines.

On macOS, ``time.monotonic()`` backs onto ``mach_absolute_time()``, which stops
advancing while the host sleeps. ``time.CLOCK_MONOTONIC`` advances across
Mac sleep (``mach_continuous_time``) and Linux ``time.CLOCK_BOOTTIME`` similarly
accounts for suspend intervals. Comparing both clocks prevents stalled deadlines
or stale camera receipts from remaining valid after a laptop wake.
"""
from __future__ import annotations

import sys
import time


def continuous_monotonic() -> float:
    """Return a monotonic clock in seconds that includes host sleep when available."""
    if sys.platform == "darwin" and hasattr(time, "CLOCK_MONOTONIC"):
        return time.clock_gettime(time.CLOCK_MONOTONIC)
    if hasattr(time, "CLOCK_BOOTTIME"):
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    return time.monotonic()


def elapsed_with_sleep(
    start_monotonic: float,
    start_continuous: float | None = None,
    *,
    now_monotonic: float | None = None,
    now_continuous: float | None = None,
) -> float:
    """Return maximum elapsed seconds across monotonic and sleep-aware clocks."""
    mono_now = time.monotonic() if now_monotonic is None else now_monotonic
    elapsed = mono_now - start_monotonic
    if start_continuous is not None:
        cont_now = continuous_monotonic() if now_continuous is None else now_continuous
        cont_elapsed = cont_now - start_continuous
        if cont_elapsed > elapsed:
            return cont_elapsed
    return elapsed
