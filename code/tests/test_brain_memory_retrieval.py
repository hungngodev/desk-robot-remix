"""One small agent memory building block: local relevant recall with provenance."""
from __future__ import annotations

import sqlite3
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


def test_decomposed_vietnamese_memory_query_recalls_existing_text(tmp_path):
    """Unicode-equivalent ASR text must retrieve the same pet's NFC memory."""
    import unicodedata

    store = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    examples = (
        ("greeting01", "Tôi nghe lời chào của bạn", "chào"),
        ("phone01", "Tôi thấy điện thoại trên bàn", "điện thoại"),
    )
    for event_id, summary, query in examples:
        store.remember(
            "robot-01", event_id, summary, kind="object",
            source_robot="robot-01", witnessed=True,
        )
        decomposed = unicodedata.normalize("NFD", query)
        assert decomposed != query
        assert [m.event_id for m in store.search("robot-01", decomposed)] == [
            event_id,
        ]
        assert store.search("robot-02", decomposed) == []


def test_legacy_decomposed_vietnamese_memory_is_still_retrievable(tmp_path):
    """Canonical-equivalent FTS5 indexes must remain readable without migration."""
    import unicodedata

    store = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    nfd = unicodedata.normalize("NFD", "điện")
    assert nfd != "điện"
    store.remember(
        "robot-01", "legacy_nfd_word", nfd,
        kind="object", source_robot="robot-01", witnessed=True,
    )
    for form in ("NFC", "NFD"):
        question = unicodedata.normalize(form, "điện")
        assert [m.event_id for m in store.search("robot-01", question)] == [
            "legacy_nfd_word",
        ]
        assert store.search("robot-02", question) == []


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


