"""Gripper only accepts two physically new ADC conversions to confirm contact."""
import pytest
from desk_robot.controller import OperationError
from desk_robot.grasp_feedback import force_adc, force_observation, grip_angles, guarded_grasp


class FakeHead:
    def __init__(self, samples):
        self.samples = iter(samples)
        self.commands = []
        self.seq = 0

    async def aux_status(self):
        value = next(self.samples)
        if value is None:
            return {"robot_id": "robot-01", "force": {"valid": False, "calibrated": False,
                              "jaw_seq": self.seq, "adc": [0, 0]}}
        if isinstance(value, tuple):
            value, self.seq = value
        else:
            self.seq += 1
        return {"robot_id": "robot-01", "force": {"valid": True, "calibrated": False,
                          "jaw_seq": self.seq, "adc": [0, value],
                          "jaw_valid": True, "jaw_age_ms": 0, "boot_id": 5103}}

    async def command(self, command):
        self.commands.append(command)


class Settings:
    grip_open = 60
    grip_closed = 100
    grip_force_delta_raw = 120
    grip_force_limit_raw = 500
    grip_force_sign = 1
    grip_step_deg = 4


async def healthy():
    return {"armed": True}


def test_servo_increments_respect_both_linkage_orientations():
    assert grip_angles(60, 73, 4) == (60, 64, 68, 72, 73)
    assert grip_angles(102, 87, 4) == (102, 98, 94, 90, 87)
    with pytest.raises(ValueError, match="Measured servo limits required"):
        grip_angles(60, 73, 5)
    with pytest.raises(ValueError):
        grip_angles(60, 60, 4)
    with pytest.raises(ValueError):
        grip_angles(60, 135, 4)


@pytest.mark.parametrize("clipped", [-32768, 32767])
def test_clipped_gripper_adc_cannot_authorize_contact(clipped):
    with pytest.raises(ValueError, match="Missing, invalid or stale"):
        force_adc({"force": {"valid": True, "calibrated": False,
                             "jaw_seq": 1, "adc": [0, clipped]}})


@pytest.mark.parametrize("age", [-1, 500, 0xffffffff + 1, "3", True])
def test_stale_or_invalid_jaw_acquisition_age_never_proves_contact(age):
    with pytest.raises(ValueError, match="Missing, invalid or stale"):
        force_adc({"force": {"valid": True, "calibrated": False,
                             "jaw_seq": 1, "jaw_age_ms": age, "adc": [0, 100]}})


async def test_late_jaw_age_during_close_aborts_before_next_step(monkeypatch):
    async def instant(_seconds):
        pass
    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    class ExpiredJaw(FakeHead):
        async def aux_status(self):
            reading = await super().aux_status()
            if self.seq >= 3:
                reading["force"]["jaw_age_ms"] = 600
            else:
                reading["force"]["jaw_age_ms"] = 0
            return reading
    head = ExpiredJaw([100, 101, 240])
    with pytest.raises(OperationError, match="Lost fresh force sensor"):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    assert head.commands == ["grip 64", "grip 60"]


def test_absent_sensor_never_fabricates_force():
    with pytest.raises(ValueError):
        force_adc({"force": {"valid": False, "adc": [0, 100]}})


def test_jaw_force_observation_succeeds_when_jaw_valid_even_if_composite_valid_is_false():
    reading = {
        "force": {
            "adc": [32767, 500],
            "belly_valid": False,
            "jaw_valid": True,
            "valid": False,
            "calibrated": False,
            "jaw_seq": 10,
            "jaw_age_ms": 15,
        }
    }
    adc, seq = force_observation(reading)
    assert adc == 500
    assert seq == 10

    reading["force"]["jaw_valid"] = False
    with pytest.raises(ValueError, match="Missing, invalid or stale"):
        force_observation(reading)


async def test_contact_stops_before_full_closure(monkeypatch):
    async def instant(_seconds):
        pass
    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 101, 130, 240, 245])
    result = await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    assert result["contact_delta_raw"] >= 120
    assert head.commands == ["grip 64", "grip 68"]
    assert result["physical_acceptance_pass"] is False


async def test_stale_feedback_fails_before_next_servo_pulse(monkeypatch):
    async def instant(_seconds):
        pass
    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 100, None])
    with pytest.raises(OperationError, match="Lost fresh"):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    # The downgraded AUX frame has no WROOM boot identity. A relief command
    # could act on a rebooted controller, so even reopening is forbidden.
    assert head.commands == ["grip 64"]


