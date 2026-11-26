"""Bound optional SQLite writes independently of voice and transport workers."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import BoundedSemaphore
from typing import Callable


class MemoryWriteBackpressure(RuntimeError):
    """Optional memory admission exhausted; no transaction was submitted."""


class OptionalMemoryWriter:
    """Keep complete transactions off-loop without an unbounded executor queue.

    A slot belongs to the underlying thread future, not its cancellable awaiter.
    Required operator corrections/deletions must not use this optional lane.
    """

    def __init__(self, workers: int):
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pet-memory")
        self._slots = BoundedSemaphore(workers)

    async def run(self, write: Callable[[], None]) -> None:
        if not self._slots.acquire(blocking=False):
            raise MemoryWriteBackpressure("Optional memory workers are busy")
        try:
            future = self._executor.submit(copy_context().run, write)
        except BaseException:
            self._slots.release()
            raise
        future.add_done_callback(lambda _: self._slots.release())
        await asyncio.wrap_future(future)

    def close(self) -> None:
        """Join admitted transactions from outside the event loop."""
        self._executor.shutdown(wait=True)


# At most one worker per pet in the five-pet fleet, shared across conversations.
# SQLite itself still owns each database's transaction ordering and rollback.
optional_memory_writer = OptionalMemoryWriter(5)
