import asyncio
import time
from types import SimpleNamespace

import pytest
from desk_robot.controller import Coordinator, Job, OperationError
from desk_robot.simulator import SimulatedHead, SimulationVision


@pytest.fixture(autouse=True)
def selected_motor_backend_for_host_tests(settings):
    # Host fakes simulate a builder who verified the assembled motor driver.
    # Production config deliberately defaults to no motor profile grant.
    for robot in settings.robots:
        robot.motor_backend = "stepper_28byj48"


def make(settings):
    head = SimulatedHead("robot-01")
    heads = {"robot-01": head, "robot-02": SimulatedHead("robot-02")}
    return Coordinator(settings, heads, SimulationVision()), head


async def test_slow_pickup_visual_result_expires_without_motion(settings):
    """A correct but old YOLO box cannot become a fresh motor decision."""
    from desk_robot.calibration import Calibration
    from desk_robot.vision import Detection

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    c, head = make(settings)
    jpeg = await head.snapshot()
    c.multimodal = SimpleNamespace(
        settings=settings,
        stream_owns_camera=lambda _id: True,
        status=lambda _id: {"camera_stream_connected": True},
        hub=SimpleNamespace(frames={"robot-01": [SimpleNamespace(
            source="proactive", jpeg=jpeg, received_at=time.monotonic()
        )]}),
    )

    class DelayedDetection:
        async def detect(self, jpeg, target):
            await asyncio.sleep(2.05)
            return [Detection(target, 0.99, (50.0, 50.0, 70.0, 70.0))]

    c.vision = DelayedDetection()
    calibration = Calibration.load(settings.robots[0].calibration)
    try:
        with pytest.raises(OperationError, match="visual evidence expired"):
            await c._observe("robot-01", "key", calibration)
        assert not any(cmd.startswith(("drive ", "grip ", "lift "))
                       for cmd in head.commands)
    finally:
        await c.close()


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
        assert head.commands[0] == "arm" and head.commands[-1] == "halt"
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
        assert head.commands[-1] == "halt"
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
        assert head.commands[-1] == "halt"
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
        assert job.state == "failed" and head.commands[-1] == "halt"
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
        assert head.commands[-1] == "halt"
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
        assert job.state == "failed" and head.commands[-1] == "halt"
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
        assert head.commands[-1] == "halt"
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
            if command == "halt":
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
        ("power", {"fuel_valid": True, "cell_mv": 3200, "soc_centi": 400}),
        ("power", {"fuel_valid": True, "cell_mv": 3800, "soc_centi": 200}),
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


@pytest.mark.parametrize("power", [
    {"fuel_valid": True, "cell_mv": "0", "soc_centi": None},
    {"fuel_valid": True, "cell_mv": True, "soc_centi": 7000},
    {"fuel_valid": True, "cell_mv": 3800, "soc_centi": False},
    {"fuel_valid": True, "cell_mv": None, "soc_centi": 7000},
    {"fuel_valid": True, "cell_mv": 3800},
    {"fuel_valid": True, "soc_centi": 7000},
    {"fuel_valid": True, "cell_mv": 2499, "soc_centi": 7000},
    {"fuel_valid": True, "cell_mv": 4501, "soc_centi": 7000},
    {"fuel_valid": True, "cell_mv": 3800, "soc_centi": -1},
    {"fuel_valid": True, "cell_mv": 3800, "soc_centi": 10001},
    {"fuel_valid": "true", "cell_mv": 3800, "soc_centi": 7000},
    {"cell_mv": 3800, "soc_centi": 7000},
    "unexpected string",
])
async def test_valid_claimed_fuel_requires_typed_physical_range_in_both_paths(
    settings, power,
):
    settings.mode = "hardware"
    head = HardwareStatusHead("robot-01")
    head.body_status["power"] = power
    coordinator = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        with pytest.raises(OperationError, match="Hardware preflight: malformed battery"):
            await coordinator.operator_arm("robot-01")
        assert coordinator.permits.get("robot-01") is None
        assert not head.commands
        head.body_status["armed"] = True
        with pytest.raises(OperationError, match="Operation blocked: malformed battery"):
            await coordinator._assert_armed_health("robot-01")
    finally:
        await coordinator.close()


@pytest.mark.parametrize("power", [
    {"fuel_valid": False},
    {"fuel_valid": True, "cell_mv": 3800, "soc_centi": 7000},
])
async def test_optional_unavailable_or_healthy_fuel_keeps_existing_arming_path(
    settings, power,
):
    settings.mode = "hardware"
    head = HardwareStatusHead("robot-01")
    head.body_status["power"] = power
    coordinator = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        permit = await coordinator.operator_arm("robot-01")
        assert permit["operator_permit"] is True
        head.body_status["armed"] = True
        assert await coordinator._assert_armed_health("robot-01")
    finally:
        await coordinator.close()


async def test_hardware_running_health_rejects_depleted_battery(settings):
    settings.mode = "hardware"
    head = HardwareStatusHead("robot-01")
    head.body_status["armed"] = True
    head.body_status["power"] = {"fuel_valid": True, "cell_mv": 3200, "soc_centi": 500}
    coordinator = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        with pytest.raises(OperationError, match="battery depleted"):
            await coordinator._assert_armed_health("robot-01")
    finally:
        await coordinator.close()





async def test_full_guarded_dc_path_is_not_confused_with_unprotected_pwm(settings):
    settings.mode = "hardware"
    head = HardwareStatusHead("robot-01")
    head.body_status["backend"] = "dc_pwm_guarded"
    settings.robots[0].motor_backend = "dc_pwm_guarded"
    coordinator = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        permit = await coordinator.operator_arm("robot-01")
        assert permit["operator_permit"] is True
        assert not head.commands
        # Real sensor fault still refuses the same guarded DC backend.
        head.body_status["safety"]["ready"] = False
        with pytest.raises(OperationError, match="Hardware preflight"):
            await coordinator.operator_arm("robot-01")
        assert not head.commands
        assert coordinator.permits.get("robot-01") is None
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
        assert head.commands[-1] == "halt"
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
        assert head.commands[-1] == "halt"
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
        assert head.commands[-1] == "halt"
        assert c.permits.get("robot-01") is None
    finally:
        await c.close()


async def test_authenticated_human_preempts_running_exploration_without_rearming(settings):
    c, head = make(settings)
    try:
        await c.operator_arm("robot-01")
        job = c.explore("robot-01")
        async with asyncio.timeout(3):
            while head.commands.count("drive 20 20 100") == 0:
                await asyncio.sleep(0.01)
        stopped = await c.stop_active_exploration()
        assert stopped == ("robot-01",)
        assert job.state in {"cancelled", "failed"}
        assert c.permits.get("robot-01") is None
        assert head.commands[-1] == "halt"
        assert any("preempted by live human" in event for event in job.events)
        before = head.commands.count("drive 20 20 100")
        await asyncio.sleep(0.2)
        assert head.commands.count("drive 20 20 100") == before
        # A repeated VAD event must not send another motor command.
        previous_count = len(head.commands)
        assert await c.stop_active_exploration() == ()
        assert len(head.commands) == previous_count
    finally:
        await c.close()


