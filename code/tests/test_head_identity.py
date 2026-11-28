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
    (config / "local.env").chmod(0o600)
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


def test_pinned_sense_overlay_provides_real_reference_channels_and_explicit_dma_flush():
    """Inspect actual generated upstream output, not merely static local strings."""
    spec = importlib.util.spec_from_file_location(
        "sense_overlay_aec", ROOT / "firmware/head/install_overlay.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    files = module.planned_files(ROOT / "upstream/xiaozhi-esp32", "sense")
    base = "main/boards/desk-robot/desk-robot-sense-s3/"
    assert (base + "sense_reference_codec.h") in files
    assert (base + "sense_reference_codec.cc") in files
    codec = files[base + "sense_reference_codec.cc"].decode()
    header = files[base + "sense_reference_codec.h"].decode()
    board = files[base + "desk_robot_sense.cc"].decode()
    assert "input_reference_ = true" in codec
    assert "input_channels_ = 2" in codec
    assert "NoAudioCodecSimplexPdm::Read" in codec
    assert "NoAudioCodec::Write" in codec
    assert "SenseReferenceCodec audio_codec" in board
    assert "sense_reference_codec.h" in board
    assert "ReadReferenceLocked" in header
    kconfig = files["main/Kconfig.projbuild"].decode()
    assert (
        "USE_AUDIO_PROCESSOR && (BOARD_TYPE_DESK_ROBOT_SENSE_S3"
    ) in kconfig
    application = files["main/application.cc"].decode()
    assert "cJSON_IsTrue(cJSON_GetObjectItem(root, \"flush\"))" in application
    assert "audio_service_.ResetDecoder();" in application
    assert "GetAudioCodec()->EnableOutput(false)" in application
    config = json.loads(files[base + "config.json"])
    extras = config["builds"][0]["sdkconfig_append"]
    assert "CONFIG_USE_AUDIO_PROCESSOR=y" in extras
    assert "CONFIG_USE_DEVICE_AEC=y" in extras
    assert "CONFIG_USE_SERVER_AEC=n" in extras


def test_aec_port_preserves_existing_sense_pin_map_and_offline_scope():
    config = (ROOT / "firmware/head/sense/config.h").read_text()
    assert "AUDIO_PDM_MIC_GPIO_SCK GPIO_NUM_42" in config
    assert "AUDIO_PDM_MIC_GPIO_DIN GPIO_NUM_41" in config
    assert "AUDIO_I2S_SPK_GPIO_BCLK GPIO_NUM_4" in config
    assert "AUDIO_I2S_SPK_GPIO_LRCK GPIO_NUM_7" in config
    assert "AUDIO_I2S_SPK_GPIO_DOUT GPIO_NUM_8" in config
    assert "ROBOT_UART_TX GPIO_NUM_2" in config
    assert "ROBOT_UART_RX GPIO_NUM_1" in config


def test_optional_sense_rgb_heart_reuses_pinned_xiaozhi_state_led_and_stays_off_by_default():
    """Software opt in is not electrical approval to wire SD-shared GPIO9."""
    root = Path(__file__).resolve().parents[1]
    board = (root / "firmware/head/sense/desk_robot_sense.cc").read_text()
    installer = (root / "firmware/head/install_overlay.py").read_text()
    plan = (root.parent / "docs/hardware/one-robot-signal-harness.generated.md").read_text()
    config = (root / "firmware/head/sense/config.h").read_text()
    assert '#include "led/single_led.h"' in board
    assert "#ifdef CONFIG_DESK_ROBOT_RGB_HEART_ENABLED" in board
    assert "#define RGB_HEART_GPIO GPIO_NUM_9" in config
    assert "static SingleLed heart(RGB_HEART_GPIO)" in board
    assert "return WifiBoard::GetLed();" in board
    assert "config DESK_ROBOT_RGB_HEART_ENABLED" in installer
    # Source Kconfig must include an actual default-off flag in the Sense
    # overlay, not merely a dangling C++ preprocessor name.
    tail = installer.split("config DESK_ROBOT_RGB_HEART_ENABLED", 1)[1]
    assert "default n" in tail.split("endmenu", 1)[0]
    assert "Do NOT wire yet" in plan
    assert "5V level buffer still unqualified" in plan
