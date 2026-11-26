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


@pytest.mark.parametrize("copy_file", [False, True])
def test_physical_calibration_is_bound_to_exact_robot(tmp_path, copy_file):
    path = tmp_path / "unit-a.json"
    original = Calibration.model_validate({**_payload(), "robot_id": "robot-01"})
    original.save(path)
    if copy_file:
        other = tmp_path / "unit-b.json"
        other.write_bytes(path.read_bytes())
        path = other
    restored = Calibration.load(path)
    restored.verify_ready(robot_id="robot-01")
    for robot_id in ("robot-02", "Robot-01"):
        with pytest.raises(ValueError, match="does not match"):
            restored.verify_ready(robot_id=robot_id)


def test_legacy_physical_calibration_cannot_authorize_a_robot(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(_payload()))
    calibration = Calibration.load(path)
    with pytest.raises(ValueError, match="no robot_id"):
        calibration.verify_ready(robot_id="robot-01")


def test_shared_simulation_calibration_remains_usable():
    calibration = Calibration.model_validate({**_payload(), "simulation_only": True})
    for robot_id in ("robot-01", "robot-02"):
        calibration.verify_ready(robot_id=robot_id)
    bound = Calibration.model_validate({**_payload(), "simulation_only": True,
                                        "robot_id": "robot-01"})
    with pytest.raises(ValueError, match="does not match"):
        bound.verify_ready(robot_id="robot-02")


@pytest.mark.parametrize("robot_id", ["", " robot-01", "../robot-01", "NUL", 1, True])
def test_calibration_rejects_invalid_robot_identity(robot_id):
    with pytest.raises(ValueError, match="robot_id"):
        Calibration.model_validate({**_payload(), "robot_id": robot_id})


def test_calibration_rejects_duplicate_owner(tmp_path):
    path = tmp_path / "ambiguous.json"
    payload = json.dumps({**_payload(), "robot_id": "robot-01"})
    path.write_text('{"robot_id": "robot-02", ' + payload[1:])
    with pytest.raises(ValueError, match="Duplicate calibration JSON field: robot_id"):
        Calibration.load(path)
