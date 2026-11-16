import asyncio
import time

import pytest
from desk_robot.controller import Coordinator, OperationError
from desk_robot.simulator import SimulatedHead, SimulationVision


def make(settings):
    head = SimulatedHead("robot-01")
    heads = {"robot-01": head, "robot-02": SimulatedHead("robot-02")}
    return Coordinator(settings, heads, SimulationVision()), head


async def test_permit_is_operator_only_one_use_per_robot(settings):
    c, head = make(settings)
    try:
        with pytest.raises(OperationError, match="permit"):
            c.manual("robot-01", "drive 20 20 100")
        permit = await c.operator_arm("robot-01")
        assert not permit["physical_armed"] and head.commands == []
        with pytest.raises(OperationError, match="permit"):
            c.manual("robot-02", "drive 20 20 100")
        job = c.manual("robot-01", "drive 20 20 100")
        await c.tasks[job.id]
        assert job.state == "succeeded"
        assert head.commands[0] == "arm" and head.commands[-1] == "stop"
        assert head.commands.count("drive 20 20 100") == 1
        with pytest.raises(OperationError, match="permit"):
            c.manual("robot-01", "drive 20 20 100")
    finally:
        await c.close()


async def test_two_argument_drive_uses_firmware_default_duration(settings):
    c, head = make(settings)
    try:
        await c.operator_arm("robot-01")
        job = c.manual("robot-01", "drive 20 20")
        await c.tasks[job.id]
        assert job.state == "succeeded", job.error
        assert head.commands.count("drive 20 20") == 1
        assert head.commands[-1] == "stop"
        # This was once a post-command IndexError in the Mac coordinator.
        assert not any("IndexError" in event for event in job.events)
    finally:
        await c.close()


async def test_permit_expiry_motion_default_and_simulation_calibration(settings):
    c, head = make(settings)
    settings.robots[0].motion_enabled = False
    with pytest.raises(OperationError, match="motion_enabled"):
        await c.operator_arm("robot-01")
    settings.robots[0].motion_enabled = True
    c.permits["robot-01"] = time.monotonic() - 1
    with pytest.raises(OperationError, match="expired"):
        c.manual("robot-01", "lift 90")
    settings.mode = "hardware"
    with pytest.raises(OperationError, match="Simulation calibration"):
        c.pickup("robot-01", "key")
    assert head.commands == []


@pytest.mark.parametrize("failure", ["drive", "keepalive"])
async def test_uncertain_commands_not_retried_and_stop_finally(settings, failure):
    c, head = make(settings)
    head.fail_command = failure
    try:
        await c.operator_arm("robot-01")
        job = c.manual("robot-01", "drive 20 20 100")
        await c.tasks[job.id]
        assert job.state == "failed"
        assert head.commands[-1] == "stop"
        assert head.commands.count("drive 20 20 100") <= 1
    finally:
        await c.close()


async def test_cancel_queued_job_can_enable_next_job(settings):
    c, head = make(settings)
    try:
        await c.operator_arm("robot-01")
        job = c.manual("robot-01", "lift 110")
        await c.stop("robot-01")
        assert job.state == "cancelled"
        await c.operator_arm("robot-01")
        next_job = c.manual("robot-01", "drive 0 0 1")
        await c.tasks[next_job.id]
        assert next_job.state == "succeeded"
    finally:
        await c.close()


async def test_deadline_cancels_work_and_stop(settings):
    settings.max_job_seconds = 1
    c, head = make(settings)
    try:
        await c.operator_arm("robot-01")
        job = c.manual("robot-01", "lift 110")
        await c.tasks[job.id]
        assert job.state == "failed" and head.commands[-1] == "stop"
    finally:
        await c.close()


async def test_simulated_closed_loop_pickup_is_not_acceptance(settings):
    c, head = make(settings)
    try:
        await c.operator_arm("robot-01")
        job = c.pickup("robot-01", "key")
        await c.tasks[job.id]
        assert job.state == "succeeded", job.error
        assert job.result["visually_verified"]
        assert job.result["placed_visually_verified"]
        assert job.result["physical_acceptance_pass"] is False
        assert any(s.startswith("drive ") for s in head.commands)
        assert head.commands.count("grip 60") == 2  # initial opening and final release
        assert head.commands.count("lift 110") == 2  # held object, then jaw withdrawal
        assert head.commands.index("grip 110") < head.commands.index("lift 110")
        assert head.commands[-1] == "stop"
    finally:
        await c.close()


