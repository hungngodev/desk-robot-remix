import json
from datetime import datetime, timezone

import pytest
from desk_robot.calibration import Calibration


def _payload():
    return {
        "measured": True,
        "image_width": 200,
        "image_height": 200,
        "pixel_points": [[0, 0], [199, 0], [199, 199], [0, 199]],
        "ground_points_mm": [[0, 0], [199, 0], [199, 199], [0, 199]],
        "work_area_mm": [20, 90, 180, 180],
        "grip_ground_mm": [100, 100],
        "lifted_roi_px": [75, 40, 125, 80],
    }


def test_expired_calibration_blocks_pickup_admission(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps({**_payload(), "expires_at": "2000-01-01T00:00:00Z"}))
    calibration = Calibration.load(path)
    with pytest.raises(ValueError, match="expired.*re-calibrate"):
        calibration.verify_ready()


def test_future_expiry_survives_save_and_load(tmp_path):
    path = tmp_path / "calibration.json"
    calibration = Calibration.model_validate({**_payload(), "expires_at": "2099-01-01T05:00:00+05:00"})
    calibration.save(path)
    restored = Calibration.load(path)
    assert restored == calibration
    assert restored.expires_at == datetime(2099, 1, 1, tzinfo=timezone.utc)
    restored.verify_ready()


def test_calibration_expiry_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone"):
        Calibration.model_validate({**_payload(), "expires_at": "2099-01-01T00:00:00"})


def test_legacy_calibration_does_not_invent_expiry():
    calibration = Calibration.model_validate(_payload())
    assert calibration.expires_at is None
    calibration.verify_ready()
