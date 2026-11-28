"""Reject cold-boot Xiaozhi identity spellings the bridge cannot match."""

import pytest
from desk_robot.config import Settings, load_settings


@pytest.mark.parametrize("device_id", [" ", " head-01", "head-01 ", "head\t01", "head\n01"])
def test_device_identity_rejects_whitespace_before_runtime_start(tmp_path, device_id):
    config = tmp_path / "fleet.toml"
    config.write_text(
        'mode = "hardware"\n[[robots]]\nid = "robot-01"\n'
        'name = "Pip"\ntoken_env = "HEAD_TOKEN"\n'
    )
    robot = {"id": "robot-01", "name": "Pip", "token_env": "HEAD_TOKEN", "device_id": device_id}
    with pytest.raises(ValueError, match="device_id"):
        load_settings(config, overrides={"robots": [robot]})


@pytest.mark.parametrize("device_id", ["", "AA:BB:CC:DD:EE:FF", "head-01"])
def test_unmapped_or_exact_device_identity_is_preserved(device_id):
    settings = Settings.model_validate({"robots": [{
        "id": "robot-01", "name": "Pip", "token_env": "HEAD_TOKEN", "device_id": device_id,
    }]})
    assert settings.robots[0].device_id == device_id


def test_autostart_cannot_accept_a_padded_device_mapping():
    with pytest.raises(ValueError, match="device_id"):
        Settings.model_validate({
            "robots": [{
                "id": "robot-01", "name": "Pip", "token_env": "HEAD_TOKEN",
                "device_id": " head-01 ",
            }],
            "pet_autostart_enabled": True,
            "voice_vision_tools_enabled": True,
            "vision_model": "local-model",
        })