@pytest.mark.parametrize("fault", ["lost", "camera", "not_lifted"])
async def test_pickup_failures_stop(settings, fault):
    c, head = make(settings)
    if fault == "lost":
        head.show_target = False
    elif fault == "camera":
        head.fail_snapshot = True
    else:
        original = head.command

        async def no_lift(command):
            result = await original(command)
            head.lifted = False
            return result

        head.command = no_lift
    try:
        await c.operator_arm("robot-01")
        job = c.pickup("robot-01", "candy")
        await c.tasks[job.id]
        assert job.state == "failed" and head.commands[-1] == "stop"
        assert job.result is None
    finally:
        await c.close()


@pytest.mark.parametrize("fault", ["vanished_on_release", "stuck_in_jaws"])
async def test_pickup_does_not_report_success_without_verified_placement(settings, fault):
    c, head = make(settings)
    original = head.command
    openings = 0

    async def faulty_placement(command):
        nonlocal openings
        result = await original(command)
        if command == "grip 60":
            openings += 1
            if openings == 2 and fault == "vanished_on_release":
                head.show_target = False
        if command == "lift 110" and openings == 2 and fault == "stuck_in_jaws":
            head.lifted = True
        return result

    head.command = faulty_placement
    try:
        await c.operator_arm("robot-01")
        job = c.pickup("robot-01", "key")
        await c.tasks[job.id]
        assert openings == 2
        assert job.state == "failed"
        assert job.result is None
        assert head.commands[-1] == "stop"
    finally:
        await c.close()


async def test_real_pickup_rejects_sub_three_second_hold(settings, tmp_path):
    import json

    original = settings.robots[0].calibration.read_text()
    config = json.loads(original)
    config["simulation_only"] = False
    config["hold_seconds"] = 0.5
    measured = tmp_path / "measured.json"
    measured.write_text(json.dumps(config))
    settings.mode = "hardware"
    settings.robots[0].calibration = measured
    c, head = make(settings)
    try:
        # Pickup validates physical hold time before consuming a motion permit,
        # so no synthetic body preflight or arm is needed for this rejection.
        with pytest.raises(OperationError, match="three seconds"):
            c.pickup("robot-01", "key")
        assert head.commands == []
    finally:
        await c.close()


async def test_emergency_stop_reaches_body_before_blocking_job_cleanup(settings):
    from desk_robot.controller import Job

    c, head = make(settings)
    stalled = asyncio.Event()
    entered = asyncio.Event()
    stop_sent = asyncio.Event()

    class ObservedHead(SimulatedHead):
        async def command(self, command):
            if command == "stop":
                stop_sent.set()
            return await super().command(command)

    c.heads["robot-01"] = ObservedHead("robot-01")

    async def cannot_cancel_quickly():
        entered.set()
        try:
            await asyncio.sleep(99)
        except asyncio.CancelledError:
            await stalled.wait()

    task = asyncio.create_task(cannot_cancel_quickly())
    job = Job("blocked-cleanup", "robot-01", "exploration", state="running")
    c.jobs[job.id], c.tasks[job.id] = job, task
    await asyncio.wait_for(entered.wait(), timeout=0.3)
    stopping = asyncio.create_task(c.stop("robot-01"))
    try:
        await asyncio.wait_for(stop_sent.wait(), timeout=0.2)
        assert not task.done()
        assert "robot-01" not in c.permits
    finally:
        stalled.set()
        await asyncio.wait_for(stopping, timeout=1)
        await c.close()
    assert job.state == "cancelled"


async def test_cancel_running_job_stops_and_ends_keepalive(settings):
    c, head = make(settings)
    try:
        await c.operator_arm("robot-01")
        job = c.manual("robot-01", "lift 110")
        await asyncio.sleep(0.05)
        await c.stop("robot-01")
        assert job.state == "cancelled"
        count = len(head.commands)
        await asyncio.sleep(0.15)
        assert len(head.commands) == count
    finally:
        await c.close()