async def test_repeated_adc_frame_cannot_confirm_twice(monkeypatch):
    async def instant(_seconds):
        pass
    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([
        (100, 1), (100, 2), (240, 3), *([(240, 3)] * 5),
    ])
    with pytest.raises(OperationError, match="No new jaw sample"):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    assert head.commands == ["grip 64", "grip 60"]


async def test_overforce_and_bad_baseline_fail_closed(monkeypatch):
    async def instant(_seconds):
        pass
    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 100, 800])
    with pytest.raises(OperationError, match="ceiling"):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    assert head.commands == ["grip 64", "grip 60"]
    head = FakeHead([100, 250])
    with pytest.raises(OperationError, match="baseline"):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    assert head.commands == []


@pytest.mark.parametrize("sign,opposite", [(1, 800), (-1, 1200)])
async def test_inverse_fsr_contact_does_not_continue_closing(monkeypatch, sign, opposite):
    async def instant(_seconds):
        pass
    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    class Calibrated(Settings):
        grip_force_sign = sign
    head = FakeHead([1000, 1000, opposite])
    with pytest.raises(OperationError, match="contradicts calibrated FSR polarity"):
        await guarded_grasp(head, Calibrated(), robot_id="robot-01", health=healthy)
    assert head.commands == ["grip 64", "grip 60"]


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

    # Overforce is the original failure. The subsequent body disarm must
    # prevent any attempted relief, not replace the overforce diagnosis.
    with pytest.raises(OperationError, match="force ceiling exceeded"):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=intermittent_health)
    assert calls >= 3
    assert head.commands == ["grip 64"]


async def test_uncertain_transport_failure_after_jaw_move_attempts_safe_relief(monkeypatch):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 101, 150])
    original = head.aux_status

    async def failing_adc():
        if "grip 64" in head.commands:
            raise OSError("ADC bus timed out after jaw movement")
        return await original()

    head.aux_status = failing_adc
    with pytest.raises(OSError, match="ADC bus timed out"):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    assert head.commands == ["grip 64", "grip 60"]


async def test_uncertain_transport_failure_does_not_override_local_disarm(monkeypatch):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 101])
    original = head.aux_status

    async def failing_adc():
        if "grip 64" in head.commands:
            raise OSError("ADC bus timed out")
        return await original()

    head.aux_status = failing_adc

    async def status():
        if head.commands:
            raise OperationError("WROOM disarmed")
        return {"armed": True}

    # The local health check disarms BEFORE another ADC read is permitted.
    # Do not manufacture an ADC timeout or send an unauthorized relief pulse.
    with pytest.raises(OperationError, match="WROOM disarmed"):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=status)
    assert head.commands == ["grip 64"]


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
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    assert head.commands == ["grip 64", "grip 60"]


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
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=disarmed_after_first_close)
    assert head.commands == ["grip 64"]


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
        if command == "grip 64":
            command_sent.set()
            await never_acknowledged.wait()

    head.command = interrupted_command
    task = asyncio.create_task(guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy))
    try:
        await asyncio.wait_for(command_sent.wait(), timeout=1)
        task.cancel()  # Real task cancellation, not manually raising the exception.
        with pytest.raises(asyncio.CancelledError):
            await task
        assert head.commands == ["grip 64", "grip 60"]
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
            guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy), timeout=0.5,
        )
    assert head.commands == (
        [] if phase == "before_first" else ["grip 64", "grip 60"]
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

    checks = 0

    async def disarmed():
        nonlocal checks
        checks += 1
        if checks >= 3:
            raise OperationError("WROOM local stop latched")
        return {"armed": True}

    with pytest.raises(OperationError, match="Lost fresh force sensor"):
        await asyncio.wait_for(
            guarded_grasp(head, Settings(), robot_id="robot-01", health=disarmed), timeout=0.5,
        )
    assert checks == 3
    assert head.commands == ["grip 64"]



async def test_hung_gripper_command_still_attempts_bounded_safe_relief(monkeypatch):
    """An unacknowledged jaw command may already have moved the servo."""
    import asyncio

    import desk_robot.grasp_feedback as feedback

    monkeypatch.setattr(feedback, "_GRIP_COMMAND_TIMEOUT_S", 0.04)
    monkeypatch.setattr(feedback, "_HEALTH_READ_TIMEOUT_S", 0.04)

    async def instant(_seconds):
        pass

    monkeypatch.setattr(feedback.asyncio, "sleep", instant)
    head = FakeHead([100, 101])
    entered = asyncio.Event()

    async def stalled_close(command):
        head.commands.append(command)
        if command == "grip 64":
            entered.set()
            await asyncio.Event().wait()

    head.command = stalled_close
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy), timeout=0.5,
        )
    assert entered.is_set()
    assert head.commands == ["grip 64", "grip 60"]


