"""Reject unhashable model supplied robot identities without writing memory."""

import pytest
from desk_robot.memory import MemoryStore


@pytest.mark.parametrize("field,bad", [
    ("robot_id", []), ("robot_id", {}),
    ("source_robot", []), ("source_robot", {}),
    ("robot_id", None), ("source_robot", None),
    ("robot_id", 7), ("source_robot", True),
])
def test_remember_rejects_malformed_robot_identity(tmp_path, field, bad):
    store = MemoryStore(tmp_path / "memory", ["robot-01"])
    kwargs = dict(
        robot_id="robot-01", event_id="evt-1", summary="Touch observed",
        kind="touch_tap", source_robot="robot-01", witnessed=True,
    )
    kwargs[field] = bad
    with pytest.raises(ValueError, match="Unknown robot identity"):
        store.remember(**kwargs)
    assert store.count("robot-01") == 0


def test_remember_keeps_firsthand_and_peer_provenance(tmp_path):
    store = MemoryStore(tmp_path / "memory", ["robot-01", "robot-02"])
    assert store.remember(
        "robot-01", "own-1", "Observed touch", kind="touch_tap",
        source_robot="robot-01", witnessed=True,
    )
    assert store.remember(
        "robot-02", "peer-1", "Robot one reported touch", kind="touch_tap",
        source_robot="robot-01", witnessed=False,
    )
    assert store.recent("robot-01")[0].witnessed is True
    assert store.recent("robot-02")[0].witnessed is False


@pytest.mark.parametrize("bad", [[], {}, None, 7, True])
@pytest.mark.parametrize("operation", [
    "recent", "search", "set_core_fact", "core_facts", "forget_core_fact",
    "correct_episode", "forget_episode", "count",
])
def test_memory_operations_reject_malformed_identity(tmp_path, operation, bad):
    store = MemoryStore(tmp_path / "memory", ["robot-01"])
    actions = {
        "recent": lambda: store.recent(bad),
        "search": lambda: store.search(bad, "touch"),
        "set_core_fact": lambda: store.set_core_fact(bad, "favorite_color", "blue"),
        "core_facts": lambda: store.core_facts(bad),
        "forget_core_fact": lambda: store.forget_core_fact(bad, "favorite_color"),
        "correct_episode": lambda: store.correct_episode(
            bad, "evt-1", "corrected observation"
        ),
        "forget_episode": lambda: store.forget_episode(bad, "evt-1"),
        "count": lambda: store.count(bad),
    }
    with pytest.raises(ValueError, match="Unknown robot memory identity"):
        actions[operation]()
    assert store.count("robot-01") == 0


@pytest.mark.parametrize("bad_ids", [
    [], [None], [[]], [{}], [7], [True], ["robot-01", {}],
    ["robot-01", None], "robot-01", None,
])
def test_constructor_rejects_malformed_robot_id_collection(tmp_path, bad_ids):
    root = tmp_path / "memory"
    with pytest.raises(ValueError, match="Every robot ID"):
        MemoryStore(root, bad_ids)
    assert not root.exists()


def test_constructor_accepts_multiple_valid_robot_ids(tmp_path):
    store = MemoryStore(tmp_path / "memory", ["robot-01", "robot-02"])
    assert store.robot_ids == {"robot-01", "robot-02"}
    assert store.count("robot-01") == store.count("robot-02") == 0
