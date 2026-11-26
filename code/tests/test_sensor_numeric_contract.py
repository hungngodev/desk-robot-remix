"""Shared sensor numeric validation must not coerce source values."""
import math
from decimal import Decimal

import pytest
from desk_robot.habituation import HabituationWindow
from desk_robot.sensor_event_contract import is_finite_number, is_int_in_range, is_uint


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


@pytest.mark.parametrize("value", [-32768, 0, 32767])
def test_signed_wire_integer_inclusive_bounds(value):
    assert is_int_in_range(value, -32768, 32767)


@pytest.mark.parametrize("value", [0, 1, 0xffffffff])
def test_unsigned_wire_integer_inclusive_bounds(value):
    assert is_uint(value, 0xffffffff)


@pytest.mark.parametrize("value", [
    True, False, 1.0, None, "1", IntSubclass(1), -32769, 0x100000000,
    math.nan, math.inf, 10**1000,
])
def test_wire_integer_rejects_type_and_range_mutations(value):
    assert not is_int_in_range(value, -32768, 32767)
    assert not is_uint(value, 0xffffffff)


def test_negative_wire_integer_is_never_unsigned():
    assert is_int_in_range(-1, -32768, 32767)
    assert not is_uint(-1, 0xffffffff)