@pytest.mark.parametrize("pulse", [0, 1])
@pytest.mark.parametrize(
    ("fence", "message"),
    [
        ("voice", "Voice priority"),
        ("disabled", "motion_enabled=false"),
        ("dock", "seated or powered on dock"),
        ("job", "job no longer owns motion"),
    ],
)
async def test_exploration_rechecks_motion_authority_after_health_io(
    settings, pulse, fence, message,
):
    c, head = make(settings)
    started, resume = asyncio.Event(), asyncio.Event()
    original_health = c._assert_armed_health
    health_reads = 0

    async def gated_health(robot_id, *, require_front_clearance=False):
        nonlocal health_reads
        health_reads += 1
        result = await original_health(
            robot_id, require_front_clearance=require_front_clearance,
        )
        if health_reads == 2 * (pulse + 1):
            started.set()
            await resume.wait()
        return result

    c._assert_armed_health = gated_health
    try:
        await c.operator_arm("robot-01")
        job = c.explore("robot-01")
        await asyncio.wait_for(started.wait(), timeout=3)
        assert head.commands.count("drive 20 20 100") == pulse
        # Exercise the synchronous authority fence before any separately
        # scheduled STOP/cancellation can reach this suspended operation.
        if fence == "voice":
            c.set_voice_state(active_robots={"robot-02"})
        elif fence == "disabled":
            settings.robots[0].motion_enabled = False
        elif fence == "dock":
            c._dock_charging_inhibited = {"robot-01": True}
        else:
            job.state = "cancelled"
        resume.set()
        await asyncio.wait_for(c.tasks[job.id], timeout=3)
        assert job.state == "failed"
        assert message in job.error
        assert head.commands.count("drive 20 20 100") == pulse
        assert head.commands.count("arm") == 1
        assert head.commands[-1] == "halt"
        assert c._fleet_motion_owner is None
    finally:
        resume.set()
        await c.close()


async def test_human_voice_roaming_stop_does_not_cancel_manual_gripper(settings):
    c, head = make(settings)
    try:
        await c.operator_arm("robot-01")
        job = c.manual("robot-01", "grip 90")
        async with asyncio.timeout(1):
            while job.state == "queued":
                await asyncio.sleep(0)
        assert job.state == "running"
        commands_before = list(head.commands)
        assert await c.stop_active_exploration() == ()
        assert head.commands == commands_before
        assert job.state == "running"
    finally:
        await c.close()


async def test_voice_roaming_stop_fault_remains_unconfirmed(settings):
    c, head = make(settings)
    try:
        await c.operator_arm("robot-01")
        job = c.explore("robot-01")
        async with asyncio.timeout(3):
            while head.commands.count("drive 20 20 100") == 0:
                await asyncio.sleep(0.01)
        head.fail_command = "halt"
        with pytest.raises(OperationError, match="STOP unconfirmed"):
            await c.stop_active_exploration()
        assert any("preempted by live human" in event for event in job.events)
        # Never claim a successful physical stop when the transport ACK failed.
    finally:
        head.fail_command = None
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
        assert head.commands[-1] == "halt"
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
        assert head.commands[-1] == "halt"
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
        assert head.commands[-1] == "halt"
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
        assert head.commands[-1] == "halt"
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
        assert head.commands[-1] == "halt"
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
        assert head.commands[-1] == "halt"
    finally:
        await c.close()


