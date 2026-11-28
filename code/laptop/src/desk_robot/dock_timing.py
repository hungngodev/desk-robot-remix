"""Shared inclusive freshness policy for dock observations, not motor permits."""

import math

DOCK_OBSERVATION_MAX_AGE_MS = 200
DOCK_OBSERVATION_MAX_AGE_S = DOCK_OBSERVATION_MAX_AGE_MS / 1000


def dock_age_is_fresh(age: float, maximum_age: float) -> bool:
    """Accept only finite native numbers in the same units; invalid ages fail closed."""
    if type(age) not in (int, float) or type(maximum_age) not in (int, float):
        return False
    try:
        return math.isfinite(maximum_age) and 0 <= age <= maximum_age
    except OverflowError:
        return False


def dock_time_remaining(age_seconds: float) -> float:
    """Return the strictly positive budget for additional receipt-bound work."""
    if not dock_age_is_fresh(age_seconds, DOCK_OBSERVATION_MAX_AGE_S):
        return 0.0
    return DOCK_OBSERVATION_MAX_AGE_S - age_seconds
