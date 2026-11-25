"""Mac lifecycle admission; never a physical preflight or motion permit."""

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


async def require_runtime_ready(request: Request) -> None:
    if not runtime_ready(request.app.state):
        raise HTTPException(503, "Runtime unavailable")
