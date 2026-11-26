"""Slow SQLite commits cannot starve urgent loop or default executor work."""

import asyncio
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Event

import pytest
from desk_robot.memory_worker import MemoryWriteBackpressure, OptionalMemoryWriter


def test_slow_commit_isolated_from_voice_workers(tmp_path):
    writer = OptionalMemoryWriter(1)
    entered, release = Event(), Event()
    db_path = tmp_path / "memory.sqlite3"
    with closing(sqlite3.connect(db_path)) as db:
        db.execute("CREATE TABLE memory (value TEXT)")
        db.commit()

    class SlowCommit(sqlite3.Connection):
        def commit(self):
            entered.set()
            if not release.wait(2):
                raise TimeoutError("Test did not release simulated fsync")
            super().commit()

    def write():
        db = sqlite3.connect(db_path, factory=SlowCommit)
        try:
            db.execute("INSERT INTO memory VALUES ('remembered')")
            db.commit()
        finally:
            db.close()

    async def scenario():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        pending = asyncio.create_task(writer.run(write))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 1), 1.5)
            before = time.monotonic()
            # Simulate urgent voice work using the otherwise shared executor.
            assert await asyncio.wait_for(asyncio.to_thread(lambda: "voice"), 0.5) == "voice"
            voice_ms = (time.monotonic() - before) * 1000
            assert voice_ms < 500
            await asyncio.sleep(0.35)
            print(f"Voice callback: {voice_ms:.2f} ms; simulated commit held >= 350 ms")
            assert not pending.done()
            with closing(sqlite3.connect(db_path)) as db:
                assert db.execute("SELECT value FROM memory").fetchall() == []
        finally:
            release.set()
            await pending

    try:
        asyncio.run(scenario())
        with closing(sqlite3.connect(db_path)) as db:
            assert db.execute("SELECT value FROM memory").fetchall() == [("remembered",)]
    finally:
        release.set()
        writer.close()


def test_cancelled_waiter_does_not_release_running_transaction():
    writer = OptionalMemoryWriter(1)
    entered, release = Event(), Event()
    finished = Event()

    def write():
        entered.set()
        if not release.wait(2):
            raise TimeoutError("Test did not release transaction")
        finished.set()

    async def scenario():
        pending = asyncio.create_task(writer.run(write))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            with pytest.raises(MemoryWriteBackpressure):
                await writer.run(lambda: pytest.fail("Overloaded transaction was admitted"))
            assert not finished.is_set()
        finally:
            release.set()

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        writer.close()
    assert finished.is_set()


def test_failed_transaction_rolls_back_and_releases_slot(tmp_path):
    writer = OptionalMemoryWriter(1)
    db_path = tmp_path / "memory.sqlite3"
    with closing(sqlite3.connect(db_path)) as db:
        db.execute("CREATE TABLE memory (value TEXT)")
        db.commit()

    def failed_write():
        db = sqlite3.connect(db_path)
        try:
            with db:
                db.execute("INSERT INTO memory VALUES ('uncommitted')")
                raise sqlite3.OperationalError("simulated write failure")
        finally:
            db.close()

    async def scenario():
        with pytest.raises(sqlite3.OperationalError):
            await writer.run(failed_write)
        await writer.run(lambda: None)

    try:
        asyncio.run(scenario())
        with closing(sqlite3.connect(db_path)) as db:
            assert db.execute("SELECT value FROM memory").fetchall() == []
    finally:
        writer.close()
