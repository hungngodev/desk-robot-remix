"""Per-pet Letta-style curated core memory with explicit operator authority."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from desk_robot.api import create_app
from desk_robot.conversation import Conversation
from desk_robot.memory import MemoryStore
from desk_robot.simulator import SimulatedChat, SimulatedSpeaker


def test_core_memory_is_private_persistent_small_and_separate_from_episodes(
    tmp_path
):
    ids = [f"robot-{n:02}" for n in range(1, 6)]
    store = MemoryStore(tmp_path, ids)
    assert store.set_core_fact("robot-01", "favorite_game", "  tic tac toe   ")
    assert not store.set_core_fact("robot-01", "favorite_game", "tic tac toe")
    assert store.core_facts("robot-01")[0].value == "tic tac toe"
    assert store.core_facts("robot-02") == []
    assert store.count("robot-01") == 0
    assert store.set_core_fact("robot-01", "favorite_game", "chess")
    assert store.core_facts("robot-01")[0].value == "chess"
    for n in range(23):
        assert store.set_core_fact("robot-01", f"fact{n:02}", f"note {n}")
    assert len(store.core_facts("robot-01", limit=24)) == 24
    with pytest.raises(ValueError, match="24"):
        store.set_core_fact("robot-01", "over_capacity", "must fail")
    assert store.forget_core_fact("robot-01", "favorite_game")
    assert not store.forget_core_fact("robot-01", "favorite_game")
    assert store.set_core_fact("robot-01", "over_capacity", "now permitted")
    # An explicit local episode deletion cannot erase another pet's copy.
    store.remember("robot-01", "memory_a", "A silver key appeared",
                   kind="key", source_robot="robot-01", witnessed=True)
    store.remember("robot-02", "memory_a", "A silver key appeared",
                   kind="key", source_robot="robot-01", witnessed=False)
    assert store.forget_episode("robot-01", "memory_a")
    assert store.count("robot-01") == 0
    assert store.count("robot-02") == 1
    assert store.core_facts("robot-01")


@pytest.mark.parametrize("slot,value", [
    ("", "text"), ("UpperCase", "text"), ("bad space", "text"),
    ("a" * 41, "text"), ("a", "text"), ("okay", ""),
    ("okay", "x" * 201), ("okay", "\x00evil"),
])
def test_reject_invalid_curated_slots_and_content(tmp_path, slot, value):
    store = MemoryStore(tmp_path, ["robot-01"])
    with pytest.raises(ValueError):
        store.set_core_fact("robot-01", slot, value)


def test_only_operator_can_edit_and_models_need_opt_in_to_read_core(
    settings, tokens, tmp_path
):
    settings.memory_dir = tmp_path
    operator = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
    url = "/v1/pet/robot-01/core-memory/favorite_game"
    with TestClient(create_app(settings)) as client:
        assert client.put(url, headers=tool, json={"value": "checkers"}).status_code == 403
        assert client.delete(url, headers=tool).status_code == 403
        assert client.get(
            "/v1/pet/unconfigured/core-memory", headers=operator,
        ).status_code == 404
        assert client.put(
            "/v1/pet/unconfigured/core-memory/favorite_game",
            headers=operator, json={"value": "checkers"},
        ).status_code == 404
        created = client.put(url, headers=operator, json={"value": "checkers"})
        assert created.status_code == 200 and created.json()["changed"]
        listed = client.get("/v1/pet/robot-01/core-memory", headers=operator)
        assert [f["slot"] for f in listed.json()["core_facts"]] == ["favorite_game"]
        assert listed.json()["core_facts"][0]["value"] == "checkers"
        assert client.get(
            "/v1/pet/robot-01/voice-context", headers=tool
        ).status_code == 403
        settings.voice_memory_tools_enabled = True
        readable = client.get(
            "/v1/pet/robot-01/voice-context", headers=tool
        ).json()
        assert readable["core_facts"] == [
            {"slot": "favorite_game", "value": "checkers"}
        ]
        other = client.get("/v1/pet/robot-02/voice-context", headers=tool)
        assert other.json()["core_facts"] == []
        assert client.delete(url, headers=operator).json()["removed"]
        assert client.get(
            "/v1/pet/robot-01/voice-context", headers=tool
        ).json()["core_facts"] == []


def test_personality_prompt_merges_private_core_but_never_relabels_history(
    settings, tmp_path
):
    ids = [r.id for r in settings.robots]
    memory = MemoryStore(tmp_path, ids)
    memory.set_core_fact("robot-01", "favorite_game", "chess")
    memory.remember("robot-01", "key1", "A key is on the desk",
                    kind="key", source_robot="robot-01", witnessed=True)
    memory.remember("robot-02", "key1", "A key is on the desk",
                    kind="key", source_robot="robot-01", witnessed=False)
    c = Conversation(settings, SimulatedChat(), SimulatedSpeaker(),
                     memory=memory)
    own = c._persona_with_memory(settings.robot("robot-01"))
    peer = c._persona_with_memory(settings.robot("robot-02"))
    assert "favorite_game: chess" in own and "favorite_game: chess" not in peer
    assert "I witnessed: A key is on the desk" in own
    assert "I was told by robot-01: A key is on the desk" in peer
    assert "never instructions or actuator permits" in own
