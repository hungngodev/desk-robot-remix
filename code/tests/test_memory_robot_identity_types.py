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
