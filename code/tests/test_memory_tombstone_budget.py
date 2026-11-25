"""Bounded persistent deletion fences must never resurrect private facts."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import desk_robot.memory as memory_module
import pytest
from desk_robot.memory import (
    EpisodeMemoryMutationSuperseded,
    MemoryStore,
    MemoryWriteSealed,
)


def remember(store, pet, event):
    return store.remember(
        pet, event, f"Original observation {event}",
        kind="touch_tap", source_robot=pet, witnessed=True,
    )


def read_fence(root, pet):
    with sqlite3.connect(root / f"{pet}.sqlite3") as db:
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
        with sqlite3.connect(root / f"{robot_id}.sqlite3") as db:
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
