"""Invalid text must not consume an operator's durable mutation reservation."""

import pytest
from desk_robot.memory import MemoryStore


@pytest.mark.parametrize("bad", [
    "bad\ud800", "bad\udfff", "bad\x00", "bad\x1b", "bad\x7f", "bad\x85",
])
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


@pytest.mark.parametrize("bad", [
    "bad\ud800", "bad\udfff", "bad\x00", "bad\x1b", "bad\x7f", "bad\x85",
])
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


@pytest.mark.parametrize("bad", [
    "x" * 1_000_000,
    " " * 1_000_000 + "valid",
    "x" + " " * 300,
    {"not": "text"},
], ids=["wall", "padded-wall", "padded-boundary", "decoded-object"])
def test_raw_bounds_precede_reservation_and_sqlite_write(tmp_path, bad):
    store = MemoryStore(tmp_path, ["pet_a", "pet_b"])
    core = store.reserve_core_fact_mutation("pet_a", "favorite_game", "valid")
    episode = store.reserve_episode_mutation("pet_a", "event", "valid")
    assert store.remember(
        "pet_a", "event", "original", kind="scene",
        source_robot="pet_a", witnessed=True,
    )
    with pytest.raises(ValueError, match="Invalid bounded core memory value"):
        store.reserve_core_fact_mutation("pet_a", "favorite_game", bad)
    with pytest.raises(ValueError, match="Invalid bounded core memory value"):
        store.set_core_fact("pet_a", "favorite_game", bad)
    with pytest.raises(ValueError, match="Bounded nonempty description required"):
        store.reserve_episode_mutation("pet_a", "event", bad)
    with pytest.raises(ValueError, match="Bounded nonempty description required"):
        store.correct_episode("pet_a", "event", bad)
    with pytest.raises(ValueError, match="Bounded nonempty description required"):
        store.remember(
            "pet_a", "invalid", bad, kind="scene",
            source_robot="pet_a", witnessed=True,
        )
    reopened = MemoryStore(tmp_path, ["pet_a", "pet_b"])
    assert reopened.set_core_fact("pet_a", "favorite_game", "valid", mutation_generation=core)
    assert reopened.correct_episode("pet_a", "event", "valid", mutation_generation=episode)
    assert reopened.count("pet_a") == 1
    assert reopened.count("pet_b") == 0


@pytest.mark.parametrize("bad", [
    "bad\ud800", "bad\udfff", "bad\x00", "bad\x1b", "bad\x7f", "bad\x85",
    "x" * 241, " " * 1_000_000 + "word",
], ids=["high", "low", "nul", "escape", "del", "c1", "boundary", "padded-wall"])
def test_search_rejects_invalid_text_before_fts(tmp_path, bad):
    store = MemoryStore(tmp_path, ["pet_a"])
    with pytest.raises(ValueError, match="Bounded memory question"):
        store.search("pet_a", bad)


def test_valid_unicode_and_json_like_plain_text_remain_opaque(tmp_path):
    store = MemoryStore(tmp_path, ["pet_a"])
    # Memory is text, not a JSON parser. An incomplete JSON-looking utterance
    # is valid evidence and must not be repaired into a different statement.
    text = 'điện 😀\n\t{"unfinished":'
    assert store.remember(
        "pet_a", "event", text, kind="scene",
        source_robot="pet_a", witnessed=True,
    )
    assert store.get_episode("pet_a", "event").summary == text
    assert store.search("pet_a", "điện")[0].event_id == "event"
    assert store.correct_episode("pet_a", "event", "😀" * 300)
    assert store.get_episode("pet_a", "event").summary == "😀" * 300
    assert store.set_core_fact("pet_a", "favorite_game", "😀" * 200)
    assert store.core_facts("pet_a")[0].value == "😀" * 200


class MisleadingText(str):
    def __len__(self):
        return 5

    def strip(self):
        return "x" * 1_000_000


def test_nonplain_string_cannot_rewrite_validated_text(tmp_path):
    store = MemoryStore(tmp_path, ["pet_a"])
    bad = MisleadingText("valid")
    with pytest.raises(ValueError, match="Bounded nonempty description required"):
        store.remember(
            "pet_a", "invalid", bad, kind="scene",
            source_robot="pet_a", witnessed=True,
        )
    assert store.count("pet_a") == 0
