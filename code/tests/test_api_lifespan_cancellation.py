"""The original lifespan cancellation must survive a failed runtime close."""

import asyncio
from types import SimpleNamespace

import pytest
from desk_robot.api import create_app


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["startup", "serving"])
async def test_cancelled_lifespan_preserves_cancellation(settings, tokens, caplog, stage):
    entered = asyncio.Event()
    closed = asyncio.Event()

    async def block():
        entered.set()
        await asyncio.Event().wait()

    async def start():
        if stage == "startup":
            await block()

    async def close():
        assert app.state.runtime_started is False
        closed.set()
        raise RuntimeError("STOP unconfirmed")

    app = create_app(settings, runtime=SimpleNamespace(start=start, close=close))

    async def lifespan():
        async with app.router.lifespan_context(app):
            await block()

    task = asyncio.create_task(lifespan())
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()
        assert "STOP unconfirmed" in caplog.text
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_uncancelled_lifespan_reports_close_failure(settings, tokens):
    async def close():
        raise RuntimeError("STOP unconfirmed")

    app = create_app(settings, runtime=SimpleNamespace(close=close))
    with pytest.raises(RuntimeError, match="STOP unconfirmed"):
        async with app.router.lifespan_context(app):
            pass
    assert app.state.runtime_started is False
