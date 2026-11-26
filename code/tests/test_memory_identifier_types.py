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


class _IdentifierSubclass(str):
    pass


def test_memory_identifiers_require_plain_schema_strings(tmp_path):
    store = MemoryStore(tmp_path, ["pet_a"])
    assert store.remember(
        "pet_a", "evt", "Original observation", kind="scene",
        source_robot="pet_a", witnessed=True,
    )
    assert store.set_core_fact("pet_a", "nickname", "original")
    event = _IdentifierSubclass("evt")
    kind = _IdentifierSubclass("scene")
    slot = _IdentifierSubclass("nickname")

    for bad_event, bad_kind in ((event, "scene"), ("new_evt", kind)):
        with pytest.raises(ValueError, match="Invalid event ID or kind"):
            store.remember(
                "pet_a", bad_event, "Invalid observation", kind=bad_kind,
                source_robot="pet_a", witnessed=True,
            )

    for action in (
        lambda: store.get_episode("pet_a", event),
        lambda: store.get_camera_provenance("pet_a", event),
        lambda: store.witnessed_episode_revision("pet_a", event),
        lambda: store.retract_peer_copy("pet_a", event, "a" * 32),
        lambda: store.reserve_episode_mutation("pet_a", event),
        lambda: store.correct_episode("pet_a", event, "Changed observation"),
        lambda: store.forget_episode("pet_a", event),
    ):
        with pytest.raises(ValueError, match="Invalid memory event ID"):
            action()

    for action in (
        lambda: store.reserve_core_fact_mutation("pet_a", slot),
        lambda: store.set_core_fact("pet_a", slot, "changed"),
        lambda: store.forget_core_fact("pet_a", slot),
    ):
        with pytest.raises(ValueError, match="Invalid core memory slot"):
            action()

    assert store.count("pet_a") == 1
    assert store.get_episode("pet_a", "evt").summary == "Original observation"
    assert store.core_facts("pet_a")[0].value == "original"