class HardwareStatusHead(SimulatedHead):
    """A simulated status transport, never a physical sensor or safety proof."""

    def __init__(self, robot_id):
        super().__init__(robot_id)
        self.body_status = {
            "robot_id": robot_id,
            "backend": "stepper_28byj48",
            "armed": False,
            "imu": {"family": 1, "gyro_id": 212, "aux_id": 73, "valid": True,
                    "acc": [0, 0, 16384], "gyro": [0, 0, 0], "age_ms": 20},
            "touch": {"active": False, "count": 0},
            "safety": {"required": True, "ready": True, "fault": "none"},
            "ranges": {
                "mm": [50, 50, 50, 50, 200],
                "age_ms": [10, 10, 10, 10, 10],
                "present_mask": 31,
                "valid_mask": 31,
            },
        }

    async def status(self):
        return self.body_status


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("backend", "dc_pwm"),
        ("robot_id", "robot-02"),
        ("armed", True),
        ("imu", {"family": 0, "valid": True, "acc": [0, 0, 16384],
                 "gyro": [0, 0, 0], "age_ms": 0}),
        ("imu", {"family": 1, "valid": False, "acc": [0, 0, 16384],
                 "gyro": [0, 0, 0], "age_ms": 0}),
        ("imu", {"family": 1, "valid": True, "acc": [0, 0, 16384],
                 "gyro": [0, 0, 0], "age_ms": 201}),
        ("imu", {"family": 1, "valid": True, "acc": [0, 0, 16384],
                 "gyro": [0, 0], "age_ms": 10}),
        ("touch", {"active": True}),
        ("touch", {}),
        ("safety", {"required": True, "ready": False, "fault": "stale_sample"}),
        ("ranges", {}),
        ("ranges", {"mm": [50] * 5, "age_ms": [0] * 5,
                    "present_mask": 31, "valid_mask": True}),
        ("ranges", {"mm": [50] * 5, "age_ms": [0] * 5,
                    "present_mask": 15, "valid_mask": 31}),
        ("ranges", {"mm": [50] * 5, "age_ms": [200] * 5,
                    "present_mask": 31, "valid_mask": 31}),
        ("ranges", {"mm": [0] * 5, "age_ms": [0] * 5,
                    "present_mask": 31, "valid_mask": 31}),
    ],
)
async def test_hardware_enable_fails_closed_on_unqualified_body_status(
    settings, field, replacement
):
    settings.mode = "hardware"
    head = HardwareStatusHead("robot-01")
    head.body_status[field] = replacement
    coordinator = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        with pytest.raises(OperationError, match="Hardware preflight"):
            await coordinator.operator_arm("robot-01")
        assert "robot-01" not in coordinator.permits
        assert head.commands == []
    finally:
        await coordinator.close()


async def test_hardware_motion_requires_new_safety_status_at_execution(settings):
    settings.mode = "hardware"
    head = HardwareStatusHead("robot-01")
    coordinator = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        permit = await coordinator.operator_arm("robot-01")
        assert permit["operator_permit"] and head.commands == []
        # Touch happens after the operator allows the job but before it runs.
        head.body_status["touch"]["active"] = True
        job = coordinator.manual("robot-01", "drive 20 20 100")
        await coordinator.tasks[job.id]
        assert job.state == "failed"
        assert "Hardware preflight" in job.error
        assert "arm" not in head.commands
        assert not any(cmd.startswith("drive") for cmd in head.commands)
        assert head.commands[-1] == "stop"
        assert "robot-01" not in coordinator.permits
    finally:
        await coordinator.close()


async def test_hardware_motion_permitted_only_when_all_status_fields_clear(settings):
    settings.mode = "hardware"
    head = HardwareStatusHead("robot-01")
    coordinator = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        await coordinator.operator_arm("robot-01")
        job = coordinator.manual("robot-01", "drive 0 0 10")
        await coordinator.tasks[job.id]
        assert job.state == "succeeded", job.error
        assert head.commands[0] == "arm"
        assert head.commands[-1] == "stop"
        assert head.commands.count("drive 0 0 10") == 1
    finally:
        await coordinator.close()


