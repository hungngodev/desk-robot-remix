"""Cosmetic and optional initiative policy; never physical evidence or authority."""
from __future__ import annotations

from typing import Literal

PersonalityProfile = Literal["balanced", "calm", "curious", "dramatic"]


def passive_interval(profile: PersonalityProfile, base: float) -> float:
    """Profiles may extend, but never shorten, the fleet speech floor."""
    return base * {"balanced": 1.0, "calm": 1.5, "curious": 1.0, "dramatic": 1.25}[profile]


def profile_waits_beyond_fleet_floor(
    profile: PersonalityProfile, *, elapsed: float, base: float,
) -> bool:
    """Skip a locally ineligible pet only after the common floor has opened."""
    return base <= elapsed < passive_interval(profile, base)


def expression_guidance(profile: PersonalityProfile) -> str:
    style = {
        "balanced": "Follow your configured persona naturally.",
        "calm": "Prefer measured, understated expression and patient silence.",
        "curious": "Prefer gentle curiosity and relevant questions when useful.",
        "dramatic": "Use playful theatrical expression without exaggerating facts.",
    }[profile]
    return (
        f"{style} Personality and OLED mood are expressive only. "
        "Never alter measured battery percentages, ToF ranges, safety faults, "
        "stop acknowledgments, or tool results to match a mood. "
        "Missing or uncertain evidence stays unknown; safety always takes priority."
    )
