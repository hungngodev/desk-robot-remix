import json

import pytest
from desk_robot.calibration import Calibration


def _payload():
    return {
        "simulation_only": False,
        "measured": True,
        "image_width": 200,
        "image_height": 200,
        "pixel_points": [[0, 0], [199, 0], [199, 199], [0, 199]],
        "ground_points_mm": [[0, 0], [199, 0], [199, 199], [0, 199]],
        "work_area_mm": [20, 90, 180, 180],
        "grip_ground_mm": [100, 100],
        "lifted_roi_px": [75, 40, 125, 80],
    }


@pytest.mark.parametrize("field", ["measured", "simulation_only"])
@pytest.mark.parametrize("value", [0, 1, "true", "false", "yes", "no"])
def test_calibration_permissions_require_json_booleans(tmp_path, field, value):
    path = tmp_path / "calibration.json"
    data = _payload()
    data[field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=field):
        Calibration.load(path)


@pytest.mark.parametrize("measured", [True, False])
@pytest.mark.parametrize("simulation_only", [True, False])
def test_calibration_permission_round_trip(tmp_path, measured, simulation_only):
    path = tmp_path / "calibration.json"
    data = _payload()
    data.update(measured=measured, simulation_only=simulation_only)
    original = Calibration.model_validate(data)
    original.save(path)
    serialized = json.loads(path.read_text())
    assert serialized["measured"] is measured
    assert serialized["simulation_only"] is simulation_only
    restored = Calibration.load(path)
    assert restored == original
    assert restored.ground((100, 100)) == pytest.approx((100, 100))
    if measured:
        restored.verify_ready()
    else:
        with pytest.raises(ValueError, match="unmeasured"):
            restored.verify_ready()
