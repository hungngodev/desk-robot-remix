from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field, replace
from typing import Awaitable, Callable, TypeVar

from .calibration import Calibration
from .config import Settings
from .dock_ir import validate_ir
from .dock_runtime import (
    detect_bounded,
    load_real_dock_calibration,
    unpack_dock_frame,
    verify_selected_dock_frame,
)
from .dock_vision import assess_dock
from .grasp_feedback import guarded_grasp
from .object_search import ObjectSearchResult, summarize_search_observation
from .object_targets import ObjectTarget
from .transport import Head, HeadError, expected_ack, validate_command
from .vision import Detection, Vision, image_size

_T = TypeVar("_T")


async def _bounded_head_reply(coro: Awaitable[_T], *, seconds: float,
                              timeout_message: str) -> _T:
    """Bound even adapters that suppress task cancellation; ignore late replies."""
    # Callers may already own a cancellable snapshot task for VAD preemption.
    task = asyncio.ensure_future(coro)
    try:
        done, _ = await asyncio.wait({task}, timeout=seconds)
        if not done:
            raise TimeoutError(timeout_message)
        return await task
    finally:
        if not task.done():
            task.cancel()
            # A late transport failure must be observed, never accepted as a
            # delayed body STOP or as an authorization from a stale status.
            task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )


async def _bounded_body_stop(head: Head) -> dict:
    """Terminal user/task STOP must revoke WROOM arming, not just wheel speed.

    Use the existing body 'halt': motor targets zero, armed false, servo PWM
    retained for a held object. An HTTP ACK is a command receipt, not a
    physically measured wheel or grasp stop.
    """
    return await _bounded_head_reply(
        head.command("halt"), seconds=1.0,
        timeout_message="WROOM STOP transport acknowledgement unconfirmed",
    )


async def _bounded_pulse_stop(head: Head) -> dict:
    """Short supervised drive pulse; the same authorized job may continue."""
    return await _bounded_head_reply(
        head.command("stop"), seconds=1.0,
        timeout_message="WROOM pulse STOP transport acknowledgement unconfirmed",
    )


class OperationError(RuntimeError):
    pass


def _require_safe_fuel_sample(
    power: object, *, min_cell_mv: int, min_soc_centi: int,
    context: str, depleted_message: str,
) -> None:
    """Reject malformed claimed-valid fuel evidence before motion decisions.

    A missing optional power section or an explicit fuel_valid:false is not
    a current measurement. The independent WROOM still owns motor cutoffs.
    """
    if power is None:
        return
    if not isinstance(power, dict) or type(power.get("fuel_valid")) is not bool:
        raise OperationError(f"{context}: malformed battery telemetry")
    if power["fuel_valid"] is False:
        return
    cell_mv = power.get("cell_mv")
    soc_centi = power.get("soc_centi")
    if (type(cell_mv) is not int or not 2500 <= cell_mv <= 4500
            or type(soc_centi) is not int or not 0 <= soc_centi <= 10000):
        raise OperationError(f"{context}: malformed battery telemetry")
    if cell_mv < min_cell_mv or soc_centi < min_soc_centi:
        raise OperationError(depleted_message)


def _require_fresh_auto_dock_fuel(
    power: object, *, max_soc_centi: int, elapsed_ms: float,
) -> None:
    """An old low-battery request is not evidence that the pack is still low."""
    if (not isinstance(power, dict) or power.get("fuel_valid") is not True
            or type(power.get("fuel_seq")) is not int
            or not 1 <= power["fuel_seq"] <= 0xffffffff
            or type(power.get("fuel_age_ms")) is not int
            or not 0 <= power["fuel_age_ms"] < 500
            or type(elapsed_ms) not in (int, float) or not 0 <= elapsed_ms < 500
            or power["fuel_age_ms"] + elapsed_ms >= 500
            or type(power.get("soc_centi")) is not int
            or not 0 <= power["soc_centi"] <= max_soc_centi):
        raise OperationError("Autonomous dock requires fresh low battery evidence")


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


@dataclass
class DeferredMotionRequest:
    id: str
    robot_id: str
    kind: str
    expires_at: float
    queue_generation: int
    submit_fn: Callable[[], Job] = field(repr=False)
    consent_check: Callable[[], bool] | None = field(default=None, repr=False)
    state: str = "queued"  # queued, dispatched, discarded, expired, failed
    job_id: str | None = None
    error: str | None = None

    def data(self) -> dict:
        return {
            "id": self.id,
            "robot_id": self.robot_id,
            "kind": self.kind,
            "state": self.state,
            "job_id": self.job_id,
            "error": self.error,
        }


