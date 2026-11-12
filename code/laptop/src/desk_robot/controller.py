from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Awaitable, Callable

from .calibration import Calibration
from .config import Settings
from .dock_runtime import load_real_dock_calibration
from .dock_vision import assess_dock, detect_apriltag
from .grasp_feedback import guarded_grasp
from .transport import Head, validate_command
from .vision import Detection, Vision, image_size


class OperationError(RuntimeError):
    pass


@dataclass
class Job:
    id: str
    robot_id: str
    kind: str
    state: str = "queued"
    result: dict | None = None
    error: str | None = None
    events: list[str] = field(default_factory=list)

    def data(self):
        return asdict(self)


class Coordinator:
    def __init__(self, settings: Settings, heads: dict[str, Head], vision: Vision):
        self.settings = settings
        self.heads = heads
        self.vision = vision
        self.locks = {r.id: asyncio.Lock() for r in settings.robots}
        self.jobs: dict[str, Job] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.closed = False
        self.permits: dict[str, float] = {}

    def robot(self, robot_id):
        try:
            return self.settings.robot(robot_id)
        except KeyError as exc:
            raise OperationError("Unknown robot") from exc

    async def _hardware_preflight(self, robot_id: str) -> None:
        """Read the actual WROOM safety state, never infer safety from a permit.

        The head transports this status from the body UART. This is an extra
        software refusal gate, not a substitute for the WROOM's independent
        fail-closed cliff, touch and watchdog enforcement.
        """
        if self.settings.mode != "hardware":
            return
        status = await self.heads[robot_id].status()
        if not isinstance(status, dict) or status.get("robot_id") != robot_id:
            raise OperationError("Hardware preflight: body identity missing or mismatched")
        if status.get("backend") != "stepper_28byj48" or status.get("armed") is not False:
            raise OperationError("Hardware preflight: stepper body must be present and disarmed")
        touch = status.get("touch")
        if not isinstance(touch, dict) or touch.get("active") is not False:
            raise OperationError("Hardware preflight: touch input unavailable or pressed")
        safety = status.get("safety")
        if (
            not isinstance(safety, dict)
            or safety.get("required") is not True
            or safety.get("ready") is not True
            or safety.get("fault") != "none"
        ):
            raise OperationError("Hardware preflight: five-channel local safety not clear")
        # Fresh six-axis identity and data are compulsory in the actual WROOM
        # motion profile. This is only a presence/freshness gate; no unmeasured
        # tilt angle or handheld state is inferred from raw sensor units.
        imu = status.get("imu")
        if (
            not isinstance(imu, dict)
            or type(imu.get("family")) is not int
            or imu["family"] not in (1, 2, 3, 4)
            or imu.get("valid") is not True
            or type(imu.get("age_ms")) is not int
            or not 0 <= imu["age_ms"] <= 200
            or any(
                not isinstance(imu.get(axis), list)
                or len(imu[axis]) != 3
                or any(type(v) is not int or not -32768 <= v <= 32767
                       for v in imu[axis])
                for axis in ("acc", "gyro")
            )
        ):
            raise OperationError("Hardware preflight: six-axis IMU missing or stale")
        ranges = status.get("ranges")
        if not isinstance(ranges, dict):
            raise OperationError("Hardware preflight: range diagnostics unavailable")
        if (
            type(ranges.get("present_mask")) is not int
            or ranges["present_mask"] != 31
            or type(ranges.get("valid_mask")) is not int
            or ranges["valid_mask"] != 31
        ):
            raise OperationError("Hardware preflight: missing or invalid ToF channels")
        ages = ranges.get("age_ms")
        readings = ranges.get("mm")
        if (
            not isinstance(ages, list) or len(ages) != 5
            or not isinstance(readings, list) or len(readings) != 5
            or any(type(age) is not int or not 0 <= age < 200 for age in ages)
            or any(type(mm) is not int or not 1 <= mm <= 1300 for mm in readings)
        ):
            raise OperationError("Hardware preflight: stale or malformed ranging telemetry")

    async def operator_arm(self, robot_id: str):
        robot = self.robot(robot_id)
        if self.closed:
            raise OperationError("Coordinator closing")
        if not robot.motion_enabled:
            raise OperationError("motion_enabled=false; no arm sent")
        if self.locks[robot_id].locked() or any(
            j.robot_id == robot_id and j.state in {"queued", "running"} for j in self.jobs.values()
        ):
            raise OperationError("Robot busy")
        self.permits.pop(robot_id, None)
        await self._hardware_preflight(robot_id)
        self.permits[robot_id] = time.monotonic() + 30
        return {
            "robot_id": robot_id,
            "operator_permit": True,
            "expires_in_seconds": 30,
            "physical_armed": False,
            "note": "One bounded job may consume this permit; no idle keepalive",
        }

    async def stop(self, robot_id: str):
        self.robot(robot_id)
        self.permits.pop(robot_id, None)
        running = [
            task
            for jid, task in self.tasks.items()
            if self.jobs[jid].robot_id == robot_id and not task.done()
        ]
        for task in running:
            task.cancel()
        # Stop physical wheels FIRST. A canceled job can be stuck in camera,
        # network or model cleanup; waiting for it would delay the real WROOM
        # stop command despite an urgent operator or human request.
        try:
            acknowledgement = await self.heads[robot_id].command("stop")
        finally:
            if running:
                # asyncio.wait_for(gather(...)) is NOT bounded if a task
                # catches cancellation. A wait() set timeout returns even
                # when an uncooperative child refuses to finish.
                done, pending = await asyncio.wait(running, timeout=2.0)
                for task in done:
                    if not task.cancelled():
                        task.exception()  # observe any failure
                if pending:
                    for jid, task in self.tasks.items():
                        if (self.jobs[jid].robot_id == robot_id
                                and task in pending):
                            self.jobs[jid].state = "failed"
                            self.jobs[jid].error = "Cancelled job ignored timeout; WROOM stop dispatched"
        for jid, task in self.tasks.items():
            if self.jobs[jid].robot_id == robot_id and task.cancelled():
                self.jobs[jid].state = "cancelled"
                self.jobs[jid].error = "Operator cancelled before job started"
        return acknowledgement

    async def close(self):
        self.closed = True
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    def _submit(self, robot_id: str, kind: str, work: Callable[[Job], Awaitable[dict]]) -> Job:
        self.robot(robot_id)
        if self.permits.get(robot_id, 0) < time.monotonic():
            self.permits.pop(robot_id, None)
            raise OperationError("Operator permit missing or expired; enable one operation first")
        if (
            self.closed
            or (
                self.settings.mode == "hardware"
                and any(
                    job.robot_id != robot_id and job.state in {"queued", "running"}
                    for job in self.jobs.values()
                )
            )
            or self.locks[robot_id].locked()
            or any(
                j.robot_id == robot_id and j.state in {"queued", "running"}
                for j in self.jobs.values()
            )
        ):
            raise OperationError("Robot busy or coordinator closing")
        # Retain only bounded history; never accumulate infinite tasks/results in a long-running server.
        if len(self.jobs) >= 100:
            for jid in list(self.jobs):
                if self.tasks[jid].done():
                    del self.jobs[jid]
                    del self.tasks[jid]
                    break
        self.permits.pop(robot_id, None)  # consume once, even if ACK/job later fails
        job = Job(uuid.uuid4().hex, robot_id, kind)
        self.jobs[job.id] = job
        self.tasks[job.id] = asyncio.create_task(self._run(job, work))
        return job

    async def _keepalive(self, robot_id: str):
        while True:
            await self.heads[robot_id].command("keepalive")
            await asyncio.sleep(0.1)

    async def _run(self, job: Job, work):
        async with self.locks[job.robot_id]:
            job.state = "running"
            keeper = None
            operation = None
            try:
                # A head can disconnect, touch can be pressed and a floor
                # sample can expire after the operator granted the permit.
                # Recheck the real body immediately before requesting arm.
                await self._hardware_preflight(job.robot_id)
                await self.heads[job.robot_id].command(
                    "arm"
                )  # only after consuming operator permit
                keeper = asyncio.create_task(self._keepalive(job.robot_id))
                operation = asyncio.create_task(work(job))
                # A failed keepalive cancels the operation immediately; do not continue blindly.
                # Exploration is a single persistent operator-approved job;
                # never require another two-minute token while it is safely
                # running. Body pulses still expire in <=250ms and the local
                # 500ms watchdog remains independent of the Mac.
                timeout = None if job.kind == "exploration" else self.settings.max_job_seconds
                async with asyncio.timeout(timeout):
                    done, _ = await asyncio.wait(
                        {keeper, operation}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if keeper in done:
                        await keeper
                        raise OperationError("Keepalive ended unexpectedly")
                    job.result = await operation
                job.state = "succeeded"
            except asyncio.CancelledError:
                job.state = "cancelled"
                job.error = "Operator cancelled"
            except Exception as exc:
                job.state = "failed"
                job.error = str(exc) or type(exc).__name__
            finally:
                for task in (operation, keeper):
                    if task is not None and not task.done():
                        task.cancel()
                # Dispatch WROOM stop before potentially slow canceled camera
                # or model cleanup. No second actor may treat this as charging.
                try:
                    await self.heads[job.robot_id].command("stop")
                    job.events.append(
                        "stop acknowledged; servo positions are commanded, not measured"
                    )
                except Exception as exc:
                    job.error = f"{job.error or ''}; STOP failed: {exc}; rely on body watchdog"
                    job.state = "failed"
                pending = [t for t in (operation, keeper) if t is not None]
                if pending:
                    done, unresponsive = await asyncio.wait(
                        pending, timeout=2.0
                    )
                    for task in done:
                        if not task.cancelled():
                            task.exception()
                    if unresponsive:
                        job.error = (
                            f"{job.error or ''}; cancellation cleanup timed out"
                        )
                        job.state = "failed"

    def manual(self, robot_id: str, command: str) -> Job:
        robot = self.robot(robot_id)
        op = validate_command(command)
        if not robot.motion_enabled or op not in {"drive", "lift", "grip"}:
            raise OperationError(
                "Manual movement requires motion_enabled and drive/lift/grip command"
            )

        async def work(job):
            result = await self.heads[robot_id].command(command)
            if op == "drive":
                parts = command.split()
                duration_ms = int(parts[3]) if len(parts) == 4 else 250
                await asyncio.sleep(duration_ms / 1000)
            else:
                await asyncio.sleep(2)  # bounded ramp/settling; does not claim measured position
            return result

        return self._submit(robot_id, "manual", work)

    async def _assert_armed_health(
        self, robot_id: str, *, require_front_clearance: bool = False
    ) -> dict:
        """Recheck WROOM local sensor verdict before every physical movement.

        This is shared by sustained exploration and each pickup phase.
        A remote status never clears a local fault or creates a new permit.
        """
        body = await self.heads[robot_id].status()
        if not isinstance(body, dict) or body.get("armed") is not True:
            raise OperationError("Operation stopped: body disarmed or unavailable")
        if self.settings.mode != "hardware":
            return body
        safety = body.get("safety")
        ranges = body.get("ranges")
        imu = body.get("imu")
        touch = body.get("touch")
        if (
            not isinstance(safety, dict)
            or safety.get("required") is not True
            or safety.get("ready") is not True
            or safety.get("fault") != "none"
            or not isinstance(ranges, dict)
            or type(ranges.get("present_mask")) is not int
            or ranges["present_mask"] != 31
            or type(ranges.get("valid_mask")) is not int
            or ranges["valid_mask"] != 31
            or not isinstance(ranges.get("mm"), list)
            or len(ranges["mm"]) != 5
            or not isinstance(ranges.get("age_ms"), list)
            or len(ranges["age_ms"]) != 5
            or any(type(n) is not int or not 1 <= n <= 1300 for n in ranges["mm"])
            or any(type(age) is not int or not 0 <= age <= 150
                   for age in ranges["age_ms"])
            or (require_front_clearance and ranges["mm"][4] <= 250)
            or not isinstance(imu, dict)
            or imu.get("valid") is not True
            or type(imu.get("age_ms")) is not int
            or not 0 <= imu["age_ms"] <= 200
            or not isinstance(touch, dict)
            or touch.get("active") is not False
        ):
            raise OperationError("Operation blocked by local sensor or corridor")
        return body

    def explore(self, robot_id: str) -> Job:
        """Start operator enabled, persistent but locally guarded exploration.

        Movement always uses the same Coordinator._run session and WROOM local
        cliff/watchdog authority as pickup. No model free-text can choose speed
        or send bypass commands. Firmware and physical swept-space qualification
        are necessary before enabling this on an assembled desk.
        """
        robot = self.robot(robot_id)
        if not robot.motion_enabled:
            raise OperationError("Exploration requires motion_enabled=true")
        if self.settings.mode == "hardware" and not robot.exploration_qualified:
            raise OperationError(
                "Hardware exploration needs measured swept-path qualification"
            )
        return self._submit(robot_id, "exploration", self._explore)

    async def _explore(self, job: Job) -> dict:
        head = self.heads[job.robot_id]
        steps = 0
        # This loop persists until a stop, quiet mode, failure, or disconnect.
        # There is no unbounded drive: every track movement expires after 100ms.
        while True:
            await self._assert_armed_health(job.robot_id, require_front_clearance=True)
            # The reused Sense camera source must be alive before and after
            # each short pulse; an image does not by itself prove a clear path.
            await asyncio.wait_for(head.snapshot(), timeout=2.0)
            # A camera request can hang while a local cliff, touch or IMU
            # fault disarms WROOM. Never drive from a pre-camera verdict.
            await self._assert_armed_health(job.robot_id, require_front_clearance=True)
            await head.command("drive 20 20 100")
            await asyncio.sleep(0.12)
            await head.command("stop")
            steps += 1
            if len(job.events) >= 96:
                job.events.pop(0)
            job.events.append(f"bounded exploration pulse {steps}, stopped for reobservation")
            await asyncio.wait_for(head.snapshot(), timeout=2.0)
            # No blind reverse/turn when only one forward beam exists. Swept
            # turns need real footprint and obstacle qualification.
            await asyncio.sleep(0.35)

    def dock(self, robot_id: str) -> Job:
        """Permit-gated camera approach ending BEFORE unqualified charge contacts."""
        robot = self.robot(robot_id)
        if not robot.motion_enabled or not robot.dock_motion_qualified:
            raise OperationError("Dock motion requires measured physical qualification")
        if self.settings.mode != "hardware":
            raise OperationError("Dock approach requires physically qualified hardware")
        if robot.dock_turn_sign not in (-1, 1) or robot.dock_forward_sign not in (-1, 1):
            raise OperationError("Dock turn and forward motor polarity are not measured")
        try:
            camera, target_mm = load_real_dock_calibration(robot.dock_calibration)
        except (OSError, ValueError, TypeError) as exc:
            raise OperationError(f"Dock calibration required: {exc}") from exc
        return self._submit(
            robot_id, "dock_approach",
            lambda job: self._dock_approach(
                job, camera, target_mm, robot.dock_turn_sign, robot.dock_forward_sign
            ),
        )

    async def _dock_approach(
        self, job: Job, camera, target_mm: float,
        turn_sign: int, forward_sign: int
    ) -> dict:
        """Real camera observations + local guard only; no charger operation."""
        head = self.heads[job.robot_id]
        for attempt in range(16):
            # Check before vision and AGAIN afterwards: camera and PnP may
            # pause for seconds while the hardware floor/front state changes.
            await self._assert_armed_health(
                job.robot_id, require_front_clearance=True
            )
            # Camera receipt time is NOT equivalent to image exposure time.
            # Local WROOM cliff stop remains mandatory for every short pulse.
            jpeg = await asyncio.wait_for(head.snapshot(), timeout=2.0)
            received_at = time.monotonic()
            # OpenCV PnP is CPU-heavy. Keep it off the Mac event loop so
            # human VAD and urgent speaker abort are not delayed by geometry.
            pose = await asyncio.wait_for(
                asyncio.to_thread(
                    detect_apriltag, jpeg, camera, captured_at=received_at
                ),
                timeout=2.0,
            )
            decision = assess_dock(
                pose, now=time.monotonic(), target_distance_mm=target_mm
            )
            job.events.append(f"dock observation {attempt}: {decision.phase}")
            if decision.phase == "hold":
                return {
                    "phase": "hold", "reason": decision.reason,
                    "charging_authorized": False, "physical_acceptance_pass": False,
                }
            # A healthy pre-camera response is NEVER reused as movement
            # authority after a slow snapshot or AprilTag inference.
            body = await self._assert_armed_health(
                job.robot_id, require_front_clearance=True
            )
            if decision.phase == "align":
                side = body.get("side_ranges")
                if (not isinstance(side, dict)
                        or type(side.get("valid_mask")) is not int
                        or side["valid_mask"] != 7
                        or not isinstance(side.get("age_ms"), list)
                        or len(side["age_ms"]) != 3
                        or any(type(n) is not int or not 0 <= n <= 350
                               for n in side["age_ms"])
                        or not isinstance(side.get("mm"), list)
                        or len(side["mm"]) != 3
                        or any(type(n) is not int or n < 300 for n in side["mm"])):
                    raise OperationError(
                        "Dock turn refused: side and rear clearance unqualified"
                    )
                direction = turn_sign if pose.x_mm > 0 else -turn_sign
                command = f"drive {20 * direction} {-20 * direction} 100"
            else:
                # Stopping at least 300mm away from a detected frontal surface
                # is intentional. The final cm and charging contacts need a
                # separate physical state machine with actual contact sensing.
                if body["ranges"]["mm"][4] < 350:
                    return {
                        "phase": "hold", "reason": "Front clearance stop",
                        "charging_authorized": False, "physical_acceptance_pass": False,
                    }
                command = f"drive {20 * forward_sign} {20 * forward_sign} 100"
            # The second fresh WROOM status request itself may take seconds.
            # It verifies sensor safety, not that the old AprilTag image is
            # still useful. Reject a marker that expired while polling safety.
            latest = assess_dock(
                pose, now=time.monotonic(), target_distance_mm=target_mm
            )
            if latest.phase != decision.phase:
                return {
                    "phase": "hold", "reason": latest.reason,
                    "charging_authorized": False, "physical_acceptance_pass": False,
                }
            await head.command(command)
            await asyncio.sleep(0.12)
            await head.command("stop")
            await asyncio.sleep(0.05)
        return {
            "phase": "hold",
            "reason": "Maximum guarded approach pulses reached",
            "charging_authorized": False, "physical_acceptance_pass": False,
        }

    def pickup(self, robot_id: str, target: str) -> Job:
        robot = self.robot(robot_id)
        if target not in {"key", "candy"}:
            raise OperationError("Pickup target must be key or candy")
        if not robot.motion_enabled or robot.calibration is None:
            raise OperationError("Pickup requires motion_enabled=true and measured calibration")
        calibration = Calibration.load(robot.calibration)
        calibration.verify_ready()
        if calibration.simulation_only and self.settings.mode != "simulation":
            raise OperationError("Simulation calibration cannot be used on hardware")
        if self.settings.mode == "hardware" and calibration.hold_seconds < 3:
            raise OperationError("Real pickup requires at least three seconds of verified hold")
        if self.settings.mode == "hardware" and calibration.grip_force_delta_raw is None:
            raise OperationError("Real pickup requires measured ADS1115 gripper contact threshold")
        return self._submit(robot_id, "pickup", lambda job: self._pickup(job, target, calibration))

    async def _observe(self, robot_id: str, target: str, c: Calibration) -> Detection:
        jpeg = await asyncio.wait_for(
            self.heads[robot_id].snapshot(), timeout=3.0
        )
        if image_size(jpeg) != (c.image_width, c.image_height):
            raise OperationError("Camera resolution differs from measured calibration")
        objects = [
            d
            for d in await asyncio.wait_for(
                self.vision.detect(jpeg, target), timeout=15.0
            )
            if d.label == target
            and d.confidence >= c.min_confidence
            and 0 <= d.box[0] < d.box[2] <= c.image_width
            and 0 <= d.box[1] < d.box[3] <= c.image_height
        ]
        if len(objects) != 1:
            raise OperationError("Lost or ambiguous target; stop and request operator intervention")
        return objects[0]

    async def _pickup(self, job: Job, target: str, c: Calibration) -> dict:
        head = self.heads[job.robot_id]
        await self._assert_armed_health(job.robot_id)
        await head.command(f"grip {c.grip_open}")
        await self._assert_armed_health(job.robot_id)
        await head.command(f"lift {c.lift_down}")
        await asyncio.sleep(c.servo_settle_seconds)
        initial = None
        for attempt in range(24):
            await self._assert_armed_health(job.robot_id)
            detection = await self._observe(job.robot_id, target, c)
            point = c.ground(detection.center)
            if not c.within(point):
                raise OperationError("Target outside calibrated work area")
            dx, dy = point[0] - c.grip_ground_mm[0], point[1] - c.grip_ground_mm[1]
            job.events.append(f"observe {attempt}: error_mm=({dx:.1f},{dy:.1f})")
            if abs(dx) <= c.alignment_tolerance_mm and abs(dy) <= c.alignment_tolerance_mm:
                initial = detection
                break
            if abs(dx) > c.alignment_tolerance_mm:
                direction = (1 if dx > 0 else -1) * c.turn_sign
                command = f"drive {direction * 20} {-direction * 20} 100"
            else:
                direction = (1 if dy > 0 else -1) * c.forward_sign
                command = f"drive {direction * 20} {direction * 20} 100"
            # Vision and geometry may have taken seconds. Never re-use the
            # pre-camera WROOM fault/IMU/cliff/bumper verdict for a drive.
            await self._assert_armed_health(job.robot_id)
            await head.command(command)  # exactly once: an uncertain ACK is a failure
            await asyncio.sleep(0.12)
            await head.command("stop")
            await self._assert_armed_health(job.robot_id)
        if initial is None:
            raise OperationError("Alignment attempt limit reached")
        await self._assert_armed_health(job.robot_id)
        if self.settings.mode == "hardware":
            tactile = await guarded_grasp(
                head, c, health=lambda: self._assert_armed_health(job.robot_id)
            )
            job.events.append(
                f"tactile contact delta={tactile['contact_delta_raw']} "
                f"commanded_angle={tactile['commanded_angle']}; not physical acceptance"
            )
        else:
            await head.command(f"grip {c.grip_closed}")
            await asyncio.sleep(c.servo_settle_seconds)
        await self._assert_armed_health(job.robot_id)
        await head.command(f"lift {c.lift_up}")
        await asyncio.sleep(c.servo_settle_seconds)
        # Image evidence: same category moves upward into measured raised-jaw region and remains
        # there in two fresh frames while wheels are stopped. A servo ACK alone never passes.
        await head.command("stop")
        a, b, x, y = c.lifted_roi_px
        observed = []
        for sample in range(2):
            if sample:
                await asyncio.sleep(c.hold_seconds)
            await self._assert_armed_health(job.robot_id)
            detection = await self._observe(job.robot_id, target, c)
            px, py = detection.center
            if not (a <= px <= x and b <= py <= y):
                raise OperationError(
                    "Pickup unverified: target not in calibrated raised-jaw region"
                )
            if initial.center[1] - py < c.min_lift_displacement_px:
                raise OperationError("Pickup unverified: insufficient upward image displacement")
            if c.within(c.ground(detection.center)):
                raise OperationError(
                    "Pickup unverified: target still projects into ground work area"
                )
            observed.append(detection.center)
        if abs(observed[0][0] - observed[1][0]) > 10 or abs(observed[0][1] - observed[1][1]) > 10:
            raise OperationError(
                "Pickup unverified: target did not remain stable in raised-jaw region"
            )
        # The existing pickup ended after a hold, leaving a real key or candy
        # suspended in the claw. Placement is a separate, observed phase: do
        # not open the jaws unless the object is visibly back over the
        # calibrated ground area. No blind wheel movement or drop command.
        job.events.append("lift and hold visually verified; begin supervised placement")
        await self._assert_armed_health(job.robot_id)
        await head.command(f"lift {c.lift_down}")
        await asyncio.sleep(c.servo_settle_seconds)
        lowered = await self._observe(job.robot_id, target, c)
        lowered_ground = c.ground(lowered.center)
        if (
            not c.within(lowered_ground)
            or max(abs(lowered_ground[i] - c.grip_ground_mm[i]) for i in (0, 1))
            > c.alignment_tolerance_mm * 2
        ):
            raise OperationError("Placement unverified: object not over calibrated release area")

        await self._assert_armed_health(job.robot_id)
        # Release only after observing the object near the table, then raise
        # the empty jaws to distinguish a placed object from one stuck in them.
        await head.command(f"grip {c.grip_open}")
        await asyncio.sleep(c.servo_settle_seconds)
        await self._assert_armed_health(job.robot_id)
        await head.command(f"lift {c.lift_up}")
        await asyncio.sleep(c.servo_settle_seconds)
        placed_positions = []
        for sample in range(2):
            if sample:
                await asyncio.sleep(0.15)
            await self._assert_armed_health(job.robot_id)
            placed = await self._observe(job.robot_id, target, c)
            ground = c.ground(placed.center)
            if (
                not c.within(ground)
                or max(abs(ground[i] - lowered_ground[i]) for i in (0, 1))
                > c.alignment_tolerance_mm * 2
            ):
                raise OperationError(
                    "Placement unverified: object not stable on calibrated ground"
                )
            placed_positions.append(ground)
        if max(
            abs(placed_positions[0][i] - placed_positions[1][i]) for i in (0, 1)
        ) > c.alignment_tolerance_mm:
            raise OperationError("Placement unverified: object moved after jaw withdrawal")
        job.events.append("two frames support placement after jaw withdrawal")
        return {
            "visually_verified": True,
            "placed_visually_verified": True,
            "criterion": "raised-jaw lift and hold followed by observed lower, release and stable placement",
            "physical_acceptance_pass": False,
            "target": target,
            "note": "Image evidence is experimental; no physical 10 mm lift or loaded object acceptance is claimed",
        }
