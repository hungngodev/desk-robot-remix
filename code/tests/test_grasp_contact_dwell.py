"""Software dwell is tactile evidence only, never physical grasp acceptance."""
from types import SimpleNamespace

import pytest
from desk_robot import grasp_feedback as feedback
from desk_robot.operations import OperationError


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "unsettled", "expired", "bump", "overforce"])
async def test_contact_dwell_requires_settled_target_and_two_fresh_samples(monkeypatch, fault):
    clock = 100.0
    first_contact_at = None
    reads = []
    commands = []
    health_checks = []
    values = iter([100, 100, 240, {"bump": 100, "overforce": 600}.get(fault, 245)])

    async def advance(seconds):
        nonlocal clock
        clock += seconds

    monkeypatch.setattr(feedback.asyncio, "sleep", advance)
    monkeypatch.setattr(feedback, "time", SimpleNamespace(monotonic=lambda: clock))

    class Head:
        async def aux_status(self):
            nonlocal first_contact_at
            reads.append(clock)
            if len(reads) == 3:
                first_contact_at = clock
            return {
                "robot_id": "robot-01",
                "force": {
                    "jaw_valid": True, "calibrated": False, "adc": [0, next(values)],
                    "jaw_seq": len(reads), "jaw_age_ms": 0, "boot_id": 5103,
                },
            }

        async def command(self, command):
            commands.append(command)
            return {"ok": True, "robot_id": "robot-01",
                    "reply": f"OK grip angle={command.split()[1]}"}

    async def health():
        nonlocal clock
        target = int(commands[-1].split()[1]) if commands else 60
        angle = target
        health_checks.append((len(reads), target, clock))
        if len(reads) == 3 and target == 64:
            if fault == "unsettled":
                angle = 63
            elif fault == "expired":
                clock += 0.5
        return {
            "armed": True, "robot_id": "robot-01", "imu": {"boot_id": 5103},
            "servo": {"grip": angle, "grip_target": target, "attached": True,
                      "position_source": "commanded"},
        }

    calibration = SimpleNamespace(
        grip_open=60, grip_closed=64, grip_step_deg=4,
        grip_force_delta_raw=120, grip_force_limit_raw=500, grip_force_sign=1,
    )
    if fault is None:
        receipt = await feedback.guarded_grasp(
            Head(), calibration, robot_id="robot-01", health=health,
        )
        assert receipt["contact_delta_raw"] == 145
        assert receipt["commanded_angle"] == 64
        assert receipt["position_measured"] is False
        assert receipt["physical_acceptance_pass"] is False
        assert commands == ["grip 64"]
    else:
        reason = {
            "unsettled": "commanded closing target not confirmed",
            "expired": "expired before contact dwell",
            "bump": "no confirmed tactile contact",
            "overforce": "force ceiling exceeded",
        }[fault]
        with pytest.raises(OperationError, match=reason):
            await feedback.guarded_grasp(
                Head(), calibration, robot_id="robot-01", health=health,
            )
        assert commands == ["grip 64", "grip 60"]
    assert (3, 64, first_contact_at) in health_checks
    if fault in ("unsettled", "expired"):
        assert len(reads) == 3
    else:
        assert len(reads) == 4
        assert reads[3] - reads[2] >= 0.149999
