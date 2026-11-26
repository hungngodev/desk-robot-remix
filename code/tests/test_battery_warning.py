"""Boundary checks for the optional per-pet battery speech budget and fuel envelope."""
import math

import pytest
from desk_robot.controller import OperationError, _require_safe_fuel_sample
from desk_robot.initiative_policy import battery_warning_pending
from desk_robot.sensor_event_contract import is_valid_fuel_measurement


@pytest.mark.parametrize(("now", "last", "expected"), [
    (100.0, -math.inf, False),
    (100.0, 100.0, True),
    (219.999, 100.0, True),
    (220.0, 100.0, False),
    (99.0, 100.0, False),
])
def test_battery_warning_minimum_interval(now, last, expected):
    assert battery_warning_pending(now=now, last=last) is expected


@pytest.mark.parametrize(("elapsed", "expected"), [
    (math.nextafter(0.0, -math.inf), False),
    (0.0, True),
    (math.nextafter(0.0, math.inf), True),
    (math.nextafter(120.0, -math.inf), True),
    (120.0, False),
    (math.nextafter(120.0, math.inf), False),
])
def test_battery_warning_adjacent_float_edges(elapsed, expected):
    assert battery_warning_pending(now=elapsed, last=0.0) is expected


@pytest.mark.parametrize(("cell_mv", "soc_centi", "expected"), [
    (2499, 5000, False),
    (2500, 5000, True),
    (2501, 5000, True),
    (4499, 5000, True),
    (4500, 5000, True),
    (4501, 5000, False),
    (3700, -1, False),
    (3700, 0, True),
    (3700, 1, True),
    (3700, 9999, True),
    (3700, 10000, True),
    (3700, 10001, False),
])
def test_battery_warning_fuel_measurement_edges(cell_mv, soc_centi, expected):
    assert is_valid_fuel_measurement(cell_mv, soc_centi) is expected


@pytest.mark.parametrize("cell_mv", range(3260, 3341))
def test_brownout_noise_is_valid_evidence_but_not_new_motion_admission(cell_mv):
    power = {"fuel_valid": True, "cell_mv": cell_mv, "soc_centi": 5000}
    assert is_valid_fuel_measurement(cell_mv, 5000)
    with pytest.raises(OperationError, match="preflight depleted"):
        _require_safe_fuel_sample(
            power, min_cell_mv=3350, min_soc_centi=500,
            context="preflight", depleted_message="preflight depleted",
        )
    # A live operation uses the lower cutoff, but only WROOM can clear its latch.
    if cell_mv < 3300:
        with pytest.raises(OperationError, match="operation depleted"):
            _require_safe_fuel_sample(
                power, min_cell_mv=3300, min_soc_centi=300,
                context="operation", depleted_message="operation depleted",
            )
    else:
        _require_safe_fuel_sample(
            power, min_cell_mv=3300, min_soc_centi=300,
            context="operation", depleted_message="operation depleted",
        )
