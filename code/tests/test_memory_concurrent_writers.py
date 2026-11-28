"""Concurrent private writers must be ordered by the SQLite transaction."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from threading import Barrier

import pytest
from desk_robot.memory import (
    CoreMemoryMutationSuperseded,
    EpisodeMemoryMutationSuperseded,
    MemoryStore,
)

_ROBOT = "robot-01"
_PEER = "robot-02"
_EVENT = "reflector_episode"
_SLOT = "favorite_game"


def _remember(store, robot, event, text):
    return store.remember(
        robot, event, text, kind="fictional_dream", source_robot=robot, witnessed=True,
    )


def _burst(pool, count, action):
    gate = Barrier(count)

    def run(index):
        gate.wait(timeout=8)
        return action(index)

    return list(pool.map(run, range(count)))


@pytest.mark.parametrize("kind", ["core", "episode"])
def test_threaded_reservations_admit_only_latest_generation(tmp_path, kind):
    stores = [MemoryStore(tmp_path, [_ROBOT, _PEER]) for _ in range(2)]
    first = stores[0]
    if kind == "core":
        assert first.set_core_fact(_PEER, _SLOT, "peer preference")

        def reserve(store):
            return store.reserve_core_fact_mutation(_ROBOT, _SLOT)

        superseded = CoreMemoryMutationSuperseded

        def mutate(store, index, generation):
            return store.set_core_fact(
                _ROBOT, _SLOT, f"revision {index}", mutation_generation=generation,
            )
    else:
        assert _remember(first, _ROBOT, _EVENT, "original")
        assert _remember(first, _PEER, _EVENT, "peer episode")

        def reserve(store):
            return store.reserve_episode_mutation(_ROBOT, _EVENT)

        superseded = EpisodeMemoryMutationSuperseded

        def mutate(store, index, generation):
            return store.correct_episode(
                _ROBOT, _EVENT, f"revision {index}", mutation_generation=generation,
            )

    count = 8
    with ThreadPoolExecutor(max_workers=count) as pool:
        generations = _burst(pool, count, lambda index: reserve(stores[index % 2]))
        assert sorted(generations) == list(range(1, count + 1))

        def apply(index):
            try:
                changed = mutate(stores[index % 2], index, generations[index])
                return "applied" if changed else "no-op"
            except superseded:
                return "superseded"

        accepted = _burst(pool, count, apply)

    winner = generations.index(count)
    assert accepted == ["applied" if index == winner else "superseded" for index in range(count)]
    reopened = MemoryStore(tmp_path, [_ROBOT, _PEER])
    if kind == "core":
        assert reopened.core_facts(_ROBOT)[0].value == f"revision {winner}"
        assert reopened.core_facts(_PEER)[0].value == "peer preference"
    else:
        assert reopened.get_episode(_ROBOT, _EVENT).summary == f"revision {winner}"
        assert reopened.get_episode(_PEER, _EVENT).summary == "peer episode"


def test_concurrent_reflectors_cannot_duplicate_or_restore_forgotten_episode(tmp_path):
    stores = [MemoryStore(tmp_path, [_ROBOT, _PEER]) for _ in range(2)]
    first = stores[0]
    assert _remember(first, _PEER, _EVENT, "peer episode")
    with ThreadPoolExecutor(max_workers=3) as pool:
        inserted = _burst(
            pool, 2, lambda index: _remember(stores[index], _ROBOT, _EVENT, f"dream {index}"),
        )
        assert inserted.count(True) == 1
        assert first.get_episode(_ROBOT, _EVENT).summary == f"dream {inserted.index(True)}"

        def race(index):
            if index == 2:
                return first.forget_episode(_ROBOT, _EVENT)
            return any(_remember(stores[index], _ROBOT, _EVENT, "late dream") for _ in range(8))

        assert _burst(pool, 3, race) == [False, False, True]

    reopened = MemoryStore(tmp_path, [_ROBOT, _PEER])
    assert reopened.get_episode(_ROBOT, _EVENT) is None
    assert reopened.get_episode(_PEER, _EVENT).summary == "peer episode"
    assert not _remember(reopened, _ROBOT, _EVENT, "replayed dream")
    with closing(sqlite3.connect(tmp_path / f"{_ROBOT}.sqlite3")) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


@pytest.mark.parametrize("operation", ["core", "episode", "remember"])
def test_writer_lease_precedes_private_read_modify_write(tmp_path, monkeypatch, operation):
    store = MemoryStore(tmp_path, [_ROBOT])
    original_connect = store._connect
    expected_read = {
        "core": "SELECT generation FROM core_fact_mutations",
        "episode": "SELECT generation FROM episode_mutations",
        "remember": "SELECT writes_sealed FROM deletion_fence_guard",
    }[operation]
    competing_writer_locked = []

    @contextmanager
    def traced_connect(robot_id):
        with original_connect(robot_id) as db:
            def trace(statement):
                if not statement.strip().startswith(expected_read):
                    return
                # An independent connection cannot acquire a write lease at
                # the read that decides the following write. Trace callback
                # exceptions are suppressed by sqlite3, so assert outside it.
                other = sqlite3.connect(tmp_path / f"{robot_id}.sqlite3", timeout=0)
                try:
                    other.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as exc:
                    competing_writer_locked.append(exc.sqlite_errorcode == sqlite3.SQLITE_BUSY)
                else:
                    competing_writer_locked.append(False)
                finally:
                    other.close()

            db.set_trace_callback(trace)
            yield db

    monkeypatch.setattr(store, "_connect", traced_connect)
    if operation == "core":
        assert store.reserve_core_fact_mutation(_ROBOT, _SLOT) == 1
    elif operation == "episode":
        assert store.reserve_episode_mutation(_ROBOT, _EVENT) == 1
    else:
        assert _remember(store, _ROBOT, _EVENT, "dream")
    assert competing_writer_locked == [True]
