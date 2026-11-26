"""Shared async operations independent of the motion coordinator."""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

_T = TypeVar("_T")


def require_active_operation(state: str) -> None:
    """Reject a revoked job even if an adapter swallowed cancellation."""
    task = asyncio.current_task()
    if state != "running" or (task is not None and task.cancelling()):
        raise asyncio.CancelledError


async def dispatch_job_command(
    head, command: str, check: Callable[[], None], *,
    dispatch_check: Callable[[], None] | None = None,
) -> dict:
    """Recheck host authority before enqueue, at supported dispatch, and after ACK."""
    def at_dispatch() -> None:
        check()
        if dispatch_check is not None:
            dispatch_check()

    check()
    if getattr(head, "supports_dispatch_check", False):
        reply = await head.command(command, dispatch_check=at_dispatch)
    else:
        reply = await head.command(command)
    check()
    return reply


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
        # Cancellation may arrive after the child finishes but before the
        # parent resumes from wait(). Observe failures in either state,
        # without replacing the original cancellation or timeout.
        if task.done():
            if not task.cancelled():
                task.exception()
        else:
            task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )


class OperationError(RuntimeError):
    pass
