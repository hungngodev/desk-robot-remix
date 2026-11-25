"""Pinned Xiaozhi tool bridge degrades gracefully when the Mac is offline.

The real plugin registry is stubbed. HTTP request semantics, authentication
and no-retry behavior use the same httpx surface as the installed server.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
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
    registry.Action = SimpleNamespace(REQLLM=3, NONE=1)
    registry.ToolType = SimpleNamespace(IOT_CTL=5)
    registry.ActionResponse = lambda action, result=None, response=None: SimpleNamespace(
        action=action, result=result, response=response
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
    monkeypatch.setenv("DESK_ROBOT_SPEECH_TOKEN", "r" * 40)
    module.registered_head = registered
    module.bridge = bridge
    return module


@pytest.mark.parametrize("speech_token", ["", "s" * 40])
async def test_tool_bridge_refuses_missing_or_shared_signing_secret_before_http(
    bridge_tools, monkeypatch, speech_token,
):
    # A valid Mac API bearer alone must never mint a trusted speech receipt.
    monkeypatch.setenv("DESK_ROBOT_SPEECH_TOKEN", speech_token)

    class ForbiddenHTTP:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Untrusted tool receipt reached Mac HTTP")

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", ForbiddenHTTP)
    result = await bridge_tools.call(bridge_tools.registered_head, "status")
    assert result == {
        "error": "Current registered head or local tool credential missing"
    }


@pytest.mark.parametrize("route", [
    "arm", "enable", "move", "drive", "../enable", "charger/enable", "",
])
async def test_xiaozhi_tool_router_refuses_unregistered_physical_actions_before_http(
    bridge_tools, monkeypatch, route,
):
    class ForbiddenHTTP:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Unknown tool route reached Mac HTTP")

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", ForbiddenHTTP)
    denied = await bridge_tools.call(
        bridge_tools.registered_head, route, {"command": "enable"}
    )
    assert denied == {
        "error": "Unsupported robot tool route", "retried": False,
    }


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
        assert request.headers["x-desk-robot-tool-receipt"] == "1"
        assert request.headers["x-desk-robot-tool-receipt-device"] == "mac-head-01"
        assert request.headers["x-desk-robot-tool-receipt-generation"] == "0"
        receipt_id = request.headers["x-desk-robot-tool-receipt-id"]
        assert len(receipt_id) == 32
        issued_us = int(request.headers["x-desk-robot-tool-receipt-at-us"])
        assert issued_us > 0
        signed_fields = [
            1, "robot-01", "mac-head-01", 0, request.method,
            request.url.path, issued_us, receipt_id,
        ]
        signing_input = json.dumps(
            signed_fields, separators=(",", ":"), ensure_ascii=True,
        ).encode("ascii")
        expected_signature = hmac.new(
            ("r" * 40).encode("utf-8"), signing_input, hashlib.sha256,
        ).hexdigest()
        assert hmac.compare_digest(
            request.headers["x-desk-robot-tool-receipt-signature"],
            expected_signature,
        )
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


@pytest.mark.parametrize("unsafe", [
    {"robot_id": "robot-02", "answer": "other pet private data"},
    {"answer": "missing authenticated identity"},
    {"robot_id": "robot-01", "motor_authorized": True},
    {"robot_id": "robot-01", "charging_authorized": True},
    {"robot_id": "robot-01", "motor_authorized": "true"},
    {"robot_id": "robot-01", "motor_authorized": 1},
    {"robot_id": "robot-01", "charging_authorized": "false"},
    {"robot_id": "robot-01", "charging_authorized": {"allowed": True}},
])
async def test_legacy_and_native_shared_tool_bridge_rejects_wrong_pet_receipt(
    bridge_tools, monkeypatch, unsafe,
):
    original = httpx.AsyncClient
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json=unsafe)

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    result = await bridge_tools.call(
        bridge_tools.registered_head, "status"
    )
    assert len(seen) == 1
    assert result == {
        "error": "Robot Mac tool identity or authority invalid",
        "retried": False,
    }
    assert "other pet" not in str(result)


@pytest.mark.parametrize("untrusted", [
    {"robot_id": "robot-01", "answer": "No real JPEG receipt"},
    {
        "robot_id": "robot-01",
        "answer": "Old image may contain a key",
        "source": "unverified_camera",
        "frames_used": 1,
        "motor_authorized": False,
        "charging_authorized": False,
    },
    {
        "robot_id": "robot-01",
        "answer": "A key is visible",
        "source": "authenticated_xiao_camera_and_local_vlm",
        "frames_used": 0,
        "motor_authorized": False,
        "charging_authorized": False,
    },
    {
        "robot_id": "robot-01",
        "answer": "",
        "source": "authenticated_xiao_camera_and_local_vlm",
        "frames_used": 1,
        "motor_authorized": False,
        "charging_authorized": False,
    },
])
async def test_readonly_visual_tool_requires_real_mac_camera_and_vlm_contract(
    bridge_tools, monkeypatch, untrusted,
):
    original = httpx.AsyncClient

    def handler(request):
        assert request.url.path == "/v1/pet/robot-01/look"
        return httpx.Response(200, json=untrusted)

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    outcome = await bridge_tools.call(
        bridge_tools.registered_head, "look",
        {"question": "What is right in front of you?"},
    )
    assert outcome == {
        "error": "Missing authenticated visual tool evidence",
        "retried": False,
    }
    assert "answer" not in outcome


async def test_readonly_visual_tool_accepts_only_real_source_labeled_vlm_reply(
    bridge_tools, monkeypatch,
):
    original = httpx.AsyncClient
    confirmed = {
        "robot_id": "robot-01",
        "answer": "A small red object might be a key",
        "source": "authenticated_xiao_camera_and_local_vlm",
        "frames_used": 2,
        "motor_authorized": False,
        "charging_authorized": False,
    }

    def client_factory(*args, **kwargs):
        return original(
            *args, transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=confirmed)
            ), **kwargs
        )

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    answer = await bridge_tools.call(
        bridge_tools.registered_head, "look",
        {"question": "What changed on the table?"},
    )
    assert answer == confirmed


async def test_five_registered_heads_route_simultaneous_status_to_own_robot(
    bridge_tools, monkeypatch,
):
    import asyncio

    bridge = bridge_tools.bridge
    heads = {
        f"mac-head-{i:02d}": SimpleNamespace(device_id=f"mac-head-{i:02d}")
        for i in range(1, 6)
    }
    # The installed plugin binds the original registry dict at import time.
    bridge.connections.clear()
    bridge.connections.update(heads)
    def resolve(device):
        return (
            "robot-" + device.rsplit("-", 1)[-1] if device in heads else None
        )
    bridge.robot_for_device = resolve
    bridge_tools.robot_for_device = resolve
    bridge.voice_turn_generation = {device: 3 for device in heads}
    original = httpx.AsyncClient
    requests = []

    async def handler(request):
        robot = request.url.path.split("/")[3]
        requests.append(robot)
        await asyncio.sleep(0)
        return httpx.Response(200, json={
            "robot_id": robot,
            "backend": "stepper_28byj48",
            "armed": False,
        })

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    results = await asyncio.gather(*(
        bridge_tools.call(head, "status") for head in heads.values()
    ))
    assert sorted(result["robot_id"] for result in results) == [
        f"robot-{i:02d}" for i in range(1, 6)
    ]
    assert sorted(requests) == sorted(result["robot_id"] for result in results)
    assert all("error" not in result for result in results)


async def test_five_registered_heads_get_only_their_own_raw_power_gauge(
    bridge_tools, monkeypatch,
):
    import asyncio

    bridge = bridge_tools.bridge
    heads = {
        f"mac-head-{i:02d}": SimpleNamespace(device_id=f"mac-head-{i:02d}")
        for i in range(1, 6)
    }
    bridge.connections.clear()
    bridge.connections.update(heads)
    def resolve(device):
        return (
            "robot-" + device.rsplit("-", 1)[-1] if device in heads else None
        )
    bridge.robot_for_device = resolve
    bridge_tools.robot_for_device = resolve
    original = httpx.AsyncClient
    requests = []

    async def handler(request):
        robot = request.url.path.split("/")[3]
        requests.append(robot)
        assert request.url.path.endswith("/power-status")
        await asyncio.sleep(0)
        return httpx.Response(200, json={
            "robot_id": robot,
            "source": "wroom_aux_fuel_gauge_raw_unqualified",
            "gauge_available": True,
            "reported_soc_centi": 6100,
            "charging_verified": False,
            "motor_authorized": False,
            "charging_authorized": False,
        })

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    results = await asyncio.gather(*(
        bridge_tools.call(head, "power-status") for head in heads.values()
    ))
    expected = [f"robot-{i:02d}" for i in range(1, 6)]
    assert sorted(requests) == expected
    assert sorted(item["robot_id"] for item in results) == expected
    assert all(item["charging_verified"] is False for item in results)


async def test_one_human_cancels_only_own_visual_tool_not_four_other_pets(
    bridge_tools, monkeypatch,
):
    import asyncio

    bridge = bridge_tools.bridge
    heads = {
        f"mac-head-{i:02d}": SimpleNamespace(device_id=f"mac-head-{i:02d}")
        for i in range(1, 6)
    }
    bridge.connections.clear()
    bridge.connections.update(heads)
    def resolve(device):
        return (
            "robot-" + device.rsplit("-", 1)[-1] if device in heads else None
        )
    bridge.robot_for_device = resolve
    bridge_tools.robot_for_device = resolve
    bridge.voice_turn_generation = {device: 3 for device in heads}
    cancelled = {device: asyncio.Event() for device in heads}
    bridge.tool_turn_cancel_event = lambda device: cancelled[device]
    held, aborted = asyncio.Event(), asyncio.Event()
    original = httpx.AsyncClient

    async def handler(request):
        robot = request.url.path.split("/")[3]
        if robot == "robot-01":
            held.set()
            try:
                await asyncio.Event().wait()
            finally:
                aborted.set()
        return httpx.Response(200, json={
            "robot_id": robot,
            "backend": "stepper_28byj48",
            "armed": False,
        })

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    tasks = {
        device: asyncio.create_task(bridge_tools.call(head, "status"))
        for device, head in heads.items()
    }
    try:
        await asyncio.wait_for(held.wait(), timeout=1)
        completed = await asyncio.wait_for(
            asyncio.gather(*(task for device, task in tasks.items()
                             if device != "mac-head-01")), timeout=1
        )
        assert {result["robot_id"] for result in completed} == {
            f"robot-{i:02d}" for i in range(2, 6)
        }
        bridge.voice_turn_generation["mac-head-01"] += 1
        cancelled["mac-head-01"].set()
        rejected = await asyncio.wait_for(tasks["mac-head-01"], timeout=1)
        assert "superseded" in rejected["error"]
        assert aborted.is_set()
        assert all(not cancelled[device].is_set()
                   for device in heads if device != "mac-head-01")
    finally:
        for task in tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)


@pytest.mark.parametrize("planned_route,accepted", [
    ("power-status", True),
    ("move", False),
    ("charger/enable", False),
])
async def test_mac_model_planned_wroom_power_route_passes_existing_xiaozhi_bridge(
    bridge_tools, monkeypatch, planned_route, accepted,
):
    """Mac plan, native worker and Xiaozhi HTTP bridge share one route set."""
    original = httpx.AsyncClient
    sent = []
    def handler(request):
        sent.append(request)
        assert request.url.path == "/v1/pet/robot-01/plan-readonly"
        assert request.method == "POST"
        return httpx.Response(200, json={
            "robot_id": "robot-01",
            "source": "existing_mac_ollama_readonly_route_selection",
            "untrusted_model_selection": True,
            "model_can_arm_motors": False,
            "motor_authorized": False,
            "charging_authorized": False,
            "tools": [
                {"route": planned_route, "payload": {}},
            ],
        })
    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    result = await bridge_tools.call(
        bridge_tools.registered_head, "plan-readonly",
        {"transcript": "How much charge is left?"},
    )
    assert len(sent) == 1
    if accepted:
        assert result["tools"] == [
            {"route": "power-status", "payload": {}},
        ]
        assert result["model_can_arm_motors"] is False
    else:
        assert result == {
            "error": "Invalid read-only Mac intent plan", "retried": False,
        }


@pytest.mark.parametrize("bad_route", [
    ["look"], {"route": "status"},
])
async def test_shared_xiaozhi_bridge_refuses_nonstring_planned_routes(
    bridge_tools, monkeypatch, bad_route,
):
    """Untrusted model JSON must return an error, never TypeError."""
    original = httpx.AsyncClient

    def handle(request):
        assert request.url.path == "/v1/pet/robot-01/plan-readonly"
        return httpx.Response(200, json={
            "robot_id": "robot-01",
            "source": "existing_mac_ollama_readonly_route_selection",
            "untrusted_model_selection": True,
            "model_can_arm_motors": False,
            "motor_authorized": False,
            "charging_authorized": False,
            "tools": [{"route": bad_route, "payload": {}}],
        })

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    result = await bridge_tools.call(
        bridge_tools.registered_head, "plan-readonly",
        {"transcript": "Could you check the desk?"},
    )
    assert result == {
        "error": "Invalid read-only Mac intent plan", "retried": False,
    }


async def test_voice_battery_tool_uses_actual_unqualified_wroom_power_source(
    bridge_tools, monkeypatch,
):
    original = httpx.AsyncClient
    seen = []

    def handler(request):
        seen.append(request)
        assert request.url.path == "/v1/pet/robot-01/power-status"
        assert request.method == "GET"
        return httpx.Response(200, json={
            "robot_id": "robot-01",
            "source": "wroom_aux_fuel_gauge_raw_unqualified",
            "gauge_available": True,
            "reported_cell_mv": 3800,
            "reported_soc_centi": 5900,
            "sample_freshness_verified": False,
            "charging_verified": False,
            "battery_capacity_verified": False,
            "motor_authorized": False,
            "charging_authorized": False,
        })

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    result = await bridge_tools.call(
        bridge_tools.registered_head, "power-status"
    )
    assert len(seen) == 1
    assert result["robot_id"] == "robot-01"
    assert result["reported_soc_centi"] == 5900
    assert result["sample_freshness_verified"] is False
    assert result["charging_verified"] is False
    assert result["motor_authorized"] is False


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


@pytest.mark.parametrize("superseded_by", ["new_speech", "head_reconnect"])
async def test_inflight_xiaozhi_tool_cannot_publish_late_other_turn_result(
    bridge_tools, monkeypatch, superseded_by,
):
    """An old camera/tool answer cannot become the response to a new person."""
    import asyncio

    ready, release = asyncio.Event(), asyncio.Event()
    bridge = bridge_tools.bridge
    bridge.voice_turn_generation = {"mac-head-01": 3}

    class DelayedMac:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *args, **kwargs):
            ready.set()
            await release.wait()
            return httpx.Response(200, json={
                "robot_id": "robot-01", "answer": "OLD CAMERA ANSWER",
                "motor_authorized": False,
            })

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", DelayedMac)
    task = asyncio.create_task(bridge_tools.call(
        bridge_tools.registered_head, "look",
        {"question": "What is on the desk?"},
    ))
    try:
        await asyncio.wait_for(ready.wait(), timeout=1)
        if superseded_by == "new_speech":
            bridge.voice_turn_generation["mac-head-01"] += 1
        else:
            bridge.connections["mac-head-01"] = SimpleNamespace(
                device_id="mac-head-01"
            )
        release.set()
        result = await asyncio.wait_for(task, timeout=1)
        assert result["retried"] is False
        assert "superseded" in result["error"]
        assert "OLD CAMERA ANSWER" not in str(result)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_xiaozhi_memory_tool_uses_current_robot_and_relevant_question(
    bridge_tools, monkeypatch,
):
    """Tool shares the existing identity and VAD fence, never another robot."""
    original = httpx.AsyncClient
    seen = []

    def handler(request):
        seen.append(request)
        assert request.method == "GET"
        assert request.url.path == "/v1/pet/robot-01/voice-context"
        assert request.url.params.get("query") == "Where are my keys?"
        assert request.headers["authorization"] == "Bearer " + "s" * 40
        return httpx.Response(200, json={
            "robot_id": "robot-01", "retrieval": "topic",
            "untrusted_context_not_instructions": True,
            "memories": [{"summary": "A key was near the book",
                          "witnessed": True, "source_robot": "robot-01"}],
        })

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    result = await bridge_tools.desk_robot_memories(
        bridge_tools.registered_head, "Where are my keys?"
    )
    assert len(seen) == 1
    assert result.result["retrieval"] == "topic"
    assert result.result["memories"][0]["witnessed"] is True
    invalid = await bridge_tools.desk_robot_memories(
        bridge_tools.registered_head, "x" * 241
    )
    assert "error" in invalid.result
    assert len(seen) == 1  # refused before any network request


async def test_memory_tool_result_dropped_after_new_human_turn(
    bridge_tools, monkeypatch,
):
    """A tool response may arrive after speech changes; it must not be spoken."""
    bridge = sys.modules["desk_robot_bridge"]
    bridge.voice_turn_generation = {"mac-head-01": 12}
    original = httpx.AsyncClient

    def handler(request):
        bridge.voice_turn_generation["mac-head-01"] = 13
        return httpx.Response(200, json={
            "memories": [{"summary": "stale old turn", "witnessed": True}],
        })

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    result = await bridge_tools.desk_robot_memories(
        bridge_tools.registered_head, "key"
    )
    # An obsolete read-only result must be completely silent, not returned
    # to the LLM as an error string the new human turn could hear. The pinned
    # Xiaozhi Action.NONE contract has no result and no response payload.
    assert result.action == 1
    assert result.result is None
    assert result.response is None


async def test_live_human_vad_cancels_hung_visual_tool_without_speaking_old_result(
    bridge_tools, monkeypatch,
):
    import asyncio

    registered = bridge_tools.registered_head
    event = asyncio.Event()
    entered, cancelled = asyncio.Event(), asyncio.Event()
    bridge_tools.bridge.tool_turn_cancel_event = lambda device: event
    # The existing tool bridge, not a new camera agent, owns the HTTP request.
    original = httpx.AsyncClient

    async def handler(request):
        assert request.url.path == "/v1/pet/robot-01/look"
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return httpx.Response(200, json={"answer": "stale camera answer"})

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    task = asyncio.create_task(bridge_tools.call(
        registered, "look", {"question": "What moved?"}
    ))
    await asyncio.wait_for(entered.wait(), timeout=1)
    event.set()  # Real bridge sets this on authenticated human speech.
    outcome = await asyncio.wait_for(task, timeout=1)
    assert "superseded" in outcome["error"]
    assert outcome["retried"] is False
    assert cancelled.is_set()
    assert "answer" not in outcome


async def test_voice_cancel_does_not_abort_required_robot_stop_request(
    bridge_tools, monkeypatch,
):
    import asyncio

    event = asyncio.Event()
    entered, release = asyncio.Event(), asyncio.Event()
    bridge_tools.bridge.tool_turn_cancel_event = lambda device: event
    original = httpx.AsyncClient

    async def handler(request):
        assert request.url.path == "/v1/robots/robot-01/stop"
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"stopped": True})

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    task = asyncio.create_task(bridge_tools.call(
        bridge_tools.registered_head, "stop"
    ))
    await asyncio.wait_for(entered.wait(), timeout=1)
    event.set()  # STOP is a safety request, not a speculative read-only tool.
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    assert await asyncio.wait_for(task, timeout=1) == {"stopped": True}


async def test_xiaozhi_situation_tool_gets_only_current_pets_ephemeral_cues(
    bridge_tools, monkeypatch,
):
    """Live sensor tool is a read-only, scoped Mac request without SQLite."""
    original = httpx.AsyncClient
    seen = []

    def handler(request):
        seen.append(request)
        assert request.method == "GET"
        assert request.url.path == "/v1/pet/robot-01/interaction-context"
        return httpx.Response(200, json={
            "robot_id": "robot-01", "persistent_memory_included": False,
            "current_interaction_timeline": [{
                "channel": "sensor", "kind": "touch_tap",
                "physical_action_verified": False,
            }],
        })

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    result = await bridge_tools.desk_robot_situation(
        bridge_tools.registered_head
    )
    assert len(seen) == 1
    assert result.result["persistent_memory_included"] is False
    assert result.result["current_interaction_timeline"][0]["kind"] == "touch_tap"


@pytest.mark.parametrize("tool_name,arguments", [
    ("desk_robot_look", ("What is on the desk?",)),
    ("desk_robot_memories", ("Where are my keys?",)),
    ("desk_robot_situation", ()),
    ("desk_robot_job", ()),
])
async def test_superseded_readonly_result_is_silent_not_asked_to_speak(
    bridge_tools, monkeypatch, tool_name, arguments,
):
    """Pinned Xiaozhi would speak ANY nonempty REQLLM result after a barge."""
    old_reply = {
        "error": "Robot tool result superseded by new speech or reconnect",
        "retried": False,
    }
    invoked = []

    async def obsolete(*args, **kwargs):
        invoked.append((args, kwargs))
        return dict(old_reply)

    monkeypatch.setattr(bridge_tools, "call", obsolete)
    response = await getattr(bridge_tools, tool_name)(
        bridge_tools.registered_head, *arguments
    )
    assert invoked
    assert response.action == 1
    assert response.result is None
    assert response.response is None


async def test_valid_readonly_tool_still_requests_model_reply_and_safety_stop_does_not_change(
    bridge_tools, monkeypatch,
):
    async def current(*args, **kwargs):
        return {"robot_id": "robot-01", "answer": "Probably a key"}

    monkeypatch.setattr(bridge_tools, "call", current)
    ready = await bridge_tools.desk_robot_look(
        bridge_tools.registered_head, "Can you see my key?"
    )
    assert ready.action == 3 and ready.result["answer"] == "Probably a key"
    stop = await bridge_tools.desk_robot_stop(bridge_tools.registered_head)
    assert stop.action == 3
    assert stop.result["robot_id"] == "robot-01"


def test_pinned_multitool_combine_preserves_structured_results_and_silent_cancellation():
    """Exercise the patched REAL upstream method, not a new tool broker."""
    import json
    from types import SimpleNamespace

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "desk_multi_overlay", root / "laptop/server/install_overlay.py"
    )
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    pinned = (
        root / "upstream/xiaozhi-esp32-server/main/xiaozhi-server"
        / "core/providers/tools/unified_tool_handler.py"
    )
    source = installer.patch_unified_tool_handler(pinned.read_text())
    assert "if response.content:" not in source
    assert "getattr(response, 'result', None)" in source
    compile(source, str(pinned), "exec")

    # Importing the whole pinned server would also start its providers.
    # Execute its exact isolated method with only its ActionResponse contract.
    begin = source.index("    def _combine_responses(")
    end = source.index("    async def register_iot_tools(", begin)
    actor = SimpleNamespace(NONE=1, RESPONSE=2, REQLLM=3, ERROR=-1)
    def response(action, result=None, response=None):
        return SimpleNamespace(action=action, result=result, response=response)
    namespace = {"Action": actor, "ActionResponse": response, "json": json,
                 "List": list}
    exec("from __future__ import annotations\nclass PinnedTools:\n"
         + source[begin:end], namespace)
    merge = namespace["PinnedTools"]()._combine_responses

    camera = response(actor.REQLLM, result={"answer": "silver key"})
    memory = response(actor.REQLLM, result={"history": "seen yesterday"})
    combined = merge([camera, memory])
    assert combined.action == actor.REQLLM
    assert combined.response is None
    assert [json.loads(item) for item in combined.result.split("; ")] == [
        {"answer": "silver key"}, {"history": "seen yesterday"}
    ]

    # A superseded tool result must contain NO text. On this pinned
    # intent handler a NONE action with response text would still be spoken.
    dropped = response(actor.NONE)
    silent = merge([dropped, dropped])
    assert silent.action == actor.RESPONSE
    assert silent.result is None and silent.response is None
    mixed = merge([dropped, camera])
    assert mixed.action == actor.REQLLM
    assert json.loads(mixed.result) == {"answer": "silver key"}
    assert merge([response(actor.ERROR, response="fail"), camera]).action == (
        actor.ERROR
    )


async def test_pickup_accepted_after_new_speech_remains_queryable_after_reconnect(
    bridge_tools, monkeypatch,
):
    """An accepted job remains in the Mac registry, not the old head socket."""
    bridge = bridge_tools.bridge
    bridge.voice_turn_generation = {"mac-head-01": 7}
    original = httpx.AsyncClient
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/pickup"):
            # The Mac accepted the job, then the person started talking.
            bridge.voice_turn_generation["mac-head-01"] = 8
            return httpx.Response(202, json={
                "id": "physical-job-83", "state": "pending",
            })
        assert request.url.path == "/v1/robots/robot-01/jobs/latest-pickup"
        return httpx.Response(200, json={
            "robot_id": "robot-01",
            "id": "physical-job-83", "state": "running",
            "physical_grasp_verified": False,
        })

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    head = bridge_tools.registered_head
    result = await bridge_tools.desk_robot_pickup(head, "key")
    assert result.action == 1 and result.result is None
    assert not hasattr(head, "desk_robot_last_job")
    replacement = SimpleNamespace(device_id="mac-head-01")
    bridge.connections["mac-head-01"] = replacement
    bridge.voice_turn_generation["mac-head-01"] = 9
    status = await bridge_tools.desk_robot_job(replacement)
    assert status.action == 3
    assert status.result["state"] == "running"
    assert status.result["physical_grasp_verified"] is False
    assert seen == [
        ("POST", "/v1/robots/robot-01/pickup"),
        ("GET", "/v1/robots/robot-01/jobs/latest-pickup"),
    ]


@pytest.mark.parametrize("code", [200, 409, 500])
async def test_stop_never_replays_previous_turn_after_new_speech(
    bridge_tools, monkeypatch, code,
):
    """STOP is sent and allowed to finish, but old vocal ACK is suppressed."""
    bridge = bridge_tools.bridge
    bridge.voice_turn_generation = {"mac-head-01": 21}
    original = httpx.AsyncClient
    submitted = []

    def handler(request):
        submitted.append(request.url.path)
        assert request.method == "POST"
        bridge.voice_turn_generation["mac-head-01"] = 22
        return httpx.Response(code, json={"stopped": code == 200})

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    response = await bridge_tools.desk_robot_stop(bridge_tools.registered_head)
    assert submitted == ["/v1/robots/robot-01/stop"]
    assert response.action == 1 and response.result is None


async def test_native_aux_sensor_tool_uses_existing_authenticated_readonly_bridge(
    bridge_tools, monkeypatch,
):
    """Actual voice tool never opens arbitrary actuator routes or a new server."""
    requests = []
    original = httpx.AsyncClient

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={
            "robot_id": "robot-01",
            "climate": {"valid": True, "temp_centi": 2150,
                        "rh_centi": 4500},
            "power": {"fuel_valid": False},
            "motor_authorized": False,
            "charging_authorized": False,
        })

    def factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", factory)
    result = await bridge_tools.call(
        bridge_tools.registered_head, "aux-status",
    )
    assert [request.url.path for request in requests] == [
        "/v1/robots/robot-01/aux",
    ]
    assert requests[0].method == "GET"
    assert requests[0].headers["authorization"] == "Bearer " + "s" * 40
    assert requests[0].headers["x-desk-robot-tool-receipt"] == "1"
    assert result["robot_id"] == "robot-01"
    assert result["climate"]["temp_centi"] == 2150
    assert result["motor_authorized"] is False


async def test_native_aux_sensor_tool_rejects_foreign_robot_result(
    bridge_tools, monkeypatch,
):
    original = httpx.AsyncClient

    def handler(request):
        return httpx.Response(200, json={
            "robot_id": "robot-02", "climate": {"valid": True},
        })

    def factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", factory)
    result = await bridge_tools.call(
        bridge_tools.registered_head, "aux-status",
    )
    assert result == {
        "error": "Robot Mac tool identity or authority invalid",
        "retried": False,
    }


async def test_already_cancelled_voice_turn_does_not_start_mac_tool_http(
    bridge_tools, monkeypatch,
):
    """A superseded turn must not trigger even one stale camera request."""
    import asyncio

    cancelled = asyncio.Event()
    cancelled.set()
    bridge_tools.bridge.tool_turn_cancel_event = lambda device: cancelled

    class ForbiddenHTTP:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Cancelled turn started a Mac HTTP request")

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", ForbiddenHTTP)
    result = await bridge_tools.call(
        bridge_tools.registered_head, "look", {"question": "What changed?"}
    )
    assert result == {
        "error": "Robot tool result superseded by new speech or reconnect",
        "retried": False,
    }
    assert bridge_tools.voice_turn_response(result).action == 1


async def test_cancelled_turn_consumes_simultaneous_mac_failure(
    bridge_tools, monkeypatch,
):
    """A cancelled read-only request must not leak an unobserved task error."""
    import asyncio

    bridge = bridge_tools.bridge
    cancelled = asyncio.Event()
    bridge.tool_turn_cancel_event = lambda device: cancelled
    started = asyncio.Event()
    release = asyncio.Event()
    unhandled = []
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))

    class FailingMac:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, *args, **kwargs):
            started.set()
            await release.wait()
            raise RuntimeError("simultaneous obsolete HTTP failure")

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", FailingMac)
    task = asyncio.create_task(
        bridge_tools.call(bridge_tools.registered_head, "status")
    )
    try:
        await asyncio.wait_for(started.wait(), 1)
        cancelled.set()
        release.set()
        result = await asyncio.wait_for(task, 1)
        assert result["retried"] is False
        assert "superseded" in result["error"]
        await asyncio.sleep(0)
        assert unhandled == []
    finally:
        release.set()
        loop.set_exception_handler(previous)
        await asyncio.gather(task, return_exceptions=True)


async def test_cancel_event_wins_even_if_waiter_task_is_not_yet_done(
    bridge_tools, monkeypatch,
):
    """HTTP completion cannot publish a receipt after the source event fires."""
    import asyncio

    event = asyncio.Event()
    bridge_tools.bridge.tool_turn_cancel_event = lambda device: event
    original_wait = asyncio.wait

    async def race_wait(tasks, *, return_when=None, timeout=None):
        if return_when == asyncio.FIRST_COMPLETED:
            request_task = next(task for task in tasks if task.get_coro().__name__ == "request_mac")
            await request_task
            event.set()
            # Simulate the event waiter not yet having resumed.
            return {request_task}, set(tasks) - {request_task}
        return await original_wait(tasks, return_when=return_when, timeout=timeout)

    class Mac:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, *args, **kwargs):
            return httpx.Response(200, json={
                "robot_id": "robot-01",
                "answer": "obsolete private observation",
                "motor_authorized": False,
                "charging_authorized": False,
            })

    monkeypatch.setattr(bridge_tools.asyncio, "wait", race_wait)
    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", lambda **kwargs: Mac())
    result = await bridge_tools.call(bridge_tools.registered_head, "status")
    assert result == {
        "error": "Robot tool result superseded by new speech or reconnect",
        "retried": False,
    }
    assert bridge_tools.voice_turn_response(result).action == 1


async def test_xiaozhi_tool_cancel_during_waiter_cleanup_never_speaks_stale_result(
    bridge_tools, monkeypatch,
):
    """The turn can end after HTTP completion but before its waiter is reaped."""
    import asyncio

    bridge = bridge_tools.bridge
    bridge.voice_turn_generation = {"mac-head-01": 3}
    signal = asyncio.Event()
    bridge.tool_turn_cancel_event = lambda device: signal
    original_client = httpx.AsyncClient
    original_wait = asyncio.wait
    waits = 0

    async def handler(request):
        await asyncio.sleep(0)
        return httpx.Response(200, json={
            "robot_id": "robot-01", "old_private_answer": "STALE_TURN",
        })

    def client_factory(*args, **kwargs):
        return original_client(
            *args, transport=httpx.MockTransport(handler), **kwargs
        )

    async def switch_turn_during_cleanup(tasks, *args, **kwargs):
        nonlocal waits
        result = await original_wait(tasks, *args, **kwargs)
        waits += 1
        if waits == 2:
            # The HTTP result already won the first wait. A new human starts
            # speaking while cancellation of the waiter finishes. The event
            # may precede the separate generation bookkeeping callback.
            signal.set()
        return result

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(bridge_tools.asyncio, "wait", switch_turn_during_cleanup)
    result = await bridge_tools.call(bridge_tools.registered_head, "status")
    assert waits == 2
    assert result == {
        "error": "Robot tool result superseded by new speech or reconnect",
        "retried": False,
    }
    assert "STALE_TURN" not in str(result)



@pytest.mark.parametrize("planned,accepted", [
    (["power-status", "aux-status", "status"], True),
    (["power-status", "aux-status", "status", "latest-pickup"], False),
    (["power-status", "aux-status", "power-status"], False),
    (["power-status", "aux-status", "move"], False),
    (["power-status", "aux-status", "../stop"], False),
])
async def test_authenticated_shared_xiaozhi_plan_accepts_three_distinct_readonly_routes(
    bridge_tools, monkeypatch, planned, accepted,
):
    """Real first Xiaozhi HTTP bridge cannot discard a valid third Mac tool."""
    original = httpx.AsyncClient
    requested = []

    def handle(request):
        requested.append(request)
        assert request.url.path == "/v1/pet/robot-01/plan-readonly"
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer " + "s" * 40
        assert request.headers["x-desk-robot-tool-receipt"] == "1"
        return httpx.Response(200, json={
            "robot_id": "robot-01",
            "source": "existing_mac_ollama_readonly_route_selection",
            "untrusted_model_selection": True,
            "model_can_arm_motors": False,
            "motor_authorized": False,
            "charging_authorized": False,
            "tools": [{"route": name, "payload": {}} for name in planned],
        })

    def client_factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(bridge_tools.httpx, "AsyncClient", client_factory)
    result = await bridge_tools.call(
        bridge_tools.registered_head, "plan-readonly",
        {"transcript": "Check charge, raw sensors, and WROOM safety status"},
    )
    assert len(requested) == 1
    if accepted:
        assert [item["route"] for item in result["tools"]] == planned
        assert result["motor_authorized"] is False
        assert result["charging_authorized"] is False
    else:
        assert result == {
            "error": "Invalid read-only Mac intent plan", "retried": False,
        }


@pytest.mark.parametrize("delay", [0, 0.01, 0.25])
async def test_obsolete_http_teardown_failure_is_observed(
    bridge_tools, monkeypatch, delay,
):
    """Observe failures within and beyond the bounded cancellation cleanup."""
    import asyncio
    import gc

    started, signal, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    bridge_tools.bridge.tool_turn_cancel_event = lambda device: signal
    unhandled = []
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))

    class FailingTeardown:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, *args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.sleep(delay)
                finished.set()
                raise RuntimeError("obsolete HTTP teardown failed") from None

    monkeypatch.setattr(
        bridge_tools.httpx, "AsyncClient", lambda **kwargs: FailingTeardown()
    )
    task = asyncio.create_task(
        bridge_tools.call(bridge_tools.registered_head, "status")
    )
    try:
        await asyncio.wait_for(started.wait(), 1)
        signal.set()
        result = await asyncio.wait_for(task, 1)
        assert result == {
            "error": "Robot tool result superseded by new speech or reconnect",
            "retried": False,
        }
        assert bridge_tools.voice_turn_response(result).action == 1
        await asyncio.wait_for(finished.wait(), 1)
        await asyncio.sleep(0)
        gc.collect()
        await asyncio.sleep(0)
        assert unhandled == []
    finally:
        signal.set()
        await asyncio.gather(task, return_exceptions=True)
        loop.set_exception_handler(previous)
