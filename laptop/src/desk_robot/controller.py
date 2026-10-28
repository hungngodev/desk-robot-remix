from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
import time
import uuid
from typing import Awaitable, Callable

from .calibration import Calibration
from .config import Settings
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

    async def operator_arm(self, robot_id: str):
        robot = self.robot(robot_id)
        if not robot.motion_enabled:
            raise OperationError("motion_enabled=false; no arm sent")
        if self.locks[robot_id].locked():
            raise OperationError("Robot busy")
        self.permits[robot_id] = time.monotonic() + 30
        return {"robot_id": robot_id, "operator_permit": True, "expires_in_seconds": 30,
                "physical_armed": False, "note": "One bounded job may consume this permit; no idle keepalive"}

    async def stop(self, robot_id: str):
        self.robot(robot_id)
        self.permits.pop(robot_id, None)
        running = [task for jid, task in self.tasks.items()
                   if self.jobs[jid].robot_id == robot_id and not task.done()]
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        return await self.heads[robot_id].command("stop")

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
        if self.closed or self.locks[robot_id].locked() or any(
                j.robot_id == robot_id and j.state in {"queued", "running"} for j in self.jobs.values()):
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
            await asyncio.sleep(.1)

    async def _run(self, job: Job, work):
        async with self.locks[job.robot_id]:
            job.state = "running"
            keeper = None
            operation = None
            try:
                await self.heads[job.robot_id].command("arm")  # only after consuming operator permit
                keeper = asyncio.create_task(self._keepalive(job.robot_id))
                operation = asyncio.create_task(work(job))
                # A failed keepalive cancels the operation immediately; do not continue blindly.
                async with asyncio.timeout(self.settings.max_job_seconds):
                    done, _ = await asyncio.wait({keeper, operation}, return_when=asyncio.FIRST_COMPLETED)
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
                await asyncio.gather(*(t for t in (operation, keeper) if t), return_exceptions=True)
                try:
                    await self.heads[job.robot_id].command("stop")
                    job.events.append("stop acknowledged; servo positions are commanded, not measured")
                except Exception as exc:
                    job.error = f"{job.error or ''}; STOP failed: {exc}; rely on body watchdog"
                    job.state = "failed"

    def manual(self, robot_id: str, command: str) -> Job:
        robot = self.robot(robot_id)
        op = validate_command(command)
        if not robot.motion_enabled or op not in {"drive", "lift", "grip"}:
            raise OperationError("Manual movement requires motion_enabled and drive/lift/grip command")

        async def work(job):
            result = await self.heads[robot_id].command(command)
            if op == "drive":
                await asyncio.sleep(int(command.split()[3]) / 1000)
            else:
                await asyncio.sleep(2)  # bounded ramp/settling; does not claim measured position
            return result
        return self._submit(robot_id, "manual", work)

    def pickup(self, robot_id: str, target: str) -> Job:
        robot = self.robot(robot_id)
        if target not in {"key", "candy"}:
            raise OperationError("Pickup target must be key or candy")
        if not robot.motion_enabled or robot.calibration is None:
            raise OperationError("Pickup requires motion_enabled=true and measured calibration")
        calibration = Calibration.load(robot.calibration)
        calibration.verify_ready()
        return self._submit(robot_id, "pickup", lambda job: self._pickup(job, target, calibration))

    async def _observe(self, robot_id: str, target: str, c: Calibration) -> Detection:
        jpeg = await self.heads[robot_id].snapshot()
        if image_size(jpeg) != (c.image_width, c.image_height):
            raise OperationError("Camera resolution differs from measured calibration")
        objects = [d for d in await self.vision.detect(jpeg, target)
                   if d.label == target and d.confidence >= c.min_confidence
                   and 0 <= d.box[0] < d.box[2] <= c.image_width
                   and 0 <= d.box[1] < d.box[3] <= c.image_height]
        if len(objects) != 1:
            raise OperationError("Lost or ambiguous target; stop and request operator intervention")
        return objects[0]

    async def _pickup(self, job: Job, target: str, c: Calibration) -> dict:
        head = self.heads[job.robot_id]
        await head.command(f"grip {c.grip_open}")
        await head.command(f"lift {c.lift_down}")
        await asyncio.sleep(c.servo_settle_seconds)
        initial = None
        for attempt in range(24):
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
                command = f"drive {direction*20} {-direction*20} 100"
            else:
                direction = (1 if dy > 0 else -1) * c.forward_sign
                command = f"drive {direction*20} {direction*20} 100"
            await head.command(command)  # exactly once: an uncertain ACK is a failure
            await asyncio.sleep(.12)
            await head.command("stop")
        if initial is None:
            raise OperationError("Alignment attempt limit reached")
        await head.command(f"grip {c.grip_closed}")
        await asyncio.sleep(c.servo_settle_seconds)
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
            detection = await self._observe(job.robot_id, target, c)
            px, py = detection.center
            if not (a <= px <= x and b <= py <= y):
                raise OperationError("Pickup unverified: target not in calibrated raised-jaw region")
            if initial.center[1] - py < c.min_lift_displacement_px:
                raise OperationError("Pickup unverified: insufficient upward image displacement")
            if c.within(c.ground(detection.center)):
                raise OperationError("Pickup unverified: target still projects into ground work area")
            observed.append(detection.center)
        if abs(observed[0][0] - observed[1][0]) > 10 or abs(observed[0][1] - observed[1][1]) > 10:
            raise OperationError("Pickup unverified: target did not remain stable in raised-jaw region")
        return {"visually_verified": True, "criterion": "two fresh raised-jaw frames, upward displacement, outside floor region",
                "physical_acceptance_pass": False, "target": target,
                "note": "Visual evidence is experimental, not force sensing or a physical acceptance trial"}
