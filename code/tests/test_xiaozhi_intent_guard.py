"""Actual pinned Xiaozhi intent worker must never speak an obsolete tool turn."""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def source_function(name: str):
    """Compile the patched upstream function itself, without its live providers."""
    path = ROOT / "laptop/server/install_overlay.py"
    spec = importlib.util.spec_from_file_location("desk_intent_installer", path)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    pinned = (ROOT / "upstream/xiaozhi-esp32-server/main/xiaozhi-server"
              / "core/handle/intentHandler.py")
    source = installer.patch_intent_speech_guard(pinned.read_text())
    module = ast.parse(source)
    target = next(
        node for node in module.body if isinstance(node, ast.AsyncFunctionDef)
        and node.name == name
    )
    return compile(ast.Module(body=[target], type_ignores=[]), str(pinned), "exec")


@pytest.mark.parametrize("new_speech_at", ["before_tool_done", "during_model", "never"])
async def test_pinned_tool_worker_cannot_speak_outside_original_human_turn(
    monkeypatch, new_speech_at,
):
    started, resume = asyncio.Event(), asyncio.Event()
    spoken, history, reports = [], [], []
    bridge = ModuleType("desk_robot_bridge")
    bridge.voice_turn_generation = {"head-01": 8}
    monkeypatch.setitem(sys.modules, "desk_robot_bridge", bridge)

    async def send_stt(*_):
        pass

    async def run_tool(_conn, _arguments):
        if new_speech_at == "before_tool_done":
            started.set()
            await resume.wait()
        return SimpleNamespace(action=3, result="a current visual interpretation",
                               response=None)

    async def reply_result(text, question):
        if new_speech_at != "before_tool_done":
            started.set()
            await resume.wait()
        return "I can see a blue mug."

    class Executor:
        runnable = None

        def submit(self, action):
            self.runnable = action

    executor = Executor()
    class Dialogue:
        def put(self, entry):
            history.append(entry)

    conn = SimpleNamespace(
        device_id="head-01",
        config={"tool_call_timeout": 2},
        executor=executor,
        intent=SimpleNamespace(replyResult=reply_result),
        func_handler=SimpleNamespace(handle_llm_function_call=run_tool),
        logger=SimpleNamespace(bind=lambda **kw: SimpleNamespace(
            error=lambda *_: None, debug=lambda *_: None)),
        dialogue=Dialogue(), loop=asyncio.get_running_loop(),
        client_abort=False,
    )
    bridge.connections = {"head-01": conn}
    namespace = {
        "json": json, "uuid": uuid, "asyncio": asyncio, "TAG": "intent",
        "Message": lambda **kw: SimpleNamespace(**kw),
        "send_stt_message": send_stt,
        "enqueue_tool_report": lambda *args, **kw: reports.append((args, kw)),
        "speak_txt": lambda _conn, text: spoken.append(text),
        "Action": SimpleNamespace(RESPONSE=2, REQLLM=3, ERROR=-1, NOTFOUND=0),
        "ActionResponse": lambda action, result=None, response=None:
            SimpleNamespace(action=action, result=result, response=response),
    }
    exec(source_function("process_intent_result"), namespace)
    intent = json.dumps({
        "function_call": {"name": "desk_robot_look",
                          "arguments": {"question": "What is here?"}}
    })
    result = await namespace["process_intent_result"](
        conn, intent, "What is here?", expected_generation=8,
    )
    assert result is True and executor.runnable is not None
    worker = asyncio.create_task(asyncio.to_thread(executor.runnable))
    try:
        await asyncio.wait_for(started.wait(), 1)
        if new_speech_at != "never":
            bridge.voice_turn_generation["head-01"] += 1
        resume.set()
        await asyncio.wait_for(worker, 2)
    finally:
        resume.set()
        await asyncio.gather(worker, return_exceptions=True)
    if new_speech_at == "never":
        assert spoken == ["I can see a blue mug."]
        assert [entry.role for entry in history] == ["user", "tool"]
    else:
        assert spoken == []
        if new_speech_at == "before_tool_done":
            assert history == []
    assert reports


