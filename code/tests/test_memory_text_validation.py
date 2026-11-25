"""Invalid text must not consume an operator's durable mutation reservation."""

import pytest
from desk_robot.memory import MemoryStore


@pytest.mark.parametrize("bad", ["bad\ud800", "bad\udfff", "bad\x00"])
def test_invalid_core_text_does_not_supersede_pending_request(tmp_path, bad):
    store = MemoryStore(tmp_path, ["pet_a", "pet_b"])
    pending = store.reserve_core_fact_mutation("pet_a", "favorite_game", "điện 😀")
    with pytest.raises(ValueError, match="Invalid bounded core memory value"):
        store.reserve_core_fact_mutation("pet_a", "favorite_game", bad)
    with pytest.raises(ValueError, match="Invalid bounded core memory value"):
        store.set_core_fact("pet_a", "favorite_game", bad)

    # Reopen to check the persisted ordering fence, not an in-memory mock.
    reopened = MemoryStore(tmp_path, ["pet_a", "pet_b"])
    assert reopened.set_core_fact(
        "pet_a", "favorite_game", "điện 😀", mutation_generation=pending,
    )
    assert reopened.core_facts("pet_a")[0].value == "điện 😀"
    assert reopened.core_facts("pet_b") == []


@pytest.mark.parametrize("bad", ["bad\ud800", "bad\udfff", "bad\x00"])
def test_invalid_episode_text_does_not_supersede_pending_request(tmp_path, bad):
    store = MemoryStore(tmp_path, ["pet_a"])
    assert store.remember(
        "pet_a", "event", "original", kind="scene",
        source_robot="pet_a", witnessed=True,
    )
    pending = store.reserve_episode_mutation("pet_a", "event", "điện 😀")
    with pytest.raises(ValueError, match="Bounded nonempty description required"):
        store.reserve_episode_mutation("pet_a", "event", bad)
    with pytest.raises(ValueError, match="Bounded nonempty description required"):
        store.correct_episode("pet_a", "event", bad)
    with pytest.raises(ValueError, match="Invalid description"):
        store.remember(
            "pet_a", "invalid", bad, kind="scene",
            source_robot="pet_a", witnessed=True,
        )

    reopened = MemoryStore(tmp_path, ["pet_a"])
    assert reopened.correct_episode(
        "pet_a", "event", "điện 😀", mutation_generation=pending,
    )
    assert reopened.get_episode("pet_a", "event").summary == "điện 😀"
    assert reopened.get_episode("pet_a", "invalid") is None
    assert reopened.count("pet_a") == 1
