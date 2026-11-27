"""Cosmetic and optional initiative policy; never physical evidence or authority."""
from __future__ import annotations

import math
from typing import Literal, get_args

from .sensor_event_contract import is_finite_number

PersonalityProfile = Literal["balanced", "calm", "curious", "dramatic"]


def _validate_profile(profile: object) -> None:
    if type(profile) is not str or profile not in get_args(PersonalityProfile):
        raise ValueError("Invalid personality profile")


def passive_interval(profile: PersonalityProfile, base: float) -> float:
    """Profiles may extend, but never shorten, the fleet speech floor."""
    _validate_profile(profile)
    if not is_finite_number(base) or not 0 <= base <= 3600:
        raise ValueError("Invalid personality base cooldown")
    return base * {"balanced": 1.0, "calm": 1.5, "curious": 1.0, "dramatic": 1.25}[profile]


def fleet_speech_elapsed(now: float, last: float) -> float | None:
    """Return elapsed seconds, +inf for no prior speech, or None for invalid time."""
    if not is_finite_number(now):
        return None
    if type(last) is float and last == -math.inf:
        return math.inf
    if not is_finite_number(last):
        return None
    elapsed = now - last
    if not is_finite_number(elapsed) or elapsed < 0:
        return None
    return elapsed


def profile_waits_beyond_fleet_floor(
    profile: PersonalityProfile, *, elapsed: float | None, base: float,
) -> bool:
    """Defer invalid clocks; otherwise skip only after the common floor opens."""
    interval = passive_interval(profile, base)
    if type(elapsed) is float and elapsed == math.inf:  # No-prior-speech sentinel.
        return False
    if not is_finite_number(elapsed) or elapsed < 0:
        return True
    return base <= elapsed < interval


def expression_guidance(profile: PersonalityProfile) -> str:
    _validate_profile(profile)
    style = {
        "balanced": "Follow your configured persona naturally.",
        "calm": "Prefer measured, understated expression and patient silence.",
        "curious": "Prefer gentle curiosity and relevant questions when useful.",
        "dramatic": "Use playful theatrical expression without exaggerating facts.",
    }[profile]
    return (
        f"{style} Personality and OLED mood are expressive only. "
        "Never alter reported battery percentages or cell voltage (millivolts), "
        "ToF ranges, safety faults, stop acknowledgments, or tool results "
        "to match a mood. Never infer battery state from tiredness, energy "
        "or personality; preserve the gauge estimate and qualification. "
        "Missing or uncertain evidence stays unknown; safety always takes priority."
    )
