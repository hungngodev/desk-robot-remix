"""A fresh hold observation must not reuse or resurrect a lost grasp."""
import asyncio
from types import SimpleNamespace

import pytest

from desk_robot.grasp_feedback import guarded_grasp, verify_grasp_hold
from desk_robot.operations import OperationError


class JawHead:
    def __init__(self, samples):
        self.samples = iter(samples)
        self.commands = []
        self.reads = 0

    async def aux_status(self):
        self.reads += 1
        raw, seq, overrides = next(self.samples)
        force = {"jaw_valid": True, "calibrated": False, "adc": [0, raw],
                 "jaw_seq": seq, "jaw_age_ms": 0, "boot_id": 5103}
        force.update(overrides)
        return {"robot_id": "robot-01", "force": force}

    async def command(self, command):
        self.commands.append(command)
        return {"ok": True, "robot_id": "robot-01",
                "reply": f"OK grip angle={command.split()[1]}"}


def calibration(sign):
    return SimpleNamespace(grip_open=60, grip_closed=100, grip_step_deg=4,
                           grip_force_delta_raw=120, grip_force_limit_raw=500,
                           grip_force_sign=sign)


async def healthy():
    return {"armed": True, "robot_id": "robot-01", "imu": {"boot_id": 5103}}


@pytest.mark.asyncio
@pytest.mark.parametrize("sign", [1, -1])
async def test_first_fresh_below_threshold_invalidates_grasp_without_retry(monkeypatch, sign):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    c = calibration(sign)
    head = JawHead([(1000, 1, {}), (1000, 2, {}), (1000 + sign * 140, 3, {}),
                    (1000 + sign * 145, 4, {}), (1000 + sign * 119, 5, {}),
                    (1000 + sign * 145, 6, {})])
    tactile = await guarded_grasp(head, c, robot_id="robot-01", health=healthy)
    assert tactile["grasped"] is True
    assert tactile["jaw_seq"] == 4
    with pytest.raises(OperationError, match="object_lost"):
        await verify_grasp_hold(head, c, tactile, robot_id="robot-01")
    assert tactile["grasped"] is False
    assert head.reads == 5
    with pytest.raises(OperationError, match="no active tactile hold"):
        await verify_grasp_hold(head, c, tactile, robot_id="robot-01")
    assert head.reads == 5
    assert head.commands == ["grip 64"]


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,seq,overrides,expected", [
    (220, 5, {}, None),
    (600, 5, {}, "grasp_unverified"),
    (-20, 5, {}, "grasp_unverified"),
    (100, 3, {}, "grasp_unverified"),
    (100, 5, {"boot_id": 5104}, "grasp_unverified"),
    (100, 5, {"jaw_age_ms": 500}, "grasp_unverified"),
    (100, 5, {"jaw_age_ms": None}, "grasp_unverified"),
    (100, 5, {"jaw_valid": False}, "grasp_unverified"),
])
async def test_hold_requires_fresh_same_boot_calibrated_evidence(raw, seq, overrides, expected):
    head = JawHead([(raw, seq, overrides)])
    tactile = {"grasped": True, "baseline_raw": 100, "boot_id": 5103,
               "jaw_seq": 4, "contact_delta_raw": 145}
    if expected:
        with pytest.raises(OperationError, match=expected):
            await verify_grasp_hold(head, calibration(1), tactile, robot_id="robot-01")
        assert tactile["grasped"] is False
    else:
        await verify_grasp_hold(head, calibration(1), tactile, robot_id="robot-01")
        assert tactile["grasped"] is True
        assert tactile["jaw_seq"] == 5
        assert tactile["contact_delta_raw"] == 120
    assert head.commands == []


@pytest.mark.asyncio
async def test_cached_low_sample_is_not_a_new_loss_observation(monkeypatch):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = JawHead([(100, 4, {})] * 6)
    tactile = {"grasped": True, "baseline_raw": 100, "boot_id": 5103,
               "jaw_seq": 4, "contact_delta_raw": 145}
    with pytest.raises(OperationError, match="grasp_unverified"):
        await verify_grasp_hold(head, calibration(1), tactile, robot_id="robot-01")
    assert tactile["grasped"] is False
    assert head.reads == 6


@pytest.mark.asyncio
async def test_cancelled_hold_read_invalidates_provenance():
    class StalledJaw:
        async def aux_status(self):
            raise asyncio.CancelledError

    tactile = {"grasped": True, "baseline_raw": 100, "boot_id": 5103,
               "jaw_seq": 4, "contact_delta_raw": 145}
    with pytest.raises(asyncio.CancelledError):
        await verify_grasp_hold(StalledJaw(), calibration(1), tactile, robot_id="robot-01")
    assert tactile["grasped"] is False
