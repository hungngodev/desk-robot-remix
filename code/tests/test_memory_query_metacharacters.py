"""FTS query punctuation must not acquire SQL or FTS operator semantics."""

import pytest
from desk_robot.memory import MemoryStore


@pytest.mark.parametrize("own_only", [False, True])
def test_metacharacters_preserve_private_recall_and_episode_integrity(tmp_path, own_only):
    store = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    for robot, event, summary, source, witnessed in (
        ("robot-01", "local_copper", "Copper or brass", "robot-01", True),
        ("robot-01", "local_decoy", "Ceramic marble", "robot-01", True),
        ("robot-01", "reported_copper", "Copper", "robot-02", False),
        ("robot-02", "private_copper", "Copper", "robot-02", True),
    ):
        store.remember(
            robot, event, summary, kind="object", source_robot=source, witnessed=witnessed,
        )
    before = {robot: store.recent(robot) for robot in ("robot-01", "robot-02")}
    for query in ("%", "_", "%_%", r".*[](){}+?^$\\", "copp%", "copp_", "copp*"):
        assert store.search("robot-01", query, own_only=own_only) == []
    # OR is searchable text here, not an FTS or SQL operator.
    assert {m.event_id for m in store.search(
        "robot-01", "' OR 1=1--", own_only=own_only,
    )} == {"local_copper"}
    expected = {"local_copper"} if own_only else {"local_copper", "reported_copper"}
    for query in ("copper", "%copper%", "_copper_", r"[copper].*"):
        assert {m.event_id for m in store.search(
            "robot-01", query, own_only=own_only,
        )} == expected
    assert [m.event_id for m in store.search(
        "robot-02", "%copper%", own_only=own_only,
    )] == ["private_copper"]
    assert store.search("robot-02", "' OR 1=1--", own_only=own_only) == []
    assert {robot: store.recent(robot) for robot in before} == before
    assert store.count("robot-01") == 3
    assert store.count("robot-02") == 1
