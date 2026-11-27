"""Fair, latest-only admission for optional fleet JPEG preprocessing."""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from .sensor_event_contract import is_finite_number


class FrameAdmissionDropped(RuntimeError):
    """An optional frame lost admission; no native work was submitted."""


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
            raise FrameAdmissionDropped("Camera preprocessing admission invalidated or expired")
        previous = self._pending.get(robot_id)
        if previous is not None and received <= previous[1]:
            raise FrameAdmissionDropped("Camera preprocessing superseded by newer frame")
        ticket = (object(), received)
        self._pending[robot_id] = ticket
        self.notify()
        try:
            while True:
                if self._pending.get(robot_id) is not ticket:
                    raise FrameAdmissionDropped("Camera preprocessing superseded by newer frame")
                remaining = 1.0 - (clock() - received)
                if self._closed or not admit() or not 0 < remaining <= 1.0:
                    raise FrameAdmissionDropped(
                        "Camera preprocessing admission invalidated or expired"
                    )
                if next(iter(self._pending)) == robot_id and reserve():
                    return
                self._changed.clear()
                try:
                    async with asyncio.timeout(remaining):
                        await self._changed.wait()
                except TimeoutError as exc:
                    raise FrameAdmissionDropped("Camera preprocessing admission expired") from exc
        finally:
            if self._pending.get(robot_id) is ticket:
                del self._pending[robot_id]
                self.notify()


@asynccontextmanager
async def vision_lock_until(lock: asyncio.Lock, remaining: float):
    """Retire queued JPEG references by their oldest frame's deadline."""
    if not is_finite_number(remaining) or remaining <= 0:
        raise RuntimeError("Camera observation expired while queued")
    try:
        async with asyncio.timeout(remaining):
            await lock.acquire()
    except TimeoutError as exc:
        raise RuntimeError("Camera observation expired while queued") from exc
    try:
        yield
    finally:
        lock.release()


class VisionCallAdmission:
    """One current model call plus at most one cancellation-resistant retiree."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[str]] = set()

    def active(self) -> set[asyncio.Task[str]]:
        return {task for task in self._tasks if not task.done()}

    def start(self, request: Callable[[], Coroutine[Any, Any, str]]) -> asyncio.Task[str]:
        if len(self.active()) >= 2:
            raise RuntimeError("Visual model capacity occupied by unfinished calls")
        task = asyncio.create_task(request())
        self._tasks.add(task)
        task.add_done_callback(self._retire)
        return task

    def _retire(self, task: asyncio.Task[str]) -> None:
        try:
            if not task.cancelled():
                task.exception()
        finally:
            self._tasks.discard(task)
