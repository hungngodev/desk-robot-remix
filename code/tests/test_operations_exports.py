import ast
import asyncio
from pathlib import Path

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



def _private_operations_imports(source: str) -> list[str]:
    return [
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
        and ((node.level == 1 and node.module == "operations")
             or (node.level == 0 and node.module == "desk_robot.operations"))
        for alias in node.names
        if alias.name.startswith("_") or alias.name == "*"
    ]


def test_internal_consumers_import_only_shared_operations():
    package = Path(operations.__file__).parent
    violations = {}
    for path in package.glob("*.py"):
        if names := _private_operations_imports(path.read_text(encoding="utf-8")):
            violations[path.name] = names
    assert not violations


@pytest.mark.parametrize("source, expected", [
    ("from .operations import _bounded_head_reply", ["_bounded_head_reply"]),
    ("from desk_robot.operations import *", ["*"]),
    ("from .operations import bounded_head_reply as _bounded_head_reply", []),
    ("from .other import _bounded_head_reply", []),
])
def test_operations_import_guard(source, expected):
    assert _private_operations_imports(source) == expected
