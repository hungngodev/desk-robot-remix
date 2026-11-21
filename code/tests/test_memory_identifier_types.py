"""Malformed memory identifiers must fail closed without regex TypeError."""

import pytest
from desk_robot.memory import MemoryStore


@pytest.mark.parametrize("field,bad", [
    ("event_id", None), ("event_id", []), ("event_id", {}),
    ("event_id", 123), ("event_id", True),
    ("kind", None), ("kind", []), ("kind", {}),
    ("kind", 123), ("kind", True),
])
def test_remember_rejects_nonstring_identifiers(tmp_path, field, bad):
    store = MemoryStore(tmp_path / "memory", ["robot-01"])
    kwargs = dict(
        robot_id="robot-01", event_id="evt-1", summary="Touch observed",
        kind="touch_tap", source_robot="robot-01", witnessed=True,
    )
    kwargs[field] = bad
    with pytest.raises(ValueError, match="Invalid event ID or kind"):
        store.remember(**kwargs)
    assert store.count("robot-01") == 0


def test_remember_accepts_valid_identifiers(tmp_path):
    store = MemoryStore(tmp_path / "memory", ["robot-01"])
    assert store.remember(
        "robot-01", "evt-1", "Touch observed", kind="touch_tap",
        source_robot="robot-01", witnessed=True,
    )
    assert store.count("robot-01") == 1


@pytest.mark.parametrize("bad", [None, [], {}, 123, True])
def test_correct_episode_rejects_nonstring_event_id_without_mutation(tmp_path, bad):
    store = MemoryStore(tmp_path / "memory", ["robot-01"])
    assert store.remember(
        "robot-01", "evt-1", "Original observation", kind="touch_tap",
        source_robot="robot-01", witnessed=True,
    )
    with pytest.raises(ValueError, match="Invalid memory event ID"):
        store.correct_episode("robot-01", bad, "Corrected observation")
    assert store.recent("robot-01")[0].summary == "Original observation"


@pytest.mark.parametrize("bad", [
    None, [], {}, 123, True, "", "   ", "\x00evil", "x" * 301,
])
def test_correct_episode_rejects_invalid_summary_without_mutation(tmp_path, bad):
    store = MemoryStore(tmp_path / "memory", ["robot-01"])
    assert store.remember(
        "robot-01", "evt-1", "Original observation", kind="touch_tap",
        source_robot="robot-01", witnessed=True,
    )
    with pytest.raises(ValueError, match="Bounded nonempty description required"):
        store.correct_episode("robot-01", "evt-1", bad)
    assert store.recent("robot-01")[0].summary == "Original observation"
