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
    validator = next(
        n for n in module.body
        if isinstance(n, ast.FunctionDef) and n.name == "_valid_tool_payload"
    )
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
    exec(compile(ast.fix_missing_locations(ast.Module(body=[validator, node], type_ignores=[])),
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
    assert response.result == {"error": "Invalid robot tool arguments", "retried": False}
    assert calls == []


@pytest.mark.parametrize("extra", [
    {"angle": 90}, {"pwm": 1500}, {"command": "grip 90"},
    {"grip_open": 60}, {"grip_closed": 120}, {"permit": True},
])
def test_pickup_rejects_raw_actuator_overrides(extra):
    handler, calls = _handler()
    response = asyncio.run(handler(object(), "key", **extra))
    assert response.result == {"error": "Invalid robot tool arguments", "retried": False}
    assert calls == []


@pytest.mark.parametrize("target", ["key", "candy"])
def test_valid_pickup_targets_reach_existing_mac_owner(target):
    handler, calls = _handler()
    conn = object()
    response = asyncio.run(handler(conn, target))
    assert response.action == "request_llm"
    assert response.result == {"robot_id": "pet1", "id": "job1"}
    assert calls == [(conn, "pickup", {"target": target})]


def test_real_registry_binds_desk_robot_pickup_schema_and_runtime_guards(monkeypatch):
    import importlib.util
    import sys

    code_root = Path(__file__).resolve().parents[1]
    register_path = (
        code_root
        / "upstream/xiaozhi-esp32-server/main/xiaozhi-server/plugins_func/register.py"
    )

    config_pkg = SimpleNamespace()
    logger_stub = SimpleNamespace(bind=lambda **kw: SimpleNamespace(debug=lambda *_a: None))
    config_logger = SimpleNamespace(setup_logging=lambda: logger_stub)
    monkeypatch.setitem(sys.modules, "config", config_pkg)
    monkeypatch.setitem(sys.modules, "config.logger", config_logger)

    reg_spec = importlib.util.spec_from_file_location("plugins_func.register", register_path)
    register_mod = importlib.util.module_from_spec(reg_spec)
    plugins_pkg = SimpleNamespace(__path__=[])
    monkeypatch.setitem(sys.modules, "plugins_func", plugins_pkg)
    monkeypatch.setitem(sys.modules, "plugins_func.register", register_mod)
    reg_spec.loader.exec_module(register_mod)

    bridge_calls = []
    bridge_stub = SimpleNamespace(
        connections={},
        robot_for_device=lambda _dev: None,
        voice_turn_generation={},
        tool_turn_cancel_event=lambda _dev: None,
    )
    monkeypatch.setitem(sys.modules, "desk_robot_bridge", bridge_stub)

    tools_spec = importlib.util.spec_from_file_location("desk_robot_tools_registered", SOURCE)
    tools_mod = importlib.util.module_from_spec(tools_spec)
    monkeypatch.setitem(sys.modules, "desk_robot_tools_registered", tools_mod)
    tools_spec.loader.exec_module(tools_mod)

    assert "desk_robot_pickup" in register_mod.all_function_registry
    item = register_mod.all_function_registry["desk_robot_pickup"]
    assert item.name == "desk_robot_pickup"
    assert item.type == register_mod.ToolType.IOT_CTL
    fn_schema = item.description["function"]
    assert fn_schema["name"] == "desk_robot_pickup"
    params = fn_schema["parameters"]
    assert params["required"] == ["target"]
    assert params["additionalProperties"] is False
    assert params["properties"]["target"] == {"type": "string", "enum": ["key", "candy"]}

    async def fake_call(*args):
        bridge_calls.append(args)
        return {"robot_id": "pet1", "id": "job1"}

    monkeypatch.setattr(tools_mod, "call", fake_call)
    missing = asyncio.run(item.func(object()))
    assert missing.result == {"error": "Invalid robot tool arguments", "retried": False}

    wrong = asyncio.run(item.func(object(), 123))
    assert wrong.action == register_mod.Action.REQLLM
    assert wrong.result == {"error": "Invalid robot tool arguments", "retried": False}
    coin = asyncio.run(item.func(object(), "coin"))
    assert coin.action == register_mod.Action.REQLLM
    assert coin.result == {"error": "Invalid robot tool arguments", "retried": False}
    assert bridge_calls == []

    conn = object()
    valid = asyncio.run(item.func(conn, "key"))
    assert valid.action == register_mod.Action.REQLLM
    assert valid.result == {"robot_id": "pet1", "id": "job1"}
    assert bridge_calls == [(conn, "pickup", {"target": "key"})]
