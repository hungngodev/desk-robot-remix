"""Boundary checks for the optional per-pet battery speech budget."""
import math

import pytest
from desk_robot.initiative_policy import battery_warning_pending


@pytest.mark.parametrize(("now", "last", "expected"), [
    (100.0, -math.inf, False),
    (100.0, 100.0, True),
    (219.999, 100.0, True),
    (220.0, 100.0, False),
    (99.0, 100.0, False),
])
def test_battery_warning_minimum_interval(now, last, expected):
    assert battery_warning_pending(now=now, last=last) is expected
