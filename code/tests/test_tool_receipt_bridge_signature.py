"""The installed Xiaozhi tool bridge signs each Mac request once."""

import asyncio
import hashlib
import hmac
import importlib.util
import json
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _load_tools(monkeypatch):
    bridge = types.ModuleType("desk_robot_bridge")
    bridge.connections = {}
    bridge.voice_turn_generation = {"mac-01": 7}
    cancel = asyncio.Event()
    bridge.tool_turn_cancel_event = lambda device_id: cancel
    bridge.robot_for_device = (
        lambda device_id: "robot-01" if device_id == "mac-01" else None
    )
    monkeypatch.setitem(sys.modules, "desk_robot_bridge", bridge)

    package = types.ModuleType("plugins_func")
    package.__path__ = []
    register = types.ModuleType("plugins_func.register")

    class Action:
        NONE = "none"
        REQLLM = "reqllm"

    class ActionResponse:
        def __init__(self, action, result=None):
            self.action = action
            self.result = result

    class ToolType:
        IOT_CTL = "iot_ctl"

    def register_function(*_args, **_kwargs):
        return lambda function: function

    register.Action = Action
    register.ActionResponse = ActionResponse
    register.ToolType = ToolType
    register.register_function = register_function
    monkeypatch.setitem(sys.modules, "plugins_func", package)
    monkeypatch.setitem(sys.modules, "plugins_func.register", register)

    spec = importlib.util.spec_from_file_location(
        "test_desk_robot_tools",
        ROOT / "laptop/server/overlay/desk_robot_tools.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, bridge


async def test_bridge_signs_current_device_generation_and_unique_request(monkeypatch):
    module, bridge = _load_tools(monkeypatch)
    tool_token = "b" * 40
    speech_token = "s" * 40
    monkeypatch.setenv("DESK_ROBOT_TOOL_TOKEN", tool_token)
    monkeypatch.setenv("DESK_ROBOT_SPEECH_TOKEN", speech_token)
    # A developer or VPN proxy must never receive Xiaozhi tool credentials.
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8899")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid:8899")
    monkeypatch.delenv("NO_PROXY", raising=False)
    connection = SimpleNamespace(device_id="mac-01")
    bridge.connections["mac-01"] = connection
    captured = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "robot_id": "robot-01",
                "motor_authorized": False,
                "charging_authorized": False,
            }

    class Client:
        def __init__(self, *, base_url, timeout, trust_env, headers):
            assert base_url == "http://127.0.0.1:8765"
            assert timeout == 5
            assert trust_env is False  # Ignore HTTP_PROXY even on local Mac.
            self.base_headers = headers

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, path, *, headers, **_kwargs):
            captured.append(("GET", path, {**self.base_headers, **headers}))
            return Response()

        async def post(self, path, *, headers, **_kwargs):
            captured.append(("POST", path, {**self.base_headers, **headers}))
            return Response()

    monkeypatch.setattr(module.httpx, "AsyncClient", Client)

    first = await module.call(connection, "status")
    second = await module.call(connection, "status")
    third = await module.call(connection, "stop", {})
    assert first["robot_id"] == second["robot_id"] == third["robot_id"] == "robot-01"
    assert len(captured) == 3
    assert [method for method, _, _ in captured] == ["GET", "GET", "POST"]
    first_id = captured[0][2]["X-Desk-Robot-Tool-Receipt-Id"]
    second_id = captured[1][2]["X-Desk-Robot-Tool-Receipt-Id"]
    assert first_id != second_id

    for method, path, headers in captured:
        assert headers["Authorization"] == "Bearer " + tool_token
        assert headers["X-Desk-Robot-Tool-Receipt"] == "1"
        assert headers["X-Desk-Robot-Tool-Receipt-Device"] == "mac-01"
        assert headers["X-Desk-Robot-Tool-Receipt-Generation"] == "7"
        receipt_id = headers["X-Desk-Robot-Tool-Receipt-Id"]
        issued_us = int(headers["X-Desk-Robot-Tool-Receipt-At-Us"])
        assert len(receipt_id) == 32
        assert abs(time.time_ns() // 1000 - issued_us) < 5_000_000
        message = json.dumps(
            [
                1,
                "robot-01",
                "mac-01",
                7,
                method,
                path,
                issued_us,
                receipt_id,
            ],
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        expected = hmac.new(
            speech_token.encode("utf-8"), message, hashlib.sha256
        ).hexdigest()
        assert hmac.compare_digest(
            headers["X-Desk-Robot-Tool-Receipt-Signature"], expected
        )
