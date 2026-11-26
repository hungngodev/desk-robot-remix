"""Shared async operations independent of the motion coordinator."""
from __future__ import annotations

import asyncio
from time import monotonic
from typing import Awaitable, Callable, TypeVar

from .command_framing import MAX_DRIVE_DURATION_MS, command_ack_matches, expected_ack

_T = TypeVar("_T")


def require_active_operation(state: str) -> None:
    """Reject a revoked job even if an adapter swallowed cancellation."""
    task = asyncio.current_task()
    if state != "running" or (task is not None and task.cancelling()):
        raise asyncio.CancelledError


async def dispatch_job_command(
    head, command: str, check: Callable[[], None], *, robot_id: str,
    dispatch_check: Callable[[], None] | None = None,
) -> dict:
    """Recheck authority and require a matching command receipt from every adapter."""
    expected = expected_ack(command)
    # A queued drive must not gain a fresh body pulse after host scheduling stalls.
    # The WROOM independently enforces the duration of commands it receives.
    deadline = (
        monotonic() + MAX_DRIVE_DURATION_MS / 1000 if command.startswith("drive ") else None
    )

    def at_dispatch() -> None:
        check()
        if dispatch_check is not None:
            dispatch_check()
        if deadline is not None and monotonic() >= deadline:
            raise OperationError("Drive dispatch expired before transport send")

    check()
    if getattr(head, "supports_dispatch_check", False):
        reply = await head.command(command, dispatch_check=at_dispatch)
    else:
        # Legacy adapters expose no queue boundary; check before handing off.
        at_dispatch()
        reply = await head.command(command)
    check()
    if not command_ack_matches(reply, robot_id, expected):
        raise OperationError("Unmatched or failed command ACK; movement not retried")
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
