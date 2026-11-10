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
        "    await desk_robot_bridge.interrupt_for_user_voice(conn, have_voice)\n"
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
    changes["plugins_func/functions/desk_robot_tools.py"] = (
        HERE / "overlay/desk_robot_tools.py"
    ).read_text()
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