async def test_hung_safety_recheck_blocks_extra_grip_and_relief(monkeypatch):
    """No cached WROOM armed state is permission for another jaw command."""
    import asyncio

    import desk_robot.grasp_feedback as feedback

    monkeypatch.setattr(feedback, "_HEALTH_READ_TIMEOUT_S", 0.04)

    async def instant(_seconds):
        pass

    monkeypatch.setattr(feedback.asyncio, "sleep", instant)
    head = FakeHead([100, 101])
    checks = 0

    async def health():
        nonlocal checks
        checks += 1
        if checks >= 2:
            await asyncio.Event().wait()
        return {"armed": True}

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            guarded_grasp(head, Settings(), robot_id="robot-01", health=health), timeout=0.5,
        )
    assert checks == 3  # Before close, after close, attempted safe relief.
    assert head.commands == ["grip 64"]


async def test_jaw_hardware_sequence_wraps_without_falsely_rejecting_fresh_force(monkeypatch):
    """The WROOM uint32 hardware counter can wrap between real conversions."""
    async def instant(_seconds):
        pass
    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    # Zero is reserved as invalid; 0xffffffff -> 1 is still forward.
    head = FakeHead([
        (100, 0xfffffffe), (101, 0xffffffff),
        (130, 1), (240, 2), (245, 3),
    ])
    result = await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    assert result["contact_delta_raw"] >= Settings.grip_force_delta_raw
    assert head.commands == ["grip 64", "grip 68"]
    assert result["physical_acceptance_pass"] is False


@pytest.mark.parametrize("first,second", [
    (50, 49),              # Backwards, not a fresh hardware sample.
    (10, 10),              # Replayed same conversion.
    (1, 0x80000002),      # An ambiguous huge jump is not forward evidence.
])
async def test_jaw_baseline_rejects_replayed_or_backwards_sequence(
    monkeypatch, first, second,
):
    async def instant(_seconds):
        pass
    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    repeats = [(101, second)] * (4 if first == second else 0)
    head = FakeHead([(100, first), (101, second), *repeats])
    with pytest.raises(OperationError, match="No new ADS1115 jaw sample"):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    assert head.commands == []


async def test_jaw_after_movement_rejects_backwards_frame_and_relaxes(monkeypatch):
    async def instant(_seconds):
        pass
    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([(100, 100), (101, 101), (240, 100)])
    with pytest.raises(OperationError, match="No new jaw sample"):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    assert head.commands == ["grip 64", "grip 60"]


async def test_gripper_rejects_foreign_robot_force_before_any_pulse(monkeypatch):
    async def instant(_seconds):
        pass
    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)

    class ForeignHead(FakeHead):
        async def aux_status(self):
            reading = await super().aux_status()
            reading["robot_id"] = "robot-02"
            return reading

    head = ForeignHead([100, 101, 240])
    with pytest.raises(OperationError, match="Fresh force feedback"):
        await guarded_grasp(
            head, Settings(), robot_id="robot-01", health=healthy,
        )
    assert head.commands == []


async def test_gripper_foreign_robot_force_mid_close_triggers_guarded_relief(
    monkeypatch,
):
    async def instant(_seconds):
        pass
    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)

    class SwitchedHead(FakeHead):
        def __init__(self, samples):
            super().__init__(samples)
            self.reads = 0

        async def aux_status(self):
            self.reads += 1
            reading = await super().aux_status()
            reading["robot_id"] = ("robot-01" if self.reads <= 2
                                   else "robot-02")
            return reading

    head = SwitchedHead([100, 101, 240])
    with pytest.raises(OperationError, match="Lost fresh force sensor"):
        await guarded_grasp(
            head, Settings(), robot_id="robot-01", health=healthy,
        )
    assert head.commands == ["grip 64", "grip 60"]


