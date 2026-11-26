"""MAX17048 evidence expires at the acquisition boundary, including transit."""

import pytest
from desk_robot.sensor_event_contract import FUEL_SAMPLE_MAX_AGE_MS, fuel_sample_is_fresh


@pytest.mark.parametrize(
    ("age", "elapsed", "expected"),
    [
        (0, 0, True),
        (499, 0, True),
        (499, 0.5, True),
        (499, 1, False),
        (250, 250, False),
        (0, 499.9, True),
        (0, 500, False),
        (500, 0, False),
        (-1, 0, False),
        (0, -1, False),
        (True, 0, False),
        (0, False, False),
        (1.0, 0, False),
        (None, 0, False),
        (0, None, False),
        ("1", 0, False),
        (0, "1", False),
        (0, float("nan"), False),
        (0, float("inf"), False),
        (0, -float("inf"), False),
        (10**400, 0, False),
        (0, 10**400, False),
    ],
)
def test_fuel_freshness_boundaries(age, elapsed, expected):
    assert fuel_sample_is_fresh(age, elapsed) is expected


def test_default_is_wire_age_only():
    assert FUEL_SAMPLE_MAX_AGE_MS == 500
    assert fuel_sample_is_fresh(499)
    assert not fuel_sample_is_fresh(500)
