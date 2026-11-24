from pathlib import Path

import pytest
from desk_robot.config import RobotConfig, Settings, load_settings


def _robot():
    return {"id": "robot-01", "name": "Pip", "token_env": "HEAD_TOKEN"}


def _file(tmp_path):
    path = tmp_path / "robots.toml"
    path.write_text(
        'mode = "hardware"\nvoice_vision_tools_enabled = true\n'
        'vision_weights = "file.weights"\n[[robots]]\n'
        'id = "robot-01"\nname = "Pip"\ntoken_env = "HEAD_TOKEN"\n'
    )
    return path


@pytest.mark.parametrize("field", ["id", "name", "token_env"])
def test_robot_required_fields_are_validated(field):
    robot = _robot()
    del robot[field]
    with pytest.raises(ValueError, match=field):
        Settings.model_validate({"robots": [robot]})


@pytest.mark.parametrize("value", [0, 1, "yes", "false"])
@pytest.mark.parametrize("field", ["motion_enabled", "exploration_qualified"])
def test_robot_flags_require_explicit_booleans(field, value):
    with pytest.raises(ValueError, match=field):
        RobotConfig.model_validate({**_robot(), field: value})


@pytest.mark.parametrize("value", [0, 1, "yes", "false"])
@pytest.mark.parametrize("field", ["voice_vision_tools_enabled", "fleet_text_sharing_enabled"])
def test_settings_flags_require_explicit_booleans(field, value):
    with pytest.raises(ValueError, match=field):
        Settings.model_validate({"robots": [_robot()], field: value})


def test_runtime_flag_rejection_preserves_consent_epoch():
    settings = Settings.model_validate({"robots": [_robot()]})
    generation = settings.camera_consent_generation
    with pytest.raises(ValueError, match="voice_vision_tools_enabled"):
        settings.voice_vision_tools_enabled = "false"
    assert settings.voice_vision_tools_enabled is False
    assert settings.camera_consent_generation == generation
    settings.voice_vision_tools_enabled = True
    with pytest.raises(ValueError, match="voice_vision_tools_enabled"):
        settings.voice_vision_tools_enabled = 0
    assert settings.voice_vision_tools_enabled is True
    assert settings.camera_consent_generation == generation
    settings.voice_vision_tools_enabled = False
    assert settings.camera_consent_generation == generation + 1
    with pytest.raises(ValueError, match="motion_enabled"):
        settings.robots[0].motion_enabled = "yes"
    assert settings.robots[0].motion_enabled is False


def test_local_runtime_override_takes_precedence(tmp_path):
    path = _file(tmp_path)
    original = path.read_bytes()
    settings = load_settings(path, overrides={
        "voice_vision_tools_enabled": False,
        "vision_weights": Path("runtime.weights"),
    })
    assert settings.voice_vision_tools_enabled is False
    assert settings.camera_consent_started_at == 0
    assert settings.vision_weights == (tmp_path / "runtime.weights").resolve()
    assert settings.robots[0].id == "robot-01"
    assert path.read_bytes() == original
    assert load_settings(path).voice_vision_tools_enabled is True


@pytest.mark.parametrize("overrides", [
    {"voice_vision_tools_enabled": "false"},
    {"room_station_context_enabled": True},
    {"robots": []},
    {"unknown_setting": False},
])
def test_runtime_overrides_are_validated_before_use(tmp_path, overrides):
    with pytest.raises(ValueError):
        load_settings(_file(tmp_path), overrides=overrides)


def test_toml_string_cannot_enable_camera(tmp_path):
    path = _file(tmp_path)
    path.write_text(path.read_text().replace('voice_vision_tools_enabled = true',
                                             'voice_vision_tools_enabled = "yes"'))
    with pytest.raises(ValueError, match="voice_vision_tools_enabled"):
        load_settings(path)
