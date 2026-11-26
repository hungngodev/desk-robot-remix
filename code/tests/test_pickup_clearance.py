import pytest
from desk_robot.calibration import Calibration
from pydantic import ValidationError


@pytest.fixture
def payload():
    return {
        "measured": True,
        "image_width": 320, "image_height": 240,
        "pixel_points": [[20, 120], [300, 120], [300, 220], [20, 220]],
        "ground_points_mm": [[-100, 50], [100, 50], [100, 150], [-100, 150]],
        "work_area_mm": [-100, 50, 100, 150],
        "grip_ground_mm": [0, 75],
        "lifted_roi_px": [120, 30, 200, 90],
    }


@pytest.mark.parametrize("value", [0, -0.1, True, "0.25", float("nan"), float("inf")])
def test_invalid_pickup_clearance(payload, value):
    with pytest.raises(ValidationError, match="pickup_floor_clearance_mm"):
        Calibration.model_validate(dict(payload, pickup_floor_clearance_mm=value))


@pytest.mark.parametrize("value,measured,expected", [
    (None, True, False),
    (0.25, False, False),
    (0.25, True, True),
])
def test_measured_pickup_clearance(payload, value, measured, expected):
    calibration = Calibration.model_validate(dict(
        payload, pickup_floor_clearance_mm=value, measured=measured,
    ))
    assert calibration.has_pickup_floor_clearance() is expected


def test_pickup_clearance_legacy_calibration(payload):
    calibration = Calibration.model_validate(payload)
    calibration.verify_ready()
    assert not calibration.has_pickup_floor_clearance()
