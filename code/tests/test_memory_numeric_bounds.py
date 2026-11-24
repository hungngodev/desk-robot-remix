"""Regression: hostile numeric confidence must fail closed without float overflow."""

import pytest
from desk_robot.memory import MemoryStore


@pytest.mark.parametrize("confidence", [10**1000, -(10**1000), float("inf"), float("-inf"), float("nan"), True])
def test_memory_rejects_unrepresentable_confidence(tmp_path, confidence):
    store = MemoryStore(tmp_path, ["pet1"])
    with pytest.raises(ValueError):
        store.remember("pet1", "numeric-bound", "saw a touch", kind="touch",
                       source_robot="pet1", witnessed=True, confidence=confidence)
    assert store.recent("pet1") == []


def test_memory_accepts_bounded_confidence(tmp_path):
    store = MemoryStore(tmp_path, ["pet1"])
    assert store.remember("pet1", "bounded-confidence", "saw a touch", kind="touch",
                          source_robot="pet1", witnessed=True, confidence=0.75)
    assert store.recent("pet1")[0].confidence == 0.75


def test_memory_rejects_far_future_observations(tmp_path):
    import time

    store = MemoryStore(tmp_path, ["pet1"])
    now = time.time()
    assert store.remember(
        "pet1", "current", "Actual fresh touch", kind="touch",
        source_robot="pet1", witnessed=True, observed_at=now,
    )
    # The previous broad 0..1e12 timestamp range allowed a faulty device
    # clock to rank this event ahead of real observations indefinitely.
    with pytest.raises(ValueError, match="Observation timestamp exceeds local clock"):
        store.remember(
            "pet1", "future", "Impossible future camera observation", kind="scene",
            source_robot="pet1", witnessed=True, observed_at=now + 86400,
        )
    assert [item.event_id for item in store.recent("pet1")] == ["current"]
    assert store.search("pet1", "future") == []
    # Small clock skew is tolerated without disrupting historical imports.
    assert store.remember(
        "pet1", "skew", "Head clock slightly ahead", kind="scene",
        source_robot="pet1", witnessed=True, observed_at=now + 5,
    )


@pytest.mark.parametrize("field", ["received_at", "interpreted_at"])
@pytest.mark.parametrize("bad_clock", [10**1000, -(10**1000), float("inf"), float("-inf"), float("nan")])
def test_camera_provenance_rejects_unbounded_integer_and_float_clocks(
    tmp_path, field, bad_clock,
):
    import time

    from desk_robot.memory import CameraProvenance

    store = MemoryStore(tmp_path, ["pet1"])
    now = time.time()
    clocks = {"received_at": now, "interpreted_at": now}
    clocks[field] = bad_clock
    with pytest.raises(ValueError, match="Invalid camera chronology"):
        store.remember(
            "pet1", "invalid-camera", "An uncertain camera observation",
            kind="scene", source_robot="pet1", witnessed=True,
            observed_at=now, camera_provenance=CameraProvenance(**clocks),
        )
    assert store.recent("pet1") == []


@pytest.mark.parametrize("generation", [0, -1, True, 1.0, "1", 1 << 63, 10**1000])
def test_memory_mutation_generation_bounds_fail_without_changing_data(tmp_path, generation):
    store = MemoryStore(tmp_path, ["pet1"])
    assert store.set_core_fact("pet1", "nickname", "original")
    assert store.remember(
        "pet1", "original", "Original touch", kind="touch",
        source_robot="pet1", witnessed=True,
    )

    for action in (
        lambda: store.set_core_fact(
            "pet1", "nickname", "changed", mutation_generation=generation,
        ),
        lambda: store.forget_core_fact(
            "pet1", "nickname", mutation_generation=generation,
        ),
        lambda: store.correct_episode(
            "pet1", "original", "Changed touch", mutation_generation=generation,
        ),
        lambda: store.forget_episode(
            "pet1", "original", mutation_generation=generation,
        ),
    ):
        with pytest.raises(ValueError, match="Invalid .* mutation generation"):
            action()

    assert store.core_facts("pet1")[0].value == "original"
    assert store.get_episode("pet1", "original").summary == "Original touch"


def test_maximum_sqlite_mutation_generation_is_valid_but_cannot_advance(tmp_path):
    store = MemoryStore(tmp_path, ["pet1"])
    assert store.set_core_fact("pet1", "nickname", "original")
    assert store.remember(
        "pet1", "original", "Original touch", kind="touch",
        source_robot="pet1", witnessed=True,
    )
    store.reserve_episode_mutation("pet1", "original")
    maximum = (1 << 63) - 1
    # Seed the boundary directly instead of performing 2**63 mutations.
    with store._connect("pet1") as db:
        db.execute("UPDATE core_fact_mutations SET generation=?", (maximum,))
        db.execute("UPDATE episode_mutations SET generation=?", (maximum,))

    assert store.set_core_fact(
        "pet1", "nickname", "changed", mutation_generation=maximum,
    )
    assert store.correct_episode(
        "pet1", "original", "Changed touch", mutation_generation=maximum,
    )
    with pytest.raises(ValueError, match="Core memory generation exhausted"):
        store.reserve_core_fact_mutation("pet1", "nickname")
    with pytest.raises(ValueError, match="Episode memory generation exhausted"):
        store.reserve_episode_mutation("pet1", "original")
    assert store.core_facts("pet1")[0].value == "changed"
    assert store.get_episode("pet1", "original").summary == "Changed touch"
