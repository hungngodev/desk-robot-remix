import json
from datetime import UTC, datetime

import pytest
from desk_robot import calibration as calibration_module
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
    calibration = Calibration.model_validate(
        {**_payload(), "expires_at": "2099-01-01T05:00:00+05:00"}
    )
    calibration.save(path)
    restored = Calibration.load(path)
    assert restored == calibration
    assert restored.expires_at == datetime(2099, 1, 1, tzinfo=UTC)
    restored.verify_ready()


def test_calibration_expiry_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone"):
        Calibration.model_validate({**_payload(), "expires_at": "2099-01-01T00:00:00"})


def test_legacy_calibration_does_not_invent_expiry():
    calibration = Calibration.model_validate(_payload())
    assert calibration.expires_at is None
    calibration.verify_ready()


def test_exact_expiry_in_different_timezone_blocks_pickup(monkeypatch):
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is UTC
            return datetime(2099, 1, 1, tzinfo=UTC)

    monkeypatch.setattr(calibration_module, "datetime", FixedClock)
    calibration = Calibration.model_validate(
        {**_payload(), "expires_at": "2099-01-01T05:00:00+05:00"}
    )
    with pytest.raises(ValueError, match="expired"):
        calibration.verify_ready()


@pytest.mark.parametrize("wall_expired", [False, True])
def test_rollback_cannot_extend_or_revive_robot_calibration(monkeypatch, wall_expired):
    wall = datetime(2099, 1, 1, 0, 0, 0, tzinfo=UTC)
    ticks = 100.0

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is UTC
            return wall

    monkeypatch.setattr(calibration_module, "datetime", FixedClock)
    monkeypatch.setattr(calibration_module, "monotonic", lambda: ticks)
    calibration = Calibration.model_validate({
        **_payload(), "robot_id": "robot-01", "expires_at": "2099-01-01T00:00:10Z",
    })
    calibration.verify_ready(robot_id="robot-01")
    with pytest.raises(ValueError, match="does not match"):
        calibration.verify_ready(robot_id="robot-02")
    ticks = 105.0
    if wall_expired:
        wall = datetime(2099, 1, 1, 0, 0, 10, tzinfo=UTC)
        with pytest.raises(ValueError, match="expired"):
            calibration.verify_ready(robot_id="robot-01")
    wall = datetime(2098, 12, 31, tzinfo=UTC)
    if not wall_expired:
        calibration.verify_ready(robot_id="robot-01")
        ticks = 110.0
    with pytest.raises(ValueError, match="expired"):
        calibration.verify_ready(robot_id="robot-01")


def test_forward_clock_correction_shortens_deadline_before_expiry(monkeypatch):
    wall = datetime(2099, 1, 1, tzinfo=UTC)
    ticks = 100.0

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is UTC
            return wall

    monkeypatch.setattr(calibration_module, "datetime", FixedClock)
    monkeypatch.setattr(calibration_module, "monotonic", lambda: ticks)
    calibration = Calibration.model_validate({
        **_payload(), "robot_id": "robot-01", "expires_at": "2099-01-01T00:00:10Z",
    })
    calibration.verify_ready(robot_id="robot-01")

    # A forward correction leaves three seconds, not the original eight.
    ticks = 102.0
    wall = datetime(2099, 1, 1, 0, 0, 7, tzinfo=UTC)
    calibration.verify_ready(robot_id="robot-01")

    # Rolling back the wall clock cannot restore the discarded five seconds.
    wall = datetime(2098, 12, 31, tzinfo=UTC)
    ticks = 104.999
    calibration.verify_ready(robot_id="robot-01")
    ticks = 105.0
    with pytest.raises(ValueError, match="expired.*re-calibrate"):
        calibration.verify_ready(robot_id="robot-01")
    ticks = 106.0
    with pytest.raises(ValueError, match="expired.*re-calibrate"):
        calibration.verify_ready(robot_id="robot-01")
