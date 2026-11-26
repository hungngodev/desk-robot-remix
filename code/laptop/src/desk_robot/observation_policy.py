"""Pure observation receipt calculations, without a database or clock owner."""
from __future__ import annotations

import math


def receipt_age_is_current(*, received_at: float, now: float, max_age: float) -> bool:
    """Reject impossible or expired Mac receipt times before admission."""
    if type(received_at) not in (int, float):
        return False
    try:
        return math.isfinite(received_at) and 0 <= now - received_at <= max_age
    except OverflowError:
        return False


# Preserve the camera-specific call site while sharing the age rule with initiative.
camera_receipt_is_current = receipt_age_is_current


def prepare_camera_receipt(
    *, robot_id: str, event_id: str, wall_now: float, monotonic_now: float,
    received_at: float, max_age: float, source_identity: tuple[int, int, int] | None,
) -> tuple[str, float] | None:
    """Calculate replay identity and original wall time before any SQLite write."""
    if not receipt_age_is_current(
        received_at=received_at, now=monotonic_now, max_age=max_age,
    ):
        return None
    if source_identity is not None:
        identity = source_identity
        if (type(identity) is not tuple or len(identity) != 3
                or any(type(value) is not int for value in identity)
                or not 0 <= identity[0] <= 0xffffffff
                or not 1 <= identity[1] <= 0xffffffff
                or not 1 <= identity[2] <= 0xffffffffffffffff):
            raise ValueError("Invalid device camera completion identity")
        event_id = (
            f"camera_{robot_id}_{identity[0]:08x}_"
            f"{identity[1]:08x}_{identity[2]:x}"
        )
    return event_id, wall_now - (monotonic_now - received_at)
