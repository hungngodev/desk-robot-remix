"""Fair, latest-only admission for optional fleet JPEG preprocessing."""
from __future__ import annotations

import asyncio
from collections.abc import Callable


class LatestFrameAdmission:
    """One pending ticket per robot; replacement never changes fleet order."""

    def __init__(self) -> None:
        self._pending: dict[str, tuple[object, float]] = {}
        self._changed = asyncio.Event()
        self._closed = False

    def notify(self) -> None:
        """Wake waiters on the owning event loop after native capacity returns."""
        self._changed.set()

    def close(self) -> None:
        self._closed = True
        self.notify()

    async def acquire(
        self, robot_id: str, received: float, *, clock: Callable[[], float],
        reserve: Callable[[], bool], admit: Callable[[], bool],
    ) -> None:
        if self._closed or not admit() or not 0 <= clock() - received < 1.0:
            raise RuntimeError("Camera preprocessing admission invalidated or expired")
        previous = self._pending.get(robot_id)
        if previous is not None and received <= previous[1]:
            raise RuntimeError("Camera preprocessing superseded by newer frame")
        ticket = (object(), received)
        self._pending[robot_id] = ticket
        self.notify()
        try:
            while True:
                if self._pending.get(robot_id) is not ticket:
                    raise RuntimeError("Camera preprocessing superseded by newer frame")
                remaining = 1.0 - (clock() - received)
                if self._closed or not admit() or not 0 < remaining <= 1.0:
                    raise RuntimeError("Camera preprocessing admission invalidated or expired")
                if next(iter(self._pending)) == robot_id and reserve():
                    return
                self._changed.clear()
                try:
                    async with asyncio.timeout(remaining):
                        await self._changed.wait()
                except TimeoutError as exc:
                    raise RuntimeError("Camera preprocessing admission expired") from exc
        finally:
            if self._pending.get(robot_id) is ticket:
                del self._pending[robot_id]
                self.notify()