async def test_pinned_intent_remembers_generation_before_slow_llm_detection(
    monkeypatch,
):
    detected, resume = asyncio.Event(), asyncio.Event()
    bridge = ModuleType("desk_robot_bridge")
    bridge.voice_turn_generation = {"head-01": 4}
    bridge.robot_for_device = lambda device: (
        "robot-01" if device == "head-01" else None
    )
    monkeypatch.setitem(sys.modules, "desk_robot_bridge", bridge)
    received = []

    async def analyze(_conn, text):
        detected.set()
        await resume.wait()
        return '{"function_call":{"name":"desk_robot_situation"}}'

    async def handle(_conn, _intent, _text, *, expected_generation):
        received.append(expected_generation)
        return True

    conn = SimpleNamespace(device_id="head-01", intent_type="other")
    bridge.connections = {"head-01": conn}
    # The installed upstream overlay awaits this existing Mac context
    # adapter BEFORE the slow intent classifier. Provide it in the isolated
    # fake module, so this test can verify true generation fencing instead
    # of crashing a detached task on AttributeError and timing out.
    async def add_live_context(_conn):
        assert _conn is conn

    bridge.inject_live_context_into_legacy_llm = add_live_context
    namespace = {
        "json": json,
        "check_direct_exit": lambda *args: asyncio.sleep(0, result=False),
        "checkWakeupWords": lambda *args: asyncio.sleep(0, result=False),
        "remove_punctuation_and_length": lambda text: (None, text),
        "analyze_intent_with_llm": analyze,
        "process_intent_result": handle,
        # This compiled real upstream function expects uuid from its original
        # module globals; isolated fixture must preserve that dependency.
        "uuid": uuid,
    }
    exec(source_function("handle_user_intent"), namespace)
    task = asyncio.create_task(namespace["handle_user_intent"](
        conn, "Do you see my key?"
    ))
    await asyncio.wait_for(detected.wait(), 1)
    bridge.voice_turn_generation["head-01"] = 5
    resume.set()
    assert await asyncio.wait_for(task, 1) is True
    assert received == [4]


@pytest.mark.parametrize("phase", [
    "stt_tool", "stt_context", "dispatch_generation",
    "dispatch_reconnect", "current", "nonrobot",
])
async def test_intent_dispatch_generation_boundary(monkeypatch, phase):
    """A thread-side generation check cannot authorize later loop dispatch."""
    bridge = ModuleType("desk_robot_bridge")
    bridge.voice_turn_generation = {"head-01": 4}
    monkeypatch.setitem(sys.modules, "desk_robot_bridge", bridge)
    submitted, invoked, spoken, reports, history = [], [], [], [], []

    async def send_stt(conn, _text):
        if phase.startswith("stt_"):
            bridge.voice_turn_generation["head-01"] = 5
            conn.client_abort = True

    async def run_tool(conn, arguments):
        invoked.append(arguments["name"])
        return SimpleNamespace(action=2, result=None, response="current result")

    class Config(dict):
        def get(self, key, default=None):
            # This executes in the thread after its initial generation check
            # but before run_coroutine_threadsafe schedules the tool.
            if phase == "dispatch_generation":
                bridge.voice_turn_generation["head-01"] = 5
            elif phase == "dispatch_reconnect":
                bridge.connections["head-01"] = object()
            return super().get(key, default)

    conn = SimpleNamespace(
        device_id="head-01",
        config=Config(tool_call_timeout=2),
        executor=SimpleNamespace(submit=submitted.append),
        func_handler=SimpleNamespace(handle_llm_function_call=run_tool),
        logger=SimpleNamespace(bind=lambda **kw: SimpleNamespace(
            error=lambda *_: None, debug=lambda *_: None)),
        dialogue=SimpleNamespace(put=history.append),
        loop=asyncio.get_running_loop(),
        client_abort=False,
    )
    bridge.connections = {"head-01": conn}
    namespace = {
        "json": json, "uuid": uuid, "asyncio": asyncio, "TAG": "intent",
        "Message": lambda **kw: SimpleNamespace(**kw),
        "send_stt_message": send_stt,
        "enqueue_tool_report": lambda *a, **kw: reports.append((a, kw)),
        "speak_txt": lambda _conn, text: spoken.append(text),
        "Action": SimpleNamespace(RESPONSE=2, REQLLM=3, ERROR=-1, NOTFOUND=0),
        "ActionResponse": lambda **kw: SimpleNamespace(**kw),
    }
    exec(source_function("process_intent_result"), namespace)
    function = (
        "result_for_context" if phase == "stt_context" else "desk_robot_pickup"
    )
    intent = json.dumps({"function_call": {
        "name": function, "arguments": {"target": "key"},
    }})
    result = await namespace["process_intent_result"](
        conn, intent, "pick up key",
        expected_generation=None if phase == "nonrobot" else 4,
    )
    assert result is True
    if phase.startswith("stt_"):
        assert submitted == []
        assert conn.client_abort is True
        assert reports == []
    else:
        assert len(submitted) == 1
        await asyncio.wait_for(asyncio.to_thread(submitted[0]), 3)
    if phase in {"current", "nonrobot"}:
        assert invoked == ["desk_robot_pickup"]
        assert spoken == ["current result"]
    else:
        assert invoked == spoken == history == []