async def test_gripper_cannot_wait_forever_for_uncooperative_force_adapter(
    monkeypatch,
):
    """A late ADC result after cancellation must never authorize jaw closure."""
    import asyncio

    import desk_robot.grasp_feedback as feedback

    monkeypatch.setattr(feedback, "_FORCE_READ_TIMEOUT_S", 0.04)
    entered = asyncio.Event()
    release = asyncio.Event()

    class StalledForceHead(FakeHead):
        async def aux_status(self):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
                return await super().aux_status()

    head = StalledForceHead([100])
    try:
        with pytest.raises(OperationError, match="Fresh force feedback required"):
            await asyncio.wait_for(
                guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy),
                timeout=0.5,
            )
        assert entered.is_set()
        assert head.commands == []
    finally:
        release.set()
        await asyncio.sleep(0)
    assert head.commands == []


@pytest.mark.parametrize("status", [
    {"armed": False},
    {"armed": True, "robot_id": "robot-02"},
    None,
])
async def test_gripper_rejects_disarmed_foreign_or_missing_health_verdict(
    monkeypatch, status,
):
    """A completed status callback is not permission to move the jaw."""
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 101, 240])

    async def unqualified_health():
        return status

    with pytest.raises(OperationError, match="WROOM health"):
        await guarded_grasp(
            head, Settings(), robot_id="robot-01", health=unqualified_health,
        )
    assert head.commands == []


async def test_gripper_disarm_response_after_jaw_close_never_reopens_unsafely(
    monkeypatch,
):
    """A false explicit WROOM verdict blocks both further pulses and relief."""
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 101, 240])
    calls = 0

    async def health_response():
        nonlocal calls
        calls += 1
        return {"armed": calls == 1, "robot_id": "robot-01"}

    with pytest.raises(OperationError, match="WROOM health"):
        await guarded_grasp(
            head, Settings(), robot_id="robot-01", health=health_response,
        )
    assert calls >= 3
    assert head.commands == ["grip 64"]


class BootEpochHead(FakeHead):
    """Two genuine conversion sequence values can belong to different boots."""

    def __init__(self, samples, boots):
        super().__init__(samples)
        self.boots = iter(boots)

    async def aux_status(self):
        reply = await super().aux_status()
        reply["force"]["boot_id"] = next(self.boots)
        return reply


async def test_reboot_near_uint32_wrap_never_authorizes_first_jaw_pulse(monkeypatch):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = BootEpochHead(
        [(100, 0xfffffffe), (101, 1)], boots=[8100, 8101],
    )
    with pytest.raises(OperationError, match="Fresh force feedback required"):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    assert head.commands == []


async def test_reboot_after_jaw_close_never_commands_second_pulse_or_relief(monkeypatch):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = BootEpochHead(
        [(100, 1), (101, 2), (240, 3)], boots=[9001, 9001, 9002],
    )
    with pytest.raises(OperationError, match="Lost fresh force sensor"):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    # The previous command could have actuated. A boot change invalidates
    # the old task, including any attempted relief on a different boot.
    assert head.commands == ["grip 64"]



@pytest.mark.parametrize("downgrade", [
    "missing_age", "missing_boot", "aged", "invalid_age_type",
    "invalid_boot_type", "out_of_range_boot",
])
async def test_grasp_refuses_missing_or_invalid_motion_provenance_before_pulse(
    monkeypatch, downgrade,
):
    """Valid force ADC plus sequence is not proof of a fresh same-boot reading."""
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)

    class DowngradedHead(FakeHead):
        async def aux_status(self):
            frame = await super().aux_status()
            force = frame["force"]
            if downgrade == "missing_age":
                del force["jaw_age_ms"]
            elif downgrade == "missing_boot":
                del force["boot_id"]
            elif downgrade == "aged":
                force["jaw_age_ms"] = 500
            elif downgrade == "invalid_age_type":
                force["jaw_age_ms"] = True
            elif downgrade == "invalid_boot_type":
                force["boot_id"] = True
            elif downgrade == "out_of_range_boot":
                force["boot_id"] = 0x100000000
            return frame

    head = DowngradedHead([100, 101, 240])
    with pytest.raises(OperationError, match="Fresh force feedback required"):
        await guarded_grasp(
            head, Settings(), robot_id="robot-01", health=healthy,
        )
    assert head.commands == []


