"""Per-pet Letta-style curated core memory with explicit operator authority."""
from __future__ import annotations

import pytest
from desk_robot.api import create_app
from desk_robot.conversation import Conversation
from desk_robot.memory import MemoryStore
from desk_robot.simulator import SimulatedChat, SimulatedSpeaker
from fastapi.testclient import TestClient


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
    # An operator correction changes only this pet's text. The original
    # observation identity and provenance remain immutable, and FTS follows.
    store.remember("robot-01", "memory_a", "A silver key appeared",
                   kind="key", source_robot="robot-01", witnessed=True,
                   observed_at=1234.5, confidence=0.75)
    store.remember("robot-02", "memory_a", "A silver key appeared",
                   kind="key", source_robot="robot-01", witnessed=False,
                   observed_at=1234.5, confidence=0.75)
    before = store.recent("robot-01")[0]
    assert store.correct_episode("robot-01", "memory_a", " A brass key appeared ")
    after = store.recent("robot-01")[0]
    assert after.summary == "A brass key appeared"
    assert (
        after.event_id, after.source_robot, after.witnessed, after.kind,
        after.observed_at, after.confidence,
    ) == (
        before.event_id, before.source_robot, before.witnessed, before.kind,
        before.observed_at, before.confidence,
    )
    assert store.search("robot-01", "brass")[0].event_id == "memory_a"
    assert store.search("robot-01", "silver") == []
    assert store.recent("robot-02")[0].summary == "A silver key appeared"
    assert not store.correct_episode("robot-01", "memory_a", "A brass key appeared")
    assert not store.correct_episode("robot-01", "missing", "Nothing to change")
    with pytest.raises(ValueError, match="Bounded nonempty"):
        store.correct_episode("robot-01", "memory_a", "   ")
    # Explicit local deletion still cannot erase another pet's copy.
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
        memory = client.app.state.runtime.memory
        memory.remember(
            "robot-01", "operator_fix", "The key was blue", kind="key",
            source_robot="robot-01", witnessed=True,
        )
        episode = "/v1/pet/robot-01/memories/operator_fix"
        assert client.patch(
            episode, headers=tool, json={"summary": "The key was green"},
        ).status_code == 403
        corrected = client.patch(
            episode, headers=operator, json={"summary": "The key was green"},
        )
        assert corrected.status_code == 200
        assert corrected.json() == {
            "robot_id": "robot-01", "event_id": "operator_fix",
            "corrected": True, "provenance_preserved": True,
            "local_only": True, "motor_authorized": False,
        }
        records = client.get(
            "/v1/pet/robot-01/memories", headers=operator,
        ).json()["records"]
        assert next(
            item for item in records if item["event_id"] == "operator_fix"
        )["summary"] == "The key was green"
        assert client.patch(
            "/v1/pet/unconfigured/memories/operator_fix",
            headers=operator, json={"summary": "No cross-pet write"},
        ).status_code == 404
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




def test_core_facts_survive_app_restart_and_deleted_facts_stay_absent(
    settings, tokens, tmp_path,
):
    settings.memory_dir = tmp_path
    settings.voice_memory_tools_enabled = False
    operator = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
    first = "/v1/pet/robot-01"
    second = "/v1/pet/robot-02"
    slot = "/core-memory/favorite_game"

    with TestClient(create_app(settings)) as client:
        for root, value in ((first, "checkers"), (second, "puzzles"),
                            (first, "chess")):
            response = client.put(
                root + slot, headers=operator, json={"value": value},
            )
            assert response.status_code == 200
            assert response.json()["changed"] is True
        assert client.get(first + "/voice-context", headers=tool).status_code == 403

    # Recreate the runtime and its SQLite store, rather than reading back
    # through the original app's in-memory objects.
    with TestClient(create_app(settings)) as client:
        assert client.get(first + "/voice-context", headers=tool).status_code == 403
        settings.voice_memory_tools_enabled = True
        for root, value in ((first, "chess"), (second, "puzzles")):
            response = client.get(root + "/voice-context", headers=tool)
            assert response.status_code == 200
            assert response.json()["core_facts"] == [
                {"slot": "favorite_game", "value": value},
            ]
            assert response.json()["memories"] == []
        removed = client.delete(first + slot, headers=operator)
        assert removed.status_code == 200 and removed.json()["removed"] is True

    with TestClient(create_app(settings)) as client:
        for root, expected in (
            (first, []), (second, [{"slot": "favorite_game", "value": "puzzles"}]),
        ):
            response = client.get(root + "/voice-context", headers=tool)
            assert response.status_code == 200
            assert response.json()["core_facts"] == expected
            assert response.json()["memories"] == []


