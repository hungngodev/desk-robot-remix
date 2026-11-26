import importlib.util
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
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    for name in (
        "desk_robot_bridge.py",
        "desk_robot_native_omni.py",
        "desk_robot_omni_audio.py",
        "desk_robot_omni_http_protocol.py",
        "desk_robot_tools.py",
        "desk_robot_voice_intents.py",
    ):
        (overlay / name).write_text(f"# {name}\n")
    monkeypatch.setattr(module, "HERE", tmp_path)
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
