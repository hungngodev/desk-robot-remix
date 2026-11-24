"""Reject malformed Xiaozhi pickup targets before any Mac motion request.

Extract only the registered handler to avoid importing the pinned Xiaozhi
server and its hardware dependencies during this contract regression.
"""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "laptop/server/overlay/desk_robot_tools.py"


def _handler():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    node = next(
        n for n in module.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "desk_robot_pickup"
    )
    node.decorator_list = []
    calls = []

    async def call(*args):
        calls.append(args)
        return {"robot_id": "pet1", "id": "job1"}

    class ActionResponse:
        def __init__(self, action, result=None):
            self.action = action
            self.result = result

    scope = {
        "call": call,
        "ActionResponse": ActionResponse,
        "Action": SimpleNamespace(REQLLM="request_llm"),
        "voice_turn_response": lambda result: ActionResponse("request_llm", result),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 str(SOURCE), "exec"), scope)
    return scope["desk_robot_pickup"], calls


@pytest.mark.parametrize("target", [
    [], {}, ["key"], {"target": "key"}, 0, 1.5, True, False, None, b"key",
    "", "Key", "CANDY", " key", "candy ", "key\n", "key\x00", "coin", "../stop",
])
def test_malformed_pickup_targets_do_not_reach_mac(target):
    handler, calls = _handler()
    response = asyncio.run(handler(object(), target))
    assert response.action == "request_llm"
    assert response.result == {"error": "Target must be key or candy"}
    assert calls == []


@pytest.mark.parametrize("target", ["key", "candy"])
def test_valid_pickup_targets_reach_existing_mac_owner(target):
    handler, calls = _handler()
    conn = object()
    response = asyncio.run(handler(conn, target))
    assert response.action == "request_llm"
    assert response.result == {"robot_id": "pet1", "id": "job1"}
    assert calls == [(conn, "pickup", {"target": target})]