@pytest.mark.parametrize("missing", ["jaw_age_ms", "boot_id"])
async def test_grasp_loses_required_provenance_after_first_pulse(
    monkeypatch, missing,
):
    """Downgraded firmware cannot trigger a second jaw closing pulse."""
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)

    class MidGraspDowngrade(FakeHead):
        async def aux_status(self):
            frame = await super().aux_status()
            if self.seq >= 3:
                frame["force"].pop(missing)
            return frame

    head = MidGraspDowngrade([100, 101, 240])
    with pytest.raises(OperationError, match="Lost fresh force sensor"):
        await guarded_grasp(
            head, Settings(), robot_id="robot-01", health=healthy,
        )
    # Without a verified boot identity, even a relief command is unsafe.
    assert head.commands == (
        ["grip 64"] if missing == "boot_id" else ["grip 64", "grip 60"]
    )


@pytest.mark.parametrize("when", ["before_first", "after_first_close"])
@pytest.mark.parametrize("invalid_boot", [None, 0, 9002, True])
async def test_compound_wroom_epoch_and_jaw_fault_blocks_all_followup_commands(
    monkeypatch, when, invalid_boot,
):
    """A bad jaw field must not hide a reset and authorize servo relief."""
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)

    class CompoundFault(FakeHead):
        async def aux_status(self):
            frame = await super().aux_status()
            if when == "before_first" or self.seq >= 3:
                group = frame["force"]
                group["jaw_valid"] = False
                if invalid_boot is None:
                    group.pop("boot_id")
                else:
                    group["boot_id"] = invalid_boot
            return frame

    head = CompoundFault([100, 101, 240])
    expected = ("Fresh force feedback required"
                if when == "before_first" else "Lost fresh force sensor")
    with pytest.raises(OperationError, match=expected):
        await guarded_grasp(
            head, Settings(), robot_id="robot-01", health=healthy,
        )
    # WROOM identity cannot be trusted even if another health adapter is armed.
    assert head.commands == ([] if when == "before_first" else ["grip 64"])


async def test_grasp_waits_for_real_mux_jaw_conversion_instead_of_aborting(
    monkeypatch,
):
    """Cached same-boot jaw samples are normal before the next mux cycle."""
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([
        (100, 1), (100, 1), (101, 2),
        (101, 2), (240, 3),
        (240, 3), (245, 4),
    ])
    result = await guarded_grasp(
        head, Settings(), robot_id="robot-01", health=healthy,
    )
    assert head.commands == ["grip 64"]
    assert result["contact_delta_raw"] >= Settings.grip_force_delta_raw
    assert result["physical_acceptance_pass"] is False


async def test_stalled_jaw_after_close_cannot_authorize_another_pulse(
    monkeypatch,
):
    """A valid cached ADC value is not a new force conversion."""
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([
        (100, 1), (101, 2), *([(101, 2)] * 5),
    ])
    with pytest.raises(OperationError, match="No new jaw sample"):
        await guarded_grasp(
            head, Settings(), robot_id="robot-01", health=healthy,
        )
    assert head.commands == ["grip 64", "grip 60"]


async def test_delayed_jaw_sample_does_not_override_local_disarm(monkeypatch):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([(100, 1), (101, 2), (101, 2), (240, 3)])
    checks = 0

    async def disarm_on_retry():
        nonlocal checks
        checks += 1
        return {"armed": checks < 3, "robot_id": "robot-01"}

    with pytest.raises(OperationError, match="WROOM health"):
        await guarded_grasp(
            head, Settings(), robot_id="robot-01", health=disarm_on_retry,
        )
    assert head.commands == ["grip 64"]


@pytest.mark.parametrize("downgrade", ["missing", "false", "string"])
@pytest.mark.parametrize("when", ["before_first", "after_first_close"])
async def test_grasp_requires_independent_jaw_valid_at_motion_boundary(
    monkeypatch, downgrade, when,
):
    """Composite force.valid cannot stand in for a channel-valid ADC verdict."""
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)

    class DowngradedJaw(FakeHead):
        async def aux_status(self):
            frame = await super().aux_status()
            if when == "before_first" or self.seq >= 3:
                if downgrade == "missing":
                    frame["force"].pop("jaw_valid")
                else:
                    frame["force"]["jaw_valid"] = (
                        False if downgrade == "false" else "true"
                    )
            return frame

    head = DowngradedJaw([100, 101, 240])
    expected = ("Fresh force feedback required"
                if when == "before_first" else "Lost fresh force sensor")
    with pytest.raises(OperationError, match=expected):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    # A failed acquired sample cannot permit a second closing command.
    # Only an independently confirmed still-armed WROOM can allow relief.
    assert head.commands == (
        [] if when == "before_first" else ["grip 64", "grip 60"]
    )


