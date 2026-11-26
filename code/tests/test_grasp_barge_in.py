import asyncio

import pytest

from desk_robot.grasp_feedback import guarded_grasp
from desk_robot.operations import OperationError


class Calibration:
    grip_open = 60
    grip_closed = 100
    grip_step_deg = 4
    grip_force_delta_raw = 120
    grip_force_limit_raw = 500
    grip_force_sign = 1


class Head:
    def __init__(self, readings):
        self.readings = iter(readings)
        self.commands = []
        self.seq = 0

    async def command(self, command):
        self.commands.append(command)
        return {"ok": True, "robot_id": "robot-01",
                "reply": f"OK grip angle={command.split()[1]}"}

    async def aux_status(self):
        reading = next(self.readings)
        self.seq += 1
        return {"robot_id": "robot-01", "force": {
            "jaw_valid": True, "calibrated": False, "adc": [0, reading],
            "jaw_seq": self.seq, "jaw_age_ms": 0, "boot_id": 5103,
        }}


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before_contact", "confirmed_contact", "no_cancel", "overforce"])
async def test_grasp_barge_in_preserves_contact_and_other_relief_paths(monkeypatch, phase):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = Head([100, 100, 240, 600 if phase == "overforce" else 245])
    entered = asyncio.Event()
    release = asyncio.Event()
    blocked = False

    async def health():
        nonlocal blocked
        if not blocked and head.commands and (
            (phase == "before_contact" and head.seq == 2)
            or (phase == "confirmed_contact" and head.seq == 4)
        ):
            blocked = True
            entered.set()
            await release.wait()
        angle = int(head.commands[-1].split()[1]) if head.commands else 60
        return {"armed": True, "robot_id": "robot-01", "imu": {"boot_id": 5103},
                "servo": {"grip": angle, "grip_target": angle, "attached": True,
                          "position_source": "commanded"}}

    task = asyncio.create_task(guarded_grasp(
        head, Calibration(), robot_id="robot-01", health=health,
    ))
    try:
        if phase in {"before_contact", "confirmed_contact"}:
            await asyncio.wait_for(entered.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)
        elif phase == "overforce":
            with pytest.raises(OperationError, match="force ceiling exceeded"):
                await task
        else:
            receipt = await task
            assert receipt["grasped"] is True
            assert receipt["physical_acceptance_pass"] is False
        assert head.commands == (
            ["grip 64", "grip 60"] if phase in {"before_contact", "overforce"}
            else ["grip 64"]
        )
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
