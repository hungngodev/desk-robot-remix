"""Offline native video/audio probe checks; no service or robot required."""
import importlib.util
import wave
from pathlib import Path

import pytest

from desk_robot.config import load_settings

ROOT = Path(__file__).resolve().parents[1]


def smoke_module():
    spec = importlib.util.spec_from_file_location(
        "omni_duplex_smoke", ROOT / "scripts/omni_duplex_smoke.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_native_audio_probe_rejects_unencrypted_remote_voice_urls():
    probe = smoke_module()
    assert probe.server_url(
        "ws://127.0.0.1:8099/v1/realtime?duplex=1"
    ).startswith("ws://")
    assert probe.server_url(
        "wss://private.example.org/v1/realtime?duplex=1"
    ).startswith("wss://")
    for url in (
        "ws://192.168.1.10/v1/realtime?duplex=1",
        "http://127.0.0.1:8099/v1/realtime?duplex=1",
        "ws://user:secret@127.0.0.1/v1/realtime?duplex=1",
        "ws://127.0.0.1:8099/not-a-model",
    ):
        with pytest.raises(ValueError):
            probe.server_url(url)


def test_native_probe_only_accepts_real_16khz_mono_pcm(tmp_path):
    probe = smoke_module()
    path = tmp_path / "voice.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0" * 3200)
    assert len(probe.read_wav(path)) == 3200
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0" * 3200)
    with pytest.raises(ValueError):
        probe.read_wav(path)


def test_full_hardware_fleet_example_is_valid_and_disarmed():
    settings = load_settings(ROOT / "config/fleet.hardware.example.toml")
    assert settings.mode == "hardware"
    assert len(settings.robots) == 5
    assert not settings.voice_vision_tools_enabled
    assert not settings.voice_memory_tools_enabled
    assert not settings.fleet_text_sharing_enabled
    assert len({robot.id for robot in settings.robots}) == 5
    for robot in settings.robots:
        assert not robot.motion_enabled
        assert not robot.dock_motion_qualified
        assert not robot.exploration_qualified
        assert not robot.gesture_interactions_qualified


def test_legacy_hardware_example_does_not_contain_removed_unknown_flags():
    settings = load_settings(ROOT / "config/robots.example.toml")
    assert settings.mode == "hardware"
    assert settings.vision_model == ""
    assert not settings.voice_vision_tools_enabled
