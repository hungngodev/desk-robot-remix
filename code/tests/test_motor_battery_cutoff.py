"""Check Mac motion admission and preflight against the WROOM battery floors."""
import pytest
from desk_robot.controller import OperationError, _require_safe_fuel_sample


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
