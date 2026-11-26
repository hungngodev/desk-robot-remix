"""Shared inclusive freshness policy for dock observations, not motor permits."""

DOCK_OBSERVATION_MAX_AGE_MS = 200
DOCK_OBSERVATION_MAX_AGE_S = DOCK_OBSERVATION_MAX_AGE_MS / 1000


def dock_age_is_fresh(age: float, maximum_age: float) -> bool:
    """Compare a prevalidated age and limit expressed in the same units."""
    return 0 <= age <= maximum_age


def dock_time_remaining(age_seconds: float) -> float:
    """Return the strictly positive budget for additional receipt-bound work."""
    if not 0 <= age_seconds < DOCK_OBSERVATION_MAX_AGE_S:
        return 0.0
    return DOCK_OBSERVATION_MAX_AGE_S - age_seconds
