"""Legacy adapters must not silently bypass dispatch-only evidence."""

import asyncio

import pytest
from desk_robot.command_framing import expected_ack
from desk_robot.operations import dispatch_job_command


@pytest.mark.asyncio
async def test_legacy_adapter_checks_evidence_before_command():
    sent = []

    class Head:
        async def command(self, command):
            sent.append(command)
            return {"ok": True, "robot_id": "robot-01", "reply": expected_ack(command)}

    def revoked():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await dispatch_job_command(Head(), "drive 20 20 100", lambda: None,
                                   robot_id="robot-01", dispatch_check=revoked)
    assert sent == []


@pytest.mark.asyncio
async def test_legacy_adapter_checks_evidence_once():
    checks = []

    class Head:
        async def command(self, command):
            assert checks == [True]
            return {"ok": True, "robot_id": "robot-01", "reply": expected_ack(command)}

    result = await dispatch_job_command(
        Head(), "drive 20 20 100", lambda: None,
        robot_id="robot-01", dispatch_check=lambda: checks.append(True),
    )
    assert result == {
        "ok": True, "robot_id": "robot-01", "reply": expected_ack("drive 20 20 100"),
    }
    assert checks == [True]
