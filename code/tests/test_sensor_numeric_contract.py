"""Shared sensor numeric validation must not coerce source values."""
import math
from decimal import Decimal

import pytest
from desk_robot.habituation import HabituationWindow
from desk_robot.sensor_event_contract import is_finite_number


class IntSubclass(int):
    pass


class FloatSubclass(float):
    pass


@pytest.mark.parametrize("value", [0, -1, 1.5, -0.0, 10**100])
def test_native_finite_numbers(value):
    assert is_finite_number(value)


@pytest.mark.parametrize("value", [
    True, False, None, "1", Decimal("1"), IntSubclass(1), FloatSubclass(1),
    math.nan, math.inf, -math.inf, 10**1000, -(10**1000),
])
def test_invalid_sensor_numbers_do_not_coerce_or_escape(value):
    assert not is_finite_number(value)
    window = HabituationWindow[str]()
    assert not window.record("touch", value)
    assert window.refresh_if_repeated("touch", value)
    assert window.recent_repeats(value) == {}
    with pytest.raises(ValueError):
        HabituationWindow(window_s=value)
