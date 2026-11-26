"""Executable boundary tests for shared read-only telemetry validators."""

import sys
from decimal import Decimal

import pytest
from desk_robot.sensor_event_contract import (
    has_upright_floor_loss,
    is_finite_number,
    is_int_in_range,
    is_uint,
)


class IntSubclass(int):
    pass


class FloatSubclass(float):
    pass


@pytest.mark.parametrize(
    "value",
    [True, False, None, "1", Decimal("1"), IntSubclass(1), FloatSubclass(1),
     float("nan"), float("inf"), -float("inf"), 10**400, -(10**400)],
)
def test_finite_number_rejects_invalid_wire_values(value):
    assert is_finite_number(value) is False


@pytest.mark.parametrize("value", [0, -1, 1, -0.0, 0.25, -0.25, sys.float_info.max])
def test_finite_number_accepts_native_finite_values(value):
    assert is_finite_number(value) is True


@pytest.mark.parametrize(
    "value",
    [True, False, None, "1", 0.0, 1.0, Decimal("1"), IntSubclass(1),
     float("nan"), float("inf"), -float("inf"), 10**400, -(10**400)],
)
def test_integer_validators_reject_invalid_wire_values(value):
    assert is_int_in_range(value, -2, 2) is False
    assert is_uint(value, 2) is False


@pytest.mark.parametrize("value", [-3, -2, -1, 0, 1, 2, 3])
def test_signed_and_unsigned_inclusive_bounds(value):
    assert is_int_in_range(value, -2, 2) is (-2 <= value <= 2)
    assert is_uint(value, 2) is (0 <= value <= 2)


def test_zero_width_integer_ranges():
    assert is_int_in_range(-1, -1, -1) is True
    assert is_int_in_range(0, -1, -1) is False
    assert is_uint(0, 0) is True
    assert is_uint(1, 0) is False
    assert is_uint(0, -1) is False


@pytest.mark.parametrize(
    "ranges, expected",
    [({"mm": [40, 40, 40, 40, 40]}, False),
     ({"mm": [40, 40, 40, 40, 40], "valid_mask": 0}, True),
     ({"mm": [121, 121, 40, 40, 40], "valid_mask": 31}, True),
     ({"mm": [120, 121, 40, 40, 40], "valid_mask": 31}, False),
     ({"mm": [121, 121, 40, 40, 40], "valid_mask": True}, False),
     ({"mm": [121, 121, 40, 40, 40], "valid_mask": -1}, False),
     ({"mm": [121, 121, 40, 40, 40], "valid_mask": 32}, False),
     ({"mm": [121, 121, False, 40, 40], "valid_mask": 31}, False),
     ({"mm": [121, 121, 40, 40], "valid_mask": 31}, False)],
)
def test_floor_loss_requires_explicit_valid_range_wire_fields(ranges, expected):
    assert has_upright_floor_loss(ranges, {"valid": True, "acc": [0, 0, 12000]}) is expected


@pytest.mark.parametrize("acc", [[0, 0, 11999], [0, False, 12000], [0, 0, 32768]])
def test_floor_loss_rejects_bad_or_non_upright_acceleration(acc):
    ranges = {"mm": [121, 121, 40, 40, 40], "valid_mask": 31}
    assert not has_upright_floor_loss(ranges, {"valid": True, "acc": acc})
