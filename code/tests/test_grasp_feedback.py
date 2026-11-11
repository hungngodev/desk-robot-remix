"""Gripper only accepts two physically new ADC conversions to confirm contact."""
import pytest
from desk_robot.controller import OperationError
from desk_robot.grasp_feedback import force_adc, grip_angles, guarded_grasp


class FakeHead:
    def __init__(self, samples):
        self.samples = iter(samples)
        self.commands = []
        self.seq = 0

    async def aux_status(self):
        value = next(self.samples)
        if value is None:
            return {"force": {"valid": False, "calibrated": False,
                              "jaw_seq": self.seq, "adc": [0, 0]}}
        if isinstance(value, tuple):
            value, self.seq = value
        else:
            self.seq += 1
        return {"force": {"valid": True, "calibrated": False,
                          "jaw_seq": self.seq, "adc": [0, value]}}

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
    assert head.commands == ["grip 65", "grip 60"]


async def test_repeated_adc_frame_cannot_confirm_twice(monkeypatch):
    async def instant(_seconds):
        pass
    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([(100, 1), (100, 2), (240, 3), (240, 3)])
    with pytest.raises(OperationError, match="No new jaw sample"):
        await guarded_grasp(head, Settings(), health=healthy)
    assert head.commands == ["grip 65", "grip 70", "grip 60"]


async def test_overforce_and_bad_baseline_fail_closed(monkeypatch):
    async def instant(_seconds):
        pass
    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 100, 800])
    with pytest.raises(OperationError, match="ceiling"):
        await guarded_grasp(head, Settings(), health=healthy)
    assert head.commands == ["grip 65", "grip 60"]
    head = FakeHead([100, 250])
    with pytest.raises(OperationError, match="baseline"):
        await guarded_grasp(head, Settings(), health=healthy)
    assert head.commands == []


async def test_local_disarm_never_bypassed_to_release_jaw(monkeypatch):
    async def instant(_seconds):
        pass
    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 100, 900])
    calls = 0

    async def intermittent_health():
        nonlocal calls
        calls += 1
        # First two checks permit a single closer pulse. Once it failed,
        # the WROOM local safety gate has disarmed.
        if calls > 2:
            raise OperationError("Body disarmed")
        return {"armed": True}

    with pytest.raises(OperationError, match="Body disarmed"):
        await guarded_grasp(head, Settings(), health=intermittent_health)
    assert head.commands == ["grip 65"]
