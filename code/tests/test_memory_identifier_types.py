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
