"""Bound optional SQLite writes independently of voice and transport workers."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from threading import BoundedSemaphore, Lock
from typing import Callable


class MemoryWriteBackpressure(RuntimeError):
    """Optional memory admission exhausted; no transaction was submitted."""


class OptionalMemoryWriter:
    """Keep complete transactions off-loop without an unbounded executor queue.

    A slot belongs to the underlying thread future, not its cancellable awaiter.
    Required operator corrections/deletions must not use this optional lane.
    """

    def __init__(self, workers: int):
        if type(workers) is not int or workers < 1:
            raise ValueError("Memory worker capacity must be a positive integer")
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pet-memory")
        self._slots = BoundedSemaphore(workers)
        self._pending: set[Future[None]] = set()
        self._pending_lock = Lock()

    async def run(self, write: Callable[[], None]) -> None:
        if not self._slots.acquire(blocking=False):
            raise MemoryWriteBackpressure("Optional memory workers are busy")
        try:
            with self._pending_lock:
                future = self._executor.submit(copy_context().run, write)
                self._pending.add(future)
        except BaseException:
            self._slots.release()
            raise
        future.add_done_callback(self._retire)
        await asyncio.shield(self._observe(future))

    def _retire(self, future: Future[None]) -> None:
        with self._pending_lock:
            self._pending.remove(future)
            self._slots.release()

    @staticmethod
    def _observe(future: Future[None]) -> asyncio.Future[None]:
        wrapped = asyncio.wrap_future(future)
        # Cancellation of an audio waiter must not cancel an admitted write,
        # including one whose executor thread has not started yet. Observe
        # late exceptions even when the original waiter has departed.
        wrapped.add_done_callback(
            lambda done: None if done.cancelled() else done.exception()
        )
        return wrapped

    async def drain(self) -> None:
        """Wait off the audio path for admitted writes after producers stop.

        A cancelled shutdown waiter does not cancel the actual transactions.
        Keep this shared pool reusable across runtime lifespans.
        """
        while True:
            with self._pending_lock:
                pending = tuple(self._pending)
            if not pending:
                return
            await asyncio.wait([self._observe(future) for future in pending])

    def close(self) -> None:
        """Join admitted transactions from outside the event loop."""
        self._executor.shutdown(wait=True)


# At most one worker per pet in the five-pet fleet, shared across conversations.
# SQLite itself still owns each database's transaction ordering and rollback.
optional_memory_writer = OptionalMemoryWriter(5)
