"""A successful episodic write means the row survived bounded retention."""

import time

from desk_robot.memory import MemoryStore


def record(store, robot_id, event_id, when, summary=None):
    return store.remember(
        robot_id,
        event_id,
        summary or f"Observation {event_id}",
        kind="scene",
        source_robot=robot_id,
        witnessed=True,
        observed_at=when,
    )


def test_backdated_new_episode_reports_eviction_not_success(tmp_path):
    store = MemoryStore(tmp_path / "private", ["pet_a", "pet_b"])
    now = time.time()
    for index in range(250):
        assert record(store, "pet_a", f"event_{index:03}", now - 500 + index)
    assert store.count("pet_a") == 250

    # INSERT OR IGNORE can insert an old event successfully, only for the
    # retention DELETE in the same transaction to evict it immediately.
    assert record(store, "pet_a", "backdated", now - 1000) is False
    assert store.get_episode("pet_a", "backdated") is None
    assert store.count("pet_a") == 250
    assert store.get_episode("pet_a", "event_000") is not None
    assert store.get_episode("pet_a", "event_249") is not None

    # A duplicate must not rewrite its original summary or observed clock.
    first = store.get_episode("pet_a", "event_249")
    assert record(store, "pet_a", "event_249", now - 1, "Wrong replacement") is False
    assert store.get_episode("pet_a", "event_249") == first

    # A different pet's bounded store cannot be evicted by this pet's writes.
    assert record(store, "pet_b", "backdated", now - 1000) is True
    assert store.count("pet_b") == 1


def test_deleted_unretained_event_stays_unwritable_after_restart(tmp_path):
    root = tmp_path / "private"
    store = MemoryStore(root, ["pet_a", "pet_b"])
    now = time.time()
    for index in range(250):
        assert record(store, "pet_a", f"new_{index:03}", now - 500 + index)
    assert record(store, "pet_a", "late", now - 1000) is False
    # Deleting an already trimmed event still fences a delayed replay.
    assert store.forget_episode("pet_a", "late") is False

    reopened = MemoryStore(root, ["pet_a", "pet_b"])
    assert record(reopened, "pet_a", "late", now - 1000) is False
    assert reopened.get_episode("pet_a", "late") is None
    assert reopened.count("pet_a") == 250
    assert record(reopened, "pet_b", "late", now - 1000) is True


def test_corrected_episode_cannot_return_after_retention_and_restart(tmp_path):
    root = tmp_path / "private"
    store = MemoryStore(root, ["pet_a", "pet_b"])
    now = time.time()
    assert store.set_core_fact("pet_a", "favorite_game", "chess")
    assert record(store, "pet_a", "original", now - 1000, "Silver key")
    assert store.correct_episode("pet_a", "original", "Brass key")
    assert store.get_episode("pet_a", "original").summary == "Brass key"
    for index in range(250):
        assert record(store, "pet_a", f"new_{index:03}", now - 500 + index)
    assert store.get_episode("pet_a", "original") is None

    # Free a slot so that an exact, backdated replay would survive retention.
    assert store.forget_episode("pet_a", "new_249")
    reopened = MemoryStore(root, ["pet_a", "pet_b"])
    assert not record(reopened, "pet_a", "original", now - 1000, "Silver key")
    assert reopened.get_episode("pet_a", "original") is None
    assert reopened.count("pet_a") == 249
    assert reopened.core_facts("pet_a")[0].value == "chess"
    assert record(reopened, "pet_b", "original", now - 1000, "Silver key")
