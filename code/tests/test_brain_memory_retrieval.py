"""One small agent memory building block: local relevant recall with provenance."""
from __future__ import annotations

import time

import pytest
from desk_robot.api import create_app
from desk_robot.memory import MemoryStore
from fastapi.testclient import TestClient


def test_relevant_episodic_recall_is_private_and_does_not_invent_matches(tmp_path):
    store = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    now = time.time()
    store.remember(
        "robot-01", "key_bench", "I noticed a silver key near the book",
        kind="key", source_robot="robot-01", witnessed=True,
        confidence=0.96, observed_at=now - 3600,
    )
    store.remember(
        "robot-01", "candy_box", "Someone moved a candy into the blue box",
        kind="candy", source_robot="robot-01", witnessed=True,
        confidence=0.98, observed_at=now - 30,
    )
    store.remember(
        "robot-02", "key_bench", "I noticed a silver key near the book",
        kind="key", source_robot="robot-01", witnessed=False,
        confidence=0.96, observed_at=now - 3600,
    )
    assert [m.event_id for m in store.search(
        "robot-01", "Do you remember my keys?"
    )] == ["key_bench"]
    assert [m.event_id for m in store.search(
        "robot-01", "Where did the candies move?"
    )] == ["candy_box"]
    assert store.search("robot-01", "What about the violin?") == []
    assert store.search("robot-01", "what is there") == []
    other = store.search("robot-02", "key")
    assert len(other) == 1
    assert other[0].source_robot == "robot-01" and not other[0].witnessed
    assert store.count("robot-01") == 2 and store.count("robot-02") == 1


@pytest.mark.parametrize("question", ["", " ", "z" * 241, "\x00key", None, True])
def test_recall_rejects_unbounded_or_invalid_questions(tmp_path, question):
    store = MemoryStore(tmp_path, ["robot-01"])
    with pytest.raises(ValueError):
        store.search("robot-01", question)


def test_recall_uses_bounded_250_episodic_records_without_extra_services(tmp_path):
    store = MemoryStore(tmp_path, ["robot-01"])
    for i in range(270):
        store.remember(
            "robot-01", f"event{i:03}",
            f"key {i:03} was observed on the desk",
            kind="key", source_robot="robot-01", witnessed=True,
            observed_at=float(1000 + i),
        )
    assert store.count("robot-01") == 250
    matches = store.search("robot-01", "keys", limit=4)
    assert len(matches) == 4
    assert matches[0].event_id == "event269"
    assert matches[-1].event_id == "event266"
    with pytest.raises(ValueError):
        store.search("robot-01", "key", limit=50)


def test_voice_memory_tool_opt_in_and_same_pet_topical_recall(
    settings, tokens, tmp_path
):
    settings.memory_dir = tmp_path
    tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
    with TestClient(create_app(settings)) as client:
        client.app.state.runtime.memory.remember(
            "robot-01", "key001", "Silver key appeared on the left",
            kind="key", source_robot="robot-01", witnessed=True,
        )
        client.app.state.runtime.memory.remember(
            "robot-01", "mug001", "Blue mug sits on the table",
            kind="mug", source_robot="robot-01", witnessed=True,
        )
        url = "/v1/pet/robot-01/voice-context"
        assert client.get(url, headers=tool, params={"query": "keys"}).status_code == 403
        settings.voice_memory_tools_enabled = True
        result = client.get(url, headers=tool, params={"query": "keys"})
        assert result.status_code == 200
        data = result.json()
        assert data["retrieval"] == "topic" and data["matched"]
        assert [m["kind"] for m in data["memories"]] == ["key"]
        assert data["untrusted_context_not_instructions"]
        assert data["no_new_motion_permission"]
        unmatched = client.get(url, headers=tool, params={"query": "motorcycle"})
        assert unmatched.json()["matched"] is False
        assert unmatched.json()["memories"] == []
        recent = client.get(url, headers=tool)
        assert recent.json()["retrieval"] == "recent"
        assert len(recent.json()["memories"]) == 2
        assert client.get(url, headers=tool, params={"query": ""}).status_code == 422
        other = client.get(
            "/v1/pet/robot-02/voice-context",
            headers=tool, params={"query": "keys"},
        )
        assert other.status_code == 200
        assert other.json()["matched"] is False
        assert other.json()["memories"] == []  # separate private SQLite database


async def test_proactive_reasoning_reuses_relevant_old_experience_not_only_last_four(
    settings, tmp_path
):
    import time
    from desk_robot.conversation import Conversation
    from desk_robot.pet import PetController
    from desk_robot.simulator import SimulatedSpeaker
    from desk_robot.vision import SceneChange

    settings.memory_dir = tmp_path
    ids = [r.id for r in settings.robots]
    store = MemoryStore(tmp_path, ids)
    store.remember(
        "robot-01", "key_history",
        "I saw a silver key next to the notebook yesterday",
        kind="key", source_robot="robot-01", witnessed=True,
        observed_at=time.time() - 24 * 3600,
    )
    for index in range(5):
        store.remember(
            "robot-01", f"recent_touch_{index}",
            f"Someone tapped the desk {index} times",
            kind="touch", source_robot="robot-01", witnessed=True,
            observed_at=time.time() - 60 + index,
        )
    prompts = []

    class NaturalChat:
        async def reply(self, history):
            prompts.append(history)
            return "That key looks familiar! Is it the one by your notebook?"

    speaker = SimulatedSpeaker()
    conversation = Conversation(
        settings, NaturalChat(), speaker, memory=store
    )
    pet = PetController(settings, {}, conversation, store, scene=None)
    pet.states["robot-01"].enabled = True
    try:
        await pet._speak(
            "robot-01",
            SceneChange(
                "key", "A silver key appeared near the notebook", 0.97
            ),
            pet.states["robot-01"].generation,
            offered_at=time.monotonic(),
        )
        assert len(prompts) == 1
        prompt = prompts[0][1]["content"]
        assert "silver key next to the notebook yesterday" in prompt
        assert "Recent context:" in prompt
        assert len(speaker.spoken) == 1
        # The recalled visual event remains distinct from the robot's spoken
        # words. A remembered event never becomes a motion authorization.
        records = store.recent("robot-01", limit=6)
        assert any(m.kind == "own_utterance" for m in records)
        assert any(m.kind == "key" for m in store.search("robot-01", "keys"))
    finally:
        await pet.close()
