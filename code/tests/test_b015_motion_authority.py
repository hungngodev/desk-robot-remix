import pytest
from desk_robot import operations


@pytest.mark.asyncio
@pytest.mark.parametrize("delay, allowed", [(0.249, True), (0.250, False), (0.251, False)])
async def test_persistent_session_does_not_extend_dispatch_deadline(monkeypatch, delay, allowed):
    """B015: even after 301s, each queued pulse has its own dispatch deadline."""
    clock = 301.0
    sent = []
    monkeypatch.setattr(operations, "monotonic", lambda: clock)

    class Head:
        supports_dispatch_check = True

        async def command(self, command, *, dispatch_check):
            nonlocal clock
            clock += delay
            dispatch_check()
            sent.append(command)
            return {"ok": True, "robot_id": "robot-01", "reply": "OK drive left=20 right=20 ms=250"}

    async def pulse():
        return await operations.dispatch_job_command(
            Head(), "drive 20 20 250", lambda: None, robot_id="robot-01"
        )

    if allowed:
        assert (await pulse())["ok"] is True
        assert sent == ["drive 20 20 250"]
    else:
        with pytest.raises(operations.OperationError, match="dispatch expired"):
            await pulse()
        assert sent == []


@pytest.mark.asyncio
async def test_persistent_session_rejects_251ms_pulse_before_transport():
    class Head:
        async def command(self, _command):
            pytest.fail("Oversized drive reached the transport")

    with pytest.raises(ValueError, match="conservative bounds"):
        await operations.dispatch_job_command(
            Head(), "drive 20 20 251", lambda: None, robot_id="robot-01"
        )
