"""A slow SQLite reservation cannot stall human speech scheduling."""

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest
from desk_robot.api import create_app
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "operation",
    ["core_put", "core_delete", "episode_patch", "episode_delete"],
)
def test_operator_memory_reservation_does_not_block_mac_event_loop(
    settings, tokens, tmp_path, monkeypatch, operation,
):
    settings.memory_dir = tmp_path
    auth = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    core_url = "/v1/pet/robot-01/core-memory/favorite_game"
    episode_url = "/v1/pet/robot-01/memories/event_a"

    with TestClient(create_app(settings)) as client:
        memory = client.app.state.runtime.memory
        if operation == "core_delete":
            assert memory.set_core_fact("robot-01", "favorite_game", "chess")
        elif operation.startswith("episode"):
            assert memory.remember(
                "robot-01", "event_a", "A silver key",
                kind="key", source_robot="robot-01", witnessed=True,
            )

        method_name = (
            "reserve_core_fact_mutation"
            if operation.startswith("core")
            else "reserve_episode_mutation"
        )
        original = getattr(memory, method_name)
        started = Event()

        def observed_reserve(*args, **kwargs):
            started.set()
            return original(*args, **kwargs)

        monkeypatch.setattr(memory, method_name, observed_reserve)
        # Obtain the real ASGI loop BEFORE blocking its SQLite writer.
        # A status callback can stand in for any urgent VAD/STOP callback.
        loop = client.portal.call(asyncio.get_running_loop)
        conn = sqlite3.connect(memory.root / "robot-01.sqlite3")
        try:
            conn.execute("BEGIN IMMEDIATE")

            def request():
                if operation == "core_put":
                    return client.put(
                        core_url, headers=auth, json={"value": "checkers"},
                    )
                if operation == "core_delete":
                    return client.delete(core_url, headers=auth)
                if operation == "episode_patch":
                    return client.patch(
                        episode_url, headers=auth, json={"summary": "A brass key"},
                    )
                return client.delete(episode_url, headers=auth)

            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(request)
                try:
                    assert started.wait(timeout=8), "Reservation never began"
                    # Original inline BEGIN IMMEDIATE blocks the Mac loop for
                    # the 3s SQLite busy timeout. The threaded owner does not.
                    tick = Event()
                    loop.call_soon_threadsafe(tick.set)
                    assert tick.wait(timeout=0.5), (
                        "SQLite reservation blocked urgent event-loop work"
                    )
                finally:
                    conn.rollback()
                result = pending.result(timeout=8)
                assert result.status_code == 200, result.text

            if operation == "core_put":
                assert memory.core_facts("robot-01")[0].value == "checkers"
            elif operation == "core_delete":
                assert memory.core_facts("robot-01") == []
            elif operation == "episode_patch":
                assert memory.get_episode("robot-01", "event_a").summary == "A brass key"
            else:
                assert memory.get_episode("robot-01", "event_a") is None
        finally:
            conn.close()


def test_cancelled_request_retains_reservation_order(
    settings, tokens, tmp_path, monkeypatch,
):
    # An HTTP disconnect cannot cancel a running SQLite thread. The thread's
    # reservation still owns its earlier position in the per-robot queue.
    settings.memory_dir = tmp_path
    headers = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    url = "/v1/pet/robot-01/memories/event_a"
    started, release, later_entered = Event(), Event(), Event()

    with TestClient(create_app(settings)) as client:
        store = client.app.state.runtime.memory
        assert store.remember(
            "robot-01", "event_a", "Original key",
            kind="key", source_robot="robot-01", witnessed=True,
        )
        original = store.reserve_episode_mutation

        def slow_reservation(robot_id, event_id, summary=None):
            if summary == "abandoned request":
                started.set()
                if not release.wait(timeout=8):
                    raise TimeoutError("Test did not release first reservation")
            if summary == "final request":
                later_entered.set()
            return original(robot_id, event_id, summary)

        monkeypatch.setattr(store, "reserve_episode_mutation", slow_reservation)

        async def scenario():
            transport = httpx.ASGITransport(app=client.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver",
            ) as api:
                first = asyncio.create_task(api.patch(
                    url, headers=headers, json={"summary": "abandoned request"},
                ))
                assert await asyncio.to_thread(started.wait, 3)
                first.cancel()
                await asyncio.gather(first, return_exceptions=True)
                later = asyncio.create_task(api.patch(
                    url, headers=headers, json={"summary": "final request"},
                ))
                try:
                    await asyncio.sleep(0.1)
                    assert not later_entered.is_set(), (
                        "Cancelled request released a live SQLite reservation"
                    )
                finally:
                    release.set()
                result = await asyncio.wait_for(later, timeout=8)
                assert result.status_code == 200, result.text
                assert result.json()["corrected"] is True

        try:
            client.portal.call(scenario)
        finally:
            release.set()
        assert later_entered.is_set()
        assert store.get_episode("robot-01", "event_a").summary == "final request"
