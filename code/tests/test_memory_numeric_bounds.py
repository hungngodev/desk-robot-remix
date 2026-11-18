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
