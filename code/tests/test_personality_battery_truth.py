"""Keep the shared personality prompt independent of power evidence."""
from __future__ import annotations

from typing import get_args

import pytest
from desk_robot.personality_policy import PersonalityProfile, expression_guidance


@pytest.mark.parametrize("profile", get_args(PersonalityProfile))
def test_personality_cannot_reinterpret_gauge_readings(profile):
    guidance = expression_guidance(profile)
    assert "Personality and OLED mood are expressive only" in guidance
    assert "Never alter reported battery percentages or cell voltage (millivolts)" in guidance
    assert "Never infer battery state from tiredness, energy or personality" in guidance
    assert "preserve the gauge estimate and qualification" in guidance
    assert "Missing or uncertain evidence stays unknown" in guidance


def test_power_truth_instruction_is_identical_across_personalities():
    suffixes = {
        expression_guidance(profile).partition("Personality and OLED mood")[2]
        for profile in get_args(PersonalityProfile)
    }
    assert len(suffixes) == 1
    assert next(iter(suffixes))