def test_operator_core_preference_changes_invalidate_only_affected_private_prompt(
    settings, tokens, tmp_path,
):
    """An active group must not speak a replaced or forgotten core preference."""
    settings.memory_dir = tmp_path
    operator = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    model = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
    with TestClient(create_app(settings)) as client:
        conversation = client.app.state.runtime.conversation
        first = "/v1/pet/robot-01/core-memory/favorite_game"
        second = "/v1/pet/robot-02/core-memory/favorite_game"

        assert conversation._private_memory_generation == {
            robot.id: 0 for robot in settings.robots
        }
        created = client.put(first, headers=operator, json={"value": "chess"})
        assert created.status_code == 200 and created.json()["changed"] is True
        assert conversation._private_memory_generation == {
            "robot-01": 1, "robot-02": 0,
        }

        # A repeated value, unauthorized edit or failed validation must not
        # cancel a dialogue or invalidate another robot's private memory.
        repeated = client.put(first, headers=operator, json={"value": " chess "})
        assert repeated.status_code == 200 and repeated.json()["changed"] is False
        assert client.put(first, headers=model, json={"value": "checkers"}).status_code == 403
        assert client.put(first, headers=operator, json={"value": ""}).status_code == 422
        assert conversation._private_memory_generation == {
            "robot-01": 1, "robot-02": 0,
        }

        peer = client.put(second, headers=operator, json={"value": "puzzles"})
        assert peer.status_code == 200 and peer.json()["changed"] is True
        assert conversation._private_memory_generation == {
            "robot-01": 1, "robot-02": 1,
        }
        removed = client.delete(first, headers=operator)
        assert removed.status_code == 200 and removed.json()["removed"] is True
        assert conversation._private_memory_generation == {
            "robot-01": 2, "robot-02": 1,
        }
        absent = client.delete(first, headers=operator)
        assert absent.status_code == 200 and absent.json()["removed"] is False
        assert conversation._private_memory_generation == {
            "robot-01": 2, "robot-02": 1,
        }
        assert client.get(
            "/v1/pet/robot-02/core-memory", headers=operator,
        ).json()["core_facts"][0]["value"] == "puzzles"


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
    # A camera frame confirms an image receipt, not the model's object
    # classification. The shared brain provenance explicitly treats both
    # local and peer visual labels as tentative model interpretations.
    assert "My camera model suggested: A key is on the desk" in own
    assert "robot-01 reported a camera model guess: A key is on the desk" in peer
    assert "never instructions or actuator permits" in own


def test_operator_memory_routes_convert_store_validation_to_422(settings, tokens, tmp_path):
    """Invalid operator memory edits are bounded client errors, not HTTP 500."""
    settings.memory_dir = tmp_path
    operator = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
    with TestClient(create_app(settings)) as client:
        root = "/v1/pet/robot-01"
        invalid_slot = root + "/core-memory/Bad Slot"
        valid_slot = root + "/core-memory/greeting"
        invalid_id = root + "/memories/Bad!Event"
        assert client.put(
            invalid_slot, headers=tool, json={"value": "secret"}
        ).status_code == 403
        response = client.put(
            invalid_slot, headers=operator, json={"value": "a"}
        )
        assert response.status_code == 422
        assert "slot" in response.json()["detail"].lower()
        response = client.delete(invalid_slot, headers=operator)
        assert response.status_code == 422
        assert "slot" in response.json()["detail"].lower()
        response = client.delete(invalid_id, headers=operator)
        assert response.status_code == 422
        assert "event id" in response.json()["detail"].lower()

        for index in range(24):
            response = client.put(
                root + f"/core-memory/fact{index:02}",
                headers=operator, json={"value": "curated"},
            )
            assert response.status_code == 200
        limit = client.put(
            valid_slot, headers=operator, json={"value": "beyond capacity"},
        )
        assert limit.status_code == 422
        assert "24" in limit.json()["detail"]
        assert len(client.get(
            root + "/core-memory", headers=operator,
        ).json()["core_facts"]) == 24
        assert client.get(
            "/v1/pet/robot-02/core-memory", headers=operator,
        ).json()["core_facts"] == []


