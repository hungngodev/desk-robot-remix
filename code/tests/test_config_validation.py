import os
from pathlib import Path

import pytest
from desk_robot.config import RobotConfig, Settings, load_settings, read_private_env, secret


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


@pytest.mark.parametrize("field,value", [
    ("name", ""),
    ("name", "   "),
    ("token_env", ""),
    ("token_env", "9TOKEN"),
    ("token_env", "HEAD TOKEN"),
    ("token_env", "HEAD=TOKEN"),
    ("head_url", "http://localhost:invalid"),
    ("head_url", "http://localhost:65536"),
])
def test_required_robot_values_reject_malformed_input(field, value):
    with pytest.raises(ValueError):
        RobotConfig.model_validate({**_robot(), field: value})


@pytest.mark.parametrize("field", [
    "coordinator_token_env", "tools_token_env", "speech_bridge_token_env",
])
def test_global_credential_env_names_are_identifiers(field):
    with pytest.raises(ValueError, match=field):
        Settings.model_validate({"robots": [_robot()], field: "BAD TOKEN"})


def _hardware_pair():
    return [
        {**_robot(), "head_url": "http://head-one.local:8081", "voice": "af_heart"},
        {"id": "robot-02", "name": "Dot", "token_env": "HEAD_TWO",
         "head_url": "http://head-two.local:8081", "voice": "am_adam"},
    ]


@pytest.mark.parametrize("alias", [
    "http://HEAD-ONE.local.:8081/", "https://head-one.local:443",
])
def test_hardware_head_host_cannot_be_shared(alias):
    robots = _hardware_pair()
    robots[1]["head_url"] = alias
    with pytest.raises(ValueError, match="unique head hosts"):
        Settings(robots=robots)


def test_hardware_ipv6_head_alias_cannot_be_shared():
    robots = _hardware_pair()
    robots[0]["head_url"] = "http://[fd00::1]:8081"
    robots[1]["head_url"] = "http://[fd00:0:0:0:0:0:0:1]:8081"
    with pytest.raises(ValueError, match="unique head hosts"):
        Settings(robots=robots)


def test_hardware_voices_are_distinct():
    robots = _hardware_pair()
    robots[1]["voice"] = robots[0]["voice"]
    with pytest.raises(ValueError, match="unique voices"):
        Settings(robots=robots)


def test_simulation_can_share_mock_hosts_and_voices():
    robots = _hardware_pair()
    robots[1]["head_url"] = robots[0]["head_url"]
    robots[1]["voice"] = robots[0]["voice"]
    assert len(Settings(mode="simulation", robots=robots).robots) == 2


@pytest.mark.parametrize("mode", ["hardware", "simulation"])
@pytest.mark.parametrize("alias", ["HEAD_TOKEN", "DESK_ROBOT_API_TOKEN",
                                   "DESK_ROBOT_TOOL_TOKEN", "DESK_ROBOT_SPEECH_TOKEN"])
def test_robot_token_env_cannot_alias_another_principal(mode, alias):
    robots = _hardware_pair()
    robots[1]["token_env"] = alias
    with pytest.raises(ValueError, match="unique credential environment names"):
        Settings(mode=mode, robots=robots)


def test_operator_and_tool_token_env_cannot_alias():
    with pytest.raises(ValueError, match="unique credential environment names"):
        Settings(robots=_hardware_pair(), tools_token_env="DESK_ROBOT_API_TOKEN")


