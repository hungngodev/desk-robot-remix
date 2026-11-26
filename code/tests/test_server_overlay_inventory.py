import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def installer(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "server_overlay_inventory", ROOT / "laptop/server/install_overlay.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    overlay = tmp_path / "server/overlay"
    overlay.mkdir(parents=True)
    for name in (
        "desk_robot_bridge.py",
        "desk_robot_native_omni.py",
        "desk_robot_omni_audio.py",
        "desk_robot_omni_http_protocol.py",
        "desk_robot_tools.py",
        "desk_robot_voice_intents.py",
    ):
        (overlay / name).write_text(f"# {name}\n")
    monkeypatch.setattr(module, "HERE", overlay.parent)
    return module, overlay


def test_new_extracted_module_is_included(installer):
    module, overlay = installer
    extra = overlay / "desk_robot_new_helper.py"
    extra.write_text("VALUE = 42\n")
    sources = module.overlay_sources()
    expected = {path.name: path.read_text() for path in overlay.glob("*.py")}
    expected["plugins_func/functions/desk_robot_tools.py"] = expected.pop("desk_robot_tools.py")
    assert sources == expected
    assert sources[extra.name] == "VALUE = 42\n"


@pytest.mark.parametrize("name", ["desk_robot_voice_intents.py", "desk_robot_tools.py"])
def test_required_overlay_module_cannot_silently_disappear(installer, name):
    module, overlay = installer
    (overlay / name).unlink()
    with pytest.raises(FileNotFoundError):
        module.overlay_sources()


@pytest.mark.parametrize(
    "name", ["other.py", "nested/desk_robot_helper.py", "desk_robot_omni_wire.py"],
)
def test_unsupported_overlay_layout_fails_closed(installer, name):
    module, overlay = installer
    path = overlay / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("VALUE = 42\n")
    with pytest.raises(ValueError, match="Unexpected server overlay module"):
        module.overlay_sources()


def test_generated_omni_wire_matches_mac_protocol_and_manifest(installer, tmp_path, monkeypatch):
    module, overlay = installer
    expected = (ROOT / "laptop/src/desk_robot/realtime_omni_protocol.py").read_bytes()
    # Mirror the laptop layout without editing the real canonical source.
    canonical = overlay.parent.parent / "src/desk_robot/realtime_omni_protocol.py"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(expected)
    # Isolate unrelated upstream anchor substitutions, not the wire generation,
    # inventory, installation, hashing or verification paths under test.
    monkeypatch.setattr(module, "once", lambda source, old, new: source)
    upstream = tmp_path / "upstream"
    root = upstream / "main/xiaozhi-server"
    for name in (
        "core/connection.py",
        "core/websocket_server.py",
        "core/handle/receiveAudioHandle.py",
        "app.py",
        "core/providers/tools/server_plugins/plugin_executor.py",
        "core/providers/tools/unified_tool_handler.py",
        "core/handle/intentHandler.py",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# unrelated upstream fixture\n")
    subprocess.run(["git", "init", "-q"], cwd=upstream, check=True)
    subprocess.run(["git", "add", "."], cwd=upstream, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Overlay Test", "-c", "user.email=test@example.invalid",
         "-c", "commit.gpgsign=false", "commit", "-qm", "Fixture"],
        cwd=upstream, check=True,
    )
    pin = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip()
    monkeypatch.setattr(module, "PIN", pin)

    name = "desk_robot_omni_wire.py"
    assert module.files(root)[name].encode() == expected
    output = tmp_path / "installed"
    module.install(upstream, output)
    installed = output / "main/xiaozhi-server" / name
    marker = output / ".desk-robot-server-overlay.json"
    assert installed.read_bytes() == expected
    assert json.loads(marker.read_text())[name] == hashlib.sha256(expected).hexdigest()
    module.verify_installed_overlay(upstream, output)

    # A later canonical change must invalidate the previous manifest and
    # regenerate the actual module, rather than retaining a stale copy.
    updated = expected + b"\n# Updated canonical protocol\n"
    canonical.write_bytes(updated)
    with pytest.raises(ValueError, match="Server overlay is stale or incomplete"):
        module.verify_installed_overlay(upstream, output)
    module.install(upstream, output)
    assert installed.read_bytes() == updated
    assert json.loads(marker.read_text())[name] == hashlib.sha256(updated).hexdigest()
    module.verify_installed_overlay(upstream, output)

    installed.write_bytes(expected)
    with pytest.raises(ValueError, match="Server overlay file differs before launch"):
        module.verify_installed_overlay(upstream, output)
