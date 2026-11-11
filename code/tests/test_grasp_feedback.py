"""Force-driven gripper must not close without real, fresh sensor data."""
import pytest
from desk_robot.controller import OperationError
from desk_robot.grasp_feedback import force_adc, grip_angles, guarded_grasp


class FakeHead:
    def __init__(self, samples):
        self.samples = iter(samples)
        self.commands = []

    async def aux_status(self):
        v = next(self.samples)
        if v is None:
            return {"force": {"valid": False, "calibrated": False, "adc": [0, 0]}}
        return {"force": {"valid": True, "calibrated": False, "adc": [0, v]}}

    async def command(self, command):
        self.commands.append(command)


class Settings:
    grip_open = 60
    grip_closed = 100
    grip_force_delta_raw = 120
    grip_force_limit_raw = 500
    grip_force_sign = 1
    grip_step_deg = 5


async def healthy():
    return {"armed": True}


def test_servo_increments_respect_both_linkage_orientations():
    assert grip_angles(60, 73, 5) == (60, 65, 70, 73)
    assert grip_angles(102, 87, 5) == (102, 97, 92, 87)
    with pytest.raises(ValueError):
        grip_angles(60, 60, 4)
    with pytest.raises(ValueError):
        grip_angles(60, 135, 4)


def test_absent_sensor_never_fabricates_force():
    with pytest.raises(ValueError):
        force_adc({"force": {"valid": False, "adc": [0, 100]}})


async def test_contact_stops_before_full_closure(monkeypatch):
    async def instant(_seconds):
        pass
    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 101, 130, 240, 245])
    result = await guarded_grasp(head, Settings(), health=healthy)
    assert result["contact_delta_raw"] >= 120
    assert head.commands == ["grip 65", "grip 70", "grip 75"]
    assert result["physical_acceptance_pass"] is False


async def test_stale_feedback_fails_before_next_servo_pulse(monkeypatch):
    async def instant(_seconds):
        pass
    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 100, None])
    with pytest.raises(OperationError, match="Lost fresh"):
        await guarded_grasp(head, Settings(), health=healthy)
    assert head.commands == ["grip 65"]


async def test_overforce_and_bad_baseline_fail_closed(monkeypatch):
    async def instant(_seconds):
        pass
    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 100, 800])
    with pytest.raises(OperationError, match="ceiling"):
        await guarded_grasp(head, Settings(), health=healthy)
    assert head.commands == ["grip 65"]
    head = FakeHead([100, 250])
    with pytest.raises(OperationError, match="baseline"):
        await guarded_grasp(head, Settings(), health=healthy)
    assert head.commands == []
