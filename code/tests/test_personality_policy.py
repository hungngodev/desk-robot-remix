"""Host-only checks for optional personality policy, not physical qualification."""

import pytest
from desk_robot.personality_policy import (
    expression_guidance,
    passive_interval,
    profile_waits_beyond_fleet_floor,
)


@pytest.mark.parametrize(
    ("profile", "expected"),
    [("balanced", 120), ("curious", 120), ("dramatic", 150), ("calm", 180)],
)
def test_personality_passive_floor(profile, expected):
    assert passive_interval(profile, 120) == expected
    assert passive_interval(profile, 0) == 0
    assert passive_interval(profile, 30) >= 30


def test_personality_expression_keeps_physical_truth_contract():
    profiles = ("calm", "curious", "dramatic")
    prompts = [expression_guidance(profile) for profile in profiles]
    assert len(set(prompts)) == len(profiles)
    for prompt in prompts:
        assert "Never alter reported battery percentages or cell voltage (millivolts), ToF ranges, safety faults" in prompt
        assert "stop acknowledgments, or tool results" in prompt
        assert "safety always takes priority" in prompt


@pytest.mark.parametrize(
    ("profile", "elapsed", "waits"),
    [("calm", 119, False), ("calm", 120, True), ("calm", 180, False),
     ("dramatic", 149, True), ("dramatic", 150, False), ("curious", 120, False)],
)
def test_extra_profile_wait_does_not_consume_common_floor(profile, elapsed, waits):
    assert profile_waits_beyond_fleet_floor(profile, elapsed=elapsed, base=120) is waits
