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
    registered = SimpleNamespace(device_id="mac-head-01")
    bridge.connections = {"mac-head-01": registered}
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
    module.registered_head = registered
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
        bridge_tools.registered_head, "look", {"question": "What moved?"},
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


async def test_reconnected_head_rejects_stale_socket_with_valid_device_id(
    bridge_tools, monkeypatch,
):
    class NoHttp:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Stale head cannot reach Mac tools")

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", NoHttp)
    old_connection = SimpleNamespace(device_id="mac-head-01")
    assert old_connection is not bridge_tools.registered_head
    result = await bridge_tools.call(old_connection, "stop", {})
    assert "error" in result


async def test_pinned_plugin_executor_keeps_live_loop_responsive_under_sync_tool(
    monkeypatch,
):
    """Use the actual locked upstream executor and our overlay backport."""
    import asyncio
    import threading

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "robot_server_installer", root / "laptop/server/install_overlay.py"
    )
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    upstream = (
        root / "upstream/xiaozhi-esp32-server/main/xiaozhi-server"
        / "core/providers/tools/server_plugins/plugin_executor.py"
    )
    patched = installer.patch_plugin_executor(upstream.read_text())
    compile(patched, str(upstream), "exec")

    for name in (
        "core", "core.providers", "core.providers.tools",
        "core.providers.tools.server_plugins",
    ):
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    base = ModuleType("core.providers.tools.base")
    base.ToolExecutor = object
    base.ToolDefinition = SimpleNamespace
    base.ToolType = SimpleNamespace(SERVER_PLUGIN=1)
    monkeypatch.setitem(sys.modules, base.__name__, base)

    ready, release, all_started = (threading.Event() for _ in range(3))
    main_thread = threading.get_ident()
    observed = []

    def blocking(conn, amount):
        observed.append(("sync", threading.get_ident(), conn.device_id))
        ready.set()
        if sum(item[0] == "sync" for item in observed) == 8:
            all_started.set()
        if not release.wait(5):
            raise TimeoutError("Fixture worker still blocked")
        return amount * 2

    async def native_async(conn, amount):
        observed.append(("async", threading.get_ident(), conn.device_id))
        return amount * 3

    registry = ModuleType("plugins_func.register")
    registry.all_function_registry = {
        "blocking": SimpleNamespace(
            func=blocking, type=SimpleNamespace(code=5)
        ),
        "async": SimpleNamespace(
            func=native_async, type=SimpleNamespace(code=5)
        ),
    }
    registry.module_func_map = {}
    registry.Action = SimpleNamespace(ERROR=2, NOTFOUND=3)
    registry.ActionResponse = lambda **kwargs: SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, "plugins_func", ModuleType("plugins_func"))
    monkeypatch.setitem(sys.modules, registry.__name__, registry)

    ns = {
        "__name__": "core.providers.tools.server_plugins.plugin_executor",
        "__package__": "core.providers.tools.server_plugins",
    }
    exec(compile(patched, str(upstream), "exec"), ns)
    owner = ns["ServerPluginExecutor"](
        SimpleNamespace(config={}, device_id="mac-head-01")
    )
    conn = SimpleNamespace(config={}, device_id="mac-head-01")
    task = asyncio.create_task(owner.execute(conn, "blocking", {"amount": 7}))
    extras = []
    try:
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        assert await asyncio.to_thread(ready.wait, 0.7)
        assert loop.time() - started_at < 0.7  # no inline event loop stall
        assert observed == [("sync", observed[0][1], "mac-head-01")]
        assert observed[0][1] != main_thread
        assert await owner.execute(conn, "async", {"amount": 5}) == 15
        assert observed[-1] == ("async", main_thread, "mac-head-01")
        extras = [asyncio.create_task(owner.execute(
            conn, "blocking", {"amount": number}
        )) for number in range(7)]
        assert await asyncio.to_thread(all_started.wait, 2)
        # Cancelling the asyncio owner does not terminate its native thread.
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        refused = await owner.execute(conn, "blocking", {"amount": 99})
        assert refused.action == registry.Action.ERROR
        assert "capacity exhausted" in refused.response
        assert len([row for row in observed if row[0] == "sync"]) == 8
        # An async tool remains callable even with all sync worker slots held.
        assert await owner.execute(conn, "async", {"amount": 2}) == 6
        release.set()
        assert await asyncio.wait_for(asyncio.gather(*extras), timeout=2) == [
            n * 2 for n in range(7)
        ]
        assert await owner.execute(conn, "blocking", {"amount": 11}) == 22
    finally:
        release.set()
        await asyncio.gather(task, *extras, return_exceptions=True)
        ns["_PLUGIN_POOL"].shutdown(wait=True, cancel_futures=True)
