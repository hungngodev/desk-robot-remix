"""Host-only checks for optional personality policy, not physical qualification."""

import math

import pytest
from desk_robot.personality_policy import (
    expression_guidance,
    fleet_speech_elapsed,
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
        assert (
            "Never alter reported battery percentages or cell voltage (millivolts), "
            "ToF ranges, safety faults"
        ) in prompt
        assert "stop acknowledgments, or tool results" in prompt
        assert "safety always takes priority" in prompt


@pytest.mark.parametrize(
    ("profile", "elapsed", "waits"),
    [("calm", 119, False), ("calm", 120, True), ("calm", 180, False),
     ("dramatic", 149, True), ("dramatic", 150, False), ("curious", 120, False)],
)
def test_extra_profile_wait_does_not_consume_common_floor(profile, elapsed, waits):
    assert profile_waits_beyond_fleet_floor(profile, elapsed=elapsed, base=120) is waits


@pytest.mark.parametrize("profile, multiplier", [
    ("balanced", 1.0), ("curious", 1.0), ("dramatic", 1.25), ("calm", 1.5),
])
def test_passive_floor_exact_limits(profile, multiplier):
    assert passive_interval(profile, 3600) == 3600 * multiplier
    assert passive_interval(profile, math.nextafter(0.0, math.inf)) > 0
    assert passive_interval(profile, 0) == 0
    assert not profile_waits_beyond_fleet_floor(profile, elapsed=0, base=0)


@pytest.mark.parametrize("base", [
    True, False, "120", None, math.nan, math.inf, -math.inf,
    math.nextafter(0.0, -math.inf), math.nextafter(3600.0, math.inf), 10**400,
])
def test_passive_floor_rejects_invalid_base(base):
    with pytest.raises(ValueError, match="Invalid personality base cooldown"):
        passive_interval("calm", base)


@pytest.mark.parametrize("profile, upper", [("calm", 180.0), ("dramatic", 150.0)])
def test_extra_wait_exact_float_boundaries(profile, upper):
    for elapsed, expected in [
        (math.nextafter(120.0, -math.inf), False), (120.0, True),
        (math.nextafter(120.0, math.inf), True),
        (math.nextafter(upper, -math.inf), True), (upper, False),
        (math.nextafter(upper, math.inf), False),
    ]:
        assert profile_waits_beyond_fleet_floor(profile, elapsed=elapsed, base=120) is expected


@pytest.mark.parametrize("elapsed", [
    None, math.nan, -math.inf, math.nextafter(0.0, -math.inf), -1.0,
    True, False, "120", 10**400,
])
def test_invalid_elapsed_defers_optional_activity(elapsed):
    assert profile_waits_beyond_fleet_floor("balanced", elapsed=elapsed, base=0)


@pytest.mark.parametrize("now,last", [
    (math.nan, 0), (math.inf, 0), (-math.inf, 0), (math.inf, -math.inf),
    (0, math.nan), (0, math.inf), (True, -math.inf), (1, False),
    (1, 2), (math.nextafter(1.0, -math.inf), 1), (10**400, 0),
    (1e308, -1e308),
])
def test_invalid_or_regressing_fleet_clock_defers(now, last):
    elapsed = fleet_speech_elapsed(now, last)
    assert elapsed is None
    assert profile_waits_beyond_fleet_floor("calm", elapsed=elapsed, base=120)


def test_valid_fleet_clock_recovers_without_consuming_first_speech():
    assert fleet_speech_elapsed(0, -math.inf) == math.inf
    assert not profile_waits_beyond_fleet_floor("calm", elapsed=math.inf, base=120)
    assert fleet_speech_elapsed(100, 100) == 0
    assert fleet_speech_elapsed(99, 100) is None
    assert fleet_speech_elapsed(220, 100) == 120
    assert profile_waits_beyond_fleet_floor("calm", elapsed=120, base=120)
    assert fleet_speech_elapsed(280, 100) == 180
    assert not profile_waits_beyond_fleet_floor("calm", elapsed=180, base=120)
