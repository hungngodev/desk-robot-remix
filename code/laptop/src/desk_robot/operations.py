"""Shared async operations independent of the motion coordinator."""
from __future__ import annotations

import asyncio
from typing import Awaitable, TypeVar

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


class OperationError(RuntimeError):
    pass
