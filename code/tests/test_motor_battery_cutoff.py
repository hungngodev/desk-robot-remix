"""Check Mac motion admission and preflight against the WROOM battery floors."""
import pytest
from desk_robot.controller import (
    OperationError,
    _require_fresh_auto_dock_fuel,
    _require_safe_fuel_sample,
)
from desk_robot.sensor_event_contract import is_valid_fuel_measurement


@pytest.mark.parametrize(
    ("cell_mv", "soc_centi", "minimum_mv", "minimum_soc", "allowed"),
    [
        (3299, 5000, 3300, 300, False),
        (3800, 299, 3300, 300, False),
        (3300, 300, 3300, 300, True),
        (3349, 500, 3350, 500, False),
        (3350, 499, 3350, 500, False),
        (3350, 500, 3350, 500, True),
    ],
)
def test_mac_battery_floors(cell_mv, soc_centi, minimum_mv, minimum_soc, allowed):
    power = {"fuel_valid": True, "cell_mv": cell_mv, "soc_centi": soc_centi}
    limits = {
        "min_cell_mv": minimum_mv,
        "min_soc_centi": minimum_soc,
        "context": "test",
        "depleted_message": "depleted",
    }
    if allowed:
        _require_safe_fuel_sample(power, **limits)
    else:
        with pytest.raises(OperationError, match="depleted"):
            _require_safe_fuel_sample(power, **limits)


@pytest.mark.parametrize("field,value", [
    ("cell_mv", -1), ("cell_mv", 0), ("cell_mv", 2499), ("cell_mv", 4501),
    ("cell_mv", 6001), ("cell_mv", True), ("cell_mv", False),
    ("cell_mv", float("nan")), ("cell_mv", float("inf")), ("cell_mv", 3800.0),
    ("cell_mv", "3800"), ("cell_mv", None),
    ("soc_centi", -1), ("soc_centi", 10001), ("soc_centi", True),
    ("soc_centi", float("nan")), ("soc_centi", None),
])
def test_claimed_valid_fuel_rejects_malformed_measurements(field, value):
    power = {"fuel_valid": True, "cell_mv": 3800, "soc_centi": 1800,
             "fuel_seq": 7, "fuel_age_ms": 10}
    power[field] = value
    with pytest.raises(OperationError, match="malformed battery telemetry"):
        _require_safe_fuel_sample(
            power, min_cell_mv=3350, min_soc_centi=500,
            context="test", depleted_message="depleted",
        )
    with pytest.raises(OperationError, match="fresh low battery"):
        _require_fresh_auto_dock_fuel(power, max_soc_centi=2000, elapsed_ms=0)


@pytest.mark.parametrize("cell_mv,soc_centi", [(2500, 0), (4500, 10000), (3800, 1800)])
def test_fuel_measurement_inclusive_bounds(cell_mv, soc_centi):
    assert is_valid_fuel_measurement(cell_mv, soc_centi)