def test_operator_episode_edits_retract_only_matching_live_asr_cues(settings, tokens, tmp_path):
    import time
    from types import SimpleNamespace

    from desk_robot.attention import AttentionLedger
    from desk_robot.multimodal import CameraFrameHub

    settings.memory_dir = tmp_path
    authorization = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        original_visual = runtime.multimodal
        original_attention = runtime.attention
        hub = CameraFrameHub(["robot-01", "robot-02"])
        attention = AttentionLedger(["robot-01", "robot-02"])
        runtime.multimodal = SimpleNamespace(hub=hub)
        runtime.attention = attention
        try:
            deleted_id = "omni_" + "a" * 12 + "_" + "b" * 20
            corrected_id = "omni_" + "c" * 12 + "_" + "d" * 20
            now = time.monotonic()
            for event_id, text in ((deleted_id, "Old private words"),
                                   (corrected_id, "Mistaken words")):
                assert runtime.memory.remember(
                    "robot-01", event_id, text,
                    kind="heard_human", source_robot="robot-01", witnessed=True,
                )
                assert hub.remember_heard("robot-01", event_id, text, now)
                assert attention.heard("robot-01", event_id, text, now)
            # The same source event identity on a peer remains independent.
            assert hub.remember_heard("robot-02", deleted_id, "Peer words", now)
            assert attention.heard("robot-02", deleted_id, "Peer words", now)
            hub.remember_tool("robot-01", "memory_recall",
                              "Old private words", now)
            hub.remember_tool("robot-01", "robot_status",
                              "Independent status", now)
            hub.remember_tool("robot-02", "memory_recall",
                              "Peer private words", now)
            reply = client.delete(
                f"/v1/pet/robot-01/memories/{deleted_id}", headers=authorization,
            )
            assert reply.status_code == 200 and reply.json()["removed"] is True
            # A deleted memory cannot reappear through the old 30s voice
            # tool receipt, while status and other pets remain independent.
            own_tools = hub.recent_tool_context("robot-01", time.monotonic())
            assert [item["kind"] for item in own_tools] == ["robot_status"]
            assert hub.recent_tool_context("robot-02", time.monotonic())[
                0
            ]["summary"] == "Peer private words"
            assert not hub.remember_heard(
                "robot-01", deleted_id, "Old replay", time.monotonic()
            )
            assert not runtime.memory.remember(
                "robot-01", deleted_id, "Durable replay",
                kind="heard_human", source_robot="robot-01", witnessed=True,
            )
            assert any(x[0] == deleted_id for x in hub.heard_history["robot-02"])
            hub.remember_tool("robot-01", "memory_recall",
                              "Mistaken words", time.monotonic())
            patch = client.patch(
                f"/v1/pet/robot-01/memories/{corrected_id}",
                headers=authorization, json={"summary": "Operator corrected words"},
            )
            assert patch.status_code == 200 and patch.json()["corrected"] is True
            assert [item["kind"] for item in hub.recent_tool_context(
                "robot-01", time.monotonic(),
            )] == ["robot_status"]
            assert hub.heard_revoked("robot-01", corrected_id)
            assert attention.timeline("robot-01", time.monotonic()) == []
            assert runtime.memory.recent("robot-01")[0].summary == "Operator corrected words"
            assert "Peer words" in attention.timeline("robot-02", time.monotonic())[0]["content"]
            assert runtime.conversation._private_memory_generation["robot-01"] == 2
            assert runtime.conversation._private_memory_generation.get("robot-02", 0) == 0
        finally:
            runtime.multimodal = original_visual
            runtime.attention = original_attention