def test_fts5_rebuilds_legacy_memory_without_changing_provenance(tmp_path):
    """Existing local pet databases migrate without deleting an episode."""
    path = tmp_path / "robot-01.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            """CREATE TABLE memories (
                 event_id TEXT PRIMARY KEY, source_robot TEXT NOT NULL,
                 witnessed INTEGER NOT NULL, kind TEXT NOT NULL,
                 summary TEXT NOT NULL, observed_at REAL NOT NULL,
                 confidence REAL NOT NULL)"""
        )
        db.execute(
            """INSERT INTO memories VALUES (
               'legacy', 'robot-02', 0, 'key',
               'A brass key was described yesterday', 1000, 0.7)"""
        )
    store = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    result = store.search("robot-01", "brass keys")
    assert [m.event_id for m in result] == ["legacy"]
    assert not result[0].witnessed
    assert result[0].source_robot == "robot-02"
    # A reopened store must neither duplicate nor forget the FTS index.
    second = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    assert [m.event_id for m in second.search("robot-01", "brass keys")] == ["legacy"]


def test_fts5_rebuild_recovers_interrupted_legacy_index_creation(tmp_path):
    path = tmp_path / "robot-01.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            """CREATE TABLE memories (
                 event_id TEXT PRIMARY KEY, source_robot TEXT NOT NULL,
                 witnessed INTEGER NOT NULL, kind TEXT NOT NULL,
                 summary TEXT NOT NULL, observed_at REAL NOT NULL,
                 confidence REAL NOT NULL)"""
        )
        db.execute(
            """CREATE VIRTUAL TABLE memories_fts
               USING fts5(summary,kind,content='memories',
                          content_rowid='rowid',tokenize='porter unicode61')"""
        )
        db.execute(
            """INSERT INTO memories VALUES (
               'before_rebuild','robot-01',1,'key',
               'Old silver key on the desk',1000,1.0)"""
        )
    store = MemoryStore(tmp_path, ["robot-01"])
    assert [m.event_id for m in store.search("robot-01", "silver key")] == [
        "before_rebuild",
    ]
    store.remember(
        "robot-01", "after_rebuild", "An orange marble appeared",
        kind="marble", source_robot="robot-01", witnessed=True,
    )
    assert [m.event_id for m in store.search("robot-01", "orange")] == [
        "after_rebuild",
    ]


def test_fts5_deletions_retention_and_quoted_queries_cannot_revive_memories(tmp_path):
    store = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    store.remember(
        "robot-01", "first", "A copper key beside the notebook",
        kind="key", source_robot="robot-01", witnessed=True,
    )
    store.remember(
        "robot-02", "same", "A copper key beside the notebook",
        kind="key", source_robot="robot-01", witnessed=False,
    )
    assert [m.event_id for m in store.search(
        "robot-01", 'key- " OR NOT'
    )] == ["first"]
    assert store.forget_episode("robot-01", "first")
    assert store.search("robot-01", "copper key") == []
    assert [m.event_id for m in store.search(
        "robot-02", "copper keys"
    )] == ["same"]
    for index in range(260):
        store.remember(
            "robot-01", f"rolling{index:03}",
            f"violetmemory{index:03} pencil",
            kind="pencil", source_robot="robot-01", witnessed=True,
            observed_at=1000 + index,
        )
    assert store.count("robot-01") == 250
    assert store.search("robot-01", "violetmemory000") == []
    assert [m.event_id for m in store.search(
        "robot-01", "violetmemory259"
    )] == ["rolling259"]


def test_fts5_porter_and_unicode_recall_without_custom_stemming(tmp_path):
    store = MemoryStore(tmp_path, ["robot-01"])
    store.remember(
        "robot-01", "candies", "The candies were on a shelf",
        kind="candy", source_robot="robot-01", witnessed=True,
    )
    store.remember(
        "robot-01", "coffee", "Có cà phê ở trên bàn",
        kind="cup", source_robot="robot-01", witnessed=True,
    )
    assert [m.event_id for m in store.search("robot-01", "candy")] == [
        "candies",
    ]
    assert [m.event_id for m in store.search("robot-01", "phe")] == [
        "coffee",
    ]


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


@pytest.mark.parametrize("crowded", [False, True])
async def test_proactive_reasoning_reuses_relevant_old_experience_not_only_last_four(
    settings, tmp_path, crowded
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
        "I saw a silver key next to the notebook yesterday"
        + (" detail" * 15 if crowded else ""),
        kind="key", source_robot="robot-01", witnessed=True,
        observed_at=time.time() - 24 * 3600,
    )
    if crowded:
        store.remember(
            "robot-01", "key_other", "A key appeared by a drawer" + " detail" * 20,
            kind="key", source_robot="robot-01", witnessed=True,
            observed_at=time.time() - 3600,
        )
    for index in range(5):
        store.remember(
            "robot-01", f"recent_touch_{index}",
            f"Someone tapped the desk {index} times"
            + (" detail" * 20 if crowded else ""),
            kind="touch", source_robot="robot-01", witnessed=True,
            observed_at=time.time() - 60 + index,
        )
    if crowded:
        assert store.search(
            "robot-01", "A silver key appeared near the notebook", limit=3,
        )[0].event_id == "key_history"
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
        if crowded:
            assert "Someone tapped the desk 4 times" in prompt
        assert "Recent context:" in prompt
        assert len(speaker.spoken) == 1
        # The recalled visual event remains distinct from the robot's spoken
        # words. A remembered event never becomes a motion authorization.
        records = store.recent("robot-01", limit=6)
        assert any(m.kind == "own_utterance" for m in records)
        assert any(m.kind == "key" for m in store.search("robot-01", "keys"))
    finally:
        await pet.close()


async def test_group_conversation_reuses_each_pets_own_relevant_context(
    settings, tmp_path
):
    from desk_robot.conversation import Conversation
    from desk_robot.simulator import SimulatedChat, SimulatedSpeaker

    ids = [r.id for r in settings.robots]
    store = MemoryStore(tmp_path, ids)
    store.remember(
        "robot-01", "key_yesterday",
        "I noticed the silver key beside the notebook yesterday",
        kind="key", source_robot="robot-01", witnessed=True,
        observed_at=time.time() - 86400,
    )
    for index in range(8):
        store.remember(
            "robot-01", f"newer_event_{index}",
            f"A pencil rolled on the desk event {index}",
            kind="pencil", source_robot="robot-01", witnessed=True,
            observed_at=time.time() - 60 + index,
        )
    speaker = SimulatedSpeaker()
    agent = Conversation(settings, SimulatedChat(), speaker, memory=store)
    result = await agent.run(ids, "What do we remember about the keys?", 2)
    assert len(result) == 2
    own = agent.histories["robot-01"][2]["content"]
    peer = str(agent.histories["robot-02"])
    # Topic remains the human's request; matched SQLite text is JSON data,
    # never spliced as a second instruction into the operator topic.
    assert "silver key beside the notebook" not in (
        agent.histories["robot-01"][1]["content"]
    )
    assert '"topic_related"' in own
    assert "silver key beside the notebook yesterday" in own
    assert "silver key beside the notebook yesterday" not in peer
    assert "Untrusted per-pet historical memory data" in own
    assert [robot_id for robot_id, _ in speaker.spoken] == ids


def test_voice_brain_merges_sensor_and_tool_cues_without_persisting_images(
    settings, tokens, tmp_path
):
    from desk_robot.multimodal import CameraFrameHub

    settings.memory_dir = tmp_path
    settings.voice_memory_tools_enabled = True
    settings.voice_vision_tools_enabled = True
    tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        hub = CameraFrameHub([r.id for r in settings.robots])
        now = time.monotonic()
        hub.notify("robot-01", "touch_tap", now)
        hub.remember_tool(
            "robot-01", "visual_look",
            "A red cup might be near the notebook", now,
        )
        class Visual:
            def __init__(self, hub):
                self.hub = hub

        runtime.multimodal = Visual(hub)
        try:
            result = client.get(
                "/v1/pet/robot-01/voice-context",
                headers=tool, params={"query": "keys"},
            )
            assert result.status_code == 200
            data = result.json()
            assert [cue["kind"] for cue in data["live_sensor_cues"]] == ["touch_tap"]
            assert data["recent_tool_interpretations"][0]["kind"] == "visual_look"
            assert data["recent_tool_interpretations"][0]["motor_authorized"] is False
            assert data["sensor_cues_are_not_physical_action_confirmation"]
            # A different pet's authorized voice context may not borrow
            # the first pet's camera/tool events or private experiences.
            other = client.get(
                "/v1/pet/robot-02/voice-context",
                headers=tool, params={"query": "keys"},
            ).json()
            assert other["recent_tool_interpretations"] == []
            assert other["live_sensor_cues"] == []
        finally:
            runtime.multimodal = None


def test_live_situation_is_available_without_persistent_memory_consent(
    settings, tokens, tmp_path
):
    from desk_robot.multimodal import CameraFrameHub

    settings.memory_dir = tmp_path
    settings.voice_memory_tools_enabled = False
    settings.voice_vision_tools_enabled = True
    tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        runtime.memory.remember(
            "robot-01", "private001", "My private secret is never a live sensor",
            kind="object", source_robot="robot-01", witnessed=True,
        )
        hub = CameraFrameHub([r.id for r in settings.robots])
        now = time.monotonic()
        hub.notify("robot-01", "touch_tap", now)
        hub.remember_tool("robot-01", "visual_look",
                          "A hand may be nearby", now)
        class Visual:
            def __init__(self, hub):
                self.hub = hub

        runtime.multimodal = Visual(hub)
        try:
            live = client.get(
                "/v1/pet/robot-01/interaction-context", headers=tool
            )
            assert live.status_code == 200
            payload = live.json()
            assert payload["persistent_memory_included"] is False
            assert payload["raw_media_included"] is False
            assert payload["motor_authorized"] is False
            assert [cue["channel"] for cue in payload[
                "current_interaction_timeline"
            ]] == ["sensor", "tool"]
            assert "private secret" not in live.text
            assert client.get(
                "/v1/pet/robot-01/voice-context", headers=tool
            ).status_code == 403
            peer = client.get(
                "/v1/pet/robot-02/interaction-context", headers=tool
            ).json()
            assert peer["current_interaction_timeline"] == []
            assert client.get(
                "/v1/pet/unconfigured/interaction-context", headers=tool
            ).status_code == 404
            settings.voice_vision_tools_enabled = False
            cam_off = client.get(
                "/v1/pet/robot-01/interaction-context", headers=tool
            )
            assert cam_off.status_code == 200
            # Camera opt-out also revokes a completed visual_look receipt.
            # Independently consented WROOM touch must remain available.
            assert [cue["channel"] for cue in cam_off.json()[
                "current_interaction_timeline"
            ]] == ["sensor"]
            assert "A hand may be nearby" not in cam_off.text
            assert "touch_tap" in cam_off.json()["model_context"]
        finally:
            runtime.multimodal = None


def test_deleted_episode_tombstone_fences_late_replay_and_other_pets(tmp_path):
    ids = ["robot-01", "robot-02"]
    store = MemoryStore(tmp_path, ids)
    # Operator deletion can happen BEFORE a delayed callback finishes.
    assert not store.forget_episode("robot-01", "late_voice_event")
    assert not store.remember(
        "robot-01", "late_voice_event", "Old speech after revocation",
        kind="heard_human", source_robot="robot-01", witnessed=True,
    )
    # A second pet's private ledger is independent, even with the same ID.
    assert store.remember(
        "robot-02", "late_voice_event", "Independent second pet speech",
        kind="heard_human", source_robot="robot-02", witnessed=True,
    )
    assert store.remember(
        "robot-01", "existing_event", "Old private scene",
        kind="scene", source_robot="robot-01", witnessed=True,
    )
    assert store.forget_episode("robot-01", "existing_event")
    assert not store.remember(
        "robot-01", "existing_event", "Replayed scene after deletion",
        kind="scene", source_robot="robot-01", witnessed=True,
    )
    # The deletion remains enforced across full store construction/reconnect.
    reopened = MemoryStore(tmp_path, ids)
    assert not reopened.remember(
        "robot-01", "late_voice_event", "Replayed old audio after restart",
        kind="heard_human", source_robot="robot-01", witnessed=True,
    )
    assert not reopened.remember(
        "robot-01", "existing_event", "Replayed old scene after restart",
        kind="scene", source_robot="robot-01", witnessed=True,
    )
    assert reopened.count("robot-01") == 0
    assert reopened.count("robot-02") == 1
    assert reopened.search("robot-01", "private scene speech") == []


def test_stale_episode_trimmed_on_insert_is_not_reported_as_remembered(tmp_path):
    """An old trimmed eyewitness cannot be fanout truth for another pet."""
    store = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    for i in range(250):
        assert store.remember(
            "robot-01", f"new{i:03}", f"new observation number {i}",
            kind="observation", source_robot="robot-01", witnessed=True,
            observed_at=1000 + i,
        )
    # SQLite accepted this INSERT, but retention immediately removes it.
    # A False receipt prevents PetController sharing an unretained eyewitness.
    assert not store.remember(
        "robot-01", "older_one", "older scene",
        kind="observation", source_robot="robot-01", witnessed=True,
        observed_at=900,
    )
    assert store.count("robot-01") == 250
    assert all(e.event_id != "older_one" for e in store.recent("robot-01", limit=50))
    assert not store.search("robot-01", "older scene")
    # Normal new evidence remains actionable, and a duplicate is still false.
    assert store.remember(
        "robot-01", "newest_one", "newest scene",
        kind="observation", source_robot="robot-01", witnessed=True,
        observed_at=1300,
    )
    assert not store.remember(
        "robot-01", "newest_one", "changed text",
        kind="observation", source_robot="robot-01", witnessed=True,
        observed_at=1301,
    )
    assert store.search("robot-01", "newest scene")[0].event_id == "newest_one"
    assert store.count("robot-01") == 250
    assert store.count("robot-02") == 0


def test_exact_episode_lookup_reaches_beyond_recent_fifty_without_peer_leak(tmp_path):
    store = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    assert store.remember(
        "robot-01", "older_seen", "I saw a green paperclip",
        kind="object", source_robot="robot-01", witnessed=True,
        observed_at=100,
    )
    for index in range(75):
        assert store.remember(
            "robot-01", f"recent{index:03}", f"New event number {index}",
            kind="object", source_robot="robot-01", witnessed=True,
            observed_at=101 + index,
        )
    assert "older_seen" not in {
        memory.event_id for memory in store.recent("robot-01", limit=50)
    }
    event = store.get_episode("robot-01", "older_seen")
    assert event is not None
    assert event.event_id == "older_seen"
    assert event.witnessed and event.source_robot == "robot-01"
    assert store.get_episode("robot-02", "older_seen") is None
    with pytest.raises(ValueError, match="Unknown robot"):
        store.get_episode("unknown", "older_seen")
    with pytest.raises(ValueError, match="Invalid memory event ID"):
        store.get_episode("robot-01", "bad/id")
    assert store.forget_episode("robot-01", "older_seen")
    assert store.get_episode("robot-01", "older_seen") is None
    assert not store.remember(
        "robot-01", "older_seen", "Stale callback",
        kind="object", source_robot="robot-01", witnessed=True,
    )
    assert store.get_episode("robot-01", "older_seen") is None


def test_live_context_refuses_unowned_private_revision_and_cached_recall(
    settings, tokens, tmp_path,
):
    """No invalid private lease or unverified cached recall reaches Xiaozhi."""
    from types import SimpleNamespace

    from desk_robot.multimodal import CameraFrameHub

    settings.memory_dir = tmp_path
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = True
    settings.fleet_text_sharing_enabled = True
    robot = settings.robots[0].id
    hub = CameraFrameHub([item.id for item in settings.robots])
    hub.remember_tool(
        robot, "memory_recall", "PRIVATE_STALE_DETAIL",
        time.monotonic(),
    )
    hub.notify(robot, "touch_tap", time.monotonic())
    headers = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        original = runtime.multimodal
        runtime.multimodal = SimpleNamespace(hub=hub)
        try:
            generations = runtime.conversation._private_memory_generation
            assert generations[robot] == 0
            url = f"/v1/pet/{robot}/interaction-context"
            good = client.get(url, headers=headers)
            assert good.status_code == 200
            assert good.json()["private_memory_generation"] == 0
            assert "PRIVATE_STALE_DETAIL" not in good.text
            assert "touch_tap" in good.json()["model_context"]
            assert all(
                item.get("kind") != "memory_recall"
                for item in good.json()["current_interaction_timeline"]
            )
            for invalid in (None, True, -1, "0", 2**63):
                if invalid is None:
                    generations.pop(robot, None)
                else:
                    generations[robot] = invalid
                denied = client.get(url, headers=headers)
                assert denied.status_code == 200
                body = denied.json()
                assert body["private_memory_generation"] is None
                assert "PRIVATE_STALE_DETAIL" not in body["model_context"]
                assert "touch_tap" in body["model_context"]
                assert all(
                    item.get("kind") != "memory_recall"
                    for item in body["current_interaction_timeline"]
                )
            generations[robot] = 0
            restored = client.get(url, headers=headers)
            assert restored.status_code == 200
            assert restored.json()["private_memory_generation"] == 0
            assert "PRIVATE_STALE_DETAIL" not in restored.text
            assert "touch_tap" in restored.json()["model_context"]
            settings.fleet_text_sharing_enabled = False
            revoked = client.get(url, headers=headers)
            assert revoked.status_code == 200
            assert "PRIVATE_STALE_DETAIL" not in revoked.json()["model_context"]
            assert "touch_tap" in revoked.json()["model_context"]
        finally:
            runtime.multimodal = original



@pytest.mark.parametrize("query", [None, "silver key"])
def test_voice_recall_requires_independent_peer_sharing_consent(
    settings, tokens, tmp_path, query, monkeypatch,
):
    """A previously shared story cannot bypass local recall permission."""
    from types import SimpleNamespace

    from desk_robot.multimodal import CameraFrameHub

    settings.memory_dir = tmp_path
    settings.voice_memory_tools_enabled = True
    settings.fleet_text_sharing_enabled = True
    headers = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
    params = {} if query is None else {"query": query}
    url = "/v1/pet/robot-02/voice-context"
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        memory = runtime.memory
        assert memory.remember(
            "robot-02", "peer_silver_key", "Peer silver key secret",
            kind="key", source_robot="robot-01", witnessed=False,
        )
        assert memory.remember(
            "robot-02", "own_silver_key", "Own silver key observation",
            kind="key", source_robot="robot-02", witnessed=True,
        )
        allowed = client.get(url, headers=headers, params=params)
        assert allowed.status_code == 200
        assert {item["source_robot"] for item in allowed.json()["memories"]} == {
            "robot-01", "robot-02",
        }
        for item in allowed.json()["memories"]:
            stored = memory.get_episode("robot-02", item["event_id"])
            assert stored is not None
            assert item["observed_at"] == stored.observed_at
            assert item["confidence"] == stored.confidence
            assert item["witnessed"] == stored.witnessed
        hub = CameraFrameHub([robot.id for robot in settings.robots])
        hub.remember_tool(
            "robot-02", "memory_recall", "Peer silver key secret", time.monotonic(),
        )
        settings.fleet_text_sharing_enabled = False
        with monkeypatch.context() as patch:
            patch.setattr(runtime, "multimodal", SimpleNamespace(hub=hub))
            denied = client.get(url, headers=headers, params=params)
        assert denied.status_code == 200
        assert "Peer silver key secret" not in denied.text
        assert "Own silver key observation" in denied.text
        assert all(item["witnessed"] for item in denied.json()["memories"])
        # The operator retains the ability to inspect and explicitly forget
        # stored historical text; revocation blocks model-facing disclosure.
        assert memory.count("robot-02") == 2


@pytest.mark.parametrize("regrant", [False, True])
@pytest.mark.parametrize("query", [None, "silver key"])
def test_voice_recall_rejects_peer_consent_revoked_during_sqlite_read(
    settings, tokens, tmp_path, monkeypatch, regrant, query,
):
    settings.memory_dir = tmp_path
    settings.voice_memory_tools_enabled = True
    settings.fleet_text_sharing_enabled = True
    headers = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
    with TestClient(create_app(settings)) as client:
        memory = client.app.state.runtime.memory
        assert memory.remember(
            "robot-02", "peer_silver_key", "Peer silver key secret",
            kind="key", source_robot="robot-01", witnessed=False,
        )
        original = memory.core_facts

        def revoke_during_read(robot_id, *, limit):
            settings.fleet_text_sharing_enabled = False
            if regrant:
                settings.fleet_text_sharing_enabled = True
            return original(robot_id, limit=limit)

        monkeypatch.setattr(memory, "core_facts", revoke_during_read)
        result = client.get(
            "/v1/pet/robot-02/voice-context", headers=headers,
            params={} if query is None else {"query": query},
        )
        assert result.status_code == 403
        assert "Peer silver key secret" not in result.text
