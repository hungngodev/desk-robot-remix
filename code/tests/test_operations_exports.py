import asyncio

import pytest

from desk_robot import operations


def test_operations_exports_only_intended_shared_boundary():
    expected = {
        "OperationError",
        "bounded_head_reply",
        "bounded_pulse_stop",
        "dispatch_job_command",
        "require_active_operation",
        "require_command_receipt",
    }
    assert set(operations.__all__) == expected
    namespace = {}
    exec("from desk_robot.operations import *", namespace)
    assert set(namespace) - {"__builtins__"} == expected
    for name in ("bounded_head_reply", "bounded_pulse_stop", "require_command_receipt"):
        assert getattr(operations, name) is getattr(operations, f"_{name}")


def test_public_receipt_boundary_rejects_wrong_robot():
    receipt = {"ok": True, "robot_id": "one", "reply": "OK stop", "extra": 1}
    assert operations.require_command_receipt(receipt, "one", "OK stop") == {
        "ok": True, "robot_id": "one", "reply": "OK stop",
    }
    with pytest.raises(operations.OperationError):
        operations.require_command_receipt(receipt, "two", "OK stop")


def test_public_bounded_reply_rejects_late_result():
    async def scenario():
        cancelled = asyncio.Event()

        async def late():
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                return "late"

        with pytest.raises(TimeoutError, match="expired"):
            await operations.bounded_head_reply(late(), seconds=0.01, timeout_message="expired")
        await asyncio.wait_for(cancelled.wait(), timeout=1)

    asyncio.run(scenario())
