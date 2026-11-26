import pytest

from desk_robot import operations
from desk_robot.motion_authority import StopConfirmationTracker


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


@pytest.mark.parametrize("newest_ack", [False, True])
@pytest.mark.parametrize("newest_finishes_first", [False, True])
def test_only_latest_stop_attempt_owns_confirmation(newest_ack, newest_finishes_first):
    tracker = StopConfirmationTracker(["robot-01", "robot-02"])
    assert not tracker.blocked()
    assert tracker.fleet_block_reason(None) is None
    older = tracker.begin("robot-01")
    newest = tracker.begin("robot-01")
    assert newest > older
    attempts = [(older, not newest_ack), (newest, newest_ack)]
    if newest_finishes_first:
        attempts.reverse()

    assert tracker.blocked("robot-01")
    assert not tracker.blocked("robot-02")
    assert tracker.blocked()
    generation, ack = attempts[0]
    tracker.finish("robot-01", generation, acknowledged=ack)
    assert tracker.blocked("robot-01")
    assert tracker.blocked()
    generation, ack = attempts[1]
    tracker.finish("robot-01", generation, acknowledged=ack)
    assert tracker.blocked("robot-01") is (not newest_ack)
    assert tracker.blocked() is (not newest_ack)
    assert not tracker.blocked("robot-02")

    recovery = tracker.begin("robot-01")
    tracker.finish("robot-01", recovery, acknowledged=True)
    assert not tracker.blocked()
    assert tracker.fleet_block_reason(None) is None


def test_fleet_owner_and_unconfirmed_stop_are_independent_fences():
    tracker = StopConfirmationTracker(["robot-01", "robot-02"])
    assert "one moving pet" in tracker.fleet_block_reason("job-1")
    generation = tracker.begin("robot-01")
    assert "STOP pending or unconfirmed" in tracker.fleet_block_reason(None)
    assert tracker.fleet_block_reason("job-1") is not None
    tracker.finish("robot-01", generation, acknowledged=False)
    peer = tracker.begin("robot-02")
    tracker.finish("robot-02", peer, acknowledged=True)
    assert tracker.blocked("robot-01")
    assert not tracker.blocked("robot-02")
    assert "STOP pending or unconfirmed" in tracker.fleet_block_reason(None)
    assert tracker.fleet_block_reason("job-1") is not None
    recovery = tracker.begin("robot-01")
    tracker.finish("robot-01", recovery, acknowledged=True)
    assert tracker.fleet_block_reason(None) is None
    assert "one moving pet" in tracker.fleet_block_reason("job-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("delay", [0.0, 0.250])
async def test_revoked_authority_precedes_queued_drive_dispatch(monkeypatch, delay):
    clock = 301.0
    tracker = StopConfirmationTracker(["robot-01"])
    sent = []
    monkeypatch.setattr(operations, "monotonic", lambda: clock)

    def check():
        if tracker.blocked():
            raise operations.OperationError("P0 STOP pending")

    class Head:
        supports_dispatch_check = True

        async def command(self, command, *, dispatch_check):
            nonlocal clock
            clock += delay
            tracker.begin("robot-01")
            dispatch_check()
            sent.append(command)
            return {"ok": True, "robot_id": "robot-01", "reply": "OK drive left=20 right=20 ms=250"}

    with pytest.raises(operations.OperationError, match="P0 STOP pending"):
        await operations.dispatch_job_command(Head(), "drive 20 20 250", check, robot_id="robot-01")
    assert sent == []
