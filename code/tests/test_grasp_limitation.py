"""Terminal grasp limitations must not invite another closing attempt."""

import pytest
from desk_robot.grasp_feedback import guarded_grasp
from desk_robot.operations import OperationError


class Settings:
    grip_open = 60
    grip_closed = 72
    grip_force_delta_raw = 120
    grip_force_limit_raw = 500
    grip_force_sign = 1
    grip_step_deg = 4


class Head:
    def __init__(self, values):
        self.values = iter(values)
        self.commands = []
        self.seq = 0
        self.angle = Settings.grip_open

    async def aux_status(self):
        self.seq += 1
        return {"robot_id": "robot-01", "force": {
            "calibrated": False, "jaw_valid": True, "jaw_seq": self.seq,
            "jaw_age_ms": 0, "boot_id": 5103, "adc": [0, next(self.values)],
        }}

    async def command(self, command):
        self.commands.append(command)
        self.angle = int(command.split()[1])
        return {"ok": True, "robot_id": "robot-01", "reply": f"OK grip angle={self.angle}"}

    async def health(self):
        return {"armed": True, "robot_id": "robot-01", "imu": {"boot_id": 5103},
                "servo": {"attached": True, "position_source": "commanded",
                          "grip": self.angle, "grip_target": self.angle}}


@pytest.mark.asyncio
@pytest.mark.parametrize(("samples", "commands", "detail"), [
    ([100, 100, 101, 101, 101], ["grip 64", "grip 68", "grip 72", "grip 60"],
     "no confirmed tactile contact"),
    ([100, 100, 240, 101, 240, 101, 240, 245], ["grip 64", "grip 68", "grip 60"],
     "contact lost twice"),
])
async def test_grasp_limitation_stops_and_relieves(monkeypatch, samples, commands, detail):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = Head(samples)
    with pytest.raises(OperationError, match="too_flat_or_slipped") as error:
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=head.health)
    assert detail in str(error.value)
    assert head.commands == commands


@pytest.mark.asyncio
async def test_one_transient_contact_can_still_be_confirmed(monkeypatch):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = Head([100, 100, 240, 101, 240, 245])
    result = await guarded_grasp(head, Settings(), robot_id="robot-01", health=head.health)
    assert result["commanded_angle"] == 68
    assert result["physical_acceptance_pass"] is False
    assert head.commands == ["grip 64", "grip 68"]


@pytest.mark.asyncio
async def test_overforce_not_mislabeled_as_slip(monkeypatch):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = Head([100, 100, 600])
    with pytest.raises(OperationError, match="force ceiling exceeded") as error:
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=head.health)
    assert "too_flat_or_slipped" not in str(error.value)
    assert head.commands == ["grip 64", "grip 60"]
