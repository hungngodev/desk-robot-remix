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
    module.registered_head = registered
    module.bridge = bridge
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
    assert "superseded" in result.result["error"]
    assert "memories" not in result.result


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
