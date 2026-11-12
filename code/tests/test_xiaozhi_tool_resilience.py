"""Pinned Xiaozhi tool bridge degrades gracefully when the Mac is offline.

The real plugin registry is stubbed. HTTP request semantics, authentication
and no-retry behavior use the same httpx surface as the installed server.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import httpx
import pytest


@pytest.fixture
def bridge_tools(monkeypatch):
    bridge = ModuleType("desk_robot_bridge")
    bridge.robot_for_device = (
        lambda device: "robot-01" if device == "mac-head-01" else None
    )
    registry = ModuleType("plugins_func.register")
    registry.Action = SimpleNamespace(REQLLM=3)
    registry.ToolType = SimpleNamespace(IOT_CTL=5)
    registry.ActionResponse = lambda action, result: SimpleNamespace(
        action=action, result=result
    )
    registry.register_function = lambda *args, **kwargs: lambda fn: fn
    monkeypatch.setitem(sys.modules, "desk_robot_bridge", bridge)
    monkeypatch.setitem(sys.modules, "plugins_func", ModuleType("plugins_func"))
    monkeypatch.setitem(sys.modules, "plugins_func.register", registry)
    path = (
        Path(__file__).resolve().parents[1]
        / "laptop/server/overlay/desk_robot_tools.py"
    )
    spec = importlib.util.spec_from_file_location("desk_tools_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("DESK_ROBOT_TOOL_TOKEN", "s" * 40)
    return module


@pytest.mark.parametrize("failure", [
    "connect", "timeout", "http_error", "invalid_json", "invalid_shape",
])
async def test_real_xiaozhi_tool_failure_returns_bounded_no_retry_error(
    bridge_tools, monkeypatch, failure,
):
    calls = []
    original = httpx.AsyncClient

    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer " + "s" * 40
        if failure == "connect":
            raise httpx.ConnectError("private host disconnected", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("upstream camera timeout", request=request)
        if failure == "http_error":
            return httpx.Response(500, text="Private server traceback: SECRET")
        if failure == "invalid_json":
            return httpx.Response(200, text="not JSON")
        return httpx.Response(200, json=["not a robot object"])

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    result = await bridge_tools.call(
        SimpleNamespace(device_id="mac-head-01"), "look",
        {"question": "What moved?"},
    )
    assert len(calls) == 1  # no retries or competing tool owner
    assert calls[0].url.path == "/v1/pet/robot-01/look"
    assert "error" in result and result["retried"] is False
    assert "SECRET" not in str(result)
    assert "private host" not in str(result)


async def test_unknown_xiaozhi_head_cannot_borrow_another_robots_mac_tool(
    bridge_tools, monkeypatch,
):
    class NoHttp:
        def __init__(self, *args, **kwargs):
            raise AssertionError("No HTTP request without authenticated identity")

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", NoHttp)
    data = await bridge_tools.call(
        SimpleNamespace(device_id="forged-head"), "pickup", {"target": "key"}
    )
    assert "error" in data