class Coordinator:
    def __init__(self, settings: Settings, heads: dict[str, Head], vision: Vision):
        self.settings = settings
        self.heads = heads
        self.vision = vision
        # Runtime injects its EXISTING continuous camera owner. Never create
        # an independent physical video client for exploration.
        self.multimodal = None
        self.locks = {r.id: asyncio.Lock() for r in settings.robots}
        # This initial fleet has ONE authorized moving pet at a time.
        # Keep ownership through WROOM STOP, not merely job-state changes.
        # A failed STOP latches the fleet until an explicit successful STOP.
        self._fleet_motion_owner: str | None = None
        self._motion_children: dict[str, tuple[asyncio.Task, ...]] = {}
        self.jobs: dict[str, Job] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.closed = False
        self.permits: dict[str, float] = {}
        self.shutdown_stop_failures: dict[str, str] = {}
        self._permit_epoch = {r.id: 0 for r in settings.robots}
        self._pending_stops: dict[str, int] = {}
        self._stop_generation = {r.id: 0 for r in settings.robots}
        self._unconfirmed_stops: set[str] = set()
        self._voice_active_robots: set[str] = set()
        self._voice_monitor_enforced = False
        self._voice_monitor_ready = True
        self._voice_stop_unconfirmed = False
        self._deferred_voice_queue: deque[DeferredMotionRequest] = deque()
        self._deferred_requests: dict[str, DeferredMotionRequest] = {}
        self._deferred_voice_generation = 0
        self._deferred_dispatch_lock: asyncio.Lock | None = None
        self._deferred_dispatch_task: asyncio.Task | None = None

    def robot(self, robot_id):
        try:
            return self.settings.robot(robot_id)
        except KeyError as exc:
            raise OperationError("Unknown robot") from exc

    async def _hardware_preflight(self, robot_id: str) -> dict | None:
        """Read the actual WROOM safety state, never infer safety from a permit.

        The head transports this status from the body UART. This is an extra
        software refusal gate, not a substitute for the WROOM's independent
        fail-closed cliff, touch and watchdog enforcement.
        """
        if self.settings.mode != "hardware":
            return
        robot = self.robot(robot_id)
        selected_backend = robot.motor_backend
        if selected_backend not in ("stepper_28byj48", "dc_pwm_guarded"):
            raise OperationError(
                "Hardware preflight: verified motor backend is not configured"
            )
        status = await _bounded_head_reply(
            self.heads[robot_id].status(), seconds=2.5,
            timeout_message="WROOM preflight status timeout",
        )
        if not isinstance(status, dict) or status.get("robot_id") != robot_id:
            raise OperationError("Hardware preflight: body identity missing or mismatched")
        if (status.get("backend") != selected_backend
                or robot.motor_backend != selected_backend):
            # A firmware swap or operator profile change cannot authorize an
            # actuator driver wired for a different physical assembly.
            raise OperationError(
                "Hardware preflight: motor backend differs from verified assembly"
            )
        if status.get("armed") is not False:
            raise OperationError("Hardware preflight: guarded body must be present and disarmed")
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
        _require_safe_fuel_sample(
            status.get("power"), min_cell_mv=3350, min_soc_centi=500,
            context="Hardware preflight",
            depleted_message="Hardware preflight: battery voltage critical (<3350 mV)",
        )
        return status

    async def operator_arm(self, robot_id: str, *, require_low_battery: bool = False):
        robot = self.robot(robot_id)
        if self.closed:
            raise OperationError("Coordinator closing")
        if not robot.motion_enabled:
            raise OperationError("motion_enabled=false; no arm sent")
        if robot_id in self._pending_stops or robot_id in self._unconfirmed_stops:
            raise OperationError("WROOM STOP pending or unconfirmed; require acknowledged halt")
        voice_reason = self.voice_blocks_motion()
        if voice_reason is not None:
            raise OperationError(voice_reason)
        if self.locks[robot_id].locked() or any(
            j.robot_id == robot_id and j.state in {"queued", "running"} for j in self.jobs.values()
        ):
            raise OperationError("Robot busy")
        # Retire any older in-flight preflight before awaiting the head.
        self._permit_epoch[robot_id] += 1
        owner_epoch = self._permit_epoch[robot_id]
        self.permits.pop(robot_id, None)
        request_at = time.monotonic()
        status = await self._hardware_preflight(robot_id)
        if require_low_battery:
            _require_fresh_auto_dock_fuel(
                status.get("power") if isinstance(status, dict) else None,
                max_soc_centi=robot.battery_low_percent * 100,
                elapsed_ms=(time.monotonic() - request_at) * 1000,
            )
        if not self.robot(robot_id).motion_enabled:
            raise OperationError("motion_enabled=false; no permit granted")
        voice_reason = self.voice_blocks_motion()
        if voice_reason is not None:
            raise OperationError(voice_reason)
        if (self.closed or self._permit_epoch[robot_id] != owner_epoch
                or self.locks[robot_id].locked()
                or any(j.robot_id == robot_id and j.state in {"queued", "running"}
                       for j in self.jobs.values())):
            raise OperationError("Operator arm superseded or robot became busy")
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
        # Fence new permits and fleet admission even for an idle body. An
        # explicit STOP without a job owner must still require a valid receipt.
        self._pending_stops[robot_id] = self._pending_stops.get(robot_id, 0) + 1
        self._stop_generation[robot_id] += 1
        generation = self._stop_generation[robot_id]
        try:
            acknowledgement = await self._stop(robot_id)
        except BaseException:
            if self._stop_generation[robot_id] == generation:
                self._unconfirmed_stops.add(robot_id)
            raise
        else:
            # An older HALT finishing cleanup cannot clear a newer failed
            # receipt. Only the latest explicit attempt owns this evidence.
            if self._stop_generation[robot_id] == generation:
                self._unconfirmed_stops.discard(robot_id)
            return acknowledgement
        finally:
            self._pending_stops[robot_id] -= 1
            if not self._pending_stops[robot_id]:
                del self._pending_stops[robot_id]

    async def _stop(self, robot_id: str):
        self.discard_deferred_motion(
            robot_id=robot_id,
            reason="STOP requested; deferred motion discarded",
        )
        self._permit_epoch[robot_id] += 1
        self.permits.pop(robot_id, None)
        running = [
            task
            for jid, task in self.tasks.items()
            if self.jobs[jid].robot_id == robot_id and not task.done()
        ]
        # Revoke the software operation immediately, even if a cancelled
        # third-party task catches CancelledError and refuses to finish.
        # The UI must not display "running" during an urgent STOP request.
        active_job_ids = [
            jid for jid, task in self.tasks.items()
            if self.jobs[jid].robot_id == robot_id and not task.done()
        ]
        for jid in active_job_ids:
            if self.jobs[jid].state in {"queued", "running"}:
                self.jobs[jid].state = "cancelled"
                self.jobs[jid].error = "STOP requested; WROOM acknowledgement pending"
        for task in running:
            task.cancel()
        # Stop physical wheels FIRST. A canceled job can be stuck in camera,
        # network or model cleanup; waiting for it would delay the real WROOM
        # stop command despite an urgent operator or human request.
        stop_acknowledged = False
        try:
            acknowledgement = await _bounded_body_stop(self.heads[robot_id])
            stop_acknowledged = True
        except BaseException:
            # A transport failure is not physical evidence of stopped wheels,
            # regardless of whether the cancelled job's Python task exited.
            for jid in active_job_ids:
                self.jobs[jid].state = "failed"
                self.jobs[jid].error = (
                    "WROOM physical STOP unconfirmed; rely on local watchdog"
                )
            raise
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
                            if stop_acknowledged:
                                self.jobs[jid].error = "Cancelled job ignored timeout; WROOM stop dispatched"
        for jid in active_job_ids:
            task = self.tasks[jid]
            if task.cancelled() and self.jobs[jid].state != "failed":
                # Only this STOP's jobs may change. A task cancelled before
                # its first instruction must not erase a failed STOP receipt.
                self.jobs[jid].state = "cancelled"
                self.jobs[jid].error = "Operator cancelled before job started"
        owner_id = getattr(self, "_fleet_motion_owner", None)
        if stop_acknowledged and owner_id is not None:
            owner = self.jobs.get(owner_id)
            owner_task = self.tasks.get(owner_id)
            if (owner is not None and owner_task is not None
                    and owner.robot_id == robot_id and owner_task.done()
                    and all(task.done() for task in self._motion_children.get(owner_id, ()))):
                # A completed abandoned job may have failed its final STOP.
                # The operator's *new* acknowledged halt is the only explicit
                # recovery; a STOP for some other pet cannot release it.
                for child in self._motion_children.pop(owner_id, ()):
                    if not child.cancelled():
                        child.exception()
                self._fleet_motion_owner = None
        return acknowledgement

    async def stop_active_exploration(self) -> tuple[str, ...]:
        """A real human voice or lost VAD monitor preempts optional roaming.

        Only autonomously exploring bodies are stopped. Do not cancel a
        manually initiated pickup, dock or other operator-approved job merely
        because another pet heard a voice. Reuse stop(), so outstanding WROOM
        permits are revoked and physical STOP is sent BEFORE job cleanup.
        Never automatically resume after speech_end or transport recovery.
        """
        active = tuple(sorted({
            job.robot_id for jid, job in self.jobs.items()
            if job.kind == "exploration"
            and job.state in {"queued", "running"}
            and jid in self.tasks
            and not self.tasks[jid].done()
        }))
        if not active:
            return ()
        for job in self.jobs.values():
            if job.robot_id in active and job.kind == "exploration":
                job.events.append("Autonomous roaming preempted by live human or monitor loss")
        results = await asyncio.gather(
            *(self.stop(robot_id) for robot_id in active),
            return_exceptions=True,
        )
        errors = [
            result for result in results if isinstance(result, BaseException)
        ]
        if errors:
            # A failed STOP is NOT proof the motors stopped. The WROOM local
            # watchdog is still required, and the monitoring caller sees the
            # unresolved physical abort rather than a fabricated success.
            raise OperationError(
                "Voice preemption of roaming: WROOM STOP unconfirmed"
            ) from errors[0]
        return active

    async def close(self):
        """Revoke permits and send bounded physical STOP before slow cleanup."""
        self.closed = True
        self.discard_deferred_motion(reason="Coordinator closing")
        dispatch_task = getattr(self, "_deferred_dispatch_task", None)
        if dispatch_task is not None and not dispatch_task.done():
            dispatch_task.cancel()
        self.shutdown_stop_failures.clear()  # Each close attempt owns fresh evidence.
        self.permits.clear()
        for robot_id in self._permit_epoch:
            self._permit_epoch[robot_id] += 1
        running = [task for task in self.tasks.values() if not task.done()]
        for task in running:
            task.cancel()
        # Every configured hardware body needs a STOP on shutdown, not just
        # active jobs: a previously uncertain command can leave motors armed.
        # One disconnected head cannot delay STOP on the other four.
        if self.settings.mode == "hardware":
            ids = sorted(self.heads)
            receipts = await asyncio.gather(
                *(_bounded_body_stop(self.heads[robot_id]) for robot_id in ids),
                return_exceptions=True,
            )
            for robot_id, result in zip(ids, receipts, strict=True):
                if isinstance(result, BaseException):
                    self.shutdown_stop_failures[robot_id] = type(result).__name__
                    for job in self.jobs.values():
                        if job.robot_id == robot_id and job.state in {"queued", "running"}:
                            job.state = "failed"
                            job.error = "Shutdown STOP unconfirmed; rely on WROOM watchdog"
        if running:
            done, pending = await asyncio.wait(running, timeout=2.0)
            for task in done:
                if not task.cancelled():
                    task.exception()
            for jid, task in self.tasks.items():
                if task in pending:
                    self.jobs[jid].state = "failed"
                    self.jobs[jid].error = (
                        "Shutdown task ignored cancellation; WROOM watchdog required"
                    )

    def _ensure_voice_gate(self) -> None:
        if not hasattr(self, "_voice_active_robots"):
            self._voice_active_robots = set()
        if not hasattr(self, "_voice_monitor_enforced"):
            self._voice_monitor_enforced = False
        if not hasattr(self, "_voice_monitor_ready"):
            self._voice_monitor_ready = True
        if not hasattr(self, "_voice_stop_unconfirmed"):
            self._voice_stop_unconfirmed = False
        if not hasattr(self, "_deferred_voice_queue"):
            self._deferred_voice_queue = deque()
        if not hasattr(self, "_deferred_requests"):
            self._deferred_requests = {}
        if not hasattr(self, "_deferred_voice_generation"):
            self._deferred_voice_generation = 0
        if getattr(self, "_deferred_dispatch_lock", None) is None:
            self._deferred_dispatch_lock = asyncio.Lock()

    def voice_blocks_motion(self) -> str | None:
        if getattr(self, "_voice_stop_unconfirmed", False):
            return "Voice priority: speaker STOP unconfirmed"
        if getattr(self, "_voice_monitor_enforced", False) and not getattr(
            self, "_voice_monitor_ready", True
        ):
            return "Voice priority: voice monitor unavailable"
        if getattr(self, "_voice_active_robots", ()):
            return "Voice priority: human speech active"
        return None

    def set_voice_state(
        self,
        *,
        active_robots: frozenset[str] | set[str] | None = None,
        monitor_enforced: bool | None = None,
        monitor_ready: bool | None = None,
        voice_stop_unconfirmed: bool | None = None,
    ) -> None:
        self._ensure_voice_gate()
        if active_robots is not None:
            self._voice_active_robots = set(active_robots)
        if monitor_enforced is not None:
            self._voice_monitor_enforced = bool(monitor_enforced)
        if monitor_ready is not None:
            self._voice_monitor_ready = bool(monitor_ready)
        if voice_stop_unconfirmed is not None:
            self._voice_stop_unconfirmed = bool(voice_stop_unconfirmed)
        if self._voice_stop_unconfirmed or (
            self._voice_monitor_enforced and not self._voice_monitor_ready
        ):
            self.discard_deferred_motion(
                reason="Voice monitor outage or unconfirmed STOP discarded deferred motion"
            )

    def discard_deferred_motion(
        self, *, robot_id: str | None = None, reason: str = "Deferred motion discarded",
    ) -> int:
        self._ensure_voice_gate()
        self._deferred_voice_generation += 1
        kept: deque[DeferredMotionRequest] = deque()
        discarded = 0
        while self._deferred_voice_queue:
            req = self._deferred_voice_queue.popleft()
            if robot_id is None or req.robot_id == robot_id:
                req.state = "discarded"
                req.error = reason
                self.permits.pop(req.robot_id, None)
                if req.robot_id in self._permit_epoch:
                    self._permit_epoch[req.robot_id] += 1
                discarded += 1
            else:
                kept.append(req)
        self._deferred_voice_queue = kept
        pending_auto = getattr(self, "_deferred_autonomous_dock", None)
        if isinstance(pending_auto, dict):
            if robot_id is None:
                discarded += len(pending_auto)
                pending_auto.clear()
            elif pending_auto.pop(robot_id, None) is not None:
                discarded += 1
        return discarded

    def defer_motion(
        self,
        robot_id: str,
        kind: str,
        *,
        submit_fn: Callable[[], Job],
        consent_check: Callable[[], bool] | None = None,
        max_wait_seconds: float = 30.0,
    ) -> DeferredMotionRequest:
        """Queue a voice-deferred request FIFO while expiring its old permit.

        Original permits NEVER survive across speech_end or resume canceled
        pre-speech exploration; dispatch requires fresh hardware preflight.
        """
        self._ensure_voice_gate()
        robot = self.robot(robot_id)
        if self.closed or robot_id in self._pending_stops or robot_id in self._unconfirmed_stops:
            raise OperationError("Robot unavailable or STOP unconfirmed; cannot defer motion")
        if not robot.motion_enabled:
            raise OperationError("Deferred motion requires motion_enabled=true")
        if self._voice_stop_unconfirmed or (
            self._voice_monitor_enforced and not self._voice_monitor_ready
        ):
            raise OperationError("Voice monitor unavailable; cannot defer motion")
        if self.permits.get(robot_id, 0) < time.monotonic():
            self.permits.pop(robot_id, None)
            raise OperationError("Operator permit missing or expired; enable one operation first")
        # Consume and retire the pre-speech permit immediately so it cannot
        # outlive the turn or bypass fresh preflight at speech_end dispatch.
        self.permits.pop(robot_id, None)
        self._permit_epoch[robot_id] += 1
        if len(self._deferred_voice_queue) >= 16:
            raise OperationError("Deferred voice motion queue is full")
        if len(self._deferred_requests) >= 128:
            for oldest_id in list(self._deferred_requests):
                if self._deferred_requests[oldest_id].state != "queued":
                    del self._deferred_requests[oldest_id]
                    break
        request = DeferredMotionRequest(
            id=uuid.uuid4().hex,
            robot_id=robot_id,
            kind=kind,
            expires_at=time.monotonic() + max_wait_seconds,
            queue_generation=self._deferred_voice_generation,
            submit_fn=submit_fn,
            consent_check=consent_check,
        )
        self._deferred_voice_queue.append(request)
        self._deferred_requests[request.id] = request
        return request

    async def dispatch_next_deferred(self) -> Job | None:
        self._ensure_voice_gate()
        assert self._deferred_dispatch_lock is not None
        async with self._deferred_dispatch_lock:
            while self._deferred_voice_queue:
                if (
                    self.closed
                    or self._fleet_motion_owner is not None
                    or self.voice_blocks_motion() is not None
                ):
                    return None
                req = self._deferred_voice_queue[0]
                if (
                    req.robot_id in self._pending_stops
                    or req.robot_id in self._unconfirmed_stops
                ):
                    return None
                if time.monotonic() > req.expires_at:
                    self._deferred_voice_queue.popleft()
                    req.state = "expired"
                    req.error = "Deferred motion permit wait window expired"
                    continue
                if (
                    not self.robot(req.robot_id).motion_enabled
                    or (self.dock_inhibited(req.robot_id) and req.kind in {"exploration", "pickup", "navigate"})
                    or (req.consent_check is not None and not req.consent_check())
                ):
                    self._deferred_voice_queue.popleft()
                    req.state = "discarded"
                    req.error = "Motion permission, dock state, or consent revoked before dispatch"
                    continue
                self._deferred_voice_queue.popleft()
                dispatch_epoch = self._permit_epoch[req.robot_id]
                try:
                    await self._hardware_preflight(req.robot_id)
                except Exception as exc:
                    req.state = "failed"
                    req.error = str(exc) or type(exc).__name__
                    return None
                if (
                    self.closed
                    or req.queue_generation != self._deferred_voice_generation
                    or self._permit_epoch[req.robot_id] != dispatch_epoch
                    or req.robot_id in self._pending_stops
                    or req.robot_id in self._unconfirmed_stops
                    or not self.robot(req.robot_id).motion_enabled
                    or (self.dock_inhibited(req.robot_id) and req.kind in {"exploration", "pickup", "navigate"})
                    or (req.consent_check is not None and not req.consent_check())
                    or self._fleet_motion_owner is not None
                ):
                    req.state = "discarded"
                    req.error = "STOP, fault, or permission change superseded deferred dispatch"
                    return None
                if self.voice_blocks_motion() is not None:
                    # Human spoke again during preflight: discard instead of replaying.
                    req.state = "discarded"
                    req.error = "New human voice or monitor loss interrupted deferred dispatch"
                    return None
                if time.monotonic() > req.expires_at:
                    req.state = "expired"
                    req.error = "Deferred motion permit wait window expired"
                    continue
                self.permits[req.robot_id] = time.monotonic() + 5.0
                try:
                    job = req.submit_fn()
                except Exception as exc:
                    self.permits.pop(req.robot_id, None)
                    req.state = "failed"
                    req.error = str(exc) or type(exc).__name__
                    return None
                req.state = "dispatched"
                req.job_id = job.id
                return job
            pending_auto = getattr(self, "_deferred_autonomous_dock", None)
            while pending_auto:
                if (
                    self.closed
                    or self._fleet_motion_owner is not None
                    or self.voice_blocks_motion() is not None
                ):
                    return None
                robot_id = next(iter(pending_auto))
                initial_low, expires_at, camera_grant = pending_auto.pop(robot_id)
                if (
                    time.monotonic() >= expires_at
                    or robot_id in self._pending_stops
                    or robot_id in self._unconfirmed_stops
                    or self.dock_inhibited(robot_id)
                ):
                    continue
                job = await self.request_autonomous_low_battery_dock(
                    robot_id, initial_low=initial_low,
                    _expires_at=expires_at, _camera_grant=camera_grant,
                )
                if job is not None:
                    return job
            return None
        return None

    def _submit(self, robot_id: str, kind: str, work: Callable[[Job], Awaitable[dict]]) -> Job:
        self.robot(robot_id)
        if self.permits.get(robot_id, 0) < time.monotonic():
            self.permits.pop(robot_id, None)
            raise OperationError("Operator permit missing or expired; enable one operation first")
        if (
            self.closed
            or self.locks[robot_id].locked()
            or any(
                j.robot_id == robot_id and j.state in {"queued", "running"}
                for j in self.jobs.values()
            )
        ):
            raise OperationError("Robot busy or coordinator closing")
        if self._fleet_motion_owner is not None:
            raise OperationError(
                "Fleet motion busy: one moving pet until WROOM STOP is acknowledged"
            )
        if self._pending_stops or self._unconfirmed_stops:
            raise OperationError("Fleet motion blocked: WROOM STOP pending or unconfirmed")
        voice_reason = self.voice_blocks_motion()
        if voice_reason is not None:
            raise OperationError(voice_reason)
        # Retain only bounded history; never accumulate infinite tasks/results in a long-running server.
        if len(self.jobs) >= 100:
            for jid in list(self.jobs):
                if self.tasks[jid].done():
                    del self.jobs[jid]
                    del self.tasks[jid]
                    break
        self._permit_epoch[robot_id] += 1
        self.permits.pop(robot_id, None)  # consume once, even if ACK/job later fails
        job = Job(uuid.uuid4().hex, robot_id, kind)
        # Claim synchronously, before the task is even scheduled. No queued
        # second body can slip in between per-robot task starts.
        self._fleet_motion_owner = job.id
        self.jobs[job.id] = job
        self.tasks[job.id] = asyncio.create_task(self._run(job, work))
        return job

    async def _keepalive(self, robot_id: str, acknowledged: asyncio.Event):
        while True:
            await self.heads[robot_id].command("keepalive")
            acknowledged.set()
            await asyncio.sleep(0.1)

    async def _watch_keepalive(self, acknowledged: asyncio.Event):
        # This separate task remains responsive even if the command adapter
        # stalls or ignores cancellation. Allow less than the local 500 ms
        # watchdog window between host receipts; this is not device timing.
        while True:
            try:
                async with asyncio.timeout(0.4):
                    await acknowledged.wait()
            except TimeoutError as exc:
                raise OperationError("WROOM keepalive acknowledgement timeout") from exc
            acknowledged.clear()

    async def _run(self, job: Job, work):
        async with self.locks[job.robot_id]:
            job.state = "running"
            keeper = None
            watchdog = None
            operation = None
            operation_result = None
            operation_finished = False
            try:
                # A head can disconnect, touch can be pressed and a floor
                # sample can expire after the operator granted the permit.
                # Recheck the real body immediately before requesting arm.
                await self._hardware_preflight(job.robot_id)
                if not self.robot(job.robot_id).motion_enabled:
                    raise OperationError("motion_enabled=false; no arm sent")
                voice_reason = self.voice_blocks_motion()
                if voice_reason is not None:
                    raise OperationError(voice_reason)
                await self.heads[job.robot_id].command(
                    "arm"
                )  # only after consuming operator permit
                # A changed configuration while ARM is in flight cannot
                # authorize subsequent actuator commands. HALT in finally.
                if not self.robot(job.robot_id).motion_enabled:
                    raise OperationError("motion_enabled=false; no movement sent")
                voice_reason = self.voice_blocks_motion()
                if voice_reason is not None:
                    raise OperationError(voice_reason)
                acknowledged = asyncio.Event()
                keeper = asyncio.create_task(self._keepalive(job.robot_id, acknowledged))
                watchdog = asyncio.create_task(self._watch_keepalive(acknowledged))
                operation = asyncio.create_task(work(job))
                # A parent task can finish or be cancelled again while one
                # of these children is still unwinding. Keep the true owners.
                self._motion_children[job.id] = (keeper, watchdog, operation)
                # A failed keepalive cancels the operation immediately; do not continue blindly.
                # Exploration is a single persistent operator-approved job;
                # never require another two-minute token while it is safely
                # running. Body pulses still expire in <=250ms and the local
                # 500ms watchdog remains independent of the Mac.
                timeout = None if job.kind == "exploration" else self.settings.max_job_seconds
                async with asyncio.timeout(timeout):
                    done, _ = await asyncio.wait(
                        {keeper, watchdog, operation}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if watchdog in done:
                        await watchdog
                        raise OperationError("Keepalive watchdog ended unexpectedly")
                    if keeper in done:
                        await keeper
                        raise OperationError("Keepalive ended unexpectedly")
                    operation_result = await operation
                    operation_finished = True
            except asyncio.CancelledError:
                # An operator STOP can already have failed at the transport.
                # Cancellation of this Python task must never erase that
                # stronger physical failure or claim the WROOM stopped.
                if job.state != "failed":
                    job.state = "cancelled"
                    job.error = "Operator cancelled"
            except Exception as exc:
                job.state = "failed"
                job.error = str(exc) or type(exc).__name__
            finally:
                for task in (operation, keeper, watchdog):
                    if task is not None and not task.done():
                        task.cancel()
                # Dispatch WROOM stop before potentially slow canceled camera
                # or model cleanup. No second actor may treat this as charging.
                stop_acknowledged = False
                try:
                    await _bounded_body_stop(self.heads[job.robot_id])
                    stop_acknowledged = True
                    job.events.append(
                        "stop acknowledged; servo positions are commanded, not measured"
                    )
                except Exception as exc:
                    job.error = f"{job.error or ''}; STOP failed: {exc}; rely on body watchdog"
                    job.state = "failed"
                pending = [t for t in (operation, keeper, watchdog) if t is not None]
                unresponsive: set[asyncio.Task] = set()
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
                if stop_acknowledged and not unresponsive:
                    # An operation result is not a completed job until the
                    # terminal HALT receipt and cancelled children settle.
                    if operation_finished and job.state == "running":
                        job.result = operation_result
                        job.state = "succeeded"
                    if getattr(self, "_fleet_motion_owner", None) == job.id:
                        self._motion_children.pop(job.id, None)
                        self._fleet_motion_owner = None
                        if (
                            not self.closed
                            and getattr(self, "_deferred_voice_queue", None)
                            and self.voice_blocks_motion() is None
                        ):
                            existing = getattr(self, "_deferred_dispatch_task", None)
                            if existing is None or existing.done():
                                task = asyncio.create_task(self.dispatch_next_deferred())
                                self._deferred_dispatch_task = task
                                task.add_done_callback(
                                    lambda done: None if done.cancelled() else done.exception()
                                )

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
        # Exploration has no overall job deadline. An alternate head adapter
        # holding this status request must not keep the WROOM armed forever.
        body = await _bounded_head_reply(
            self.heads[robot_id].status(), seconds=2.5,
            timeout_message="WROOM active health status timeout",
        )
        if not isinstance(body, dict) or body.get("armed") is not True:
            raise OperationError("Operation stopped: body disarmed or unavailable")
        if self.settings.mode != "hardware":
            return body
        # Preflight identity alone is insufficient. Every subsequent motion
        # health read must still belong to this WROOM, including after a
        # head reconnect or reassignment of an alternate transport adapter.
        if body.get("robot_id") != robot_id:
            raise OperationError("Operation blocked: body identity mismatch")
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
        _require_safe_fuel_sample(
            body.get("power"), min_cell_mv=3300, min_soc_centi=300,
            context="Operation blocked",
            depleted_message=(
                "Operation blocked: battery depleted below motor operating limit"
            ),
        )
        return body

    def dock_inhibited(self, robot_id: str) -> bool:
        """True while dock seat/power/CHG telemetry inhibits away-from-dock motion."""
        return bool(getattr(self, "_dock_charging_inhibited", {}).get(robot_id, False))

    def set_dock_charge_inhibition(self, robot_id: str, inhibited: bool) -> None:
        """Sync read-only dock seat/charge-pin status into motion admission."""
        table = getattr(self, "_dock_charging_inhibited", None)
        if table is None:
            table = {}
            self._dock_charging_inhibited = table
        flag = bool(inhibited)
        table[robot_id] = flag
        if not flag:
            return
        discard = getattr(self, "discard_deferred_motion", None)
        if callable(discard):
            discard(robot_id=robot_id, reason="Robot seated or powered on dock")
        active = self.jobs.get(self._fleet_motion_owner) if self._fleet_motion_owner else None
        task = self.tasks.get(active.id) if active is not None else None
        if (
            active is not None
            and active.robot_id == robot_id
            and active.kind in {"exploration", "pickup", "navigate", "dock_approach"}
            and task is not None
            and not task.done()
            and not task.cancelling()
        ):
            active.error = "Stopped: robot seated or powered on dock"
            task.cancel()

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
        if self.dock_inhibited(robot_id):
            raise OperationError("Exploration refused: robot is seated or powered on dock")
        if self.settings.mode == "hardware" and not robot.exploration_qualified:
            raise OperationError(
                "Hardware exploration needs measured swept-path qualification"
            )
        return self._submit(robot_id, "exploration", self._explore)

    async def request_autonomous_low_battery_dock(
        self, robot_id: str, *, initial_low: bool = False,
        _expires_at: float | None = None, _camera_grant: int | None = None,
    ) -> Job | None:
        """Queue or start bounded dock approach on sustained low battery.

        Fail-closed: requires autonomous_low_battery_dock_enabled, motion_enabled,
        dock_motion_qualified, measured calibration, assigned beacon, valid
        steering signs, active camera consent in hardware mode, no dock/charger
        inhibition, no active fleet motion job, and fresh _hardware_preflight +
        operator_arm + dock() checks. Never authorizes terminal charging.
        """
        robot = self.robot(robot_id)
        expires_at = time.monotonic() + 30 if _expires_at is None else _expires_at
        camera_grant = (
            self.settings.camera_consent_generation if _camera_grant is None else _camera_grant
        )
        if (time.monotonic() >= expires_at
                or self.settings.camera_consent_generation != camera_grant):
            return None
        if not robot.autonomous_low_battery_dock_enabled:
            return None
        if not robot.motion_enabled or not robot.dock_motion_qualified:
            return None
        if (
            robot.dock_turn_sign not in (-1, 1)
            or robot.dock_forward_sign not in (-1, 1)
            or robot.dock_beacon_id is None
            or robot.dock_calibration is None
        ):
            return None
        if self.settings.mode == "hardware" and not self.settings.voice_vision_tools_enabled:
            return None
        if self.dock_inhibited(robot_id):
            return None
        try:
            load_real_dock_calibration(robot.dock_calibration, robot_id=robot_id)
        except Exception:
            return None
        if any(not task.done() for task in self.tasks.values()):
            return None

        if self.voice_blocks_motion() is not None:
            pending_auto = getattr(self, "_deferred_autonomous_dock", None)
            if pending_auto is None:
                pending_auto = {}
                self._deferred_autonomous_dock = pending_auto
            pending_auto[robot_id] = (initial_low, expires_at, camera_grant)
            return None
        try:
            await self.operator_arm(robot_id, require_low_battery=True)
            if (
                time.monotonic() >= expires_at
                or self.settings.camera_consent_generation != camera_grant
                or not robot.autonomous_low_battery_dock_enabled
                or not robot.motion_enabled
                or not robot.dock_motion_qualified
                or self.dock_inhibited(robot_id)
            ):
                self.permits.pop(robot_id, None)
                return None
            if self.settings.mode == "hardware" and not self.settings.voice_vision_tools_enabled:
                self.permits.pop(robot_id, None)
                return None
            return self.dock(robot_id)
        except OperationError:
            self.permits.pop(robot_id, None)
            return None

    async def _explore(self, job: Job) -> dict:
        head = self.heads[job.robot_id]
        last_live_frame_at = float("-inf")
        camera_grant = (
            self.settings.camera_consent_generation
            if self.settings.mode == "hardware" else None
        )

        def require_camera_grant() -> None:
            # Revoking and immediately regranting consent must not revive
            # a camera-based motion job started under the old grant.
            if (camera_grant is not None
                    and (not self.settings.voice_vision_tools_enabled
                         or self.settings.camera_consent_generation != camera_grant)):
                raise OperationError("Hardware exploration camera consent revoked")

        def require_motion_authority() -> None:
            if job.id in self.jobs and job.state != "running":
                raise OperationError("Exploration halted: job no longer owns motion")
            voice_reason = self.voice_blocks_motion()
            if voice_reason is not None:
                raise OperationError(voice_reason)
            if not self.robot(job.robot_id).motion_enabled:
                raise OperationError("Exploration halted: motion_enabled=false")
            if self.dock_inhibited(job.robot_id):
                raise OperationError("Exploration halted: robot seated or powered on dock")

        async def observe_camera() -> None:
            nonlocal last_live_frame_at
            require_camera_grant()
            if self.settings.mode == "hardware":
                # Hardware exploration MUST consume a genuinely NEW
                # authenticated XIAO frame from the one Mac MJPEG owner.
                # A successful but stale snapshot is not motion evidence.
                media = self.multimodal
                if (media is None
                        or not media.settings.voice_vision_tools_enabled
                        or not media.stream_owns_camera(job.robot_id)
                        or not media.status(job.robot_id)["camera_stream_connected"]):
                    # A reconnecting worker is NOT a live camera socket,
                    # even if its asyncio task has not exited.
                    raise OperationError(
                        "Hardware exploration requires connected live XIAO camera stream"
                    )

                def newest():
                    return next((
                        frame for frame in reversed(media.hub.frames[job.robot_id])
                        if frame.source == "proactive"
                        and frame.received_at > last_live_frame_at
                        and 0 <= time.monotonic() - frame.received_at <= 1.0
                    ), None)

                frame = newest()
                if frame is None:
                    received = await _bounded_head_reply(
                        media.wait_for_proactive_frame(
                            job.robot_id, last_live_frame_at, timeout_s=2.0
                        ), seconds=2.5,
                        timeout_message="Live exploration camera stalled",
                    )
                    if not received:
                        raise OperationError("Live exploration camera stalled")
                    frame = newest()
                require_camera_grant()
                if (frame is None or not media.stream_owns_camera(job.robot_id)
                        or not media.settings.voice_vision_tools_enabled
                        or not media.status(job.robot_id)["camera_stream_connected"]):
                    # Connection can drop during frame preparation. A
                    # recently cached receipt cannot certify a live stream.
                    raise OperationError(
                        "Hardware exploration camera frame expired or disconnected"
                    )
                last_live_frame_at = frame.received_at
                jpeg = frame.jpeg
            else:
                # Simulation retains its historical synthetic snapshot.
                jpeg = await _bounded_head_reply(
                    head.snapshot(), seconds=2.0,
                    timeout_message="Camera snapshot timeout",
                )
            # An HTTP success with an empty, partial or non-JPEG response
            # is not evidence of a functioning XIAO camera stream.
            if (not isinstance(jpeg, bytes) or not 4 <= len(jpeg) <= 512000
                    or not jpeg.startswith(b"\xff\xd8")
                    or not jpeg.endswith(b"\xff\xd9")):
                raise OperationError("Exploration camera returned invalid JPEG")
            try:
                width, height = image_size(jpeg)
            except (OSError, ValueError, SyntaxError) as exc:
                raise OperationError("Exploration camera returned invalid JPEG") from exc
            if not 80 <= width <= 2048 or not 80 <= height <= 1536:
                raise OperationError("Exploration camera returned invalid JPEG dimensions")

        steps = 0
        # This loop persists until a stop, quiet mode, failure, or disconnect.
        # There is no unbounded drive: every track movement expires after 100ms.
        while True:
            require_motion_authority()
            require_camera_grant()
            await self._assert_armed_health(job.robot_id, require_front_clearance=True)
            # The reused Sense camera source must be alive before and after
            # each short pulse; an image does not by itself prove a clear path.
            await observe_camera()
            # A camera request can hang while a local cliff, touch or IMU
            # fault disarms WROOM. Never drive from a pre-camera verdict.
            await self._assert_armed_health(job.robot_id, require_front_clearance=True)
            # A voice edge or operator revocation may arrive while health IO
            # is suspended, before the separate asynchronous STOP task runs.
            require_motion_authority()
            require_camera_grant()
            await head.command("drive 20 20 100")
            await asyncio.sleep(0.12)
            await _bounded_pulse_stop(head)
            steps += 1
            if len(job.events) >= 96:
                job.events.pop(0)
            job.events.append(f"bounded exploration pulse {steps}, stopped for reobservation")
            await observe_camera()
            # No blind reverse/turn when only one forward beam exists. Swept
            # turns need real footprint and obstacle qualification.
            await asyncio.sleep(0.35)

    def _camera_motion_grant(self) -> int | None:
        """Bind physical camera-guided work to one operator grant epoch."""
        if self.settings.mode != "hardware":
            return None
        if not self.settings.voice_vision_tools_enabled:
            raise OperationError("Hardware motion requires camera consent")
        return self.settings.camera_consent_generation

    def _require_camera_motion_grant(self, grant: int | None) -> None:
        if grant is not None and (
            not self.settings.voice_vision_tools_enabled
            or self.settings.camera_consent_generation != grant
        ):
            raise OperationError("Camera consent revoked during physical operation")

    def dock(self, robot_id: str) -> Job:
        """Permit-gated camera approach ending BEFORE unqualified charge contacts."""
        robot = self.robot(robot_id)
        if self.dock_inhibited(robot_id):
            raise OperationError("Dock approach refused: robot is seated or powered on dock")
        if not robot.motion_enabled or not robot.dock_motion_qualified:
            raise OperationError("Dock motion requires measured physical qualification")
        if self.settings.mode != "hardware":
            raise OperationError("Dock approach requires physically qualified hardware")
        if robot.dock_turn_sign not in (-1, 1) or robot.dock_forward_sign not in (-1, 1):
            raise OperationError("Dock turn and forward motor polarity are not measured")
        try:
            camera, target_mm = load_real_dock_calibration(
                robot.dock_calibration, robot_id=robot.id,
                head_device_id=robot.device_id,
            )
        except (OSError, ValueError, TypeError) as exc:
            raise OperationError(f"Dock calibration required: {exc}") from exc
        # Read-only AprilTag diagnostics may retain legacy zero-distortion
        # assumptions. Physically permitted docking must not assume that
        # an unmeasured XIAO lens has zero distortion.
        if camera.distortion_coeffs is None:
            raise OperationError(
                "Dock motion requires measured camera lens distortion"
            )
        if camera.image_width_px is None or camera.image_height_px is None:
            raise OperationError(
                "Dock motion requires calibrated camera frame resolution"
            )
        if (camera.mount_lateral_offset_mm is None
                or camera.mount_yaw_deg is None):
            raise OperationError(
                "Dock motion requires measured camera to chassis mounting geometry"
            )
        if camera.camera_sensor_pid not in ("OV3660", "OV5640"):
            raise OperationError(
                "Dock motion requires recorded actual camera sensor PID"
            )
        if robot.dock_beacon_id is None:
            raise OperationError("Dock approach needs the assigned physical NEC beacon")
        camera_grant = self._camera_motion_grant()
        return self._submit(
            robot_id, "dock_approach",
            lambda job: self._dock_approach(
                job, camera, target_mm, robot.dock_turn_sign,
                robot.dock_forward_sign, camera_grant=camera_grant,
            ),
        )

    async def _dock_approach(
        self, job: Job, camera, target_mm: float,
        turn_sign: int, forward_sign: int,
        *, camera_grant: int | None = None,
    ) -> dict:
        """Camera plus fresh assigned dock IR plus local guard; NEVER charge."""
        self._require_camera_motion_grant(camera_grant)
        head = self.heads[job.robot_id]
        expected_dock = self.robot(job.robot_id).dock_beacon_id
        previous_ir: tuple[int, int] | None = None
        for attempt in range(16):
            if self.dock_inhibited(job.robot_id):
                raise OperationError("Dock approach refused: robot is seated or powered on dock")
            # Check before vision and AGAIN afterwards: camera and PnP may
            # pause for seconds while the hardware floor/front state changes.
            await self._assert_armed_health(
                job.robot_id, require_front_clearance=True
            )
            # Camera receipt time is NOT equivalent to image exposure time.
            # Local WROOM cliff stop remains mandatory for every short pulse.
            # Real docking reuses a strictly fresh MJPEG frame.
            capture_dock = getattr(head, "snapshot_for_dock", head.snapshot)
            observation = await _bounded_head_reply(
                capture_dock(), seconds=2.0,
                timeout_message="Camera snapshot timeout",
            )
            self._require_camera_motion_grant(camera_grant)
            # Physical steering requires the selected Sense stream boot,
            # frame sequence and camera generation. Compatibility JPEGs
            # may be read by diagnostics but can never authorize a pulse.
            if self.settings.mode == "hardware" and (
                not isinstance(observation, tuple) or len(observation) != 4
                or not callable(getattr(head, "dock_receipt_current", None))
            ):
                raise OperationError(
                    "Dock motion requires authenticated live camera stream receipt"
                )
            try:
                jpeg, received_at = unpack_dock_frame(observation)
            except ValueError as exc:
                raise OperationError("Stale or invalid dock camera receipt") from exc
            if camera.camera_sensor_pid is not None:
                # This method checks Espressif's live sensor PID AND the
                # accepted JPEG boot nonce; a JSON calibration alone cannot
                # authorize steering an OV5640 with OV3660 intrinsics.
                read_identity = getattr(head, "camera_identity", None)
                if not callable(read_identity):
                    raise OperationError(
                        "Dock camera live sensor identity unavailable"
                    )
                remaining = 0.20 - (time.monotonic() - received_at)
                if remaining <= 0:
                    raise OperationError("Stale dock camera receipt before PID lookup")
                observed_pid = await _bounded_head_reply(
                    (read_identity(observation) if isinstance(observation, tuple)
                     and len(observation) == 4 else read_identity()), seconds=remaining,
                    timeout_message="Dock camera live sensor identity timeout",
                )
                if observed_pid != camera.camera_sensor_pid:
                    raise OperationError(
                        "Dock camera sensor PID differs from measured calibration"
                    )
            # The isolated detector is shared with read-only diagnostics.
            # Expired or revoked evidence must never enter a native process.
            self._require_camera_motion_grant(camera_grant)
            try:
                pose = await detect_bounded(
                    jpeg, camera, captured_at=received_at
                )
            except TimeoutError:
                return {
                    "phase": "hold", "reason": "Stale AprilTag camera receipt",
                    "charging_authorized": False, "physical_acceptance_pass": False,
                }
            # A centered AprilTag in the camera frame is not necessarily
            # centered on the wheel chassis. Apply measured camera yaw and
            # lateral lens offset before choosing a left/right/forward pulse.
            aligned = (
                replace(pose, x_mm=camera.chassis_lateral_mm(pose))
                if pose is not None else None
            )
            decision = assess_dock(
                aligned, now=time.monotonic(), target_distance_mm=target_mm
            )
            job.events.append(f"dock observation {attempt}: {decision.phase}")
            if decision.phase == "hold":
                return {
                    "phase": "hold", "reason": decision.reason,
                    "charging_authorized": False, "physical_acceptance_pass": False,
                }
            # Actual hardware docking requires BOTH independent IR receivers
            # to see the code flashed on THIS pet's assigned station. A valid
            # foreign dock NEC frame never justifies a turn/forward pulse.
            # This does not grant any movement or charging authorization:
            # the five local WROOM ranging and dock-contact interlocks still
            # own the physical STOP verdict.
            if expected_dock is not None:
                getter = getattr(head, "ir_status", None)
                if not callable(getter):
                    raise OperationError("Assigned dock IR receiver unavailable")
                ir_request_at = time.monotonic()
                reading = await _bounded_head_reply(
                    getter(), seconds=1.0,
                    timeout_message="Assigned dock IR status timeout",
                )
                try:
                    beacon = validate_ir(
                        reading, job.robot_id, expected_dock_id=expected_dock,
                        elapsed_ms=(time.monotonic() - ir_request_at) * 1000,
                    )
                except ValueError as exc:
                    raise OperationError(f"Assigned dock IR rejected: {exc}") from exc
                if not beacon["match"]:
                    return {
                        "phase": "hold", "reason": "Assigned dock IR not jointly visible",
                        "charging_authorized": False, "physical_acceptance_pass": False,
                    }
                current_ir = (beacon["left_seq"], beacon["right_seq"])
                if previous_ir is not None and any(
                    (new - old) & 0xffffffff not in range(1, 0x80000000)
                    for new, old in zip(current_ir, previous_ir, strict=True)
                ):
                    return {
                        "phase": "hold", "reason": "Assigned dock IR replay or stale conversion",
                        "charging_authorized": False, "physical_acceptance_pass": False,
                    }
                previous_ir = current_ir
            # The assigned IR request may stall after the earlier camera check.
            # Read live WROOM health and corridor clearance only AFTER it.
            # A healthy pre-camera response is NEVER reused as movement
            # authority after a slow snapshot or AprilTag inference.
            body = await self._assert_armed_health(
                job.robot_id, require_front_clearance=True
            )
            if decision.phase == "align":
                side = body.get("side_ranges")
                if (not isinstance(side, dict)
                        or type(side.get("present_mask")) is not int
                        or side["present_mask"] != 7
                        or type(side.get("valid_mask")) is not int
                        or side["valid_mask"] != 7
                        or not isinstance(side.get("age_ms"), list)
                        or len(side["age_ms"]) != 3
                        or any(type(n) is not int or not 0 <= n <= 350
                               for n in side["age_ms"])
                        or not isinstance(side.get("mm"), list)
                        or len(side["mm"]) != 3
                        or any(type(n) is not int or not 300 <= n <= 1300
                               for n in side["mm"])):
                    raise OperationError(
                        "Dock turn refused: side and rear clearance unqualified"
                    )
                direction = turn_sign if aligned.x_mm > 0 else -turn_sign
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
            # IR and the second fresh WROOM status can each delay movement.
            # Never use an old camera frame simply because the NEC code matched.
            latest = assess_dock(
                aligned, now=time.monotonic(), target_distance_mm=target_mm
            )
            if latest.phase != decision.phase:
                return {
                    "phase": "hold", "reason": latest.reason,
                    "charging_authorized": False, "physical_acceptance_pass": False,
                }
            # IR and WROOM checks can await across a camera reconnect.
            # Refuse any pulse that no longer belongs to the selected boot.
            try:
                await verify_selected_dock_frame(head, observation)
            except Exception as exc:
                raise OperationError("Dock JPEG source changed before drive") from exc
            self._require_camera_motion_grant(camera_grant)
            if expected_dock is not None:
                # WROOM health and the selected camera boot are awaited after
                # the beacon read. A valid IR reply can expire during either
                # wait; never authorize a pulse from that expired sample.
                try:
                    validate_ir(
                        reading, job.robot_id, expected_dock_id=expected_dock,
                        elapsed_ms=(time.monotonic() - ir_request_at) * 1000,
                    )
                except ValueError:
                    return {
                        "phase": "hold",
                        "reason": "Assigned dock IR expired before guarded drive",
                        "charging_authorized": False,
                        "physical_acceptance_pass": False,
                    }
            # Seat or charger evidence may arrive during any preceding await.
            if self.dock_inhibited(job.robot_id):
                raise OperationError("Dock approach refused: robot is seated or powered on dock")
            await head.command(command)
            await asyncio.sleep(0.12)
            await _bounded_pulse_stop(head)
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
        if self.dock_inhibited(robot_id):
            raise OperationError("Pickup refused: robot is seated or powered on dock")
        calibration = Calibration.load(robot.calibration)
        calibration.verify_ready()
        if calibration.simulation_only and self.settings.mode != "simulation":
            raise OperationError("Simulation calibration cannot be used on hardware")
        if self.settings.mode == "hardware" and calibration.hold_seconds < 3:
            raise OperationError("Real pickup requires at least three seconds of verified hold")
        if self.settings.mode == "hardware" and calibration.grip_force_delta_raw is None:
            raise OperationError("Real pickup requires measured ADS1115 gripper contact threshold")
        if self.settings.mode == "hardware":
            self._pickup_live_media(robot_id)
        camera_grant = self._camera_motion_grant()
        return self._submit(
            robot_id, "pickup",
            lambda job: self._pickup(
                job, target, calibration, camera_grant=camera_grant,
            ),
        )

    def _pickup_live_media(
        self, robot_id: str, camera_grant: int | None = None,
    ):
        """Never let hardware grasp use a stale or privately disabled camera."""
        self._require_camera_motion_grant(camera_grant)
        media = self.multimodal
        if (media is None or not self.settings.voice_vision_tools_enabled
                or not media.stream_owns_camera(robot_id)
                or not media.status(robot_id)["camera_stream_connected"]):
            raise OperationError("Hardware pickup requires connected live XIAO camera stream")
        return media

    async def _observe(
        self, robot_id: str, target: str, c: Calibration,
        *, after: float = float("-inf"),
        camera_grant: int | None = None,
    ) -> tuple[Detection, float]:
        if self.settings.mode == "hardware":
            # Grasp must share the SAME authenticated pushed XIAO MJPEG feed
            # as exploration and voice, never fall back to /api/camera.jpg.
            media = self._pickup_live_media(robot_id, camera_grant)

            def newest():
                return next((
                    frame for frame in reversed(media.hub.frames[robot_id])
                    if frame.source in ("proactive", "speech")
                    and frame.received_at > after
                    and 0 <= time.monotonic() - frame.received_at <= 1.0
                ), None)

            frame = newest()
            if frame is None:
                await _bounded_head_reply(
                    media.wait_for_proactive_frame(
                        robot_id, after, timeout_s=2.0
                    ), seconds=2.5,
                    timeout_message="Live pickup camera stalled",
                )
                frame = newest()
            self._pickup_live_media(robot_id, camera_grant)
            if frame is None:
                raise OperationError("Live pickup camera stalled")
            jpeg = frame.jpeg
            jpeg_received_at = frame.received_at
        else:
            jpeg = await _bounded_head_reply(
                self.heads[robot_id].snapshot(), seconds=3.0,
                timeout_message="Pickup camera snapshot timeout",
            )
            jpeg_received_at = time.monotonic()
        # A Mac receipt is NOT actual exposure time; a newer physical
        # stream frame is required for every successive grasp observation.
        if image_size(jpeg) != (c.image_width, c.image_height):
            raise OperationError("Camera resolution differs from measured calibration")
        objects = [
            d
            for d in await _bounded_head_reply(
                self.vision.detect(jpeg, target), seconds=15.0,
                timeout_message="Pickup vision inference timeout",
            )
            if d.label == target
            and d.confidence >= c.min_confidence
            and 0 <= d.box[0] < d.box[2] <= c.image_width
            and 0 <= d.box[1] < d.box[3] <= c.image_height
        ]
        if len(objects) != 1:
            raise OperationError("Lost or ambiguous target; stop and request operator intervention")
        if self.settings.mode == "hardware":
            self._pickup_live_media(robot_id, camera_grant)
            if time.monotonic() - jpeg_received_at > 2.0:
                raise OperationError("Pickup visual evidence expired during inference")
        return objects[0], jpeg_received_at

    async def _pickup(
        self, job: Job, target: str, c: Calibration,
        *, camera_grant: int | None = None,
    ) -> dict:
        head = self.heads[job.robot_id]
        if self.settings.mode == "hardware":
            # A missing camera must stop BEFORE jaw or lift preposition.
            self._pickup_live_media(job.robot_id, camera_grant)
        last_live_frame_at = float("-inf")

        async def observe() -> tuple[Detection, float]:
            nonlocal last_live_frame_at
            result = await self._observe(
                job.robot_id, target, c, after=last_live_frame_at,
                camera_grant=camera_grant,
            )
            last_live_frame_at = result[1]
            return result

        def fence_observation() -> None:
            # A newer cached JPEG may still predate movement or the hold.
            # Fence Mac receipt time at completion of each supervised phase.
            nonlocal last_live_frame_at
            last_live_frame_at = max(last_live_frame_at, time.monotonic())

        def require_ack(reply: object, command: str) -> None:
            if (type(reply) is not dict or reply.get("ok") is not True
                    or reply.get("robot_id") != job.robot_id
                    or reply.get("reply") != expected_ack(command)):
                raise OperationError(f"Unmatched pickup command ACK: {command}")

        async def send_command(command: str) -> None:
            reply = await _bounded_head_reply(
                head.command(command), seconds=2.5,
                timeout_message="Pickup command acknowledgement timed out",
            )
            require_ack(reply, command)

        def require_fresh_observation() -> None:
            if self.settings.mode == "hardware":
                self._pickup_live_media(job.robot_id, camera_grant)
                if not 0 <= time.monotonic() - last_live_frame_at <= 2.0:
                    raise OperationError("Pickup visual evidence expired after health check")

        await self._assert_armed_health(job.robot_id)
        self._require_camera_motion_grant(camera_grant)
        await send_command(f"grip {c.grip_open}")
        await self._assert_armed_health(job.robot_id)
        self._require_camera_motion_grant(camera_grant)
        await send_command(f"lift {c.lift_down}")
        await asyncio.sleep(c.servo_settle_seconds)
        fence_observation()
        initial = None
        for attempt in range(24):
            await self._assert_armed_health(job.robot_id)
            detection, visual_received_at = await observe()
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
            if (self.settings.mode == "hardware"
                    and time.monotonic() - visual_received_at > 2.0):
                raise OperationError("Pickup visual evidence expired before movement")
            self._require_camera_motion_grant(camera_grant)
            await send_command(command)  # exactly once: an uncertain ACK is a failure
            await asyncio.sleep(0.12)
            require_ack(await _bounded_pulse_stop(head), "stop")
            fence_observation()
            await self._assert_armed_health(job.robot_id)
        if initial is None:
            raise OperationError("Alignment attempt limit reached")
        await self._assert_armed_health(job.robot_id)
        require_fresh_observation()
        if self.settings.mode == "hardware":
            async def grasp_health() -> dict:
                body = await self._assert_armed_health(job.robot_id)
                self._require_camera_motion_grant(camera_grant)
                return body

            self._require_camera_motion_grant(camera_grant)
            tactile = await guarded_grasp(
                head, c, robot_id=job.robot_id, health=grasp_health,
            )
            job.events.append(
                f"tactile contact delta={tactile['contact_delta_raw']} "
                f"commanded_angle={tactile['commanded_angle']}; not physical acceptance"
            )
        else:
            self._require_camera_motion_grant(camera_grant)
            await send_command(f"grip {c.grip_closed}")
            await asyncio.sleep(c.servo_settle_seconds)
        await self._assert_armed_health(job.robot_id)
        self._require_camera_motion_grant(camera_grant)
        await send_command(f"lift {c.lift_up}")
        await asyncio.sleep(c.servo_settle_seconds)
        # Image evidence: same category moves upward into measured raised-jaw region and remains
        # there in two fresh frames while wheels are stopped. A servo ACK alone never passes.
        require_ack(await _bounded_pulse_stop(head), "stop")
        fence_observation()
        a, b, x, y = c.lifted_roi_px
        observed = []
        for sample in range(2):
            if sample:
                await asyncio.sleep(c.hold_seconds)
                fence_observation()
            await self._assert_armed_health(job.robot_id)
            detection, _ = await observe()
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
        await self._assert_armed_health(job.robot_id)
        require_fresh_observation()
        job.events.append("lift and hold visually verified; begin supervised placement")
        self._require_camera_motion_grant(camera_grant)
        await send_command(f"lift {c.lift_down}")
        await asyncio.sleep(c.servo_settle_seconds)
        fence_observation()
        lowered, _ = await observe()
        lowered_ground = c.ground(lowered.center)
        if (
            not c.within(lowered_ground)
            or max(abs(lowered_ground[i] - c.grip_ground_mm[i]) for i in (0, 1))
            > c.alignment_tolerance_mm * 2
        ):
            raise OperationError("Placement unverified: object not over calibrated release area")

        await self._assert_armed_health(job.robot_id)
        require_fresh_observation()
        # Release only after observing the object near the table, then raise
        # the empty jaws to distinguish a placed object from one stuck in them.
        self._require_camera_motion_grant(camera_grant)
        await send_command(f"grip {c.grip_open}")
        await asyncio.sleep(c.servo_settle_seconds)
        await self._assert_armed_health(job.robot_id)
        self._require_camera_motion_grant(camera_grant)
        await send_command(f"lift {c.lift_up}")
        await asyncio.sleep(c.servo_settle_seconds)
        fence_observation()
        placed_positions = []
        for sample in range(2):
            if sample:
                await asyncio.sleep(0.15)
                fence_observation()
            await self._assert_armed_health(job.robot_id)
            placed, _ = await observe()
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
        await self._assert_armed_health(job.robot_id)
        require_fresh_observation()
        job.events.append("two frames support placement after jaw withdrawal")
        return {
            "visually_verified": True,
            "placed_visually_verified": True,
            "criterion": "raised-jaw lift and hold followed by observed lower, release and stable placement",
            "physical_acceptance_pass": False,
            "target": target,
            "note": "Image evidence is experimental; no physical 10 mm lift or loaded object acceptance is claimed",
        }

    def navigate(
        self,
        robot_id: str,
        *,
        label: str | None = None,
        goal: tuple[int, int] | None = None,
        goal_heading: int | None = None,
        start: tuple[int, int] | None = None,
        heading: int | None = None,
    ) -> Job:
        """Execute a bounded, revalidated Guide 60 route proposal through Coordinator."""
        robot = self.robot(robot_id)
        if not robot.motion_enabled or not robot.spatial_navigation_qualified:
            raise OperationError(
                "Spatial navigation requires motion_enabled=true and spatial_navigation_qualified=true"
            )
        if self.dock_inhibited(robot_id):
            raise OperationError("Navigation refused: robot is seated or powered on dock")
        spatial = getattr(self, "spatial", None)
        if spatial is None:
            raise OperationError("Spatial runtime unavailable")
        camera_grant = self._camera_motion_grant()
        memory_grant = None
        if label is not None and self.settings.mode == "hardware":
            if not self.settings.voice_memory_tools_enabled:
                raise OperationError("Object navigation requires private memory consent")
            memory_grant = self.settings.voice_memory_consent_generation
        st = spatial.state(robot_id)
        if self.settings.mode == "hardware" and st.map_to_odom is None:
            raise OperationError("Navigation refused: map-to-odom localization unqualified")
        if label is None and goal is None:
            raise OperationError("Navigation refused: missing_goal_or_target")

        require_localized_pose = self.settings.mode == "hardware" or st.map_to_odom is not None
        if require_localized_pose and (start is None or heading is None):
            if st.grid is None or not st.grid.anchored or st.envelope is None:
                raise OperationError("Navigation refused: unanchored_or_stale_map")
            expected_epoch = st.epoch
            return self._submit(
                robot_id,
                "navigate",
                lambda job: self._navigate(
                    job,
                    route=None,
                    initial_heading=0 if heading is None else heading,
                    expected_epoch=expected_epoch,
                    label=label,
                    goal=goal,
                    goal_heading=goal_heading,
                    requested_start=start,
                    requested_heading=heading,
                    camera_grant=camera_grant,
                    memory_grant=memory_grant,
                    target=None,
                    search=None,
                ),
            )

        chosen_start = (0, 0) if start is None else start
        chosen_heading = 0 if heading is None else heading
        route, target, search = spatial.plan_navigation(
            robot_id,
            start=chosen_start,
            heading=chosen_heading,
            goal=goal,
            label=label,
            goal_heading=goal_heading,
        )
        if route.status != "planned" or route.may_execute is not False or not route.cells:
            raise OperationError(f"Navigation refused: {route.reason}")
        expected_epoch = route.epoch
        if spatial.state(robot_id).epoch != expected_epoch:
            raise OperationError("Navigation refused: spatial map invalidated")
        return self._submit(
            robot_id,
            "navigate",
            lambda job: self._navigate(
                job,
                route=route,
                initial_heading=chosen_heading,
                expected_epoch=expected_epoch,
                label=label,
                camera_grant=camera_grant,
                memory_grant=memory_grant,
                target=target,
                search=search,
            ),
        )

    async def _navigate(
        self,
        job: Job,
        *,
        route,
        initial_heading: int,
        expected_epoch: int,
        label: str | None = None,
        goal: tuple[int, int] | None = None,
        goal_heading: int | None = None,
        requested_start: tuple[int, int] | None = None,
        requested_heading: int | None = None,
        camera_grant: int | None = None,
        memory_grant: int | None = None,
        target: ObjectTarget | None = None,
        search: ObjectSearchResult | None = None,
    ) -> dict:
        from .object_detector import DEFAULT_FRAME_FRESH_US, DetectorFrame
        from .route_planner import revalidate_route_step
        from .spatial_pose import PoseError

        spatial = getattr(self, "spatial", None)
        if spatial is None:
            raise OperationError("Spatial runtime unavailable")
        head = self.heads[job.robot_id]
        robot = self.robot(job.robot_id)
        turn_sign = robot.dock_turn_sign if robot.dock_turn_sign in (-1, 1) else 1
        forward_sign = robot.dock_forward_sign if robot.dock_forward_sign in (-1, 1) else 1
        step_vectors = {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}
        cur_heading = initial_heading

        async def _observe_live_pose():
            pose_reader = getattr(head, "pose_status", None)
            if callable(pose_reader):
                req_start = time.monotonic()
                try:
                    pose_payload = await _bounded_head_reply(
                        pose_reader(),
                        seconds=1.0,
                        timeout_message="Spatial navigation pose status timeout",
                    )
                except Exception:
                    spatial.invalidate_robot(job.robot_id, reason="pose_transport_lost")
                    raise
                return spatial.observe_pose(
                    job.robot_id,
                    pose_payload,
                    received_at=time.monotonic(),
                    request_started_at=req_start,
                    source_fence=getattr(head, "pose_fence", None),
                )
            if self.settings.mode == "hardware":
                spatial.invalidate_robot(job.robot_id, reason="pose_transport_lost")
                raise OperationError("Navigation halted: live pose unavailable")
            return None

        if route is None:
            try:
                self._require_camera_motion_grant(camera_grant)
            except OperationError:
                spatial.invalidate_robot(job.robot_id, reason="camera_consent_revoked")
                raise
            if label is not None and self.settings.mode == "hardware" and (
                memory_grant is None or not self.settings.voice_memory_tools_enabled
                or self.settings.voice_memory_consent_generation != memory_grant
            ):
                raise OperationError("Navigation halted: memory consent changed")
            if self.dock_inhibited(job.robot_id):
                raise OperationError("Navigation halted: robot seated or powered on dock")
            st_init = spatial.state(job.robot_id)
            if (st_init.epoch != expected_epoch or st_init.grid is None
                    or not st_init.grid.anchored or st_init.envelope is None
                    or st_init.map_to_odom is None):
                raise OperationError("Navigation halted: spatial map invalidated")
            receipt = await _observe_live_pose()
            if receipt is None:
                spatial.invalidate_robot(job.robot_id, reason="pose_transport_lost")
                raise OperationError("Navigation halted: live pose unavailable")
            try:
                observed_cell, observed_heading = spatial.localized_pose_cell_heading(
                    job.robot_id, receipt,
                )
            except PoseError as exc:
                spatial.invalidate_robot(job.robot_id, reason="pose_odometry_divergence")
                raise OperationError(f"Navigation halted: {exc}") from exc
            if (requested_start is not None and observed_cell != requested_start) or (
                requested_heading is not None and observed_heading != requested_heading
            ):
                spatial.invalidate_robot(job.robot_id, reason="pose_odometry_divergence")
                raise OperationError("Navigation halted: requested start diverges from localized pose")
            route, target, search = spatial.plan_navigation(
                job.robot_id,
                start=observed_cell,
                heading=observed_heading,
                goal=goal,
                label=label,
                goal_heading=goal_heading,
            )
            if route.status != "planned" or route.may_execute is not False or not route.cells:
                raise OperationError(f"Navigation halted: {route.reason}")
            expected_epoch = route.epoch
            cur_heading = observed_heading

        def _check_step_authority(start_cell: tuple[int, int], goal_cell: tuple[int, int]):
            try:
                self._require_camera_motion_grant(camera_grant)
            except OperationError:
                spatial.invalidate_robot(job.robot_id, reason="camera_consent_revoked")
                raise
            if label is not None and self.settings.mode == "hardware" and (
                memory_grant is None or not self.settings.voice_memory_tools_enabled
                or self.settings.voice_memory_consent_generation != memory_grant
            ):
                raise OperationError("Navigation halted: memory consent changed")
            if self.dock_inhibited(job.robot_id):
                raise OperationError("Navigation halted: robot seated or powered on dock")
            st = spatial.state(job.robot_id)
            if (st.epoch != expected_epoch or st.grid is None or not st.grid.anchored
                    or st.envelope is None):
                reason = st.invalidated_reason or "epoch_changed"
                raise OperationError(f"Navigation halted: spatial map invalidated ({reason})")
            if self.settings.mode == "hardware":
                media = self.multimodal
                # Reuse the authenticated MJPEG owner; a cached JPEG after
                # disconnect or from another camera boot is not current evidence.
                if (media is None or not media.stream_owns_camera(job.robot_id)
                        or not media.status(job.robot_id)["camera_stream_connected"]
                        or not any(
                            frame.source == "proactive"
                            and frame.source_identity is not None
                            and frame.source_identity[0] == st.camera_boot
                            and 0 <= time.monotonic() - frame.received_at <= 1.0
                            for frame in media.hub.frames.get(job.robot_id, ())
                        )):
                    spatial.invalidate_robot(job.robot_id, reason="camera_lost")
                    raise OperationError("Navigation halted: live anchored camera unavailable")
            now_us = spatial.now_us()
            if not revalidate_route_step(
                st.grid.to_route_snapshot(now_us=now_us), route, st.envelope,
                start=start_cell, heading=cur_heading, goal=goal_cell,
                now_us=now_us, clock_us=spatial.now_us,
            ):
                raise OperationError("Navigation halted: route clearance or validity lost")

        async def _verify_step_authority(start_cell: tuple[int, int],
                                         goal_cell: tuple[int, int]) -> None:
            _check_step_authority(start_cell, goal_cell)
            receipt = await _observe_live_pose()
            st_pose = spatial.state(job.robot_id)
            if self.settings.mode == "hardware" or st_pose.map_to_odom is not None:
                if receipt is None:
                    spatial.invalidate_robot(job.robot_id, reason="pose_transport_lost")
                    raise OperationError("Navigation halted: live pose unavailable")
                try:
                    spatial.verify_pose_matches_route_state(
                        job.robot_id,
                        receipt,
                        expected_cell=start_cell,
                        expected_heading=cur_heading,
                    )
                except PoseError as exc:
                    raise OperationError(f"Navigation halted: {exc}") from exc
            # Pose IO can yield to sensor updates, STOP and consent revocation.
            # Refresh local health and then recheck the full inflated edge
            # synchronously immediately before the caller dispatches a pulse.
            await self._assert_armed_health(
                job.robot_id, require_front_clearance=start_cell != goal_cell,
            )
            _check_step_authority(start_cell, goal_cell)
            if self.voice_blocks_motion() is not None:
                raise OperationError("Navigation halted: voice preempted motion")

        def _turn_once(target_heading: int) -> str:
            delta = (target_heading - cur_heading) % 4
            if delta == 1:
                direction = turn_sign
            elif delta == 3:
                direction = -turn_sign
            else:
                raise OperationError("Navigation refused uncalibrated 180-degree spin")
            return f"drive {20 * direction} {-20 * direction} 100"

        try:
            if len(route.cells) <= 1 and (
                route.final_heading is None or route.final_heading == cur_heading
            ):
                await self._assert_armed_health(job.robot_id, require_front_clearance=False)
                await _verify_step_authority(route.cells[0], route.cells[0])
            else:
                prev_cell = route.cells[0]
                for next_cell in route.cells[1:]:
                    await self._assert_armed_health(job.robot_id, require_front_clearance=True)
                    voice_block = self.voice_blocks_motion()
                    if voice_block is not None:
                        return {
                            "status": "stopped_for_voice",
                            "reason": voice_block,
                            "arrived": False,
                            "motor_authorized": False,
                            "charging_authorized": False,
                            "physical_acceptance_pass": False,
                        }
                    await _verify_step_authority(prev_cell, next_cell)
                    dx = next_cell[0] - prev_cell[0]
                    dy = next_cell[1] - prev_cell[1]
                    desired_heading = step_vectors.get((dx, dy))
                    if desired_heading is None:
                        raise OperationError("Navigation halted: non-adjacent route cell")
                    if desired_heading != cur_heading:
                        cmd = _turn_once(desired_heading)
                        await head.command(cmd)
                        await asyncio.sleep(0.05)
                        await _bounded_pulse_stop(head)
                        cur_heading = desired_heading
                        await self._assert_armed_health(
                            job.robot_id, require_front_clearance=True
                        )
                        if self.voice_blocks_motion() is not None:
                            return {
                                "status": "stopped_for_voice",
                                "reason": "voice_barge_in",
                                "arrived": False,
                                "motor_authorized": False,
                                "charging_authorized": False,
                                "physical_acceptance_pass": False,
                            }
                        await _verify_step_authority(prev_cell, next_cell)
                    await head.command(f"drive {20 * forward_sign} {20 * forward_sign} 100")
                    await asyncio.sleep(0.05)
                    await _bounded_pulse_stop(head)
                    job.events.append(f"nav step {next_cell} heading={cur_heading}")
                    prev_cell = next_cell

                if route.final_heading is not None and route.final_heading != cur_heading:
                    raise OperationError("Navigation halted: unplanned final turn")

            if len(route.cells) > 1 and (
                self.settings.mode == "hardware"
                or spatial.state(job.robot_id).map_to_odom is not None
            ):
                await _verify_step_authority(route.cells[-1], route.cells[-1])
            _check_step_authority(route.cells[-1], route.cells[-1])
            if label is None:
                return {
                    "status": "waypoint_reached",
                    "arrived": True,
                    "final_cell": route.cells[-1],
                    "final_heading": cur_heading,
                    "motor_authorized": False,
                    "charging_authorized": False,
                    "physical_acceptance_pass": False,
                }

            def target_result(status: str, reason: str) -> dict:
                return summarize_search_observation(
                    label=label, final_cell=route.cells[-1], target=target,
                    search=search, observation_status=status, reason=reason,
                )

            await self._assert_armed_health(job.robot_id)
            _check_step_authority(route.cells[-1], route.cells[-1])
            if self.voice_blocks_motion() is not None:
                return target_result("rejected", "voice_barge_in")
            if not robot.object_detector_qualified:
                return target_result("rejected", "detector_not_qualified")

            # The detector contract requires a mapped Mac capture time, not
            # merely an MJPEG receipt timestamp or an ESP32 completion clock.
            # Until the qualified stationary capture producer is integrated,
            # never manufacture physical frame identity or a current sighting.
            if self.settings.mode == "hardware":
                return target_result("rejected", "camera_capture_clock_unmapped")

            # Explicit synthetic replay only. Preserve monotonic simulated
            # frame sequence even when the bounded observation list evicts rows.
            try:
                jpeg = await _bounded_head_reply(
                    head.snapshot(), seconds=2.0,
                    timeout_message="Navigation verification snapshot timeout",
                )
            except (HeadError, OSError, TimeoutError):
                _check_step_authority(route.cells[-1], route.cells[-1])
                return target_result("rejected", "camera_unavailable")
            _check_step_authority(route.cells[-1], route.cells[-1])
            if not isinstance(jpeg, bytes):
                return target_result("rejected", "invalid_camera_jpeg")
            st = spatial.state(job.robot_id)
            now_us = spatial.now_us()
            frame_seq = 1 + max((
                item.frame_seq for item in st.observations
                if item.camera_boot == st.camera_boot
                and item.host_boot_id == spatial.host_boot_id
                and item.camera_grant == self.settings.camera_consent_generation
                and type(item.frame_seq) is int
            ), default=0)
            if not 1 <= frame_seq <= 0xFFFFFFFF:
                return target_result("rejected", "simulation_frame_sequence_exhausted")
            frame = DetectorFrame(
                robot_id=job.robot_id,
                session_id=route.session_id,
                turn_id=route.turn_id,
                origin_id=st.origin_id,
                epoch=st.epoch,
                anchor_id=st.anchor_id,
                calibration_id=st.calibration_id,
                camera_boot=st.camera_boot,
                host_boot_id=spatial.host_boot_id,
                camera_grant=self.settings.camera_consent_generation,
                frame_seq=frame_seq,
                captured_us=now_us,
                received_us=now_us,
                seen_at_wall_s=time.time(),
                jpeg=jpeg,
            )
            receipt = await spatial.confirm_target_frame(
                self.vision,
                frame,
                label=label,
                session_id=route.session_id,
                turn_id=route.turn_id,
                model_qualified=True,
                safety_clear=lambda: (
                    spatial.state(job.robot_id).epoch == expected_epoch
                    and not self.dock_inhibited(job.robot_id)
                    and self.voice_blocks_motion() is None
                ),
                request_is_current=lambda: (
                    not job.id or self.jobs.get(job.id, job).state == "running"
                ),
            )
            await self._assert_armed_health(job.robot_id)
            _check_step_authority(route.cells[-1], route.cells[-1])
            if self.voice_blocks_motion() is not None:
                return target_result("rejected", "voice_barge_in")
            current_us = spatial.now_us()
            if (type(current_us) is not int
                    or not 0 <= current_us - frame.captured_us <= DEFAULT_FRAME_FRESH_US):
                return target_result("rejected", "frame_expired")
            if receipt.evidence is not None:
                spatial.record_object_sighting(job.robot_id, receipt.evidence)
            return target_result(receipt.status, receipt.reason)
        except asyncio.CancelledError:
            spatial.invalidate_robot(job.robot_id, reason="navigation_cancelled")
            raise
