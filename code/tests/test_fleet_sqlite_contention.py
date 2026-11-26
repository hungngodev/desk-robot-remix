"""Exercise real private SQLite transactions under simultaneous fleet load."""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from desk_robot.memory import MemoryStore

IDS = [f"robot-{i:02}" for i in range(1, 6)]
WORDS = ("amber", "birch", "cobalt", "dahlia", "elm")


def _insert(db, robot_id, word, index):
    db.execute(
        "INSERT INTO memories "
        "(event_id,source_robot,witnessed,kind,summary,observed_at,confidence) "
        "VALUES (?,?,1,'observation',?,?,1)",
        (f"event_{index}", robot_id, word, index),
    )


@pytest.mark.parametrize("journal_mode", ["delete", "wal"])
def test_five_private_writers_hold_transactions_simultaneously(tmp_path, journal_mode):
    store = MemoryStore(tmp_path, IDS)
    # Fresh databases use rollback journaling. Exercise existing WAL databases
    # too without requiring a global production journal-mode migration.
    if journal_mode == "wal":
        for robot_id in IDS:
            with store._connect(robot_id) as db:
                assert db.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)

    writers_ready = threading.Barrier(len(IDS), timeout=10)
    readers_done = threading.Barrier(len(IDS), timeout=10)

    def workload(robot_id, word):
        for index in range(20):
            with store._connect(robot_id) as db:
                assert db.execute("PRAGMA journal_mode").fetchone() == (journal_mode,)
                assert db.execute("PRAGMA busy_timeout").fetchone() == (3000,)
                assert db.execute("PRAGMA secure_delete").fetchone() == (1,)
                db.execute("BEGIN IMMEDIATE")
                _insert(db, robot_id, word, index)
                if index == 0:
                    # Every writer must acquire its real SQLite write lock
                    # before ANY commit. A shared database cannot pass this.
                    writers_ready.wait()
                    with store._connect(robot_id) as reader:
                        assert reader.execute("SELECT count(*) FROM memories").fetchone() == (0,)
                    readers_done.wait()
            with store._connect(robot_id) as reader:
                count = reader.execute("SELECT count(*) FROM memories").fetchone()
                assert count == (index + 1,)

    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = [
            pool.submit(workload, robot_id, word)
            for robot_id, word in zip(IDS, WORDS, strict=True)
        ]
        for job in jobs:
            job.result(timeout=30)

    # Reused event IDs must not collide or leak into another pet's FTS index.
    for robot_id, word in zip(IDS, WORDS, strict=True):
        with store._connect(robot_id) as db:
            assert db.execute(
                "SELECT DISTINCT source_robot,summary FROM memories"
            ).fetchall() == [(robot_id, word)]
            for candidate in WORDS:
                assert db.execute(
                    "SELECT count(*) FROM memories_fts WHERE memories_fts MATCH ?",
                    (candidate,),
                ).fetchone() == (20 if candidate == word else 0,)
            assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_busy_writer_is_local_to_one_pet(tmp_path):
    store = MemoryStore(tmp_path, IDS)

    def write(robot_id):
        with store._connect(robot_id) as db:
            db.execute("BEGIN IMMEDIATE")
            _insert(db, robot_id, "local", 0)

    with ThreadPoolExecutor(max_workers=5) as pool:
        with store._connect(IDS[0]) as locked:
            locked.execute("BEGIN IMMEDIATE")
            blocked = pool.submit(write, IDS[0])
            peers = [pool.submit(write, robot_id) for robot_id in IDS[1:]]
            for peer in peers:
                peer.result(timeout=10)
            with pytest.raises(sqlite3.OperationalError, match="database is locked"):
                blocked.result(timeout=10)
            assert locked.execute("SELECT count(*) FROM memories").fetchone() == (0,)
        # The failed writer did not poison future writes or affect peer data.
        write(IDS[0])
    for robot_id in IDS:
        with store._connect(robot_id) as db:
            assert db.execute("SELECT source_robot FROM memories").fetchall() == [(robot_id,)]
