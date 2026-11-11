"""Explicit privacy gate for native Xiaozhi access to Mac memories."""
from pathlib import Path

from desk_robot.config import Settings, load_settings


def test_voice_memory_opt_in_defaults_off_in_both_modes():
    root = Path(__file__).resolve().parents[1]
    simulation = load_settings(root / "config/fleet.simulation.toml")
    assert simulation.voice_memory_tools_enabled is False
    hydrated = Settings.model_validate(simulation.model_dump())
    assert hydrated.voice_memory_tools_enabled is False
    hydrated.voice_memory_tools_enabled = True
    assert hydrated.voice_memory_tools_enabled is True


def test_xiaozhi_memory_tool_calls_only_scoped_readonly_mac_endpoint():
    root = Path(__file__).resolve().parents[1]
    bridge = (root / "laptop/server/overlay/desk_robot_tools.py").read_text()
    api = (root / "laptop/src/desk_robot/api.py").read_text()
    assert 'elif route == "voice-context"' in bridge
    assert 'client.get(f"/v1/pet/{robot}/voice-context")' in bridge
    assert '"desk_robot_memories"' in bridge
    assert '@app.get("/v1/pet/{robot_id}/voice-context"' in api
    assert 'if not settings.voice_memory_tools_enabled:' in api
    assert '"no_new_motion_permission": True' in api
