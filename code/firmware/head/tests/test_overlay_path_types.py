"""Fail closed on filesystem objects outside the overlay transaction contract."""

import base64
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("overlay_path_types", HEAD / "install_overlay.py")
overlay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(overlay)


@pytest.fixture
def recipe(tmp_path, monkeypatch):
    root = tmp_path / "recipe"
    root.mkdir()
    (root / "overlay").mkdir()
    (root / "install_overlay.py").write_bytes(b"installer")
    (root / "BOARD_README.md").write_bytes(b"documentation")
    (root / "overlay/bridge.cc").write_bytes(b"source")
    monkeypatch.setattr(overlay, "HERE", root)
    return root


@pytest.mark.parametrize("kind", ["fifo", "directory", "symlink", "dangling"])
def test_recipe_rejects_nonregular_source_input(recipe, tmp_path, kind):
    foreign = tmp_path / "foreign.cc"
    foreign.write_bytes(b"external source")
    candidate = recipe / "overlay/foreign.cc"
    if kind == "fifo":
        os.mkfifo(candidate)
    elif kind == "directory":
        candidate.mkdir()
    else:
        candidate.symlink_to(foreign if kind == "symlink" else tmp_path / "absent")
    with pytest.raises(ValueError, match="regular file|symlink"):
        overlay.overlay_recipe_digest("cores3")
    assert foreign.read_bytes() == b"external source"


def test_recipe_rejects_symlinked_source_directory(recipe, tmp_path):
    external = tmp_path / "external"
    (recipe / "overlay").rename(external)
    (recipe / "overlay").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        overlay.overlay_recipe_digest("cores3")


@pytest.mark.parametrize("name", ["main/blocker/child.cc", "scripts/p3_tools/p3_gui_player.py"])
def test_journal_refuses_regular_file_as_ancestor(tmp_path, name):
    previous = tmp_path / "main/existing.cc"
    previous.parent.mkdir()
    previous.write_bytes(b"overlaid")
    blocker = (tmp_path / name).parent
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_bytes(b"unrelated")
    state = {
        "main/existing.cc": {
            "sha256": overlay.digest(b"overlaid"),
            "original": base64.b64encode(b"original").decode(),
        },
        name: {"sha256": overlay.digest(b"new"), "original": None},
    }
    marker = tmp_path / overlay.MARKER
    marker.write_text(json.dumps(state))
    original = marker.read_bytes()
    with pytest.raises(ValueError, match="non-directory"):
        overlay.remove(tmp_path)
    assert marker.read_bytes() == original
    assert previous.read_bytes() == b"overlaid"
    assert blocker.read_bytes() == b"unrelated"


def test_apply_refuses_fifo_before_reading_original(tmp_path, monkeypatch, recipe):
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    name = "scripts/audio_debug_server.py"
    fifo = root / name
    os.mkfifo(fifo)
    monkeypatch.setattr(overlay.subprocess, "check_output", lambda *a, **k: overlay.PIN
                        if "rev-parse" in a[0] else "")
    monkeypatch.setattr(overlay, "planned_files", lambda *a: {name: b"replacement"})
    read_bytes = Path.read_bytes

    def guarded_read(path):
        if path == fifo:
            pytest.fail("Installer attempted a blocking FIFO read")
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    with pytest.raises(ValueError, match="regular file"):
        overlay.apply(root)
    assert fifo.is_fifo()
    assert not (root / overlay.MARKER).exists()


@pytest.mark.parametrize("text", ["missing", "anchor anchor"])
def test_patch_anchor_requires_exactly_one_match(text):
    with pytest.raises(ValueError, match="anchor changed"):
        overlay.replace_once(text, "anchor", "replacement")
    assert overlay.replace_once("one anchor", "anchor", "replacement") == "one replacement"


def test_process_exit_during_install_recovers_main_and_host_script(tmp_path, recipe):
    root = tmp_path / "checkout"
    main = root / "main/existing.cc"
    main.parent.mkdir(parents=True)
    main.write_bytes(b"original main")
    script = root / "scripts/p3_tools/p3_gui_player.py"
    script.parent.mkdir(parents=True)
    script.write_bytes(b"original host")
    child = """
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location('crash_overlay', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.HERE = Path(sys.argv[3])
module.subprocess.check_output = lambda args, **kw: module.PIN if 'rev-parse' in args else ''
module.planned_files = lambda *args: {
    'main/existing.cc': b'patched main',
    'scripts/p3_tools/p3_gui_player.py': b'patched host',
}
replace = module.atomic_replace_bytes


def interrupted(path, data):
    replace(path, data)
    if path.name == 'existing.cc':
        os._exit(71)

module.atomic_replace_bytes = interrupted
module.apply(Path(sys.argv[2]))
"""
    result = subprocess.run(
        [sys.executable, "-c", child, str(HEAD / "install_overlay.py"), str(root), str(recipe)],
        timeout=10, check=False,
    )
    assert result.returncode == 71
    marker = root / overlay.MARKER
    assert marker.is_file()
    assert main.read_bytes() == b"patched main"
    assert script.read_bytes() == b"original host"
    overlay.remove(root)
    assert main.read_bytes() == b"original main"
    assert script.read_bytes() == b"original host"
    assert not marker.exists()
