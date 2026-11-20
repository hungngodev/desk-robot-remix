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
