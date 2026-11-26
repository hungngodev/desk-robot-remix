"""Read-only native dispatch must not reach the shared actuator tool bridge."""
import sys
from types import ModuleType

import pytest
from test_native_omni_xiaozhi import connection
from test_native_omni_xiaozhi import native as native


@pytest.mark.parametrize("route", ["pickup", "stop", "enable", "move", None, ["status"]])
async def test_readonly_batch_rejects_non_observation_routes(native, monkeypatch, route):
    module, bridge = native
    conn, _ = connection()
    bridge.connections["mac-01"] = conn
    session = module.NativeOmniSession(
        conn, url="ws://127.0.0.1:8099/v1/realtime?duplex=1",
        model="openbmb/MiniCPM-o-4_5", token="p" * 32,
    )
    session.connected = True
    calls = []

    async def call(current, selected, payload):
        assert current is conn
        calls.append(selected)
        return {
            "robot_id": "robot-01", "armed": False,
            "safety": {"fault": "none"},
        }

    pkg = ModuleType("plugins_func")
    pkg.__path__ = []
    funcs = ModuleType("plugins_func.functions")
    funcs.__path__ = []
    tools = ModuleType("plugins_func.functions.desk_robot_tools")
    tools.call = call
    for key, value in (
        ("plugins_func", pkg),
        ("plugins_func.functions", funcs),
        ("plugins_func.functions.desk_robot_tools", tools),
    ):
        monkeypatch.setitem(sys.modules, key, value)

    epoch, turn = session._generation, session._readonly_turn
    rejected = (route, {}, epoch, turn)
    assert await session._run_readonly_batch([rejected]) == []
    assert calls == []
    assert session.native_readonly_tools_dropped == 1

    facts = await session._run_readonly_batch([
        rejected, ("status", {}, epoch, turn),
    ])
    assert calls == ["status"]
    assert len(facts) == 1
    assert facts[0]["source"] == "wroom_status"
    assert session.native_readonly_tools_dropped == 2
    assert session.native_readonly_tools_completed == 1
