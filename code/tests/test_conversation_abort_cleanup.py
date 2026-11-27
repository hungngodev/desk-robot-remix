import asyncio
import gc

import pytest
from desk_robot.conversation import _bounded_speaker_abort


def test_cancelled_abort_observes_already_failed_interrupt():
    async def scenario():
        loop = asyncio.get_running_loop()
        reports = []
        loop.set_exception_handler(lambda _loop, context: reports.append(context))

        async def interrupt(_robot):
            owner.cancel()
            raise RuntimeError("injected interrupt failure")

        owner = asyncio.create_task(_bounded_speaker_abort(interrupt, object()))
        try:
            await owner
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("owner did not cancel")
        del owner
        for _ in range(3):
            await asyncio.sleep(0)
            gc.collect()
        assert not reports, [report.get("message") for report in reports]

    asyncio.run(scenario())


def test_abort_propagates_interrupt_error():
    async def interrupt(_robot):
        raise RuntimeError("injected interrupt failure")

    with pytest.raises(RuntimeError, match="injected interrupt failure"):
        asyncio.run(_bounded_speaker_abort(interrupt, object()))


def test_abort_returns_success_receipt():
    receipt = object()

    async def interrupt(_robot):
        return receipt

    assert asyncio.run(_bounded_speaker_abort(interrupt, object())) is receipt
