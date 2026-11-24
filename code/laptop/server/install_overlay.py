#!/usr/bin/env python3
"""Create an isolated pinned Xiaozhi server build and add the small speech/tool adapter."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

PIN = "d9c2e8c5d92627b670dec57d72a07a4226a410a3"
HERE = Path(__file__).resolve().parent


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f"Upstream anchor changed: {old[:60]}")
    return source.replace(old, new, 1)


def patch_plugin_executor(source: str) -> str:
    """Backport upstream's dedicated worker pool without upgrading custom hooks.

    Sync Xiaozhi plugin functions must not monopolize the live audio/VAD
    event loop. Async plugins still run as coroutines on that loop.
    Derived from upstream xinnan-tech/xiaozhi-esp32-server (MIT).
    """
    source = once(
        source, "import asyncio\n",
        "import asyncio\nimport functools\nimport threading\n"
        "from concurrent.futures import ThreadPoolExecutor\n",
    )
    source = once(
        source, "\n\nclass ServerPluginExecutor(ToolExecutor):",
        '\n\n_PLUGIN_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="plugin")'
        '\n_PLUGIN_SLOTS = threading.BoundedSemaphore(8)'
        "\n\nclass ServerPluginExecutor(ToolExecutor):",
    )
    old = (
        "            # 根据工具类型决定如何调用\n"
        '            if hasattr(func_item, "type"):\n'
        "                func_type = func_item.type\n"
        "                if func_type.code in [4, 5]:  # SYSTEM_CTL, IOT_CTL (需要conn参数)\n"
        "                    result = func_item.func(conn, **arguments)\n"
        "                elif func_type.code == 2:  # WAIT\n"
        "                    result = func_item.func(**arguments)\n"
        "                elif func_type.code == 3:  # CHANGE_SYS_PROMPT\n"
        "                    result = func_item.func(conn, **arguments)\n"
        "                else:\n"
        "                    result = func_item.func(**arguments)\n"
        "            else:\n"
        "                # 默认不传conn参数\n"
        "                result = func_item.func(**arguments)\n"
        "\n"
        "            # 兼容 async def 工具函数\n"
        "            if asyncio.iscoroutine(result):\n"
        "                result = await result"
    )
    new = (
        '            func_type = getattr(func_item, "type", None)\n'
        "            if func_type is not None and func_type.code in [3, 4, 5]:\n"
        "                call = functools.partial(func_item.func, conn, **arguments)\n"
        "            else:\n"
        "                call = functools.partial(func_item.func, **arguments)\n"
        "\n"
        "            if asyncio.iscoroutinefunction(func_item.func):\n"
        "                result = await call()\n"
        "            else:\n"
        "                # Strictly bound native work, even if asyncio cancels the awaiter.\n"
        "                if not _PLUGIN_SLOTS.acquire(blocking=False):\n"
        '                    raise RuntimeError("Synchronous plugin capacity exhausted")\n'
        "                try:\n"
        "                    native = _PLUGIN_POOL.submit(call)\n"
        "                except (RuntimeError, OSError):\n"
        "                    _PLUGIN_SLOTS.release()\n"
        "                    raise\n"
        "                def finished(completed):\n"
        "                    try:\n"
        "                        if not completed.cancelled():\n"
        "                            completed.exception()\n"
        "                    finally:\n"
        "                        _PLUGIN_SLOTS.release()\n"
        "                native.add_done_callback(finished)\n"
        "                result = await asyncio.wrap_future(native)\n"
        "                if asyncio.iscoroutine(result):\n"
        "                    result = await result"
    )
    return once(source, old, new)


def patch_unified_tool_handler(source: str) -> str:
    """Backport the pinned multi-tool ActionResponse result contract.

    The upstream _combine_responses reads response.content, but its actual
    ActionResponse defines result, response and action only. Preserve data
    from each valid tool call while dropping silent cancelled tool results.
    Do not change upstream tool actions or replay old audio.
    """
    old = (
        "            if response.content:\n"
        "                contents.append(response.content)\n"
    )
    new = (
        "            # The pinned ActionResponse has .result, not .content.\n"
        "            # Action.NONE with no payload must remain truly silent.\n"
        "            value = getattr(response, 'result', None)\n"
        "            if response.action != Action.NONE and value is not None:\n"
        "                contents.append(value if isinstance(value, str)\n"
        "                                else json.dumps(value, ensure_ascii=False, default=str))\n"
    )
    return once(source, old, new)


def patch_intent_speech_guard(source: str) -> str:
    """Fence late pinned intent/tool results to the original desk-robot VAD turn.

    The upstream process_function_call worker may outlive a later human speech
    event. The existing tool HTTP generation guard alone cannot fence the
    intent model's replyResult or the final synchronous speak_txt enqueue.
    Only registered desk robot heads are changed.
    """
    source = once(
        source,
        'async def handle_user_intent(conn: "ConnectionHandler", text):\n',
        'async def handle_user_intent(conn: "ConnectionHandler", text):\n'
        '    import desk_robot_bridge as _desk_turn\n'
        '    _desk_device = getattr(conn, "device_id", None)\n'
        '    _desk_registered = _desk_turn.robot_for_device(_desk_device) is not None\n'
        '    _desk_generation = (\n'
        '        _desk_turn.voice_turn_generation.get(_desk_device, 0)\n'
        '        if _desk_registered else None\n'
        '    )\n',
    )
    source = once(
        source,
        '    if conn.intent_type == "function_call":\n',
        '    if _desk_registered:\n'
        '        await _desk_turn.inject_live_context_into_legacy_llm(conn)\n'
        '        # Live context HTTP must not delay a now-obsolete human turn.\n'
        '        if (_desk_turn.connections.get(_desk_device) is not conn\n'
        '                or _desk_turn.voice_turn_generation.get(_desk_device, 0)\n'
        '                    != _desk_generation):\n'
        '            return True\n'
        '    if conn.intent_type == "function_call":\n',
    )
    source = once(
        source, "    return await process_intent_result(conn, intent_result, text)\n",
        "    return await process_intent_result(\n"
        "        conn, intent_result, text, expected_generation=_desk_generation\n"
        "    )\n",
    )
    source = once(
        source,
        'async def process_intent_result(\n'
        '    conn: "ConnectionHandler", intent_result, original_text\n'
        '):\n'
        '    """处理意图识别结果"""\n',
        'async def process_intent_result(\n'
        '    conn: "ConnectionHandler", intent_result, original_text,\n'
        '    expected_generation=None,\n'
        '):\n'
        '    """处理意图识别结果"""\n'
        '    import desk_robot_bridge as _desk_turn\n'
        '    def current_utterance():\n'
        '        return expected_generation is None or (\n'
        '            _desk_turn.connections.get(conn.device_id) is conn\n'
        '            and _desk_turn.voice_turn_generation.get(conn.device_id, 0)\n'
        '                == expected_generation\n'
        '        )\n'
        '    if not current_utterance():\n'
        '        return True  # A newer human turn already owns audio.\n',
    )
    source = once(
        source,
        '                def process_context_result():\n'
        '                    conn.dialogue.put(Message(role="user", content=original_text))',
        '                def process_context_result():\n'
        '                    if not current_utterance():\n'
        '                        return\n'
        '                    conn.dialogue.put(Message(role="user", content=original_text))',
    )
    source = once(
        source,
        '                    if response:\n'
        '                        speak_txt(conn, response)\n',
        '                    if response and current_utterance():\n'
        '                        speak_txt(conn, response)\n',
    )
    source = once(
        source,
        '            def process_function_call():\n'
        '                conn.dialogue.put(Message(role="user", content=original_text))',
        '            def process_function_call():\n'
        '                if not current_utterance():\n'
        '                    return\n'
        '                if expected_generation is None:\n'
        '                    conn.dialogue.put(Message(role="user", content=original_text))',
    )
    source = once(
        source,
        '                # 上报工具调用结果\n'
        '                if result:\n',
        '                # The new voice owner must not receive an old tool result,\n'
        '                # TTS or dialogue history even if replyResult is still busy.\n'
        '                if not current_utterance():\n'
        '                    return\n'
        '                if expected_generation is not None:\n'
        '                    conn.dialogue.put(Message(role="user", content=original_text))\n'
        '                # 上报工具调用结果\n'
        '                if result:\n',
    )
    source = once(
        source,
        '                        speak_txt(conn, llm_result)\n',
        '                        if current_utterance():\n'
        '                            speak_txt(conn, llm_result)\n',
    )
    # STT delivery can suspend while a newer human turn sets client_abort.
    for spaces in (12, 16):
        indent = " " * spaces
        stt = indent + "await send_stt_message(conn, original_text)\n"
        reset = indent + "conn.client_abort = False\n"
        source = once(
            source, "\n" + stt + reset,
            "\n" + stt + indent + "if not current_utterance():\n"
            + indent + "    return True\n" + reset,
        )
    # The thread's check cannot authorize an event-loop coroutine that
    # starts after a different human turn or a replacement head connects.
    source = once(
        source,
        '            def process_function_call():\n',
        '            async def dispatch_current_tool():\n'
        '                if not current_utterance():\n'
        '                    return None\n'
        '                return await conn.func_handler.handle_llm_function_call(\n'
        '                    conn, function_call_data\n'
        '                )\n\n'
        '            def process_function_call():\n',
    )
    source = once(
        source,
        '                        conn.func_handler.handle_llm_function_call(\n'
        '                            conn, function_call_data\n'
        '                        ),\n',
        '                        dispatch_current_tool(),\n',
    )
    # Synchronous result branches have no await once the turn is checked;
    # only the possibly slow nested replyResult requires a second fence.
    return source


def files(root):
    changes = {}
    path = "core/connection.py"
    source = (root / path).read_text()
    source = once(
        source,
        "            self.websocket = ws",
        "            self.websocket = ws\n            import desk_robot_bridge\n            desk_robot_bridge.register(self)",
    )
    source = once(
        source,
        '        """消息路由"""',
        '        """消息路由"""\n        import desk_robot_bridge\n        if desk_robot_bridge.suppress_message(self, message):\n            return',
    )
    source = once(
        source,
        "            tts = initialize_tts(self.config)",
        "            import desk_robot_bridge\n"
        "            tts = initialize_tts(desk_robot_bridge.native_tts_config(self))",
    )
    changes[path] = source
    path = "core/websocket_server.py"
    source = (root / path).read_text()
    source = once(
        source,
        "        finally:\n            # 强制关闭连接",
        "        finally:\n            import desk_robot_bridge\n            desk_robot_bridge.unregister(handler)\n            # 强制关闭连接",
    )
    changes[path] = source
    path = "core/handle/receiveAudioHandle.py"
    source = (root / path).read_text()
    source = once(
        source,
        "    # 服务端AEC功能需要实时触发打断",
        "    import desk_robot_bridge\n"
        "    try:\n"
        "        await desk_robot_bridge.interrupt_for_user_voice(conn, have_voice)\n"
        "        await desk_robot_bridge.interrupt_for_normal_voice(conn, have_voice)\n"
        "    except Exception as stop_error:\n"
        "        # Failed device STOP must not discard a real human microphone frame.\n"
        "        # Head generation remains aborted; never claim physical silence.\n"
        "        import logging\n"
        "        logging.getLogger('desk_robot_bridge').warning(\n"
        "            'Xiaozhi speaker STOP unconfirmed; preserving human PCM: %s',\n"
        "            type(stop_error).__name__,\n"
        "        )\n"
        "    desk_robot_bridge.observe_idle_human_voice(conn, have_voice)\n"
        "    import desk_robot_native_omni\n"
        "    if desk_robot_native_omni.route_audio(conn, pcm_frame, have_voice):\n"
        "        return\n"
        "    # 服务端AEC功能需要实时触发打断",
    )
    source = once(
        source,
        'async def startToChat(conn: "ConnectionHandler", text):',
        'async def startToChat(conn: "ConnectionHandler", text):\n'
        '    import desk_robot_bridge\n'
        '    if (desk_robot_bridge.muted(conn.device_id)\n'
        '            and not desk_robot_bridge.was_interrupted_by_human(conn.device_id)):\n'
        '        return',
    )
    changes[path] = source
    path = "app.py"
    source = (root / path).read_text()
    source = once(
        source,
        "    ws_server = WebSocketServer(config)",
        "    import desk_robot_bridge\n    robot_speech_runner = await desk_robot_bridge.start()\n    ws_server = WebSocketServer(config)",
    )
    source = once(
        source,
        "        # 停止全局GC管理器",
        "        await robot_speech_runner.cleanup()\n        # 停止全局GC管理器",
    )
    changes[path] = source
    changes["desk_robot_bridge.py"] = (HERE / "overlay/desk_robot_bridge.py").read_text()
    changes["desk_robot_native_omni.py"] = (
        HERE / "overlay/desk_robot_native_omni.py"
    ).read_text()
    changes["desk_robot_voice_intents.py"] = (
        HERE / "overlay/desk_robot_voice_intents.py"
    ).read_text()
    # Reuse the same vLLM Omni protocol from the Mac package.
    changes["desk_robot_omni_wire.py"] = (
        HERE.parent / "src/desk_robot/realtime_omni_protocol.py"
    ).read_text()
    changes["plugins_func/functions/desk_robot_tools.py"] = (
        HERE / "overlay/desk_robot_tools.py"
    ).read_text()
    path = "core/providers/tools/server_plugins/plugin_executor.py"
    changes[path] = patch_plugin_executor((root / path).read_text())
    path = "core/providers/tools/unified_tool_handler.py"
    changes[path] = patch_unified_tool_handler((root / path).read_text())
    path = "core/handle/intentHandler.py"
    changes[path] = patch_intent_speech_guard((root / path).read_text())
    # Verify syntax before modifying any build source.
    for name, source in changes.items():
        compile(source, name, "exec")
    return changes


def install(upstream: Path, output: Path):
    pin = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip()
    if pin != PIN:
        raise ValueError("Use the pinned server source from upstream-lock.json")
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=upstream, text=True).strip():
        raise ValueError("Preserve upstream source changes before installing")
    changes = files(upstream / "main/xiaozhi-server")
    marker = output / ".desk-robot-server-overlay.json"
    if output.exists():
        current = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=output, text=True).strip()
        if current != PIN or not marker.is_file():
            raise ValueError("Existing output is not this pinned managed build")
        for name, checksum in json.loads(marker.read_text()).items():
            path = output / "main/xiaozhi-server" / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
                raise ValueError(f"Preserve changed overlaid file before refresh: {name}")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--no-hardlinks", str(upstream.resolve()), str(output.resolve())],
            check=True,
        )
        subprocess.run(["git", "checkout", "--detach", PIN], cwd=output, check=True)
    root = output / "main/xiaozhi-server"
    for name, source in changes.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    manifest = {
        name: hashlib.sha256(source.encode()).hexdigest() for name, source in changes.items()
    }
    marker.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Installed server adapter in {root}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    install(args.upstream, args.output)
