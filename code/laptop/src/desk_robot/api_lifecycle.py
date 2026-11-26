"""Mac lifecycle admission; never a physical preflight or motion permit."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import HTTPException, Request
from starlette.datastructures import State


def runtime_ready(state: State) -> bool:
    owner = getattr(state, "runtime", None)
    return (
        owner is not None
        and getattr(state, "runtime_started", False) is True
        and not getattr(owner, "_closed", False)
        and getattr(owner, "_fatal_service_error", None) is None
    )


@asynccontextmanager
async def runtime_lifespan(state: State):
    """Preserve the initiating failure while reporting unconfirmed cleanup."""
    state.runtime_started = False
    primary: BaseException | None = None
    try:
        start = getattr(state.runtime, "start", None)
        if callable(start):
            await start()
        state.runtime_started = True
        yield
    except BaseException as error:
        primary = error
        raise
    finally:
        state.runtime_started = False
        try:
            await state.runtime.close()
        except (Exception, asyncio.CancelledError) as error:
            if primary is None:
                raise
            primary.add_note(f"Runtime shutdown also failed: {type(error).__name__}")
            logging.getLogger(__name__).error(
                "Runtime shutdown failed after lifespan failure", exc_info=error,
            )


async def require_runtime_ready(request: Request) -> None:
    if not runtime_ready(request.app.state):
        raise HTTPException(503, "Runtime unavailable")
