"""Synchronous host motion admission evidence; never physical motor authority."""

from collections.abc import Iterable
from typing import Literal, TypedDict

HostStopStatus = Literal[
    "idle_or_confirmed",
    "pending",
    "unconfirmed",
    "local_fault_latched",
    "fleet_blocked",
]


class HostStopState(TypedDict):
    """Typed, source-labelled host WROOM STOP confirmation latch state."""

    source: Literal["mac_coordinator_stop_tracker"]
    state: HostStopStatus
    blocked: bool
    robot_blocked: bool
    fleet_blocked: bool
    stop_pending: bool
    stop_unconfirmed: bool
    local_fault_latched: bool
    pending_robots: list[str]
    unconfirmed_robots: list[str]
    local_fault_robots: list[str]
    explicit_recovery_required: bool
    motor_authorized: Literal[False]
    physical_stop_verified: Literal[False]


class StopConfirmationTracker:
    """Fence the fleet until the latest explicit STOP attempt is confirmed.

    Calls are synchronous on the coordinator event loop. No transport or task
    cleanup belongs here: those remain the responsibility of Coordinator.
    """

    def __init__(self, robot_ids: Iterable[str]) -> None:
        self.pending: dict[str, int] = {}
        self.generation: dict[str, int] = dict.fromkeys(robot_ids, 0)
        self.unconfirmed: set[str] = set()
        self.local_faults: set[str] = set()
        self.recovered_generation: dict[str, int] = dict.fromkeys(self.generation, 0)

    def latch_fault(self, robot_id: str) -> None:
        # A new fault also fences any explicit recovery already in flight.
        self.generation[robot_id] += 1
        self.local_faults.add(robot_id)

    def begin(self, robot_id: str, *, local_fault: bool = False) -> int:
        if local_fault:
            self.latch_fault(robot_id)
        else:
            self.generation[robot_id] += 1
        self.pending[robot_id] = self.pending.get(robot_id, 0) + 1
        return self.generation[robot_id]

    def finish(
        self, robot_id: str, generation: int, *, acknowledged: bool,
        explicit_recovery: bool = True,
    ) -> None:
        # Automatic HALT can confirm stopping but cannot authorize recovery.
        # A newer automatic success must not hide an older failed STOP.
        if acknowledged and explicit_recovery and self.generation[robot_id] == generation:
            self.recovered_generation[robot_id] = generation
            self.unconfirmed.discard(robot_id)
            self.local_faults.discard(robot_id)
        elif not acknowledged and generation > self.recovered_generation[robot_id]:
            self.unconfirmed.add(robot_id)
        self.pending[robot_id] -= 1
        if not self.pending[robot_id]:
            del self.pending[robot_id]

    def blocked(self, robot_id: str | None = None) -> bool:
        if robot_id is None:
            return bool(self.pending or self.unconfirmed)
        return (robot_id in self.pending or robot_id in self.unconfirmed
                or robot_id in self.local_faults)

    def fleet_block_reason(self, owner_id: str | None) -> str | None:
        if owner_id is not None:
            return "Fleet motion busy: one moving pet until WROOM STOP is acknowledged"
        if self.blocked():
            return "Fleet motion blocked: WROOM STOP pending or unconfirmed"
        return None

    def host_stop_state(self, robot_id: str | None = None) -> HostStopState:
        """Return the host STOP latch view for one robot or the fleet."""
        pending_robots = sorted(self.pending)
        unconfirmed_robots = sorted(self.unconfirmed)
        local_fault_robots = sorted(self.local_faults)
        fleet_blocked = self.blocked()
        if robot_id is None:
            robot_pending = bool(pending_robots)
            robot_unconfirmed = bool(unconfirmed_robots)
            robot_local_fault = bool(local_fault_robots)
            robot_blocked = bool(
                robot_pending or robot_unconfirmed or robot_local_fault
            )
            if robot_unconfirmed:
                state: HostStopStatus = "unconfirmed"
            elif robot_local_fault:
                state = "local_fault_latched"
            elif robot_pending:
                state = "pending"
            else:
                state = "idle_or_confirmed"
        else:
            robot_pending = robot_id in self.pending
            robot_unconfirmed = robot_id in self.unconfirmed
            robot_local_fault = robot_id in self.local_faults
            robot_blocked = self.blocked(robot_id)
            if robot_unconfirmed:
                state = "unconfirmed"
            elif robot_local_fault:
                state = "local_fault_latched"
            elif robot_pending:
                state = "pending"
            elif fleet_blocked:
                state = "fleet_blocked"
            else:
                state = "idle_or_confirmed"
        return {
            "source": "mac_coordinator_stop_tracker",
            "state": state,
            "blocked": robot_blocked or fleet_blocked,
            "robot_blocked": robot_blocked,
            "fleet_blocked": fleet_blocked,
            "stop_pending": robot_pending,
            "stop_unconfirmed": robot_unconfirmed,
            "local_fault_latched": robot_local_fault,
            "pending_robots": pending_robots,
            "unconfirmed_robots": unconfirmed_robots,
            "local_fault_robots": local_fault_robots,
            "explicit_recovery_required": bool(
                unconfirmed_robots or local_fault_robots
            ),
            "motor_authorized": False,
            "physical_stop_verified": False,
        }