async def test_exploration_persists_under_one_permit_until_explicit_stop(settings):
    c, head = make(settings)
    settings.max_job_seconds = 1
    try:
        with pytest.raises(OperationError, match="permit"):
            c.explore("robot-01")
        await c.operator_arm("robot-01")
        job = c.explore("robot-01")
        async with asyncio.timeout(4):
            while head.commands.count("drive 20 20 100") < 3:
                await asyncio.sleep(.01)
        assert job.state == "running"
        async with asyncio.timeout(2):
            while head.commands.count("stop") < 3:
                await asyncio.sleep(.01)
        assert head.commands.count("stop") >= 3
        assert head.commands.count("arm") == 1
        assert c.tasks[job.id].done() is False
        await c.stop("robot-01")
        assert job.state == "cancelled"
        assert head.commands[-1] == "stop"
        assert c.permits.get("robot-01") is None
    finally:
        await c.close()


async def test_exploration_drops_on_body_disarm_and_never_rearms(settings):
    c, head = make(settings)
    await c.operator_arm("robot-01")
    original = head.status
    calls = 0
    async def status():
        nonlocal calls
        calls += 1
        data = await original()
        if calls >= 2:
            data["armed"] = False
        return data
    head.status = status
    try:
        job = c.explore("robot-01")
        await asyncio.wait_for(c.tasks[job.id], 4)
        assert job.state == "failed"
        assert "disarmed" in job.error
        assert head.commands.count("arm") == 1
        assert head.commands[-1] == "stop"
    finally:
        await c.close()


async def test_exploration_rechecks_body_after_slow_camera_before_drive(settings):
    """A new cliff fault after a JPEG must stop the robot without a pulse."""
    c, head = make(settings)
    old_snapshot = head.snapshot

    async def disarm_during_camera():
        image = await old_snapshot()
        head.armed = False
        return image

    head.snapshot = disarm_during_camera
    try:
        await c.operator_arm("robot-01")
        job = c.explore("robot-01")
        await asyncio.wait_for(c.tasks[job.id], timeout=4)
        assert job.state == "failed"
        assert "disarmed" in job.error
        assert not any(cmd.startswith("drive ") for cmd in head.commands)
        assert head.commands[-1] == "stop"
    finally:
        await c.close()


async def test_exploration_camera_hang_expires_before_any_drive(settings):
    c, head = make(settings)

    async def hung_camera():
        await asyncio.sleep(30)

    head.snapshot = hung_camera
    try:
        await c.operator_arm("robot-01")
        job = c.explore("robot-01")
        await asyncio.wait_for(c.tasks[job.id], timeout=4)
        assert job.state == "failed"
        assert "timeout" in (job.error or "").lower()
        assert not any(cmd.startswith("drive ") for cmd in head.commands)
        assert head.commands[-1] == "stop"
    finally:
        await c.close()


async def test_hardware_exploration_requires_real_swept_path_qualification(settings):
    c, head = make(settings)
    settings.mode = "hardware"
    try:
        with pytest.raises(OperationError, match="swept-path"):
            c.explore("robot-01")
        assert head.commands == []
    finally:
        await c.close()


async def test_pickup_cancels_before_grip_when_body_loses_arm_mid_alignment(settings):
    c, head = make(settings)
    original = head.status
    polls = 0
    async def fail_status():
        nonlocal polls
        polls += 1
        status = await original()
        if polls >= 3:
            status["armed"] = False
        return status
    head.status = fail_status
    try:
        await c.operator_arm("robot-01")
        job = c.pickup("robot-01", "key")
        await asyncio.wait_for(c.tasks[job.id], 5)
        assert job.state == "failed" and "disarmed" in job.error
        assert "grip 110" not in head.commands
        assert head.commands[-1] == "stop"
        assert head.commands.count("arm") == 1
    finally:
        await c.close()


async def test_shared_body_armed_health_checks_do_not_assume_front_camera_safety(settings):
    c, head = make(settings)
    settings.mode = "hardware"
    try:
        head.armed = True
        head.last_control = time.monotonic()
        async def status():
            return {
                "robot_id": "robot-01",
                "armed": True,
                "safety": {"required": True, "ready": True, "fault": "none"},
                "ranges": {"mm": [30, 30, 30, 30, 220],
                           "age_ms": [5, 5, 5, 5, 5],
                           "present_mask": 31, "valid_mask": 31},
                "imu": {"valid": True, "age_ms": 30},
                "touch": {"active": False},
            }
        head.status = status
        await c._assert_armed_health("robot-01")  # pickup may face target
        with pytest.raises(OperationError, match="sensor or corridor"):
            await c._assert_armed_health("robot-01", require_front_clearance=True)
        async def fault_status():
            body = await status()
            body["safety"]["fault"] = "front_obstacle"
            return body
        head.status = fault_status
        with pytest.raises(OperationError, match="sensor"):
            await c._assert_armed_health("robot-01")
    finally:
        await c.close()


