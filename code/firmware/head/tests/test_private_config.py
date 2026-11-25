"""Private head configuration must not escape the ignored build tree."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "private_config_exp037", Path(__file__).resolve().parents[1] / "private_config.py"
)
private = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(private)

BOARD = Path("firmware/head/build/xiaozhi-sense/main/boards/desk-robot/desk-robot-sense-s3")
SYNTHETIC_TOKEN = "x" * 40


def configure(root, monkeypatch):
    fleet = root / "fleet.toml"
    fleet.write_text('[[robots]]\nid="robot-01"\ntoken_env="EXP037_TEST_TOKEN"\n')
    monkeypatch.setattr(private, "ROOT", root)
    monkeypatch.setenv("EXP037_TEST_TOKEN", SYNTHETIC_TOKEN)
    monkeypatch.setattr(sys, "argv", [
        "private_config.py", "--board", "sense", "--robot", "robot-01",
        "--server-ip", "192.168.1.15", "--config", str(fleet),
        "--secrets", str(root / "missing.env"),
    ])


def template(board):
    board.mkdir(parents=True, exist_ok=True)
    source = board / "config.json"
    source.write_text(json.dumps({"builds": [{"sdkconfig_append": ["CONFIG_UNRELATED=y"]}]}))
    return source


@pytest.mark.parametrize("depth", range(1, len(BOARD.parts) + 1))
def test_private_config_rejects_redirected_build_directory(tmp_path, monkeypatch, capsys, depth):
    configure(tmp_path, monkeypatch)
    link = tmp_path.joinpath(*BOARD.parts[:depth])
    link.parent.mkdir(parents=True, exist_ok=True)
    tracked = tmp_path / "tracked-source"
    tracked.mkdir()
    link.symlink_to(tracked, target_is_directory=True)
    redirected_board = tracked.joinpath(*BOARD.parts[depth:])
    source = template(redirected_board)
    original = source.read_bytes()
    with pytest.raises(SystemExit) as error:
        private.main()
    assert error.value.code == 2
    assert SYNTHETIC_TOKEN not in capsys.readouterr().err
    assert source.read_bytes() == original
    assert not list(tracked.rglob("config.private.json"))
    assert not list(tracked.rglob(".config.private.*.tmp"))


def test_private_config_normal_build_keeps_token_private(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    board = tmp_path / BOARD
    source = template(board)
    original = source.read_bytes()
    private.main()
    output = capsys.readouterr()
    assert SYNTHETIC_TOKEN not in output.out + output.err
    assert source.read_bytes() == original
    target = board / "config.private.json"
    assert target.stat().st_mode & 0o777 == 0o600
    settings = json.loads(target.read_text())["builds"][0]["sdkconfig_append"]
    assert f'CONFIG_DESK_ROBOT_TOKEN="{SYNTHETIC_TOKEN}"' in settings
    assert not list(board.glob(".config.private.*.tmp"))


@pytest.mark.parametrize("exists", [True, False])
def test_private_config_refuses_target_symlink(tmp_path, monkeypatch, capsys, exists):
    configure(tmp_path, monkeypatch)
    board = tmp_path / BOARD
    template(board)
    victim = tmp_path / "tracked.json"
    if exists:
        victim.write_bytes(b"tracked source")
    target = board / "config.private.json"
    target.symlink_to(victim)
    with pytest.raises(SystemExit) as error:
        private.main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert SYNTHETIC_TOKEN not in output.out + output.err
    assert target.is_symlink()
    if exists:
        assert victim.read_bytes() == b"tracked source"
    else:
        assert not victim.exists()
    assert not list(board.glob(".config.private.*.tmp"))


def test_private_config_failed_replace_preserves_previous_settings(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    board = tmp_path / BOARD
    template(board)
    private.main()
    target = board / "config.private.json"
    original = target.read_bytes()
    monkeypatch.setenv("EXP037_TEST_TOKEN", "y" * 40)

    def replace_failed(*args):
        raise OSError("injected replace failure")

    monkeypatch.setattr(private.os, "replace", replace_failed)
    with pytest.raises(OSError, match="injected replace failure"):
        private.main()
    assert target.read_bytes() == original
    assert target.stat().st_mode & 0o777 == 0o600
    assert not list(board.glob(".config.private.*.tmp"))
    output = capsys.readouterr()
    assert SYNTHETIC_TOKEN not in output.out + output.err
    assert "y" * 40 not in output.out + output.err