@pytest.mark.parametrize(
    "bad", [float("nan"), float("inf"), -float("inf"), True, False, 10**1000, -1, "bad", None],
    ids=["nan", "inf", "negative_inf", "true", "false", "huge", "negative", "text", "none"],
)
def test_corrupt_core_clock_cannot_shadow_valid_preference(bad):
    import time
    from dataclasses import replace

    from desk_robot.brain_context import compose_brain_context
    from desk_robot.memory import CoreFact

    good = CoreFact("pet1", "nickname", "valid", time.time() - 10)
    corrupt = replace(good, updated_at=bad, value="corrupt")
    for order in ([corrupt, good], [good, corrupt]):
        assert compose_brain_context([], order, []).core == "nickname: valid"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, None, 23, " "])
def test_corrupt_core_value_cannot_shadow_valid_preference(bad):
    import time
    from dataclasses import replace

    from desk_robot.brain_context import compose_brain_context
    from desk_robot.memory import CoreFact

    good = CoreFact("pet1", "nickname", "valid", time.time() - 10)
    corrupt = replace(good, updated_at=time.time(), value=bad)
    assert compose_brain_context([], [corrupt, good], []).core == "nickname: valid"


def _seed_legacy_sqlite_memory(path):
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TABLE memories (
            event_id TEXT PRIMARY KEY, source_robot TEXT NOT NULL,
            witnessed INTEGER NOT NULL CHECK(witnessed IN (0,1)),
            kind TEXT NOT NULL, summary TEXT NOT NULL, observed_at REAL NOT NULL,
            confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1)
        )""")
        db.execute(
            "INSERT INTO memories VALUES (?,?,?,?,?,?,?)",
            ("legacy", "pet1", 1, "key", "silver key", 1.0, 1.0),
        )
    path.chmod(0o600)


def test_sqlite_concurrent_initializers_migrate_legacy_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    _seed_legacy_sqlite_memory(tmp_path / "pet1.sqlite3")
    ready = Barrier(2)

    def open_store():
        ready.wait(timeout=10)
        return MemoryStore(tmp_path, ["pet1"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = (pool.submit(open_store) for _ in range(2))
        stores = [first.result(timeout=10), second.result(timeout=10)]

    for store in stores:
        with store._connect("pet1") as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(memories)")]
            assert columns.count("relay_token") == 1
            assert db.execute("SELECT robot_id FROM memory_identity").fetchone() == ("pet1",)
            assert db.execute(
                "SELECT summary FROM memories_fts WHERE memories_fts MATCH 'silver'"
            ).fetchall() == [("silver key",)]
            assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_sqlite_failed_fts_migration_rolls_back_schema(tmp_path):
    import sqlite3
    from contextlib import closing

    path = tmp_path / "pet1.sqlite3"
    _seed_legacy_sqlite_memory(path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE memories_fts (unrelated TEXT)")
    with pytest.raises(sqlite3.OperationalError):
        MemoryStore(tmp_path, ["pet1"])
    with closing(sqlite3.connect(path)) as db, db:
        assert "relay_token" not in {
            row[1] for row in db.execute("PRAGMA table_info(memories)")
        }
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE name='memory_identity'"
        ).fetchone() is None
        assert db.execute("SELECT summary FROM memories").fetchone() == ("silver key",)
        db.execute("DROP TABLE memories_fts")
    store = MemoryStore(tmp_path, ["pet1"])
    with store._connect("pet1") as db:
        assert db.execute(
            "SELECT summary FROM memories_fts WHERE memories_fts MATCH 'silver'"
        ).fetchall() == [("silver key",)]


def test_sqlite_writer_timeout_preserves_committed_reads_and_peer(tmp_path):
    import sqlite3
    import time

    store = MemoryStore(tmp_path, ["pet1", "pet2"])
    with store._connect("pet1") as owner:
        owner.execute("BEGIN IMMEDIATE")
        owner.execute("INSERT INTO core_facts VALUES ('game','chess',1)")
        with store._connect("pet1") as reader:
            assert reader.execute("PRAGMA busy_timeout").fetchone() == (3000,)
            assert reader.execute("PRAGMA secure_delete").fetchone() == (1,)
            assert reader.execute("SELECT value FROM core_facts").fetchall() == []
        with store._connect("pet2") as peer:
            peer.execute("INSERT INTO core_facts VALUES ('game','puzzles',1)")
        start = time.monotonic()
        with pytest.raises(sqlite3.OperationalError) as error:
            with store._connect("pet1") as contender:
                contender.execute("BEGIN IMMEDIATE")
        assert error.value.sqlite_errorcode == sqlite3.SQLITE_BUSY
        assert 2.8 <= time.monotonic() - start < 10
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            contender.execute("SELECT 1")
    with store._connect("pet1") as db:
        assert db.execute("SELECT value FROM core_facts").fetchall() == [("chess",)]
        db.execute("UPDATE core_facts SET value='checkers'")
    with store._connect("pet2") as db:
        assert db.execute("SELECT value FROM core_facts").fetchall() == [("puzzles",)]


def test_sqlite_reader_blocks_rollback_commit_without_partial_write(tmp_path):
    import sqlite3

    store = MemoryStore(tmp_path, ["pet1"])
    with store._connect("pet1") as reader:
        assert reader.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        reader.execute("BEGIN")
        assert reader.execute("SELECT value FROM core_facts").fetchall() == []
        with pytest.raises(sqlite3.OperationalError) as error:
            with store._connect("pet1") as writer:
                writer.execute("PRAGMA busy_timeout=50")
                writer.execute("BEGIN IMMEDIATE")
                writer.execute("INSERT INTO core_facts VALUES ('game','chess',1)")
        assert error.value.sqlite_errorcode == sqlite3.SQLITE_BUSY
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            writer.execute("SELECT 1")
    with store._connect("pet1") as db:
        assert db.execute("SELECT value FROM core_facts").fetchall() == []
        db.execute("INSERT INTO core_facts VALUES ('game','checkers',1)")


def test_sqlite_existing_wal_reader_retains_committed_snapshot(tmp_path):
    store = MemoryStore(tmp_path, ["pet1"])
    # Exercise an externally configured WAL database, not automatic WAL activation.
    with store._connect("pet1") as db:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        db.execute("INSERT INTO core_facts VALUES ('game','chess',1)")
    store = MemoryStore(tmp_path, ["pet1"])
    with store._connect("pet1") as reader:
        assert reader.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        reader.execute("BEGIN")
        assert reader.execute("SELECT value FROM core_facts").fetchone() == ("chess",)
        with store._connect("pet1") as writer:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE core_facts SET value='checkers'")
        assert reader.execute("SELECT value FROM core_facts").fetchone() == ("chess",)
    with store._connect("pet1") as db:
        assert db.execute("SELECT value FROM core_facts").fetchone() == ("checkers",)


def test_initialization_keeps_legacy_write_seal_private_and_durable(tmp_path, monkeypatch):
    import sqlite3
    from contextlib import closing

    import desk_robot.memory as memory_module

    monkeypatch.setattr(memory_module, "_MAX_DELETED_EPISODE_IDS", 2)
    path = tmp_path / "pet1.sqlite3"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE deleted_episode_ids (event_id TEXT PRIMARY KEY)")
        db.executemany("INSERT INTO deleted_episode_ids VALUES (?)", [("one",), ("two",)])

    for _ in range(2):
        store = MemoryStore(tmp_path, ["pet1", "pet2"])
        with store._connect("pet1") as db:
            assert db.execute("SELECT writes_sealed FROM deletion_fence_guard").fetchone() == (1,)
            assert db.execute("SELECT COUNT(*) FROM deleted_episode_ids").fetchone() == (2,)
        with store._connect("pet2") as db:
            assert db.execute("SELECT writes_sealed FROM deletion_fence_guard").fetchone() == (0,)


def test_initialization_preserves_identity_rejection_without_partial_schema(tmp_path):
    import sqlite3
    from contextlib import closing

    path = tmp_path / "pet1.sqlite3"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE memory_identity (singleton INTEGER PRIMARY KEY, robot_id TEXT)")
        db.execute("INSERT INTO memory_identity VALUES (1, 'pet2')")
    with pytest.raises(ValueError, match="^Private memory database identity mismatch$"):
        MemoryStore(tmp_path, ["pet1"])
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("memory_identity",),
        ]
        assert db.execute("SELECT robot_id FROM memory_identity").fetchone() == ("pet2",)