async def test_pickup_never_drives_using_safety_from_before_slow_vision(settings):
    """Body disarmed during first camera read: no movement based on old status."""
    coordinator, head = make(settings)
    original_snapshot = head.snapshot

    async def loss_during_image():
        image = await original_snapshot()
        # A real WROOM could latch cliff/touch safety during YOLO inference.
        # The mock disarm happens after the previously healthy status check.
        head.armed = False
        return image

    head.snapshot = loss_during_image
    try:
        await coordinator.operator_arm("robot-01")
        job = coordinator.pickup("robot-01", "key")
        await coordinator.tasks[job.id]
        assert job.state == "failed"
        assert job.result is None
        assert all(not command.startswith("drive ") for command in head.commands)
        assert head.commands[-1] == "stop"
    finally:
        await coordinator.close()


async def test_pickup_never_drives_if_wroom_faults_during_object_detector(settings):
    """YOLO inference cannot reuse the safety response from its first frame."""
    c, head = make(settings)
    original_detect = c.vision.detect

    async def disarm_during_detector(image, label):
        result = await original_detect(image, label)
        head.armed = False
        return result

    c.vision.detect = disarm_during_detector
    try:
        await c.operator_arm("robot-01")
        job = c.pickup("robot-01", "candy")
        await c.tasks[job.id]
        assert job.state == "failed"
        assert job.result is None
        assert all(not line.startswith("drive ") for line in head.commands)
        assert head.commands[-1] == "stop"
    finally:
        await c.close()


@pytest.mark.parametrize("bad_frame", [
    None, b"", b"<html>camera unavailable</html>",
    b"\xff\xd8incomplete", b"incomplete\xff\xd9",
    b"\xff\xd8" + b"x" * 512001 + b"\xff\xd9",
])
async def test_exploration_refuses_invalid_camera_before_any_drive(settings, bad_frame):
    c, head = make(settings)

    async def invalid_camera():
        return bad_frame

    head.snapshot = invalid_camera
    try:
        await c.operator_arm("robot-01")
        job = c.explore("robot-01")
        await asyncio.wait_for(c.tasks[job.id], timeout=4)
        assert job.state == "failed"
        assert "invalid JPEG" in (job.error or "")
        assert not any(cmd.startswith("drive ") for cmd in head.commands)
        assert head.commands[-1] == "stop"
    finally:
        await c.close()


async def test_exploration_stops_after_corrupted_post_drive_camera(settings):
    c, head = make(settings)
    original = head.snapshot
    calls = 0

    async def camera_then_corruption():
        nonlocal calls
        calls += 1
        return await original() if calls == 1 else b"<html>camera fault</html>"

    head.snapshot = camera_then_corruption
    try:
        await c.operator_arm("robot-01")
        job = c.explore("robot-01")
        await asyncio.wait_for(c.tasks[job.id], timeout=4)
        assert job.state == "failed"
        assert "invalid JPEG" in (job.error or "")
        assert head.commands.count("drive 20 20 100") == 1
        assert head.commands[-1] == "stop"
    finally:
        await c.close()


@pytest.mark.parametrize("reported_id", [None, "", "robot-02", 1])
async def test_hardware_running_health_rechecks_body_identity(settings, reported_id):
    """A preflight on this robot never authorizes later foreign WROOM status."""
    settings.mode = "hardware"
    head = HardwareStatusHead("robot-01")
    coordinator = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        head.body_status["armed"] = True
        head.body_status["ranges"]["mm"][4] = 300
        head.body_status["robot_id"] = reported_id
        with pytest.raises(OperationError, match="body identity mismatch"):
            await coordinator._assert_armed_health(
                "robot-01", require_front_clearance=True
            )
        assert head.commands == []
    finally:
        await coordinator.close()
