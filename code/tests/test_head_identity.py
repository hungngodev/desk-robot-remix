import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "head_private_config", ROOT / "firmware/head/private_config.py"
)
HEAD_CONFIG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HEAD_CONFIG)


def test_all_five_heads_resolve_distinct_credentials():
    config = ROOT / "config/fleet.example.toml"
    names = [HEAD_CONFIG.robot_token_env(config, f"robot-{n:02}") for n in range(1, 6)]
    assert names == [f"DESK_ROBOT_HEAD_{n:02}_TOKEN" for n in range(1, 6)]
    with pytest.raises(ValueError, match="robot ID"):
        HEAD_CONFIG.robot_token_env(config, "robot-06")


def test_shared_or_malformed_credential_names_are_rejected(tmp_path):
    config = tmp_path / "robots.toml"
    config.write_text(
        '[[robots]]\nid="robot-01"\ntoken_env="SAME_TOKEN"\n'
        '[[robots]]\nid="robot-02"\ntoken_env="SAME_TOKEN"\n'
    )
    with pytest.raises(ValueError, match="own credential"):
        HEAD_CONFIG.robot_token_env(config, "robot-01")
    config.write_text('[[robots]]\nid="robot-01"\ntoken_env="bad-name"\n')
    with pytest.raises(ValueError, match="valid credential"):
        HEAD_CONFIG.robot_token_env(config, "robot-01")


def test_private_settings_write_only_selected_fifth_identity(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(HEAD_CONFIG, "ROOT", tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    (config / "fleet.example.toml").write_text(
        '[[robots]]\nid="robot-01"\ntoken_env="DESK_ROBOT_HEAD_01_TOKEN"\n'
        '[[robots]]\nid="robot-05"\ntoken_env="DESK_ROBOT_HEAD_05_TOKEN"\n'
    )
    first, fifth = "a" * 40, "e" * 40
    for name in ("DESK_ROBOT_HEAD_01_TOKEN", "DESK_ROBOT_HEAD_05_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    (config / "local.env").write_text(
        f"DESK_ROBOT_HEAD_01_TOKEN={first}\nDESK_ROBOT_HEAD_05_TOKEN={fifth}\n"
    )
    board = (tmp_path / "firmware/head/build/xiaozhi-modular/main/boards/desk-robot"
             / "desk-robot-modular-s3")
    board.mkdir(parents=True)
    original = {"builds": [{"sdkconfig_append": [
        'CONFIG_DESK_ROBOT_ID="robot-01"', 'CONFIG_DESK_ROBOT_TOKEN="stale"',
        'CONFIG_OTA_URL="http://old/"', "CONFIG_UNRELATED=y",
    ]}]}
    (board / "config.json").write_text(json.dumps(original))
    target = board / "config.private.json"
    target.write_text("old")
    target.chmod(0o644)
    monkeypatch.setattr("sys.argv", [
        "private_config.py", "--board", "modular", "--robot", "robot-05",
        "--server-ip", "192.168.1.20",
    ])
    HEAD_CONFIG.main()
    settings = json.loads(target.read_text())["builds"][0]["sdkconfig_append"]
    assert settings == [
        "CONFIG_UNRELATED=y", 'CONFIG_DESK_ROBOT_ID="robot-05"',
        f'CONFIG_DESK_ROBOT_TOKEN="{fifth}"',
        'CONFIG_OTA_URL="http://192.168.1.20:8003/xiaozhi/ota/"',
    ]
    assert json.loads((board / "config.json").read_text()) == original
    assert target.stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr().out
    assert first not in output and fifth not in output and "robot-05" in output
