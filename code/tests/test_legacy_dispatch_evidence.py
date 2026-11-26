"""Legacy adapters must not silently bypass dispatch-only evidence."""

import asyncio

import pytest
from desk_robot.operations import dispatch_job_command


@pytest.mark.asyncio
async def test_legacy_adapter_checks_evidence_before_command():
    sent = []

    class Head:
        async def command(self, command):
            sent.append(command)
            return {"ok": True}

    def revoked():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await dispatch_job_command(Head(), "drive 20 20 100", lambda: None,
                                   dispatch_check=revoked)
    assert sent == []


@pytest.mark.asyncio
async def test_legacy_adapter_checks_evidence_once():
    checks = []

    class Head:
        async def command(self, command):
            assert checks == [True]
            return {"ok": True}

    result = await dispatch_job_command(
        Head(), "drive 20 20 100", lambda: None, dispatch_check=lambda: checks.append(True)
    )
    assert result == {"ok": True}
    assert checks == [True]
