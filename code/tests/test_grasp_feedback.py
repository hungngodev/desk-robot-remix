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


async def test_uncertain_transport_failure_after_jaw_move_attempts_safe_relief(monkeypatch):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 101, 150])
    original = head.aux_status

    async def failing_adc():
        if "grip 65" in head.commands:
            raise OSError("ADC bus timed out after jaw movement")
        return await original()

    head.aux_status = failing_adc
    with pytest.raises(OSError, match="ADC bus timed out"):
        await guarded_grasp(head, Settings(), health=healthy)
    assert head.commands == ["grip 65", "grip 60"]


async def test_uncertain_transport_failure_does_not_override_local_disarm(monkeypatch):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 101])
    original = head.aux_status

    async def failing_adc():
        if "grip 65" in head.commands:
            raise OSError("ADC bus timed out")
        return await original()

    head.aux_status = failing_adc

    async def status():
        if head.commands:
            raise OperationError("WROOM disarmed")
        return {"armed": True}

    with pytest.raises(OSError, match="ADC bus timed out"):
        await guarded_grasp(head, Settings(), health=status)
    assert head.commands == ["grip 65"]


async def test_cancelled_close_attempts_relief_only_with_live_safety(monkeypatch):
    """A cancelled task must not leave a commanded MG90S jaw squeezing."""
    import asyncio

    head = FakeHead([100, 101])
    sleeps = 0

    async def cancel_after_close(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:  # First closing pulse has already been sent.
            raise asyncio.CancelledError()

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", cancel_after_close)
    with pytest.raises(asyncio.CancelledError):
        await guarded_grasp(head, Settings(), health=healthy)
    assert head.commands == ["grip 65", "grip 60"]


async def test_cancelled_close_does_not_bypass_body_disarm(monkeypatch):
    """Cancellation relief remains subordinate to the WROOM motor interlock."""
    import asyncio

    head = FakeHead([100, 101])
    sleeps = 0

    async def cancel_after_close(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:
            raise asyncio.CancelledError()

    async def disarmed_after_first_close():
        if head.commands:
            raise OperationError("WROOM no longer armed")
        return {"armed": True}

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", cancel_after_close)
    with pytest.raises(asyncio.CancelledError):
        await guarded_grasp(head, Settings(), health=disarmed_after_first_close)
    assert head.commands == ["grip 65"]


async def test_real_task_cancellation_during_unacknowledged_jaw_command(monkeypatch):
    """A timed-out servo ACK cannot be assumed to mean no jaw movement."""
    import asyncio

    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 101])
    command_sent = asyncio.Event()
    never_acknowledged = asyncio.Event()

    async def interrupted_command(command):
        head.commands.append(command)
        if command == "grip 65":
            command_sent.set()
            await never_acknowledged.wait()

    head.command = interrupted_command
    task = asyncio.create_task(guarded_grasp(head, Settings(), health=healthy))
    try:
        await asyncio.wait_for(command_sent.wait(), timeout=1)
        task.cancel()  # Real task cancellation, not manually raising the exception.
        with pytest.raises(asyncio.CancelledError):
            await task
        assert head.commands == ["grip 65", "grip 60"]
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)



@pytest.mark.parametrize("phase", ["before_first", "during_close"])
async def test_stalled_force_feedback_is_bounded_and_jaw_relaxes_only_if_safe(
    monkeypatch, phase,
):
    """A stalled WROOM auxiliary read cannot hold an active jaw indefinitely."""
    import asyncio
    import desk_robot.grasp_feedback as feedback

    monkeypatch.setattr(feedback, "_FORCE_READ_TIMEOUT_S", 0.04)

    async def instant(_seconds):
        pass

    monkeypatch.setattr(feedback.asyncio, "sleep", instant)
    head = FakeHead([100, 101])
    original = head.aux_status
    waiting = asyncio.Event()

    async def stalls():
        if phase == "before_first" or head.commands:
            await waiting.wait()
        return await original()

    head.aux_status = stalls
    with pytest.raises(OperationError, match=(
        "Fresh force feedback" if phase == "before_first"
        else "Lost fresh force sensor"
    )):
        await asyncio.wait_for(
            guarded_grasp(head, Settings(), health=healthy), timeout=0.5,
        )
    assert head.commands == (
        [] if phase == "before_first" else ["grip 65", "grip 60"]
    )


async def test_stalled_force_feedback_never_bypasses_local_wroom_disarm(monkeypatch):
    import asyncio
    import desk_robot.grasp_feedback as feedback

    monkeypatch.setattr(feedback, "_FORCE_READ_TIMEOUT_S", 0.04)

    async def instant(_seconds):
        pass

    monkeypatch.setattr(feedback.asyncio, "sleep", instant)
    head = FakeHead([100, 101])
    original = head.aux_status

    async def stalled_after_jaw_move():
        if head.commands:
            await asyncio.Event().wait()
        return await original()

    head.aux_status = stalled_after_jaw_move

    async def disarmed():
        if head.commands:
            raise OperationError("WROOM local stop latched")
        return {"armed": True}

    with pytest.raises(OperationError, match="WROOM local stop latched"):
        await asyncio.wait_for(
            guarded_grasp(head, Settings(), health=disarmed), timeout=0.5,
        )
    assert head.commands == ["grip 65"]
