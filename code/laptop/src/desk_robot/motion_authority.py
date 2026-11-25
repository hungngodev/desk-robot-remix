"""Synchronous host motion admission evidence; never physical motor authority."""

from collections.abc import Iterable


class StopConfirmationTracker:
    """Fence the fleet until the latest explicit STOP attempt is confirmed.

    Calls are synchronous on the coordinator event loop. No transport or task
    cleanup belongs here: those remain the responsibility of Coordinator.
    """

    def __init__(self, robot_ids: Iterable[str]) -> None:
        self.pending: dict[str, int] = {}
        self.generation: dict[str, int] = dict.fromkeys(robot_ids, 0)
        self.unconfirmed: set[str] = set()

    def begin(self, robot_id: str) -> int:
        self.generation[robot_id] += 1
        self.pending[robot_id] = self.pending.get(robot_id, 0) + 1
        return self.generation[robot_id]

    def finish(self, robot_id: str, generation: int, *, acknowledged: bool) -> None:
        # Only the latest explicit attempt owns confirmation evidence. Older
        # attempts still own their pending counts until their cleanup settles.
        if self.generation[robot_id] == generation:
            if acknowledged:
                self.unconfirmed.discard(robot_id)
            else:
                self.unconfirmed.add(robot_id)
        self.pending[robot_id] -= 1
        if not self.pending[robot_id]:
            del self.pending[robot_id]

    def blocked(self, robot_id: str | None = None) -> bool:
        if robot_id is None:
            return bool(self.pending or self.unconfirmed)
        return robot_id in self.pending or robot_id in self.unconfirmed

    def fleet_block_reason(self, owner_id: str | None) -> str | None:
        if owner_id is not None:
            return "Fleet motion busy: one moving pet until WROOM STOP is acknowledged"
        if self.blocked():
            return "Fleet motion blocked: WROOM STOP pending or unconfirmed"
        return None
