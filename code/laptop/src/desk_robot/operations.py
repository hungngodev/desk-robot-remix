"""Shared async operations independent of the motion coordinator."""
from __future__ import annotations

import asyncio
from time import monotonic
from typing import Awaitable, Callable, TypeVar

from .command_framing import MAX_DRIVE_DURATION_MS, command_ack_matches, expected_ack
from .sleep_clock import continuous_monotonic

__all__ = [
    "OperationError",
    "bounded_head_reply",
    "bounded_pulse_stop",
    "dispatch_job_command",
    "require_active_operation",
    "require_command_receipt",
]

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
    cont_deadline = (
        continuous_monotonic() + MAX_DRIVE_DURATION_MS / 1000
        if command.startswith("drive ") else None
    )

    def at_dispatch() -> None:
        check()
        if dispatch_check is not None:
            dispatch_check()
        if (deadline is not None and monotonic() >= deadline) or (
            cont_deadline is not None and continuous_monotonic() >= cont_deadline
        ):
            raise OperationError("Drive dispatch expired before transport send")

    check()
    if getattr(head, "supports_dispatch_check", False):
        reply = await head.command(command, dispatch_check=at_dispatch)
    else:
        # Legacy adapters expose no queue boundary; check before handing off.
        at_dispatch()
        reply = await head.command(command)
    check()
    return _require_command_receipt(reply, robot_id, expected)


def _require_command_receipt(reply: dict, robot_id: str, expected: str) -> dict:
    if type(reply) is not dict or not command_ack_matches(reply, robot_id, expected):
        raise OperationError(f"Unmatched or failed command ACK: {expected}; movement not retried")
    # Only the wire acknowledgement is established; adapter extras are not evidence.
    return {"ok": True, "robot_id": robot_id, "reply": expected}


async def _bounded_head_reply(coro: Awaitable[_T], *, seconds: float,
                              timeout_message: str) -> _T:
    """Bound even adapters that suppress task cancellation; ignore late replies."""
    # Callers may already own a cancellable snapshot task for VAD preemption.
    task = asyncio.ensure_future(coro)
    try:
        done, _ = await asyncio.wait({task}, timeout=seconds)
        if not done:
            raise TimeoutError(timeout_message)
        # An independently cancelled child may suppress CancelledError and
        # return a plausible receipt (or translate it to another exception).
        # Reject that child's outcome, not the parent's cancellation count:
        # terminal STOP cleanup may run inside a cancelling parent.
        if isinstance(task, asyncio.Task) and task.cancelling():
            raise asyncio.CancelledError
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


async def _bounded_pulse_stop(head, robot_id: str) -> dict:
    """Require an exact STOP receipt before another supervised pulse."""
    receipt = await _bounded_head_reply(
        head.command("stop"), seconds=1.0,
        timeout_message="WROOM pulse STOP transport acknowledgement unconfirmed",
    )
    return _require_command_receipt(receipt, robot_id, expected_ack("stop"))


class OperationError(RuntimeError):
    pass


# Shared subsystem boundary; retain existing private names for legacy callers.
bounded_head_reply = _bounded_head_reply
bounded_pulse_stop = _bounded_pulse_stop
require_command_receipt = _require_command_receipt
