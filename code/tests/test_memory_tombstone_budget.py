"""Bounded persistent deletion fences must never resurrect private facts."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from threading import Event

import desk_robot.memory as memory_module
import pytest
from desk_robot.memory import (
    EpisodeMemoryMutationSuperseded,
    MemoryStore,
    MemoryWriteSealed,
)


@contextmanager
def open_database(path):
    # sqlite3's transaction context commits or rolls back but does not close.
    with closing(sqlite3.connect(path)) as db, db:
        yield db


def test_database_context_closes_after_commit_and_rollback(tmp_path):
    path = tmp_path / "lifecycle.sqlite3"
    with open_database(path) as db:
        db.execute("CREATE TABLE entries (value INTEGER)")
        db.execute("INSERT INTO entries VALUES (1)")
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        db.execute("SELECT 1")

    with pytest.raises(RuntimeError, match="rollback probe"), open_database(path) as db:
        db.execute("INSERT INTO entries VALUES (2)")
        raise RuntimeError("rollback probe")
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        db.execute("SELECT 1")

    with open_database(path) as db:
        assert db.execute("SELECT value FROM entries").fetchall() == [(1,)]


def remember(store, pet, event):
    return store.remember(
        pet, event, f"Original observation {event}",
        kind="touch_tap", source_robot=pet, witnessed=True,
    )


def read_fence(root, pet):
    with open_database(root / f"{pet}.sqlite3") as db:
        return (
            db.execute("SELECT COUNT(*) FROM deleted_episode_ids").fetchone()[0],
            db.execute(
                "SELECT writes_sealed FROM deletion_fence_guard WHERE singleton=1"
            ).fetchone()[0],
        )


def test_deleted_episode_fence_is_bounded_and_seals_new_writes_across_restarts(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(memory_module, "_MAX_DELETED_EPISODE_IDS", 3)
    root = tmp_path / "private"
    store = MemoryStore(root, ["robot-01", "robot-02"])
    assert remember(store, "robot-01", "first")
    assert remember(store, "robot-02", "peer")
    assert store.forget_episode("robot-01", "first")
    assert store.forget_episode("robot-01", "unknown-2") is False
    assert read_fence(root, "robot-01") == (2, 0)

    # Third unique deletion reaches the cap. There is NO unsafe eviction.
    assert store.forget_episode("robot-01", "unknown-3") is False
    assert read_fence(root, "robot-01") == (3, 1)
    for i in range(50):
        store.forget_episode("robot-01", f"other-{i}")
    assert read_fence(root, "robot-01") == (3, 1)
    assert store.count("robot-01") == 0
    for event in ("first", "unknown-2", "unknown-3", "other-49", "new"):
        with pytest.raises(MemoryWriteSealed, match="writes sealed"):
            remember(store, "robot-01", event)

    # A new process must not reset the irreversible replay prohibition.
    reopened = MemoryStore(root, ["robot-01", "robot-02"])
    assert read_fence(root, "robot-01") == (3, 1)
    with pytest.raises(MemoryWriteSealed):
        remember(reopened, "robot-01", "other-40")
    assert reopened.count("robot-01") == 0
    # No cross-pet tombstone or seal; unrelated private identity still writes.
    assert read_fence(root, "robot-02") == (0, 0)
    assert remember(reopened, "robot-02", "peer-new")
    assert reopened.count("robot-02") == 2


def test_saturated_fence_still_allows_operator_deletion_of_existing_memory(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(memory_module, "_MAX_DELETED_EPISODE_IDS", 2)
    root = tmp_path / "private"
    store = MemoryStore(root, ["robot-01"])
    assert remember(store, "robot-01", "keep")
    store.forget_episode("robot-01", "not-yet-1")
    store.forget_episode("robot-01", "not-yet-2")
    assert read_fence(root, "robot-01") == (2, 1)
    assert store.forget_episode("robot-01", "keep") is True
    assert store.get_episode("robot-01", "keep") is None
    assert read_fence(root, "robot-01") == (2, 1)
    with pytest.raises(MemoryWriteSealed):
        remember(store, "robot-01", "keep")


def test_legacy_tombstone_database_is_sealed_on_upgrade(tmp_path, monkeypatch):
    root = tmp_path / "private"
    initial = MemoryStore(root, ["robot-01"])
    for i in range(5):
        initial.forget_episode("robot-01", f"preexisting-{i}")
    assert read_fence(root, "robot-01") == (5, 0)
    monkeypatch.setattr(memory_module, "_MAX_DELETED_EPISODE_IDS", 3)
    upgraded = MemoryStore(root, ["robot-01"])
    assert read_fence(root, "robot-01") == (5, 1)
    with pytest.raises(MemoryWriteSealed):
        remember(upgraded, "robot-01", "new-after-upgrade")
    upgraded.forget_episode("robot-01", "more")
    assert read_fence(root, "robot-01") == (5, 1)


def test_forget_and_delayed_writer_are_serialized_at_saturation(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(memory_module, "_MAX_DELETED_EPISODE_IDS", 1)
    root = tmp_path / "private"
    store = MemoryStore(root, ["robot-01"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        # A late callback cannot get past a committed delete fence.
        delete = pool.submit(store.forget_episode, "robot-01", "delayed")
        delete.result(timeout=5)
        attempted = pool.submit(remember, store, "robot-01", "delayed")
        with pytest.raises(MemoryWriteSealed):
            attempted.result(timeout=5)
    assert read_fence(root, "robot-01") == (1, 1)
    assert store.count("robot-01") == 0


def test_sealed_absent_edits_do_not_grow_episode_mutation_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_module, "_MAX_DELETED_EPISODE_IDS", 3)
    root = tmp_path / "private"
    store = MemoryStore(root, ["robot-01", "robot-02"])
    pet = "robot-01"

    def generations(robot_id):
        with open_database(root / f"{robot_id}.sqlite3") as db:
            return dict(db.execute("SELECT event_id,generation FROM episode_mutations"))

    assert remember(store, pet, "retained")
    assert remember(store, "robot-02", "peer")
    for i in range(3):
        assert not store.forget_episode(pet, f"fence-{i}")
    initial = generations(pet)
    assert read_fence(root, pet) == (3, 1)

    for pass_index in range(2):
        store = MemoryStore(root, ["robot-01", "robot-02"])
        for i in range(20):
            event = f"absent-{pass_index}-{i}"
            assert not store.forget_episode(pet, event)
            assert not store.correct_episode(pet, event, "new description")
            # The operator route reserves before the offloaded edit.
            delete = store.reserve_episode_mutation(pet, event)
            assert not store.forget_episode(pet, event, mutation_generation=delete)
            patch = store.reserve_episode_mutation(pet, event, "new description")
            assert not store.correct_episode(
                pet, event, "new description", mutation_generation=patch,
            )
        assert generations(pet) == initial
        assert read_fence(root, pet) == (3, 1)

    # Sealing must not weaken ordering for episodes that still exist.
    old = store.reserve_episode_mutation(pet, "retained")
    new = store.reserve_episode_mutation(pet, "retained", "corrected")
    assert store.correct_episode(pet, "retained", "corrected", mutation_generation=new)
    with pytest.raises(EpisodeMemoryMutationSuperseded):
        store.forget_episode(pet, "retained", mutation_generation=old)
    assert store.get_episode(pet, "retained").summary == "corrected"
    assert store.forget_episode(pet, "retained")
    with pytest.raises(MemoryWriteSealed):
        remember(store, pet, "absent-0-0")
    assert generations("robot-02") == {}
    assert store.get_episode("robot-02", "peer") is not None


def test_correction_replay_fences_share_bounded_per_pet_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_module, "_MAX_DELETED_EPISODE_IDS", 2)
    root = tmp_path / "private"
    store = MemoryStore(root, ["robot-01", "robot-02"])
    pet = "robot-01"
    assert remember(store, pet, "first")
    assert remember(store, pet, "second")
    assert store.correct_episode(pet, "first", "Corrected first")
    assert store.correct_episode(pet, "first", "Corrected again")
    assert read_fence(root, pet) == (1, 0)
    assert not store.correct_episode(pet, "missing", "Nothing to correct")
    assert read_fence(root, pet) == (1, 0)
    assert store.correct_episode(pet, "second", "Corrected second")
    assert read_fence(root, pet) == (2, 1)
    reopened = MemoryStore(root, ["robot-01", "robot-02"])
    assert reopened.get_episode(pet, "second").summary == "Corrected second"
    assert reopened.correct_episode(pet, "second", "Still editable")
    assert reopened.forget_episode(pet, "first")
    assert read_fence(root, pet) == (2, 1)
    with pytest.raises(MemoryWriteSealed):
        remember(reopened, pet, "first")
    assert remember(reopened, "robot-02", "first")


def test_direct_absent_corrections_do_not_grow_unsealed_mutation_ledger(tmp_path):
    root = tmp_path / "private"
    pet = "robot-01"
    store = MemoryStore(root, [pet])
    for i in range(30):
        assert not store.correct_episode(pet, f"absent-{i}", "No such observation")

    with open_database(root / f"{pet}.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM episode_mutations").fetchone() == (0,)
    assert read_fence(root, pet) == (0, 0)

    # A direct edit must still retire an older pending reservation, even
    # when the episode is absent at the instant of the newer edit.
    older = store.reserve_episode_mutation(pet, "pending", "Old correction")
    assert not store.correct_episode(pet, "pending", "New correction")
    reopened = MemoryStore(root, [pet])
    assert remember(reopened, pet, "pending")
    with pytest.raises(EpisodeMemoryMutationSuperseded):
        reopened.correct_episode(
            pet, "pending", "Old correction", mutation_generation=older,
        )
    assert reopened.get_episode(pet, "pending").summary == "Original observation pending"


def test_forget_status_and_search_across_overlapping_reader_and_restart(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(memory_module, "_MAX_DELETED_EPISODE_IDS", 2)
    root = tmp_path / "private"
    pet, peer = "robot-01", "robot-02"
    event = "concurrent"
    store = MemoryStore(root, [pet, peer])
    assert remember(store, pet, event)
    assert remember(store, peer, event)

    fenced = Event()
    original = MemoryStore._fence_episode_replay

    def signal_fence(db, event_id):
        original(db, event_id)
        fenced.set()

    monkeypatch.setattr(MemoryStore, "_fence_episode_replay", staticmethod(signal_fence))
    with ThreadPoolExecutor(max_workers=1) as pool:
        with open_database(root / f"{pet}.sqlite3") as reader:
            reader.execute("BEGIN")
            try:
                assert reader.execute(
                    "SELECT summary FROM memories WHERE event_id=?", (event,),
                ).fetchone() == ("Original observation concurrent",)
                deleted = pool.submit(store.forget_episode, pet, event)
                assert fenced.wait(timeout=5)
            finally:
                # The already-started read may see its old snapshot. Release
                # it before awaiting the writer's committed deletion receipt.
                reader.rollback()
        assert deleted.result(timeout=5) is True

    for current in (store, MemoryStore(root, [pet, peer])):
        assert current.get_episode(pet, event) is None
        assert current.recent(pet) == []
        assert current.search(pet, "concurrent") == []
        assert current.count(pet) == 0
        assert not current.forget_episode(pet, event)
        assert not remember(current, pet, event)
        assert read_fence(root, pet) == (1, 0)
        assert current.get_episode(peer, event) is not None
        assert len(current.search(peer, "concurrent")) == 1

    assert not store.forget_episode(pet, "unknown")
    assert read_fence(root, pet) == (2, 1)
    reopened = MemoryStore(root, [pet, peer])
    with pytest.raises(MemoryWriteSealed):
        remember(reopened, pet, event)
    assert reopened.search(pet, "concurrent") == []
    assert read_fence(root, peer) == (0, 0)


def test_forget_rolls_back_cleanup_and_seal_without_touching_four_peers(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(memory_module, "_MAX_DELETED_EPISODE_IDS", 2)
    root = tmp_path / "private"
    pets = [f"robot-{number:02d}" for number in range(1, 6)]
    target = pets[0]
    event = "shared-event"
    store = MemoryStore(root, pets)

    def snapshot(pet):
        with open_database(root / f"{pet}.sqlite3") as db:
            return {
                "episode": db.execute("SELECT * FROM memories").fetchall(),
                "camera": db.execute("SELECT * FROM camera_provenance").fetchall(),
                "spatial": db.execute("SELECT * FROM spatial_observations").fetchall(),
                "fts": db.execute(
                    "SELECT rowid FROM memories_fts WHERE memories_fts MATCH 'observation'"
                ).fetchall(),
                "fences": db.execute(
                    "SELECT event_id FROM deleted_episode_ids ORDER BY event_id"
                ).fetchall(),
                "seal": db.execute("SELECT * FROM deletion_fence_guard").fetchall(),
                "mutations": db.execute(
                    "SELECT * FROM episode_mutations ORDER BY event_id"
                ).fetchall(),
            }

    for pet in pets:
        assert remember(store, pet, event)
        # Seed the sidecars directly: this test targets the database deletion
        # transaction, not camera ingestion or the spatial mapping pipeline.
        with open_database(root / f"{pet}.sqlite3") as db:
            db.execute(
                "INSERT INTO camera_provenance VALUES (?, 1, 2, 3, 4, '5')", (event,)
            )
            db.execute(
                "INSERT INTO spatial_observations VALUES "
                "(?, 'key', 1, 2, 'origin', 3, 4, 5, 6, '7', 'cal', "
                "8, 9, 10, 11, 'odom', NULL)", (event,),
            )
    assert not store.forget_episode(target, "previous")
    assert not store.forget_episode(pets[1], "peer-only")
    before = {pet: snapshot(pet) for pet in pets}

    # Abort from a sidecar cleanup trigger, after the writer has advanced its
    # mutation generation and tentatively saturated the replay fence.
    with open_database(root / f"{target}.sqlite3") as db:
        db.execute(
            """CREATE TRIGGER injected_cleanup_failure
               AFTER DELETE ON camera_provenance BEGIN
                   SELECT RAISE(ABORT, 'injected cleanup failure');
               END"""
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected cleanup failure"):
        store.forget_episode(target, event)
    assert {pet: snapshot(pet) for pet in pets} == before
    assert read_fence(root, target) == (1, 0)

    with open_database(root / f"{target}.sqlite3") as db:
        db.execute("DROP TRIGGER injected_cleanup_failure")
    assert store.forget_episode(target, event)
    after = snapshot(target)
    for table in ("episode", "camera", "spatial", "fts"):
        assert after[table] == []
    assert after["fences"] == [("previous",), (event,)]
    assert after["mutations"] == [("previous", 1), (event, 1)]
    assert read_fence(root, target) == (2, 1)

    reopened = MemoryStore(root, pets)
    assert reopened.get_episode(target, event) is None
    assert not reopened.search(target, "observation")
    assert snapshot(target) == after
    for peer in pets[1:]:
        assert snapshot(peer) == before[peer]
        assert reopened.get_episode(peer, event) is not None
        assert remember(reopened, peer, "new-observation")
    with pytest.raises(MemoryWriteSealed):
        remember(reopened, target, event)
