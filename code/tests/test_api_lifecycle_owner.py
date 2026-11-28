"""Exercise Mac owner lifecycle without claiming any physical STOP receipt."""

import asyncio
from types import SimpleNamespace

import pytest
from desk_robot.api_lifecycle import runtime_lifespan, runtime_ready
from starlette.datastructures import State


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["startup", "serving"])
@pytest.mark.parametrize("failure_type", [ValueError, asyncio.CancelledError])
async def test_lifespan_preserves_primary_failure_and_reports_cleanup_failure(
    stage, failure_type, caplog,
):
    state = State()
    failure = failure_type("primary lifecycle failure")
    calls = []

    async def start():
        assert not runtime_ready(state)
        calls.append("start")
        if stage == "startup":
            raise failure

    async def close():
        assert not runtime_ready(state)
        calls.append("close")
        raise RuntimeError("STOP unconfirmed")

    state.runtime = SimpleNamespace(start=start, close=close)
    with pytest.raises(failure_type) as caught:
        async with runtime_lifespan(state):
            assert runtime_ready(state)
            assert stage == "serving"
            raise failure

    assert caught.value is failure
    assert failure.__notes__ == ["Runtime shutdown also failed: RuntimeError"]
    assert calls == ["start", "close"]
    assert not runtime_ready(state)
    assert "STOP unconfirmed" in caplog.text


@pytest.mark.asyncio
async def test_lifespan_reports_cleanup_failure_without_primary_failure():
    state = State()

    async def close():
        assert not runtime_ready(state)
        raise RuntimeError("STOP unconfirmed")

    state.runtime = SimpleNamespace(close=close)
    with pytest.raises(RuntimeError, match="STOP unconfirmed"):
        async with runtime_lifespan(state):
            assert runtime_ready(state)
    assert not runtime_ready(state)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["startup", "serving"])
async def test_lifespan_keeps_cleanup_bound_to_started_owner(stage):
    state = State()
    calls = []

    async def replacement_close():
        calls.append("replacement close")

    replacement = SimpleNamespace(close=replacement_close)

    async def start():
        calls.append("original start")
        if stage == "startup":
            state.runtime = replacement

    async def close():
        assert not runtime_ready(state)
        calls.append("original close")

    state.runtime = SimpleNamespace(start=start, close=close)
    if stage == "startup":
        with pytest.raises(RuntimeError, match="Runtime owner changed during startup"):
            async with runtime_lifespan(state):
                pytest.fail("replacement runtime must not be admitted")
    else:
        async with runtime_lifespan(state):
            assert runtime_ready(state)
            state.runtime = replacement
            assert not runtime_ready(state)

    assert calls == ["original start", "original close"]
    assert not runtime_ready(state)
