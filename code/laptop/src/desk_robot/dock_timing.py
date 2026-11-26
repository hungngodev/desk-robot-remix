"""Shared inclusive freshness policy for dock observations, not motor permits."""

DOCK_OBSERVATION_MAX_AGE_MS = 200
DOCK_OBSERVATION_MAX_AGE_S = DOCK_OBSERVATION_MAX_AGE_MS / 1000


def dock_age_is_fresh(age: float, maximum_age: float) -> bool:
    """Compare a prevalidated age and limit expressed in the same units."""
    return 0 <= age <= maximum_age
