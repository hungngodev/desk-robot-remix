import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import httpx
import pytest


@pytest.fixture
def tools(monkeypatch):
    bridge = ModuleType("desk_robot_bridge")
    head = SimpleNamespace(device_id="head-01")
    bridge.connections = {head.device_id: head}
    bridge.robot_for_device = lambda device: "robot-01" if device == head.device_id else None
    bridge.voice_turn_generation = {head.device_id: 1}
    registry = ModuleType("plugins_func.register")
    registry.Action = SimpleNamespace(REQLLM=3, NONE=1)
    registry.ToolType = SimpleNamespace(IOT_CTL=5)
    registry.ActionResponse = lambda action, result=None: SimpleNamespace(
        action=action, result=result
    )
    registry.register_function = lambda *args, **kwargs: lambda fn: fn
    wire = ModuleType("desk_robot_omni_wire")
    wire.coordinator_base_url = lambda: "http://127.0.0.1:8765"
    monkeypatch.setitem(sys.modules, "desk_robot_bridge", bridge)
    monkeypatch.setitem(sys.modules, "plugins_func", ModuleType("plugins_func"))
    monkeypatch.setitem(sys.modules, "plugins_func.register", registry)
    monkeypatch.setitem(sys.modules, "desk_robot_omni_wire", wire)
    path = Path(__file__).resolve().parents[1] / "laptop/server/overlay/desk_robot_tools.py"
    spec = importlib.util.spec_from_file_location("desk_tools_json_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("DESK_ROBOT_TOOL_TOKEN", "s" * 40)
    monkeypatch.setenv("DESK_ROBOT_SPEECH_TOKEN", "r" * 40)
    return module, head


@pytest.mark.asyncio
@pytest.mark.parametrize("route,payload", [("status", None), ("stop", None),
                                           ("pickup", {"target": "key"})])
@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e400", "-1e400", "1.25"])
async def test_tool_receipt_requires_finite_json(tools, monkeypatch, route, payload, number):
    module, head = tools
    original = httpx.AsyncClient
    calls = []
    body = '{"robot_id":"robot-01","observations":[{"value":' + number + '}]}'

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=body.encode("ascii"))

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", client_factory)
    result = await module.call(head, route, payload)
    assert len(calls) == 1
    if number == "1.25":
        assert result == json.loads(body)
    else:
        assert result == {"error": "Malformed robot Mac tool response", "retried": False}
