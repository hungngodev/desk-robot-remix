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


@pytest.mark.asyncio
@pytest.mark.parametrize("name,arguments", [
    ("pickup", {}),
    ("pickup", {"target": None}),
    ("pickup", {"target": 1}),
    ("pickup", {"target": "key", "unexpected": True}),
    ("look", {}),
    ("look", {"question": float("nan")}),
    ("look", {"question": " " * 280 + "key"}),
    ("look", {"question": "key\x00"}),
    ("look", {"question": "key", "unexpected": True}),
    ("memories", {"question": float("inf")}),
    ("memories", {"question": "key", "unexpected": True}),
    ("stop", {"unexpected": True}),
    ("job", {"unexpected": True}),
    ("situation", {"unexpected": True}),
    ("stop", {"conn": "not the registered connection"}),
])
async def test_registered_handlers_reject_invalid_arguments(tools, monkeypatch, name, arguments):
    module, head = tools

    def forbidden_http(*args, **kwargs):
        pytest.fail("Invalid tool arguments reached HTTP")

    monkeypatch.setattr(module.httpx, "AsyncClient", forbidden_http)
    result = await getattr(module, "desk_robot_" + name)(head, **arguments)
    assert result.action == module.Action.REQLLM
    assert result.result == {"error": "Invalid robot tool arguments", "retried": False}


@pytest.mark.asyncio
async def test_valid_visual_question_is_trimmed_after_schema_validation(tools, monkeypatch):
    module, head = tools
    original = httpx.AsyncClient
    receipt = {
        "robot_id": "robot-01",
        "source": "authenticated_xiao_camera_and_local_vlm",
        "frames_used": 1,
        "answer": "A key may be visible",
        "motor_authorized": False,
        "charging_authorized": False,
    }

    def handler(request):
        assert json.loads(request.content) == {"question": "Where is the key?"}
        return httpx.Response(200, json=receipt)

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", client_factory)
    result = await module.desk_robot_look(head, question="  Where is the key?  ")
    assert result.action == module.Action.REQLLM
    assert result.result == receipt


@pytest.mark.asyncio
@pytest.mark.parametrize("route,payload,path", [
    ("stop", None, "/v1/robots/robot-01/stop"),
    ("pickup", {"target": "key"}, "/v1/robots/robot-01/pickup"),
    ("status", None, "/v1/robots/robot-01/status"),
    ("voice-context", None, "/v1/pet/robot-01/voice-context"),
])
@pytest.mark.parametrize("identity", [None, "robot-02", 1, "robot-01"])
@pytest.mark.parametrize("superseded", [False, True])
async def test_tool_receipt_is_bound_to_current_robot(
    tools, monkeypatch, route, payload, path, identity, superseded,
):
    module, head = tools
    original = httpx.AsyncClient
    receipt = {"id": "private-job", "state": "queued"}
    if identity is not None:
        receipt["robot_id"] = identity
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if superseded:
            module.bridge.voice_turn_generation[head.device_id] += 1
        return httpx.Response(200, json=receipt)

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", client_factory)
    result = await module.call(head, route, payload)
    assert calls == [path]
    if superseded:
        if route in {"stop", "pickup"}:
            assert result == {"_desk_robot_turn_superseded": True}
        else:
            assert result == {
                "error": "Robot tool result superseded by new speech or reconnect",
                "retried": False,
            }
        assert module.voice_turn_response(result).action == module.Action.NONE
    elif identity == "robot-01":
        assert result == receipt
    else:
        assert result == {
            "error": "Robot Mac tool identity or authority invalid",
            "error_code": "robot_identity_mismatch",
            "retried": False,
        }
