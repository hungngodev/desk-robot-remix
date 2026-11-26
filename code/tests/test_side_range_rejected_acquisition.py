"""Closed PR #16 successor: rejected side samples cannot become live cues."""
import pytest
from desk_robot.side_ranging import SideRangeEvents


@pytest.mark.parametrize("rejection", ["age", "transport", "invalid", "range"])
@pytest.mark.parametrize("start", [100, 0xffffff00])
def test_rejected_present_conversion_advances_only_its_acquisition_fence(rejection, start):
    tracker = SideRangeEvents()
    calls = 0

    def observe(distance, offset, *, age=30, valid=7, elapsed=0):
        nonlocal calls
        calls += 1
        stamp = (start + offset) & 0xffffffff
        data = {
            "side_ranges": {
                "mm": [distance, 600, 600],
                "age_ms": [age, 30, 30],
                "sample_ms": [stamp] * 3,
                "boot_id": 901,
                "present_mask": 7,
                "valid_mask": valid,
                "motion_certified": False,
            },
            "imu": {"boot_id": 901},
        }
        return tracker.observe(data, now=10 + calls / 10, near_mm=170,
                               require_hardware_identity=True, request_elapsed_ms=elapsed)

    assert observe(600, 0) == []
    if rejection == "age":
        assert observe(90, 400, age=351) == []
    elif rejection == "transport":
        assert observe(90, 400, elapsed=351) == []
    elif rejection == "invalid":
        assert observe(90, 400, valid=6) == []
    else:
        assert observe(8190, 400) == []
    # Earlier or identical conversions cannot form a new baseline or vote.
    assert observe(600, 100) == []
    assert observe(95, 200) == []
    assert observe(90, 300) == []
    assert observe(85, 400) == []
    # New conversions still recover after a real far baseline.
    assert observe(600, 500) == []
    assert observe(95, 600) == []
    assert observe(90, 700) == [("left", 90)]