@pytest.mark.parametrize("value", [None, "", "x" * 24, "x" * 31])
def test_secret_requires_at_least_32_characters(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("HEAD_TOKEN", raising=False)
    else:
        monkeypatch.setenv("HEAD_TOKEN", value)
    with pytest.raises(ValueError, match="at least 32 characters"):
        secret("HEAD_TOKEN")


def test_secret_accepts_32_character_boundary(monkeypatch):
    value = "0123456789abcdef" * 2
    monkeypatch.setenv("HEAD_TOKEN", value)
    assert secret("HEAD_TOKEN") == value


def test_hardware_omitted_defaults_remain_disarmed():
    settings = Settings(robots=_hardware_pair())
    assert settings.mode == "hardware"
    assert all(not r.motion_enabled and r.motor_backend is None for r in settings.robots)
    assert all(not r.dock_motion_qualified for r in settings.robots)
    assert not settings.voice_vision_tools_enabled
    assert not settings.fleet_text_sharing_enabled


def test_missing_private_env_allows_environment_only_startup(tmp_path):
    assert read_private_env(tmp_path / "missing.env") == {}


def test_private_env_requires_owner_only_permissions(tmp_path):
    path = tmp_path / "private.env"
    path.write_text("HEAD_TOKEN=" + "x" * 40 + "\n")
    path.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        read_private_env(path)
    path.chmod(0o600)
    assert read_private_env(path) == {"HEAD_TOKEN": "x" * 40}


def test_private_env_rejects_symlinks_and_nonregular_files(tmp_path):
    path = tmp_path / "private.env"
    path.write_text("HEAD_TOKEN=" + "x" * 40 + "\n")
    path.chmod(0o600)
    link = tmp_path / "alias.env"
    link.symlink_to(path)
    with pytest.raises(OSError):
        read_private_env(link)
    fifo = tmp_path / "fifo.env"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(ValueError, match="regular file"):
        read_private_env(fifo)


@pytest.mark.parametrize("suffix", ["BROKEN", "HEAD_TOKEN=duplicate", "BAD NAME=x", "NUL=\x00"])
def test_private_env_rejects_whole_malformed_file_without_leaking_values(tmp_path, suffix):
    path = tmp_path / "private.env"
    private = "super-private-credential-value" * 2
    path.write_text(f"HEAD_TOKEN={private}\n{suffix}\n")
    path.chmod(0o600)
    with pytest.raises(ValueError, match="malformed or duplicate") as error:
        read_private_env(path)
    assert private not in str(error.value)


def test_private_env_bounds_read_size(tmp_path):
    path = tmp_path / "private.env"
    path.write_text("HEAD_TOKEN=" + "x" * 65536)
    path.chmod(0o600)
    with pytest.raises(ValueError, match="too large"):
        read_private_env(path)


@pytest.mark.parametrize("value", ["é" * 40, "x" * 32 + "\nother", "x" * 32 + " other"])
def test_secret_rejects_non_bearer_characters_without_leaking_values(monkeypatch, value):
    monkeypatch.setenv("HEAD_TOKEN", value)
    with pytest.raises(ValueError, match="bearer token") as error:
        secret("HEAD_TOKEN")
    assert value not in str(error.value)


@pytest.mark.parametrize("field,value", [
    ("max_job_seconds", True), ("max_job_seconds", 121),
    ("max_job_seconds", float("nan")), ("max_job_seconds", float("inf")),
    ("pet_activity_min_interval_seconds", "30"),
    ("fleet_social_min_interval_seconds", 29),
])
def test_settings_numeric_limits_do_not_coerce_invalid_values(field, value):
    with pytest.raises(ValueError, match=field):
        Settings(robots=[_robot()], **{field: value})


@pytest.mark.parametrize("field,value", [
    ("dock_beacon_id", True), ("dock_beacon_id", 6),
    ("dock_forward_sign", True), ("dock_turn_sign", 0),
    ("battery_low_percent", "20"), ("handling_tilt_threshold_deg", 76),
    ("side_near_threshold_mm", 1001),
])
def test_robot_numeric_limits_do_not_coerce_invalid_values(field, value):
    with pytest.raises(ValueError):
        RobotConfig(**_robot(), **{field: value})


@pytest.mark.parametrize("field,value", [
    ("watchdog_ms", 1000), ("drive_permit_ms", 500), ("max_speed", 100),
    ("pins", {"motor": 21, "i2c": 21}),
])
def test_mac_config_cannot_override_body_safety_or_pin_assignments(field, value):
    with pytest.raises(ValueError, match=field):
        Settings(robots=[_robot()], **{field: value})
    with pytest.raises(ValueError, match=field):
        RobotConfig(**_robot(), **{field: value})


@pytest.mark.parametrize("backend", ["stepper", "guarded_dc", "unknown"])
def test_robot_rejects_unrecognized_motor_profiles(backend):
    with pytest.raises(ValueError, match="motor_backend"):
        RobotConfig(**_robot(), motor_backend=backend)


@pytest.mark.parametrize("backend", ["stepper_28byj48", "dc_pwm_guarded"])
def test_valid_motor_profile_does_not_arm_by_itself(backend):
    robot = RobotConfig(**_robot(), motor_backend=backend)
    assert robot.motor_backend == backend
    assert robot.motion_enabled is False


@pytest.mark.parametrize("url", [
    "http://@head.local:8081", "http://head.local:8081?route=x",
    "http://head.local:8081#fragment", " http://head.local:8081",
])
def test_head_url_rejects_ambiguous_route_suffixes_and_credentials(url):
    with pytest.raises(ValueError, match="head_url"):
        RobotConfig(**_robot(), head_url=url)


def test_device_id_case_aliases_are_rejected():
    robots = _hardware_pair()
    robots[0]["device_id"] = "AA:BB:CC:DD:EE:FF"
    robots[1]["device_id"] = "aa:bb:cc:dd:ee:ff"
    with pytest.raises(ValueError, match="device_id must uniquely"):
        Settings(robots=robots)

@pytest.mark.parametrize("field", ["voice_vision_tools_enabled", "unknown_setting"])
def test_configuration_error_does_not_echo_rejected_values(tmp_path, field):
    marker = "synthetic-private-value-1234"
    diagnostic = "unknown field" if field == "unknown_setting" else field
    with pytest.raises(ValueError, match=diagnostic) as error:
        load_settings(_file(tmp_path), overrides={field: marker})
    assert marker not in str(error.value)


@pytest.mark.parametrize("value", [
    "http://head.local:synthetic-private-value-1234",
    "http://[synthetic-private-value-1234]:8081",
    "http://synthetic-private-value-1234@head.local:8081",
])
def test_malformed_head_address_does_not_echo_rejected_values(value):
    for validate in (
        lambda: RobotConfig(**_robot(), head_url=value),
        lambda: Settings(robots=[{**_robot(), "head_url": value}]),
    ):
        with pytest.raises(ValueError, match="head_url") as error:
            validate()
        assert "synthetic-private-value-1234" not in str(error.value)


def test_nested_configuration_type_error_does_not_echo_rejected_values(tmp_path):
    marker = "synthetic-private-value-1234"
    path = _file(tmp_path)
    path.write_text(path.read_text() + f'\nmotion_enabled = "{marker}"\n')
    with pytest.raises(ValueError, match=r"robots\.0\.motion_enabled") as error:
        load_settings(path)
    assert marker not in str(error.value)
