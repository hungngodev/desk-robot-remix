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

    def replace_failed(*args, **kwargs):
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


@pytest.mark.parametrize("insecure", ["permissions", "symlink", "duplicate"])
def test_private_config_rejects_insecure_input_credentials(tmp_path, monkeypatch, capsys, insecure):
    configure(tmp_path, monkeypatch)
    board = tmp_path / BOARD
    template(board)
    path = tmp_path / "missing.env"
    if insecure == "symlink":
        other = tmp_path / "other.env"
        other.write_text(f"EXP037_TEST_TOKEN={SYNTHETIC_TOKEN}\n")
        other.chmod(0o600)
        path.symlink_to(other)
    else:
        path.write_text(f"EXP037_TEST_TOKEN={SYNTHETIC_TOKEN}\n")
        path.chmod(0o644 if insecure == "permissions" else 0o600)
        if insecure == "duplicate":
            with path.open("a") as stream:
                stream.write(f"EXP037_TEST_TOKEN={SYNTHETIC_TOKEN}\n")
    with pytest.raises(SystemExit) as error:
        private.main()
    assert error.value.code == 2
    assert not (board / "config.private.json").exists()
    assert SYNTHETIC_TOKEN not in capsys.readouterr().err


@pytest.mark.parametrize("depth", range(1, len(BOARD.parts) + 1))
def test_private_config_refuses_directory_swap_after_template_read(
    tmp_path, monkeypatch, capsys, depth
):
    configure(tmp_path, monkeypatch)
    board = tmp_path / BOARD
    template(board)
    private.main()
    target = board / "config.private.json"
    original = target.read_bytes()
    ancestor = tmp_path.joinpath(*BOARD.parts[:depth])
    displaced = ancestor.with_name(ancestor.name + ".displaced")
    tracked = tmp_path / "tracked-source"
    redirected_board = tracked.joinpath(*BOARD.parts[depth:])
    template(redirected_board)
    loads = json.loads

    def swap_directory(*args, **kwargs):
        config = loads(*args, **kwargs)
        ancestor.rename(displaced)
        ancestor.symlink_to(tracked, target_is_directory=True)
        return config

    monkeypatch.setattr(private.json, "loads", swap_directory)
    monkeypatch.setenv("EXP037_TEST_TOKEN", "y" * 40)
    with pytest.raises(SystemExit) as error:
        private.main()
    assert error.value.code == 2
    assert not (redirected_board / "config.private.json").exists()
    old_board = displaced.joinpath(*BOARD.parts[depth:])
    assert (old_board / "config.private.json").read_bytes() == original
    assert not list(tmp_path.rglob(".config.private.*.tmp"))
    output = capsys.readouterr()
    assert SYNTHETIC_TOKEN not in output.out + output.err
    assert "y" * 40 not in output.out + output.err


@pytest.mark.parametrize("depth", range(1, len(BOARD.parts) + 1))
def test_private_config_refuses_dangling_ancestor(tmp_path, monkeypatch, capsys, depth):
    configure(tmp_path, monkeypatch)
    ancestor = tmp_path.joinpath(*BOARD.parts[:depth])
    ancestor.parent.mkdir(parents=True, exist_ok=True)
    missing = tmp_path / "missing-directory"
    ancestor.symlink_to(missing, target_is_directory=True)
    with pytest.raises(SystemExit) as error:
        private.main()
    assert error.value.code == 2
    assert not missing.exists()
    assert SYNTHETIC_TOKEN not in capsys.readouterr().err


def test_private_config_removes_staged_secret_after_directory_swap(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    board = tmp_path / BOARD
    template(board)
    private.main()
    original = (board / "config.private.json").read_bytes()
    displaced = board.with_name("displaced")
    tracked = tmp_path / "tracked-source"
    template(tracked)
    fsync = private.os.fsync

    def swap_after_fsync(descriptor):
        fsync(descriptor)
        board.rename(displaced)
        board.symlink_to(tracked, target_is_directory=True)

    monkeypatch.setattr(private.os, "fsync", swap_after_fsync)
    monkeypatch.setenv("EXP037_TEST_TOKEN", "y" * 40)
    with pytest.raises(SystemExit) as error:
        private.main()
    assert error.value.code == 2
    assert (displaced / "config.private.json").read_bytes() == original
    assert not (tracked / "config.private.json").exists()
    assert not list(tmp_path.rglob(".config.private.*.tmp"))
    output = capsys.readouterr()
    assert SYNTHETIC_TOKEN not in output.out + output.err
    assert "y" * 40 not in output.out + output.err


@pytest.mark.parametrize("invalid", [
    None, [], {}, {"builds": []}, {"builds": [None]},
    {"builds": [{}, {}]}, {"builds": [{}]},
    {"builds": [{"sdkconfig_append": "CONFIG_OTHER=y"}]},
    {"builds": [{"sdkconfig_append": [None]}]},
])
def test_private_config_invalid_template_preserves_previous(tmp_path, monkeypatch, capsys, invalid):
    configure(tmp_path, monkeypatch)
    board = tmp_path / BOARD
    source = template(board)
    private.main()
    target = board / "config.private.json"
    original = target.read_bytes()
    source.write_text(json.dumps(invalid))
    with pytest.raises(SystemExit) as error:
        private.main()
    assert error.value.code == 2
    assert target.read_bytes() == original
    assert not list(board.glob(".config.private.*.tmp"))
    output = capsys.readouterr()
    assert SYNTHETIC_TOKEN not in output.out + output.err
    assert "template is missing or invalid" in output.err


@pytest.mark.parametrize("fleet", [
    'robots = "robot-01"', 'robots = [1]',
    '[[robots]]\nid="robot-01"\ntoken_env=123',
])
def test_private_config_invalid_fleet_rejected(tmp_path, monkeypatch, capsys, fleet):
    configure(tmp_path, monkeypatch)
    (tmp_path / "fleet.toml").write_text(fleet)
    board = tmp_path / BOARD
    template(board)
    with pytest.raises(SystemExit) as error:
        private.main()
    assert error.value.code == 2
    assert not (board / "config.private.json").exists()
    assert SYNTHETIC_TOKEN not in capsys.readouterr().err
