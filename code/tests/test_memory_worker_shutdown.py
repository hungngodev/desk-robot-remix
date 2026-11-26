"""Shutdown drains admitted optional memory without blocking audio scheduling."""

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Event

import pytest
from desk_robot.memory_worker import MemoryWriteBackpressure, OptionalMemoryWriter


def test_cancelled_queued_write_survives_drain_and_close(tmp_path):
    path = tmp_path / "memory.sqlite3"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE memories (value TEXT)")
    entered, release = Event(), Event()
    writer = OptionalMemoryWriter(1)
    writer.close()

    def initialize():
        entered.set()
        assert release.wait(5), "Executor initializer not released"

    # A real executor with a blocked initializer makes the admitted but not
    # yet running future deterministic, unlike racing a newly created thread.
    writer._executor = ThreadPoolExecutor(max_workers=1, initializer=initialize)

    def persist():
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("INSERT INTO memories VALUES ('retained')")

    async def run():
        task = asyncio.create_task(writer.run(persist))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0)
            with pytest.raises(MemoryWriteBackpressure):
                await asyncio.wait_for(writer.run(lambda: None), 0.2)
            draining = asyncio.create_task(writer.drain())
            await asyncio.sleep(0)
            assert not draining.done()
            draining.cancel()
            with pytest.raises(asyncio.CancelledError):
                await draining
            release.set()
            await asyncio.wait_for(writer.drain(), 2)
            await asyncio.to_thread(writer.close)
            with closing(sqlite3.connect(path)) as db, db:
                assert db.execute("SELECT value FROM memories").fetchall() == [("retained",)]
        finally:
            release.set()
            await asyncio.to_thread(writer.close)

    asyncio.run(run())


def test_drain_waits_for_real_sqlite_write_without_blocking_loop(tmp_path):
    path = tmp_path / "memory.sqlite3"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE memories (value TEXT)")
    lock = sqlite3.connect(path)
    lock.execute("BEGIN IMMEDIATE")
    started = Event()
    writer = OptionalMemoryWriter(1)

    def persist():
        with closing(sqlite3.connect(path, timeout=3)) as db, db:
            started.set()
            db.execute("INSERT INTO memories VALUES ('flushed')")

    async def run():
        task = asyncio.create_task(writer.run(persist))
        draining = None
        try:
            assert await asyncio.to_thread(started.wait, 2)
            draining = asyncio.create_task(writer.drain())
            await asyncio.sleep(0)
            assert not draining.done() and not task.done()
            tick = asyncio.Event()
            asyncio.get_running_loop().call_soon(tick.set)
            await asyncio.wait_for(tick.wait(), 0.5)
            assert not draining.done() and not task.done()
            lock.rollback()
            await asyncio.wait_for(draining, 2)
            await asyncio.wait_for(task, 2)
            # Runtime shutdown drains without permanently closing the pool.
            await writer.run(lambda: None)
            assert lock.execute("SELECT value FROM memories").fetchall() == [("flushed",)]
        finally:
            lock.rollback()
            await asyncio.to_thread(writer.close)
            await asyncio.gather(task, return_exceptions=True)
            if draining is not None:
                await asyncio.gather(draining, return_exceptions=True)

    try:
        asyncio.run(run())
    finally:
        lock.close()


def test_runtime_close_drains_after_urgent_owners(monkeypatch):
    from threading import Lock
    from types import SimpleNamespace

    from desk_robot import memory_worker
    from desk_robot.runtime import Runtime

    writer = OptionalMemoryWriter(1)
    monkeypatch.setattr(memory_worker, "optional_memory_writer", writer)
    entered, release, finished = Event(), Event(), Event()

    def persist():
        entered.set()
        assert release.wait(5), "Shutdown test did not release memory write"
        finished.set()

    async def run():
        order = []
        drain_entered = asyncio.Event()

        def owner(label):
            async def stop():
                order.append(label)
            return stop

        original_drain = writer.drain

        async def observed_drain():
            order.append("memory")
            drain_entered.set()
            await original_drain()

        monkeypatch.setattr(writer, "drain", observed_drain)
        runtime = Runtime.__new__(Runtime)
        runtime.settings = SimpleNamespace(mode="simulation")
        runtime.coordinator = SimpleNamespace(
            close=owner("motion"), shutdown_stop_failures={},
        )
        runtime.pet = SimpleNamespace(close=owner("pet"))
        runtime.conversation = SimpleNamespace(stop=owner("conversation"))
        runtime.client = SimpleNamespace(aclose=owner("http"))
        runtime.multimodal = None
        runtime._voice_task = None
        runtime._room_dispatch_lock = Lock()
        runtime._room_dispatch_pending = None
        pending = asyncio.create_task(writer.run(persist))
        shutdown = None
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            shutdown = asyncio.create_task(runtime.close())
            await asyncio.wait_for(drain_entered.wait(), 2)
            assert order == ["motion", "pet", "conversation", "http", "memory"]
            assert not shutdown.done() and not finished.is_set()
            release.set()
            await asyncio.wait_for(shutdown, 2)
            assert finished.is_set()
        finally:
            release.set()
            await asyncio.to_thread(writer.close)
            await asyncio.gather(pending, return_exceptions=True)
            if shutdown is not None:
                await asyncio.gather(shutdown, return_exceptions=True)

    asyncio.run(run())
