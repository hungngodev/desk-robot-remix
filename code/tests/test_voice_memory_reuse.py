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


def test_natural_polite_memory_questions_reuse_existing_scoped_tool():
    """Real ASR phrasing must not turn a private recall into a generic chat guess."""
    import importlib.util

    source = (Path(__file__).resolve().parents[1]
              / "laptop/server/overlay/desk_robot_voice_intents.py")
    spec = importlib.util.spec_from_file_location("desk_voice_memory_intents", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    topical = (
        "Could you please tell me what you remember about the blue key?",
        "Can you please remind me about the mug?",
        "What do you remember about the last experiment?",
    )
    for words in topical:
        route = module.native_readonly_request(words)
        assert route == ("voice-context", {"question": words})
        assert module.native_readonly_requests(words) == (route,)

    for words in (
        "Please tell me what you remember?",
        "Can you recall anything?",
        "Do you remember anything?",
    ):
        assert module.native_readonly_request(words) == ("voice-context", {})

    # Advice and a request to change the world never become memory reads.
    assert module.native_readonly_request("How do I remember my password?") is None
    assert module.native_readonly_request(
        "Please remember to turn on the motors"
    ) is None