async def test_invalid_jaw_valid_after_close_cannot_relieve_disarmed_body(monkeypatch):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)

    class LostJaw(FakeHead):
        async def aux_status(self):
            frame = await super().aux_status()
            if self.seq >= 3:
                frame["force"].pop("jaw_valid")
            return frame

    head = LostJaw([100, 101, 240])

    checks = 0

    async def health():
        nonlocal checks
        checks += 1
        return {"armed": checks < 3, "robot_id": "robot-01"}

    with pytest.raises(OperationError, match="Lost fresh force sensor"):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=health)
    assert head.commands == ["grip 64"]


@pytest.mark.parametrize("when", ["before_first", "after_first_close"])
async def test_zero_boot_epoch_never_authorizes_jaw_command_or_relief(
    monkeypatch, when,
):
    """An uninitialized WROOM identity cannot authorize servo movement."""
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    boots = [0, 0, 0] if when == "before_first" else [5103, 5103, 0]
    head = BootEpochHead([100, 101, 240], boots=boots)
    expected = ("Fresh force feedback required"
                if when == "before_first" else "Lost fresh force sensor")
    with pytest.raises(OperationError, match=expected):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    # No cross-boot relief even if a stale health adapter still says armed.
    assert head.commands == ([] if when == "before_first" else ["grip 64"])


@pytest.mark.parametrize("when", ["before_close", "after_close"])
@pytest.mark.parametrize("health_boot", [None, 0, True, 5104])
async def test_armed_health_boot_must_match_jaw_boot_before_servo_motion(
    monkeypatch, when, health_boot,
):
    """A fresh armed verdict from a new or unknown boot cannot use old ADC."""
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 101, 240])
    checks = 0

    async def mixed_epoch_health():
        nonlocal checks
        checks += 1
        # A first jaw command may have happened before the body rebooted.
        observed = (5103 if when == "after_close" and checks == 1
                    else health_boot)
        imu = {} if observed is None else {"boot_id": observed}
        return {"armed": True, "robot_id": "robot-01", "imu": imu}

    with pytest.raises(OperationError, match="WROOM health boot"):
        await guarded_grasp(
            head, Settings(), robot_id="robot-01", health=mixed_epoch_health,
        )
    assert head.commands == ([] if when == "before_close" else ["grip 64"])


async def test_matching_wroom_health_and_jaw_boot_allows_bounded_grasp(monkeypatch):
    """The real same-boot status path must retain the calibrated jaw sequence."""
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 101, 130, 240, 245])

    async def current_wroom_health():
        return {"armed": True, "robot_id": "robot-01", "imu": {"boot_id": 5103}}

    result = await guarded_grasp(
        head, Settings(), robot_id="robot-01", health=current_wroom_health,
    )
    assert result["physical_acceptance_pass"] is False
    assert head.commands == ["grip 64", "grip 68"]

@pytest.mark.parametrize("bad_ack", [
    {"ok": False, "robot_id": "robot-01", "reply": "ERR grip rejected"},
    {"ok": True, "robot_id": "robot-02", "reply": "OK grip angle=64"},
    {"ok": True, "robot_id": "robot-01", "reply": "OK grip angle=68"},
    {"ok": "true", "robot_id": "robot-01", "reply": "OK grip angle=64"},
    "OK grip angle=64",
])
async def test_grasp_rejects_explicit_bad_command_ack_before_more_closing(
    monkeypatch, bad_ack,
):
    """A returned failure is not physical servo completion or force contact."""
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 101, 240, 245])

    async def rejected_command(command):
        head.commands.append(command)
        if command == "grip 64":
            return bad_ack
        return {
            "ok": True, "robot_id": "robot-01",
            "reply": "OK grip angle=60",
        }

    head.command = rejected_command
    with pytest.raises(OperationError, match="Unmatched gripper command ACK"):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    # The uncertain first pulse gets only one health-gated relief attempt.
    # No second closing pulse and no fabricated contact receipt are allowed.
    assert head.commands == ["grip 64", "grip 60"]