@pytest.mark.parametrize("bad_frame", [
    None, b"", b"<html>camera unavailable</html>",
    b"\xff\xd8incomplete", b"incomplete\xff\xd9",
    b"\xff\xd8fake but properly delimited\xff\xd9",
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
        assert head.commands[-1] == "halt"
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
        assert head.commands[-1] == "halt"
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


async def test_exploration_rejects_valid_jpeg_with_unusable_dimensions(settings):
    """Even a decodable one pixel image is not a meaningful live camera feed."""
    from io import BytesIO

    from PIL import Image

    image = BytesIO()
    Image.new("RGB", (1, 1), "white").save(image, format="JPEG")
    c, head = make(settings)

    async def tiny_camera():
        return image.getvalue()

    head.snapshot = tiny_camera
    try:
        await c.operator_arm("robot-01")
        job = c.explore("robot-01")
        await asyncio.wait_for(c.tasks[job.id], timeout=4)
        assert job.state == "failed"
        assert "invalid JPEG dimensions" in (job.error or "")
        assert not any(cmd.startswith("drive ") for cmd in head.commands)
        assert head.commands[-1] == "halt"
    finally:
        await c.close()


async def test_exploration_stalled_body_health_times_out_before_motion(settings):
    """Persistent exploration cannot wait indefinitely on a hung status adapter."""
    c, head = make(settings)
    try:
        await c.operator_arm("robot-01")

        async def stalled_status():
            await asyncio.sleep(30)

        head.status = stalled_status
        job = c.explore("robot-01")
        await asyncio.wait_for(c.tasks[job.id], timeout=4)
        assert job.state == "failed"
        assert "timeout" in (job.error or "").lower()
        assert not any(cmd.startswith("drive ") for cmd in head.commands)
        assert head.commands[-1] == "halt"
    finally:
        await c.close()


async def test_unresponsive_body_stop_is_bounded(settings):
    """An operator STOP must not await a hung alternate head forever."""
    c, head = make(settings)
    async def hung_stop(command):
        if command == "halt":
            await asyncio.sleep(30)
        return await original(command)

    original = head.command
    head.command = hung_stop
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(c.stop("robot-01"), timeout=2)
        assert c.permits.get("robot-01") is None
    finally:
        await c.close()


async def test_job_cleanup_stop_timeout_fails_without_false_ack(settings):
    """After command completion, never label an unacknowledged STOP as safe."""
    c, head = make(settings)
    original = head.command
    async def hung_stop(command):
        if command == "halt":
            await asyncio.sleep(30)
        return await original(command)

    head.command = hung_stop
    try:
        await c.operator_arm("robot-01")
        job = c.manual("robot-01", "drive 0 0 10")
        await asyncio.wait_for(c.tasks[job.id], timeout=2)
        assert job.state == "failed"
        assert "STOP failed" in (job.error or "")
        assert not any("stop acknowledged" in event for event in job.events)
        assert head.commands.count("drive 0 0 10") == 1
    finally:
        await c.close()


async def test_cancellation_resistant_stop_returns_before_transport_finishes(settings):
    """STOP timeout stays bounded even if a transport suppresses CancelledError."""
    c, head = make(settings)
    reached = asyncio.Event()
    release = asyncio.Event()
    original = head.command

    async def stubborn_stop(command):
        if command != "halt":
            return await original(command)
        reached.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
            return {"ok": True, "reply": "OK halt", "robot_id": "robot-01"}

    head.command = stubborn_stop
    try:
        with pytest.raises(TimeoutError, match="STOP transport acknowledgement unconfirmed"):
            await asyncio.wait_for(c.stop("robot-01"), timeout=1.8)
        assert reached.is_set()
        assert not release.is_set()
    finally:
        release.set()
        await asyncio.sleep(0)
        await c.close()


async def test_cleanup_cannot_claim_late_uncertain_stop_ack(settings):
    """A late ACK after timed-out STOP is not successful job cleanup."""
    c, head = make(settings)
    reached = asyncio.Event()
    release = asyncio.Event()
    original = head.command

    async def stubborn_stop(command):
        if command != "halt":
            return await original(command)
        reached.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
            return {"ok": True, "reply": "OK halt", "robot_id": "robot-01"}

    head.command = stubborn_stop
    try:
        await c.operator_arm("robot-01")
        job = c.manual("robot-01", "drive 0 0 10")
        await asyncio.wait_for(c.tasks[job.id], timeout=1.8)
        assert reached.is_set()
        assert job.state == "failed"
        assert "STOP failed" in (job.error or "")
        assert not any("stop acknowledged" in event for event in job.events)
        release.set()
        await asyncio.sleep(0)
        assert job.state == "failed"
    finally:
        release.set()
        await asyncio.sleep(0)
        await c.close()


async def test_exploration_inflight_stop_timeout_aborts_before_second_drive(settings):
    """An unconfirmed post-pulse STOP fails, even if final cleanup succeeds."""
    c, head = make(settings)
    original = head.command
    started = asyncio.Event()
    release = asyncio.Event()
    stop_calls = 0

    async def stubborn_first_stop(command):
        nonlocal stop_calls
        if command == "stop":
            stop_calls += 1
            if stop_calls == 1:
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    await release.wait()
                    return {"ok": True, "reply": "stop", "robot_id": "robot-01"}
        return await original(command)

    head.command = stubborn_first_stop
    try:
        await c.operator_arm("robot-01")
        job = c.explore("robot-01")
        await asyncio.wait_for(c.tasks[job.id], timeout=3)
        assert started.is_set()
        assert not release.is_set()
        assert job.state == "failed"
        assert "STOP transport acknowledgement unconfirmed" in (job.error or "")
        assert head.commands.count("drive 20 20 100") == 1
        assert head.commands[-1] == "halt"
        release.set()
        await asyncio.sleep(0)
        assert job.state == "failed"
    finally:
        release.set()
        await asyncio.sleep(0)
        await c.close()


async def test_slow_operator_arm_cannot_revive_permit_after_stop(settings):
    """A STOP supersedes an unfinished but previously healthy preflight."""
    settings.mode = "hardware"
    head = HardwareStatusHead("robot-01")
    arrived = asyncio.Event()
    release = asyncio.Event()
    original = head.status

    async def delayed_status():
        arrived.set()
        await release.wait()
        return await original()

    head.status = delayed_status
    c = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        arm = asyncio.create_task(c.operator_arm("robot-01"))
        await asyncio.wait_for(arrived.wait(), timeout=1)
        assert not c.permits
        await c.stop("robot-01")
        release.set()
        with pytest.raises(OperationError, match="superseded"):
            await asyncio.wait_for(arm, timeout=1)
        assert c.permits.get("robot-01") is None
    finally:
        release.set()
        await c.close()


async def test_latest_operator_arm_wins_over_older_delayed_preflight(settings):
    """A stale callback cannot overwrite a later operator permit."""
    settings.mode = "hardware"
    head = HardwareStatusHead("robot-01")
    arrived = asyncio.Event()
    release = asyncio.Event()
    reads = 0
    original = head.status

    async def delayed_first_status():
        nonlocal reads
        reads += 1
        if reads == 1:
            arrived.set()
            await release.wait()
        return await original()

    head.status = delayed_first_status
    c = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        first = asyncio.create_task(c.operator_arm("robot-01"))
        await asyncio.wait_for(arrived.wait(), timeout=1)
        latest = await c.operator_arm("robot-01")
        assert latest["operator_permit"] is True
        permit = c.permits["robot-01"]
        release.set()
        with pytest.raises(OperationError, match="superseded"):
            await asyncio.wait_for(first, timeout=1)
        assert c.permits["robot-01"] == permit
        assert head.commands == []
    finally:
        release.set()
        await c.close()


async def test_uncooperative_preflight_times_out_without_permit(settings):
    """An alternate status adapter can ignore cancellation but cannot arm."""
    settings.mode = "hardware"
    head = HardwareStatusHead("robot-01")
    entered = asyncio.Event()
    release = asyncio.Event()
    original = head.status

    async def unresponsive_status():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
            return await original()

    head.status = unresponsive_status
    c = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        with pytest.raises(TimeoutError, match="preflight status timeout"):
            await asyncio.wait_for(c.operator_arm("robot-01"), timeout=3.5)
        assert entered.is_set()
        assert c.permits.get("robot-01") is None
        release.set()
        await asyncio.sleep(0)
        assert c.permits.get("robot-01") is None
    finally:
        release.set()
        await asyncio.sleep(0)
        await c.close()


async def test_exploration_uncooperative_status_timeout_stops_motion(settings):
    """A status adapter ignoring cancellation cannot hang persistent explore."""
    c, head = make(settings)
    entered = asyncio.Event()
    release = asyncio.Event()
    original = head.status

    async def unresponsive_status():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
            return await original()

    try:
        await c.operator_arm("robot-01")
        head.status = unresponsive_status
        job = c.explore("robot-01")
        await asyncio.wait_for(c.tasks[job.id], timeout=3.5)
        assert entered.is_set()
        assert job.state == "failed"
        assert "active health status timeout" in (job.error or "")
        assert not any(command.startswith("drive ") for command in head.commands)
        assert head.commands[-1] == "halt"
        release.set()
        await asyncio.sleep(0)
        assert job.state == "failed"
    finally:
        release.set()
        await asyncio.sleep(0)
        await c.close()


async def test_close_revokes_permits_and_stops_active_hardware_job(settings):
    """Shutdown attempts real STOP before awaiting stale job cleanup."""
    from desk_robot.controller import Job

    settings.mode = "hardware"
    head = HardwareStatusHead("robot-01")
    c = Coordinator(settings, {"robot-01": head}, SimulationVision())
    blocked = asyncio.Event()
    task = asyncio.create_task(blocked.wait())
    job = Job("shutdown-unit", "robot-01", "exploration", state="running")
    c.tasks[job.id] = task
    c.jobs[job.id] = job
    c.permits["robot-01"] = time.monotonic() + 30
    await c.close()
    assert c.closed is True
    assert c.permits == {}
    assert task.cancelled()
    assert head.commands == ["halt"]


async def test_close_reports_unconfirmed_stop_without_hanging(settings):
    """One failed hardware STOP must not freeze runtime shutdown."""
    from desk_robot.controller import Job

    settings.mode = "hardware"
    head = HardwareStatusHead("robot-01")
    original = head.command
    async def stuck_stop(command):
        if command == "halt":
            await asyncio.sleep(30)
        return await original(command)
    head.command = stuck_stop
    c = Coordinator(settings, {"robot-01": head}, SimulationVision())
    blocked = asyncio.Event()
    task = asyncio.create_task(blocked.wait())
    job = Job("shutdown-unconfirmed", "robot-01", "exploration", state="running")
    c.tasks[job.id] = task
    c.jobs[job.id] = job
    await asyncio.wait_for(c.close(), timeout=1.8)
    assert c.closed and task.cancelled()
    assert job.state == "failed"
    assert "Shutdown STOP unconfirmed" in (job.error or "")


async def test_hardware_close_stops_idle_registered_bodies_concurrently(settings):
    """A permit consumed earlier is no excuse to skip physical fleet STOP."""
    settings.mode = "hardware"
    first = HardwareStatusHead("robot-01")
    second = HardwareStatusHead("robot-02")
    c = Coordinator(
        settings, {"robot-01": first, "robot-02": second},
        SimulationVision(),
    )
    await asyncio.wait_for(c.close(), timeout=1)
    assert c.closed and not c.permits
    assert first.commands == ["halt"]
    assert second.commands == ["halt"]


async def test_hardware_close_stalled_peer_does_not_starve_other_body(settings):
    settings.mode = "hardware"
    first = HardwareStatusHead("robot-01")
    second = HardwareStatusHead("robot-02")
    sent = asyncio.Event()
    release = asyncio.Event()
    original = first.command

    async def uncooperative_first(command):
        if command == "halt":
            sent.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
                return {"ok": True, "reply": "OK halt", "robot_id": "robot-01"}
        return await original(command)

    first.command = uncooperative_first
    c = Coordinator(
        settings, {"robot-01": first, "robot-02": second},
        SimulationVision(),
    )
    try:
        await asyncio.wait_for(c.close(), timeout=1.8)
        assert sent.is_set()
        assert c.closed
        assert second.commands == ["halt"]
        assert c.shutdown_stop_failures["robot-01"] == "TimeoutError"
        assert not release.is_set()
    finally:
        release.set()
        await asyncio.sleep(0)


async def test_exploration_uncooperative_camera_cannot_hold_motion_job_open(settings):
    """A cancelled but stubborn capture must not pin the exploration job."""
    c, head = make(settings)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def stale_camera():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
            return b"\\xff\\xd8late\\xff\\xd9"

    head.snapshot = stale_camera
    try:
        await c.operator_arm("robot-01")
        job = c.explore("robot-01")
        await asyncio.wait_for(c.tasks[job.id], timeout=3.2)
        assert entered.is_set()
        assert job.state == "failed"
        assert "Camera snapshot timeout" in (job.error or "")
        assert not any(command.startswith("drive ") for command in head.commands)
        assert head.commands[-1] == "halt"
    finally:
        release.set()
        await asyncio.sleep(0)
        await c.close()


async def test_bounded_head_reply_disregards_uncooperative_late_success():
    """The reusable deadline must never await a transport ignoring cancel."""
    from desk_robot.controller import _bounded_head_reply

    entered = asyncio.Event()
    release = asyncio.Event()
    async def fake_adapter():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
            return {"ok": True}

    try:
        with pytest.raises(TimeoutError, match="camera deadline"):
            await asyncio.wait_for(
                _bounded_head_reply(fake_adapter(), seconds=0.03,
                                    timeout_message="camera deadline"),
                timeout=0.2,
            )
        assert entered.is_set()
    finally:
        release.set()
        await asyncio.sleep(0)


async def test_hardware_pickup_refuses_snapshot_without_live_camera_before_jaw_motion(settings):
    from desk_robot.calibration import Calibration

    settings.mode = "hardware"
    c, head = make(settings)

    async def forbidden_snapshot():
        raise AssertionError("No hardware JPEG should be fetched while consent is off")

    head.snapshot = forbidden_snapshot
    try:
        with pytest.raises(OperationError, match="connected live XIAO camera"):
            await c._pickup(
                Job("missing-pickup-video", "robot-01", "pickup"),
                "key", Calibration.load(settings.robots[0].calibration),
            )
        assert head.commands == []
    finally:
        await c.close()


async def test_hardware_pickup_consumes_distinct_stream_frames_not_snapshot(settings):
    from desk_robot.calibration import Calibration

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    c, head = make(settings)
    jpeg = await head.snapshot()

    async def forbidden_snapshot():
        raise AssertionError("Pickup duplicated live stream with a physical snapshot")

    async def no_fresh_frame(_robot_id, _after, *, timeout_s):
        return False

    head.snapshot = forbidden_snapshot
    c.multimodal = SimpleNamespace(
        settings=settings,
        stream_owns_camera=lambda _id: True,
        status=lambda _id: {"camera_stream_connected": True},
        hub=SimpleNamespace(frames={"robot-01": [SimpleNamespace(
            source="proactive", jpeg=jpeg, received_at=time.monotonic()
        )]}),
        wait_for_proactive_frame=no_fresh_frame,
    )
    cals = Calibration.load(settings.robots[0].calibration)
    try:
        detection, first_at = await c._observe("robot-01", "key", cals)
        assert detection.label == "key"
        with pytest.raises(OperationError, match="camera stalled"):
            await c._observe("robot-01", "key", cals, after=first_at)
    finally:
        await c.close()


async def test_hardware_pickup_cannot_use_camera_frame_after_consent_revoke(settings):
    from desk_robot.calibration import Calibration

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    c, head = make(settings)
    jpeg = await head.snapshot()

    async def delayed_detect(image, target):
        settings.voice_vision_tools_enabled = False
        return await SimulationVision().detect(image, target)

    async def forbidden_snapshot():
        raise AssertionError("Pickup must not use legacy still camera")

    head.snapshot = forbidden_snapshot
    c.vision.detect = delayed_detect
    c.multimodal = SimpleNamespace(
        settings=settings,
        stream_owns_camera=lambda _id: True,
        status=lambda _id: {"camera_stream_connected": True},
        hub=SimpleNamespace(frames={"robot-01": [SimpleNamespace(
            source="proactive", jpeg=jpeg, received_at=time.monotonic()
        )]}),
    )
    try:
        with pytest.raises(OperationError, match="connected live XIAO camera"):
            await c._observe(
                "robot-01", "key", Calibration.load(settings.robots[0].calibration),
            )
    finally:
        await c.close()


async def test_hardware_exploration_needs_existing_continuous_camera_owner(settings):
    c, head = make(settings)
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    async def healthy(_robot_id, *, require_front_clearance=False):
        return {"armed": True}
    c._assert_armed_health = healthy
    try:
        with pytest.raises(OperationError, match="live XIAO camera stream"):
            await c._explore(Job("live-missing", "robot-01", "exploration"))
        assert not any(cmd.startswith("drive ") for cmd in head.commands)
    finally:
        await c.close()


@pytest.mark.parametrize("grant_change", ["off", "regrant", "unchanged"])
async def test_hardware_exploration_camera_grant_checked_after_health_await(
    settings, grant_change,
):
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    c, head = make(settings)
    jpeg = await head.snapshot()
    await head.command("arm")  # Same simulated motor permit as existing live-frame test.
    paused = asyncio.Event()
    release = asyncio.Event()
    health_reads = 0

    async def gated_health(_robot_id, *, require_front_clearance=False):
        nonlocal health_reads
        health_reads += 1
        if health_reads == 2:
            paused.set()
            await release.wait()
        return {"armed": True}

    async def no_new_frame(_robot_id, _after, *, timeout_s):
        return False

    c._assert_armed_health = gated_health
    c.multimodal = SimpleNamespace(
        settings=settings,
        stream_owns_camera=lambda _robot_id: True,
        status=lambda _robot_id: {"camera_stream_connected": True},
        hub=SimpleNamespace(frames={"robot-01": [SimpleNamespace(
            source="proactive", jpeg=jpeg, received_at=time.monotonic()
        )]}),
        wait_for_proactive_frame=no_new_frame,
    )
    task = asyncio.create_task(
        c._explore(Job("camera-grant-gated", "robot-01", "exploration"))
    )
    try:
        await asyncio.wait_for(paused.wait(), timeout=1)
        if grant_change != "unchanged":
            settings.voice_vision_tools_enabled = False
            if grant_change == "regrant":
                settings.voice_vision_tools_enabled = True
        release.set()
        if grant_change == "unchanged":
            with pytest.raises(OperationError, match="camera stalled"):
                await asyncio.wait_for(task, timeout=2)
            assert head.commands.count("drive 20 20 100") == 1
        else:
            with pytest.raises(OperationError, match="camera consent revoked"):
                await asyncio.wait_for(task, timeout=2)
            assert not any(cmd.startswith("drive ") for cmd in head.commands)
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await c.close()


async def test_hardware_exploration_uses_live_hub_frames_not_individual_snapshot(settings):
    c, head = make(settings)
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    jpeg = await head.snapshot()
    async def forbidden_snapshot():
        raise AssertionError("A second camera capture duplicated the active live feed")
    head.snapshot = forbidden_snapshot
    await head.command("arm")
    async def healthy(_robot_id, *, require_front_clearance=False):
        return {"armed": True}
    c._assert_armed_health = healthy
    frames = [SimpleNamespace(
        source="proactive", jpeg=jpeg, received_at=time.monotonic()
    )]
    async def no_new_frame(_robot_id, _after, *, timeout_s):
        return False
    c.multimodal = SimpleNamespace(
        settings=settings,
        stream_owns_camera=lambda _robot_id: True,
        status=lambda _robot_id: {"camera_stream_connected": True},
        hub=SimpleNamespace(frames={"robot-01": frames}),
        wait_for_proactive_frame=no_new_frame,
    )
    try:
        # A new frame permits one physically guarded pulse; the same
        # cached JPEG cannot be reused for a SECOND pulse afterward.
        with pytest.raises(OperationError, match="camera stalled"):
            await c._explore(Job("live-only", "robot-01", "exploration"))
        assert head.commands.count("drive 20 20 100") == 1
        assert head.commands.count("stop") == 1
    finally:
        await c.close()


async def test_hardware_exploration_rejects_stale_stream_receipt_before_drive(settings):
    c, head = make(settings)
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    jpeg = await head.snapshot()
    head.fail_snapshot = True
    async def healthy(_robot_id, *, require_front_clearance=False):
        return {"armed": True}
    c._assert_armed_health = healthy
    frames = [SimpleNamespace(
        source="proactive", jpeg=jpeg, received_at=time.monotonic() - 15.0
    )]
    async def stale_stream(_robot_id, _after, *, timeout_s):
        return False
    c.multimodal = SimpleNamespace(
        settings=settings,
        stream_owns_camera=lambda _robot_id: True,
        status=lambda _robot_id: {"camera_stream_connected": True},
        hub=SimpleNamespace(frames={"robot-01": frames}),
        wait_for_proactive_frame=stale_stream,
    )
    try:
        with pytest.raises(OperationError, match="camera stalled"):
            await c._explore(Job("stale-video", "robot-01", "exploration"))
        assert not any(cmd.startswith("drive ") for cmd in head.commands)
    finally:
        await c.close()


async def test_hardware_exploration_rejects_reconnecting_camera_task(settings):
    # A long-lived MJPEG worker may be in its reconnect/backoff loop while
    # stream_owns_camera still returns True. No fresh physical socket means
    # a cached JPEG is not a navigation permission.
    c, head = make(settings)
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    jpeg = await head.snapshot()
    async def healthy(_robot_id, *, require_front_clearance=False):
        return {"armed": True}
    c._assert_armed_health = healthy
    c.multimodal = SimpleNamespace(
        settings=settings,
        stream_owns_camera=lambda _robot_id: True,
        status=lambda _robot_id: {"camera_stream_connected": False},
        hub=SimpleNamespace(frames={"robot-01": [SimpleNamespace(
            source="proactive", jpeg=jpeg, received_at=time.monotonic()
        )]}),
    )
    try:
        with pytest.raises(OperationError, match="connected live XIAO"):
            await c._explore(Job("reconnect-video", "robot-01", "exploration"))
        assert not any(command.startswith("drive ") for command in head.commands)
    finally:
        await c.close()


async def test_hardware_fleet_allows_only_one_moving_pet_until_acknowledged_stop(settings):
    """Two arm permits are fine, but a second body may not drive concurrently."""
    settings.mode = "hardware"
    c, _ = make(settings)
    head1 = HardwareStatusHead("robot-01")
    head2 = HardwareStatusHead("robot-02")
    c.heads["robot-01"] = head1
    c.heads["robot-02"] = head2

    await c.operator_arm("robot-01")
    await c.operator_arm("robot-02")
    assert "robot-01" in c.permits
    assert "robot-02" in c.permits

    try:
        first = c.manual("robot-01", "drive 10 10 100")
        assert c._fleet_motion_owner == first.id
        with pytest.raises(OperationError, match="one moving pet"):
            c.manual("robot-02", "drive 10 10 100")
        assert not any(command.startswith("drive ") for command in head2.commands)
        assert "robot-02" in c.permits  # refusal does not consume consent
        await c.tasks[first.id]
        assert first.state == "succeeded"
        assert c._fleet_motion_owner is None
        assert head1.commands[-1] == "halt"
        second = c.manual("robot-02", "drive 10 10 100")
        await c.tasks[second.id]
        assert second.state == "succeeded"
        assert c._fleet_motion_owner is None
    finally:
        await c.close()


async def test_fleet_motion_owner_latches_failed_stop_until_explicit_recovery(settings):
    """A failed final halt is not a license to start another moving pet."""
    c, head = make(settings)
    await c.operator_arm("robot-01")
    await c.operator_arm("robot-02")
    head.fail_command = "halt"
    try:
        first = c.manual("robot-01", "drive 10 10 100")
        await c.tasks[first.id]
        assert first.state == "failed"
        assert c._fleet_motion_owner == first.id
        with pytest.raises(OperationError, match="one moving pet"):
            c.manual("robot-02", "drive 10 10 100")
        assert "robot-02" in c.permits
        # An explicit independently acknowledged WROOM STOP unblocks later
        # operator-approved motion. Reconnect or task completion alone cannot.
        head.fail_command = None
        ack = await c.stop("robot-01")
        assert ack["ok"] is True
        assert c._fleet_motion_owner is None
        second = c.manual("robot-02", "drive 10 10 100")
        await c.tasks[second.id]
        assert second.state == "succeeded"
    finally:
        head.fail_command = None
        await c.close()


@pytest.mark.parametrize(
    ("selected", "reported", "allowed"),
    [
        ("stepper_28byj48", "stepper_28byj48", True),
        ("dc_pwm_guarded", "dc_pwm_guarded", True),
        (None, "stepper_28byj48", False),
        ("stepper_28byj48", "dc_pwm_guarded", False),
        ("dc_pwm_guarded", "stepper_28byj48", False),
        ("dc_pwm_guarded", "dc_pwm", False),
    ],
)
async def test_hardware_operator_arm_requires_selected_motor_profile(
    settings, selected, reported, allowed,
):
    settings.mode = "hardware"
    settings.robots[0].motor_backend = selected
    head = HardwareStatusHead("robot-01")
    head.body_status["backend"] = reported
    coordinator = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        if allowed:
            permit = await coordinator.operator_arm("robot-01")
            assert permit["operator_permit"] is True
        else:
            with pytest.raises(OperationError, match="motor backend"):
                await coordinator.operator_arm("robot-01")
            assert "robot-01" not in coordinator.permits
        assert not head.commands
    finally:
        await coordinator.close()


async def test_motor_backend_change_during_status_never_creates_permit(settings):
    settings.mode = "hardware"
    started, resume = asyncio.Event(), asyncio.Event()

    class DelayedStatus(HardwareStatusHead):
        async def status(self):
            started.set()
            await resume.wait()
            return await super().status()

    head = DelayedStatus("robot-01")
    coordinator = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        pending = asyncio.create_task(coordinator.operator_arm("robot-01"))
        await asyncio.wait_for(started.wait(), timeout=1)
        settings.robots[0].motor_backend = "dc_pwm_guarded"
        resume.set()
        with pytest.raises(OperationError, match="motor backend"):
            await asyncio.wait_for(pending, timeout=1)
        assert "robot-01" not in coordinator.permits
        assert not head.commands
    finally:
        resume.set()
        await coordinator.close()


async def test_idle_stop_fences_fresh_permit_and_peer_motion_until_ack(settings):
    c, head = make(settings)
    entered = asyncio.Event()
    release = asyncio.Event()
    original = head.command

    async def delayed_halt(command):
        if command == "halt":
            entered.set()
            await release.wait()
        return await original(command)

    head.command = delayed_halt
    await c.operator_arm("robot-02")
    stopping = asyncio.create_task(c.stop("robot-01"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=0.5)
        with pytest.raises(OperationError, match="STOP pending"):
            await c.operator_arm("robot-01")
        with pytest.raises(OperationError, match="STOP pending"):
            c.manual("robot-02", "drive 10 10 100")
        assert "robot-01" not in c.permits
        assert "robot-02" in c.permits
        release.set()
        assert (await stopping)["ok"] is True
        await c.operator_arm("robot-01")
        job = c.manual("robot-01", "drive 10 10 100")
        await c.tasks[job.id]
        assert job.state == "succeeded"
    finally:
        release.set()
        await asyncio.gather(stopping, return_exceptions=True)
        await c.close()


async def test_failed_idle_stop_requires_explicit_acknowledged_recovery(settings):
    from desk_robot.transport import HeadError

    c, head = make(settings)
    await c.operator_arm("robot-02")
    head.fail_command = "halt"
    try:
        with pytest.raises(HeadError, match="Simulated uncertain ACK"):
            await c.stop("robot-01")
        with pytest.raises(OperationError, match="STOP pending or unconfirmed"):
            await c.operator_arm("robot-01")
        with pytest.raises(OperationError, match="STOP pending or unconfirmed"):
            c.manual("robot-02", "drive 10 10 100")
        assert "robot-02" in c.permits
        head.fail_command = None
        assert (await c.stop("robot-01"))["ok"] is True
        job = c.manual("robot-02", "drive 10 10 100")
        await c.tasks[job.id]
        assert job.state == "succeeded"
    finally:
        head.fail_command = None
        await c.close()


async def test_explicit_stop_cannot_release_fleet_with_live_cancelled_child(settings):
    c, head = make(settings)
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    original = head.command

    async def stubborn_lift(command):
        if command != "lift 110":
            return await original(command)
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
        finally:
            finished.set()
        return {"ok": True, "reply": "OK lift angle=110", "robot_id": "robot-01"}

    head.command = stubborn_lift
    await c.operator_arm("robot-01")
    await c.operator_arm("robot-02")
    job = c.manual("robot-01", "lift 110")
    try:
        await asyncio.wait_for(entered.wait(), timeout=0.5)
        await c.stop("robot-01")
        await asyncio.wait_for(cancelled.wait(), timeout=0.5)
        await asyncio.wait_for(c.tasks[job.id], timeout=1)
        assert not finished.is_set()
        # The parent is done, but its abandoned transport task still owns
        # potential motion. A new HALT receipt alone cannot retire that task.
        assert (await c.stop("robot-01"))["ok"] is True
        assert c._fleet_motion_owner == job.id
        with pytest.raises(OperationError, match="one moving pet"):
            c.manual("robot-02", "drive 10 10 100")
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=0.5)
        # The manual work still has its existing servo-settling wait.
        await asyncio.wait_for(
            asyncio.gather(*c._motion_children[job.id], return_exceptions=True),
            timeout=3,
        )
        assert (await c.stop("robot-01"))["ok"] is True
        assert c._fleet_motion_owner is None
        next_job = c.manual("robot-02", "drive 10 10 100")
        await c.tasks[next_job.id]
        assert next_job.state == "succeeded"
    finally:
        release.set()
        await c.close()


async def test_stalled_keepalive_ack_aborts_manual_job_before_settling(settings):
    c, head = make(settings)
    entered = asyncio.Event()
    halted = asyncio.Event()
    original = head.command
    attempts = 0

    async def missing_heartbeat(command):
        nonlocal attempts
        if command == "keepalive":
            attempts += 1
            entered.set()
            await asyncio.Event().wait()
        result = await original(command)
        if command == "halt":
            halted.set()
        return result

    head.command = missing_heartbeat
    await c.operator_arm("robot-01")
    job = c.manual("robot-01", "lift 110")
    try:
        await asyncio.wait_for(entered.wait(), timeout=0.5)
        # Manual settling takes two seconds. A missing heartbeat must cancel
        # that job, not wait for completion or the overall operation deadline.
        await asyncio.wait_for(halted.wait(), timeout=1.0)
        await asyncio.wait_for(c.tasks[job.id], timeout=0.5)
        assert job.state == "failed"
        assert "keepalive acknowledgement timeout" in job.error
        assert job.result is None
        assert attempts == 1
        assert not head.armed
        assert c._fleet_motion_owner is None
    finally:
        await c.close()


async def test_older_idle_stop_success_cannot_clear_newer_failed_stop(settings):
    from desk_robot.transport import HeadError

    c, head = make(settings)
    entered = asyncio.Event()
    release = asyncio.Event()
    original = head.command
    attempts = 0

    async def overlapping_halt(command):
        nonlocal attempts
        if command == "halt":
            attempts += 1
            if attempts == 1:
                entered.set()
                await release.wait()
            elif attempts == 2:
                raise HeadError("Newer HALT acknowledgement failed")
        return await original(command)

    head.command = overlapping_halt
    await c.operator_arm("robot-02")
    older = asyncio.create_task(c.stop("robot-01"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=0.5)
        with pytest.raises(HeadError, match="Newer HALT"):
            await c.stop("robot-01")
        release.set()
        assert (await older)["ok"] is True
        with pytest.raises(OperationError, match="STOP pending or unconfirmed"):
            await c.operator_arm("robot-01")
        with pytest.raises(OperationError, match="STOP pending or unconfirmed"):
            c.manual("robot-02", "drive 10 10 100")
        assert (await c.stop("robot-01"))["ok"] is True
        job = c.manual("robot-02", "drive 10 10 100")
        await c.tasks[job.id]
        assert job.state == "succeeded"
    finally:
        release.set()
        await asyncio.gather(older, return_exceptions=True)
        await c.close()


@pytest.mark.parametrize("halt_fails", [False, True])
async def test_job_result_not_published_before_terminal_halt_receipt(settings, halt_fails):
    from desk_robot.transport import HeadError

    c, head = make(settings)
    entered = asyncio.Event()
    release = asyncio.Event()
    original = head.command

    async def delayed_terminal_halt(command):
        if command == "halt":
            entered.set()
            await release.wait()
            if halt_fails:
                raise HeadError("Terminal HALT acknowledgement lost")
        return await original(command)

    head.command = delayed_terminal_halt
    await c.operator_arm("robot-01")
    job = c.manual("robot-01", "drive 0 0 10")
    try:
        await asyncio.wait_for(entered.wait(), timeout=0.5)
        assert job.state == "running"
        assert job.result is None
        assert c._fleet_motion_owner == job.id
        release.set()
        await asyncio.wait_for(c.tasks[job.id], timeout=0.5)
        if halt_fails:
            assert job.state == "failed"
            assert job.result is None
            assert "STOP failed" in job.error
            assert c._fleet_motion_owner == job.id
        else:
            assert job.state == "succeeded"
            assert job.result["ok"] is True
            assert c._fleet_motion_owner is None
    finally:
        release.set()
        head.command = original
        await c.stop("robot-01")
        await c.close()


async def test_manual_command_rejection_precedes_permit_consumption_and_dispatch(settings):
    c, head = make(settings)
    try:
        await c.operator_arm("robot-01")
        expiry = c.permits["robot-01"]
        for command in (
            "drive 41 0 100", "drive 0 0 251", "drive 0 0 0",
            "drive 0 0 nan", "drive 0  0 100", "drive 0 0 100\narm",
            "lift 59", "grip 121", "rearm", "stop extra",
        ):
            with pytest.raises(ValueError):
                c.manual("robot-01", command)
        for command in ("arm", "keepalive", "stop", "halt", "disarm", "ping", "status"):
            with pytest.raises(OperationError, match="Manual movement requires"):
                c.manual("robot-01", command)
        assert head.commands == []
        assert not c.jobs and not c.tasks
        assert c._fleet_motion_owner is None
        assert c.permits["robot-01"] == expiry

        job = c.manual("robot-01", "drive -40 40 1")
        await asyncio.wait_for(c.tasks[job.id], timeout=2)
        assert job.state == "succeeded", job.error
        assert head.commands.count("drive -40 40 1") == 1
        assert head.commands[-1] == "halt"
        assert "robot-01" not in c.permits
    finally:
        await c.close()


async def test_voice_during_operator_preflight_never_grants_permit(settings):
    c, head = make(settings)
    started, resume = asyncio.Event(), asyncio.Event()
    original = c._hardware_preflight

    async def gated_preflight(robot_id):
        await original(robot_id)
        started.set()
        await resume.wait()

    c._hardware_preflight = gated_preflight
    task = asyncio.create_task(c.operator_arm("robot-01"))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        c.set_voice_state(active_robots={"robot-02"})
        resume.set()
        with pytest.raises(OperationError, match="Voice priority"):
            await asyncio.wait_for(task, timeout=2)
        assert "robot-01" not in c.permits
        assert head.commands == []
    finally:
        resume.set()
        await asyncio.gather(task, return_exceptions=True)
        await c.close()


@pytest.mark.parametrize("stage", ["queued", "preflight", "arm_receipt"])
async def test_voice_before_actuation_fences_new_motion_job(settings, stage):
    c, head = make(settings)
    started, resume = asyncio.Event(), asyncio.Event()
    original_preflight = c._hardware_preflight
    original_command = head.command

    async def gated_preflight(robot_id):
        await original_preflight(robot_id)
        started.set()
        await resume.wait()

    async def gated_command(command):
        result = await original_command(command)
        if command == "arm":
            started.set()
            await resume.wait()
        return result

    try:
        await c.operator_arm("robot-01")
        if stage == "preflight":
            c._hardware_preflight = gated_preflight
        elif stage == "arm_receipt":
            head.command = gated_command
        job = c.manual("robot-01", "drive 10 10 100")
        if stage != "queued":
            await asyncio.wait_for(started.wait(), timeout=2)
        c.set_voice_state(active_robots={"robot-02"})
        resume.set()
        await asyncio.wait_for(c.tasks[job.id], timeout=2)
        assert job.state == "failed"
        assert "Voice priority" in job.error
        assert head.commands == (
            ["arm", "halt"] if stage == "arm_receipt" else ["halt"]
        )
        assert c._fleet_motion_owner is None
    finally:
        resume.set()
        await c.close()


async def test_deferred_motion_expiry_rechecked_after_preflight(settings):
    c, head = make(settings)
    started, resume = asyncio.Event(), asyncio.Event()
    original = c._hardware_preflight
    task = None

    async def gated_preflight(robot_id):
        await original(robot_id)
        started.set()
        await resume.wait()

    try:
        await c.operator_arm("robot-01")
        c.set_voice_state(active_robots={"robot-02"})
        request = c.defer_motion(
            "robot-01", "manual",
            submit_fn=lambda: c.manual("robot-01", "drive 10 10 100"),
        )
        c.set_voice_state(active_robots=set())
        c._hardware_preflight = gated_preflight
        task = asyncio.create_task(c.dispatch_next_deferred())
        await asyncio.wait_for(started.wait(), timeout=2)
        # Move the deadline behind the current clock at the exact IO barrier.
        request.expires_at = time.monotonic() - 1
        resume.set()
        assert await asyncio.wait_for(task, timeout=2) is None
        assert request.state == "expired"
        assert not c.permits
        assert not c.jobs
        assert head.commands == []
    finally:
        resume.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await c.close()


async def test_motion_disabled_during_operator_preflight_never_creates_permit(settings):
    settings.mode = "hardware"
    started, resume = asyncio.Event(), asyncio.Event()
    head = HardwareStatusHead("robot-01")
    original_status = head.status

    async def delayed_status():
        started.set()
        await resume.wait()
        return await original_status()

    head.status = delayed_status
    c = Coordinator(settings, {"robot-01": head}, SimulationVision())
    pending = asyncio.create_task(c.operator_arm("robot-01"))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        settings.robots[0].motion_enabled = False
        resume.set()
        with pytest.raises(OperationError, match="motion_enabled=false"):
            await asyncio.wait_for(pending, timeout=1)
        assert "robot-01" not in c.permits
        assert head.commands == []
    finally:
        resume.set()
        await asyncio.gather(pending, return_exceptions=True)
        await c.close()


@pytest.mark.parametrize("stage", ["queued", "preflight", "arm_receipt"])
async def test_motion_disabled_before_manual_dispatch(settings, stage):
    settings.mode = "hardware"
    started, resume = asyncio.Event(), asyncio.Event()
    head = HardwareStatusHead("robot-01")
    original_status = head.status
    original_command = head.command
    c = Coordinator(settings, {"robot-01": head}, SimulationVision())

    async def gated_status():
        started.set()
        await resume.wait()
        return await original_status()

    async def gated_command(command):
        result = await original_command(command)
        if command == "arm":
            started.set()
            await resume.wait()
        return result

    try:
        await c.operator_arm("robot-01")
        if stage == "preflight":
            head.status = gated_status
        elif stage == "arm_receipt":
            head.command = gated_command
        job = c.manual("robot-01", "drive 20 20 100")
        if stage != "queued":
            await asyncio.wait_for(started.wait(), timeout=1)
        settings.robots[0].motion_enabled = False
        resume.set()
        await asyncio.wait_for(c.tasks[job.id], timeout=2)
        assert job.state == "failed"
        assert "motion_enabled=false" in job.error
        assert job.result is None
        assert head.commands == (
            ["arm", "halt"] if stage == "arm_receipt" else ["halt"]
        )
        assert "robot-01" not in c.permits
        assert c._fleet_motion_owner is None
    finally:
        resume.set()
        await c.close()

async def test_tactile_pickup_fleet_owner_covers_contact_release_and_halt(settings, tmp_path):
    """Replay real Mac grasp code with synthetic WROOM and live-frame receipts."""
    import json

    calibration = json.loads(settings.robots[0].calibration.read_text())
    calibration.update(
        simulation_only=False, hold_seconds=3,
        grip_force_delta_raw=100, grip_force_limit_raw=500,
    )
    measured = tmp_path / "synthetic-grasp-calibration.json"
    measured.write_text(json.dumps(calibration))
    settings.robots[0].calibration = measured
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    c, _ = make(settings)
    head = HardwareStatusHead("robot-01")
    peer = HardwareStatusHead("robot-02")
    c.heads.update({"robot-01": head, "robot-02": peer})
    contact_pending = asyncio.Event()
    allow_contact = asyncio.Event()
    halt_pending = asyncio.Event()
    allow_halt = asyncio.Event()
    seq = 0
    original_command = head.command
    original_status = head.status

    async def status():
        body = await original_status()
        head._watchdog(time.monotonic())
        return {**body, "armed": head.armed, "imu": {**body["imu"], "boot_id": 1}}

    async def aux_status():
        nonlocal seq
        seq += 1
        if head.gripped and not contact_pending.is_set():
            contact_pending.set()
            await allow_contact.wait()
        return {
            "robot_id": head.id,
            "force": {
                "jaw_valid": True, "calibrated": False,
                "adc": [0, 350 if head.gripped else 100],
                "jaw_seq": seq, "jaw_age_ms": 0, "boot_id": 1,
            },
        }

    async def command(value):
        receipt = await original_command(value)
        if value == "halt" and not halt_pending.is_set():
            halt_pending.set()
            await allow_halt.wait()
        return receipt

    head.status = status
    head.aux_status = aux_status
    head.command = command
    frames = []

    async def wait_for_frame(robot_id, after, *, timeout_s):
        assert robot_id == head.id
        jpeg = await head.snapshot()
        frames[:] = [SimpleNamespace(
            source="proactive", jpeg=jpeg, received_at=time.monotonic(),
        )]
        return True

    c.multimodal = SimpleNamespace(
        settings=settings,
        stream_owns_camera=lambda _id: True,
        status=lambda _id: {"camera_stream_connected": True},
        hub=SimpleNamespace(frames={head.id: frames}),
        wait_for_proactive_frame=wait_for_frame,
    )
    try:
        await c.operator_arm(head.id)
        await c.operator_arm(peer.id)
        job = c.pickup(head.id, "key")
        # Admission is synchronous, even before the pickup task runs.
        assert c._fleet_motion_owner == job.id
        with pytest.raises(OperationError, match="one moving pet"):
            c.manual(peer.id, "drive 10 10 100")
        await asyncio.wait_for(contact_pending.wait(), timeout=12)
        assert head.gripped and c._fleet_motion_owner == job.id
        assert job.state == "running" and job.result is None
        with pytest.raises(OperationError, match="one moving pet"):
            c.manual(peer.id, "drive 10 10 100")
        with pytest.raises(OperationError, match="Robot busy"):
            await c.operator_arm(head.id)
        assert "robot-02" in c.permits and peer.commands == []
        contact_command_count = len(head.commands)
        allow_contact.set()

        await asyncio.wait_for(halt_pending.wait(), timeout=10)
        # Verified placement and jaw opening alone cannot release ownership:
        # the terminal HALT receipt is still in flight.
        assert not head.gripped
        assert c._fleet_motion_owner == job.id and job.result is None
        assert not any(cmd.startswith("drive ") for cmd in head.commands[contact_command_count:])
        with pytest.raises(OperationError, match="one moving pet"):
            c.manual(peer.id, "drive 10 10 100")
        assert peer.commands == []
        allow_halt.set()
        await c.tasks[job.id]
        assert job.state == "succeeded", job.error
        assert job.result["placed_visually_verified"]
        assert job.result["physical_acceptance_pass"] is False
        assert any(event.startswith("tactile contact delta=") for event in job.events)
        assert c._fleet_motion_owner is None

        next_job = c.manual(peer.id, "drive 10 10 100")
        await c.tasks[next_job.id]
        assert next_job.state == "succeeded", next_job.error
        assert peer.commands.count("drive 10 10 100") == 1
        assert peer.commands[-1] == "halt"
    finally:
        allow_contact.set()
        allow_halt.set()
        await c.close()


async def test_pickup_camera_receipts_follow_motion_and_hold_boundaries(settings):
    """A cached frame newer than the last observation may still predate actuation."""
    c, head = make(settings)
    original_command = head.command
    original_observe = c._observe
    latest_motion_at = float("-inf")
    first_held_at = None
    checked = []

    async def command(value):
        nonlocal latest_motion_at
        result = await original_command(value)
        if value.startswith(("grip ", "lift ", "drive ")) or value == "stop":
            latest_motion_at = time.monotonic()
        return result

    async def observe(robot_id, target, calibration, *, after, camera_grant):
        nonlocal first_held_at
        # This is the actual cutoff passed to the live MJPEG selector, even
        # though the simulator itself always takes a fresh synthetic image.
        assert after >= latest_motion_at
        result = await original_observe(
            robot_id, target, calibration, after=after, camera_grant=camera_grant,
        )
        checked.append(after)
        if (
            head.commands.count(f"lift {calibration.lift_up}") == 1
            and head.commands.count(f"grip {calibration.grip_open}") == 1
        ):
            if first_held_at is None:
                first_held_at = result[1]
            else:
                assert after >= first_held_at + calibration.hold_seconds
        return result

    head.command = command
    c._observe = observe
    try:
        await c.operator_arm("robot-01")
        job = c.pickup("robot-01", "key")
        await c.tasks[job.id]
        assert job.state == "succeeded", job.error
        assert len(checked) >= 6
        assert first_held_at is not None
        assert job.result["physical_acceptance_pass"] is False
    finally:
        await c.close()


@pytest.mark.parametrize("phase", ["grip", "lift", "drive", "stop"])
async def test_pickup_fails_when_command_ack_is_lost(settings, phase):
    c, head = make(settings)
    original = head.command

    async def dropped_ack(command):
        receipt = await original(command)
        if command.split()[0] == phase:
            return None
        return receipt

    head.command = dropped_ack
    try:
        await c.operator_arm("robot-01")
        job = c.pickup("robot-01", "key")
        await c.tasks[job.id]
        assert job.state == "failed"
        assert "Unmatched pickup command ACK" in job.error
        assert job.result is None
        assert head.commands[-1] == "halt"
    finally:
        await c.close()


async def test_pickup_final_inference_cannot_hide_body_disarm(settings):
    c, head = make(settings)
    original = c._observe
    placement_frames = 0

    async def observe(robot_id, target, calibration, *, after, camera_grant):
        nonlocal placement_frames
        result = await original(
            robot_id, target, calibration, after=after, camera_grant=camera_grant,
        )
        if head.commands.count(f"lift {calibration.lift_up}") == 2:
            placement_frames += 1
            if placement_frames == 2:
                head.armed = False
        return result

    c._observe = observe
    try:
        await c.operator_arm("robot-01")
        job = c.pickup("robot-01", "key")
        await c.tasks[job.id]
        assert placement_frames == 2
        assert job.state == "failed"
        assert job.result is None
        assert head.commands[-1] == "halt"
        assert "two frames support placement after jaw withdrawal" not in job.events
    finally:
        await c.close()
