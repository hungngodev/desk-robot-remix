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
@pytest.mark.parametrize("phase", ["reserve", "mutate"])
def test_operator_memory_reservation_does_not_block_mac_event_loop(
    settings, tokens, tmp_path, monkeypatch, operation, phase,
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

        reserve_name = (
            "reserve_core_fact_mutation"
            if operation.startswith("core")
            else "reserve_episode_mutation"
        )
        mutate_name = {
            "core_put": "set_core_fact",
            "core_delete": "forget_core_fact",
            "episode_patch": "correct_episode",
            "episode_delete": "forget_episode",
        }[operation]
        original_reserve = getattr(memory, reserve_name)
        original_mutate = getattr(memory, mutate_name)
        reserved = Event()
        reserve_release = Event()
        started = Event()

        def observed_reserve(*args, **kwargs):
            if phase == "reserve":
                started.set()
                return original_reserve(*args, **kwargs)
            generation = original_reserve(*args, **kwargs)
            reserved.set()
            assert reserve_release.wait(timeout=8), "Test did not acquire SQLite lock for mutation phase"
            return generation

        def observed_mutate(*args, **kwargs):
            if phase == "mutate":
                started.set()
            return original_mutate(*args, **kwargs)

        monkeypatch.setattr(memory, reserve_name, observed_reserve)
        monkeypatch.setattr(memory, mutate_name, observed_mutate)
        # Obtain the real ASGI loop BEFORE blocking its SQLite writer.
        # A status callback can stand in for any urgent VAD/STOP callback.
        loop = client.portal.call(asyncio.get_running_loop)
        conn = sqlite3.connect(memory.root / "robot-01.sqlite3")
        try:
            if phase == "reserve":
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
                    if phase == "mutate":
                        assert reserved.wait(timeout=8), "Reservation never committed"
                        conn.execute("BEGIN IMMEDIATE")
                        reserve_release.set()
                    assert started.wait(timeout=8), f"{phase} SQLite phase never began"
                    # Original inline BEGIN IMMEDIATE blocks the Mac loop for
                    # the 3s SQLite busy timeout. The threaded owner does not.
                    tick = Event()
                    loop.call_soon_threadsafe(tick.set)
                    assert tick.wait(timeout=0.5), (
                        f"SQLite {phase} blocked urgent event-loop work"
                    )
                    assert not pending.done(), (
                        f"HTTP request returned while SQLite write lock held during {phase}"
                    )
                finally:
                    reserve_release.set()
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


@pytest.mark.parametrize("operation", ["core_put", "episode_patch"])
def test_cancelled_mutation_finishes_and_invalidates_private_context(
    settings, tokens, tmp_path, monkeypatch, operation,
):
    """A disconnected caller cannot abandon an admitted privacy edit."""
    settings.memory_dir = tmp_path
    headers = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    robot_id = "robot-01"
    peer_id = "robot-02"
    committed, release, invalidated = Event(), Event(), Event()

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        store = runtime.memory
        conversation = runtime.conversation
        assert store.set_core_fact(robot_id, "favorite_game", "chess")
        assert store.set_core_fact(peer_id, "favorite_game", "puzzles")
        if operation == "core_put":
            method = "PUT"
            url = f"/v1/pet/{robot_id}/core-memory/favorite_game"
            payload = {"value": "checkers"}
            mutate_name = "set_core_fact"
        else:
            assert store.remember(
                robot_id, "event_a", "Original key",
                kind="key", source_robot=robot_id, witnessed=True,
            )
            method = "PATCH"
            url = f"/v1/pet/{robot_id}/memories/event_a"
            payload = {"summary": "Corrected key"}
            mutate_name = "correct_episode"

        original_mutate = getattr(store, mutate_name)
        original_invalidate = conversation.invalidate_private_memory
        baseline = dict(conversation._private_memory_generation)

        def observed_mutate(*args, **kwargs):
            changed = original_mutate(*args, **kwargs)
            if args[0] == robot_id:
                committed.set()
                if not release.wait(timeout=8):
                    raise TimeoutError("Test did not release committed mutation")
            return changed

        def observed_invalidate(target):
            original_invalidate(target)
            if target == robot_id:
                invalidated.set()

        monkeypatch.setattr(store, mutate_name, observed_mutate)
        monkeypatch.setattr(conversation, "invalidate_private_memory", observed_invalidate)

        async def scenario():
            transport = httpx.ASGITransport(app=client.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver",
            ) as api:
                first = asyncio.create_task(api.request(
                    method, url, headers=headers, json=payload,
                ))
                try:
                    assert await asyncio.to_thread(committed.wait, 3)
                    first.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await first
                    assert not invalidated.is_set()
                    peer = await asyncio.wait_for(api.put(
                        f"/v1/pet/{peer_id}/core-memory/favorite_game",
                        headers=headers, json={"value": "go"},
                    ), timeout=3)
                    assert peer.status_code == 200, peer.text
                finally:
                    release.set()
                assert await asyncio.to_thread(invalidated.wait, 3), (
                    "Committed edit lost prompt invalidation when its caller cancelled"
                )
                followup = await asyncio.wait_for(api.put(
                    f"/v1/pet/{robot_id}/core-memory/favorite_color",
                    headers=headers, json={"value": "blue"},
                ), timeout=3)
                assert followup.status_code == 200, followup.text

        try:
            client.portal.call(scenario)
        finally:
            release.set()
        assert conversation._private_memory_generation == {
            robot_id: baseline[robot_id] + 2,
            peer_id: baseline[peer_id] + 1,
        }
        assert store.core_facts(peer_id)[0].value == "go"
        facts = {fact.slot: fact.value for fact in store.core_facts(robot_id)}
        assert facts["favorite_color"] == "blue"
        if operation == "core_put":
            assert facts["favorite_game"] == "checkers"
        else:
            assert store.get_episode(robot_id, "event_a").summary == "Corrected key"
            assert facts["favorite_game"] == "chess"