async def test_grasp_accepts_exact_structured_head_command_ack(monkeypatch):
    """The normal authenticated command reply remains usable."""
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 101, 130, 240, 245])

    async def acknowledged_command(command):
        head.commands.append(command)
        return {
            "ok": True,
            "robot_id": "robot-01",
            "reply": f"OK grip angle={int(command.split()[1])}",
        }

    head.command = acknowledged_command
    result = await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    assert result["contact_delta_raw"] >= 120
    assert result["physical_acceptance_pass"] is False
    assert head.commands == ["grip 64", "grip 68"]


async def test_contact_at_final_angle_can_be_confirmed_without_another_pulse(monkeypatch):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)

    class OneStep(Settings):
        grip_closed = 64

    head = FakeHead([100, 100, 240, 245])
    result = await guarded_grasp(head, OneStep(), robot_id="robot-01", health=healthy)
    assert result["commanded_angle"] == 64
    assert head.commands == ["grip 64"]
    assert result["physical_acceptance_pass"] is False


async def test_contact_confirmation_overforce_relaxes_without_more_closure(monkeypatch):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 100, 240, 800])
    with pytest.raises(OperationError, match="force ceiling exceeded"):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    assert head.commands == ["grip 64", "grip 60"]


async def test_transient_contact_requires_two_fresh_samples_at_one_angle(monkeypatch):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)
    head = FakeHead([100, 100, 240, 101, 240, 245])
    result = await guarded_grasp(head, Settings(), robot_id="robot-01", health=healthy)
    assert result["commanded_angle"] == 68
    assert head.commands == ["grip 64", "grip 68"]


@pytest.mark.parametrize("expire_after_close", [False, True])
async def test_jaw_evidence_must_still_be_fresh_at_closing_dispatch(
    monkeypatch, expire_after_close,
):
    """A slow health check cannot spend an expired ADC observation."""
    from types import SimpleNamespace

    import desk_robot.grasp_feedback as feedback

    clock = 100.0

    async def instant(_seconds):
        pass

    monkeypatch.setattr(feedback.asyncio, "sleep", instant)
    monkeypatch.setattr(feedback, "time", SimpleNamespace(monotonic=lambda: clock))

    class AgingJaw(FakeHead):
        async def aux_status(self):
            reply = await super().aux_status()
            if self.seq == (3 if expire_after_close else 2):
                reply["force"]["jaw_age_ms"] = 400
            return reply

    head = AgingJaw([100, 100, 130, 240, 245])
    checks = 0

    async def slow_health():
        nonlocal clock, checks
        checks += 1
        if checks == (3 if expire_after_close else 1):
            clock += 0.15
        return {"armed": True, "robot_id": "robot-01", "imu": {"boot_id": 5103}}

    with pytest.raises(OperationError, match="expired before closing dispatch"):
        await guarded_grasp(head, Settings(), robot_id="robot-01", health=slow_health)
    assert head.commands == (["grip 64", "grip 60"] if expire_after_close else [])


@pytest.mark.parametrize("sign", [-1, 1])
@pytest.mark.parametrize("ceiling_first", [False, True])
async def test_exclusive_force_ceiling(monkeypatch, sign, ceiling_first):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)

    class Calibrated(Settings):
        grip_force_sign = sign

    baseline = 1000
    ceiling = baseline + sign * 500
    contact = baseline + sign * 499
    readings = [ceiling, contact] if ceiling_first else [contact, ceiling]
    head = FakeHead([baseline, baseline, *readings])
    with pytest.raises(OperationError, match="force ceiling exceeded"):
        await guarded_grasp(head, Calibrated(), robot_id="robot-01", health=healthy)
    assert head.commands == ["grip 64", "grip 60"]


@pytest.mark.parametrize("sign", [-1, 1])
async def test_one_below_ceiling_is_tactile_only(monkeypatch, sign):
    async def instant(_seconds):
        pass

    monkeypatch.setattr("desk_robot.grasp_feedback.asyncio.sleep", instant)

    class Calibrated(Settings):
        grip_force_sign = sign

    head = FakeHead([1000, 1000, 1000 + sign * 499, 1000 + sign * 499])
    result = await guarded_grasp(head, Calibrated(), robot_id="robot-01", health=healthy)
    assert result["contact_delta_raw"] == 499
    assert result["physical_acceptance_pass"] is False
    assert head.commands == ["grip 64"]
