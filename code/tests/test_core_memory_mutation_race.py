"""Operator core fact mutation order survives delayed SQLite workers."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from desk_robot.api import create_app
from desk_robot.api_memory_routes import (
    CoreMemoryRequest,
    EpisodeMemoryCorrectionRequest,
    register_memory_routes,
)
from desk_robot.memory import CoreMemoryMutationSuperseded, MemoryStore
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_core_slot_mutations_are_versioned_and_private_across_reopen(tmp_path):
    store = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    early = store.reserve_core_fact_mutation("robot-01", "favorite_color", "red")
    deletion = store.reserve_core_fact_mutation("robot-01", "favorite_color")
    assert deletion > early
    assert not store.forget_core_fact(
        "robot-01", "favorite_color", mutation_generation=deletion,
    )
    with pytest.raises(CoreMemoryMutationSuperseded):
        store.set_core_fact(
            "robot-01", "favorite_color", "red", mutation_generation=early,
        )
    assert store.core_facts("robot-01") == []

    reopened = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    with pytest.raises(CoreMemoryMutationSuperseded):
        reopened.set_core_fact(
            "robot-01", "favorite_color", "red", mutation_generation=early,
        )
    fresh = reopened.reserve_core_fact_mutation(
        "robot-01", "favorite_color", "green",
    )
    assert reopened.set_core_fact(
        "robot-01", "favorite_color", "green", mutation_generation=fresh,
    )
    assert reopened.core_facts("robot-01")[0].value == "green"
    assert reopened.core_facts("robot-02") == []
    for invalid in (0, -1, True, 3.0, "3"):
        with pytest.raises(ValueError, match="generation"):
            reopened.set_core_fact(
                "robot-01", "favorite_color", "blue",
                mutation_generation=invalid,
            )


def test_completed_operator_delete_fences_older_pending_put(
    settings, tokens, tmp_path, monkeypatch,
):
    settings.memory_dir = tmp_path
    auth = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    key = "/v1/pet/robot-01/core-memory/favorite_color"
    peer = "/v1/pet/robot-02/core-memory/favorite_color"
    started, release = Event(), Event()
    with TestClient(create_app(settings)) as client:
        assert client.put(key, headers=auth, json={"value": "red"}).status_code == 200
        assert client.put(peer, headers=auth, json={"value": "yellow"}).status_code == 200
        store = client.app.state.runtime.memory
        original = store.set_core_fact

        def delayed_put(robot_id, slot, value, *, mutation_generation=None):
            if robot_id == "robot-01" and value == "blue":
                started.set()
                assert release.wait(timeout=8), "Timed out waiting for DELETE"
            return original(
                robot_id, slot, value, mutation_generation=mutation_generation,
            )

        monkeypatch.setattr(store, "set_core_fact", delayed_put)
        with ThreadPoolExecutor(max_workers=1) as workers:
            old_put = workers.submit(
                client.put, key, headers=auth, json={"value": "blue"},
            )
            try:
                assert started.wait(timeout=8), "Old PUT never reached worker"
                removal = client.delete(key, headers=auth)
                assert removal.status_code == 200
                assert removal.json()["removed"] is True
                assert client.get(
                    key.rsplit("/", 1)[0], headers=auth,
                ).json()["core_facts"] == []
            finally:
                release.set()
            assert old_put.result(timeout=8).status_code == 409

        assert client.get(
            key.rsplit("/", 1)[0], headers=auth,
        ).json()["core_facts"] == []
        assert client.get(
            peer.rsplit("/", 1)[0], headers=auth,
        ).json()["core_facts"][0]["value"] == "yellow"
        response = client.put(key, headers=auth, json={"value": "green"})
        assert response.status_code == 200 and response.json()["changed"]
        assert client.get(
            key.rsplit("/", 1)[0], headers=auth,
        ).json()["core_facts"][0]["value"] == "green"


def test_old_delete_cannot_remove_newer_operator_update(tmp_path):
    store = MemoryStore(tmp_path, ["robot-01"])
    store.set_core_fact("robot-01", "nickname", "old")
    old_delete = store.reserve_core_fact_mutation("robot-01", "nickname")
    later_put = store.reserve_core_fact_mutation("robot-01", "nickname", "new")
    assert store.set_core_fact(
        "robot-01", "nickname", "new", mutation_generation=later_put,
    )
    with pytest.raises(CoreMemoryMutationSuperseded):
        store.forget_core_fact(
            "robot-01", "nickname", mutation_generation=old_delete,
        )
    assert store.core_facts("robot-01")[0].value == "new"


@pytest.mark.parametrize(
    "action",
    ["core_put", "core_delete", "episode_patch", "episode_delete",
     "episode_missing_delete"],
)
def test_cancelled_dispatched_memory_edit_still_retracts_prompt(
    settings, tmp_path, monkeypatch, action,
):
    """Cancelling the route cannot abandon cleanup for a committed edit."""
    async def run():
        robot_id, event_id, slot = "robot-01", "old_event", "nickname"
        store = MemoryStore(tmp_path, ["robot-01", "robot-02"])
        store.set_core_fact(robot_id, slot, "old")
        store.set_core_fact("robot-02", slot, "peer")
        if action != "episode_missing_delete":
            assert store.remember(
                robot_id, event_id, "old episode", kind="key",
                source_robot=robot_id, witnessed=True,
            )
        assert store.remember(
            "robot-02", event_id, "peer episode", kind="key",
            source_robot="robot-02", witnessed=True,
        )
        invalidated = asyncio.Event()
        revisions, discarded_tools, discarded_heard = [], [], []
        started, release = Event(), Event()

        def invalidate(rid):
            revisions.append(rid)
            invalidated.set()

        hub = SimpleNamespace(
            discard_memory_tools=discarded_tools.append,
            discard_heard=lambda rid, eid: discarded_heard.append((rid, eid)),
        )
        app = FastAPI()
        app.state.runtime = SimpleNamespace(
            memory=store, multimodal=SimpleNamespace(hub=hub),
            conversation=SimpleNamespace(invalidate_private_memory=invalidate),
        )
        register_memory_routes(app, settings, operator=lambda: None)
        endpoints = {route.name: route.endpoint for route in app.routes}
        if action == "core_put":
            method, route_name = "set_core_fact", "set_core_memory"
            args = (robot_id, slot, CoreMemoryRequest(value="new"))
        elif action == "core_delete":
            method, route_name = "forget_core_fact", "delete_core_memory"
            args = (robot_id, slot)
        elif action == "episode_patch":
            method, route_name = "correct_episode", "correct_episode"
            args = (robot_id, event_id, EpisodeMemoryCorrectionRequest(
                summary="new episode",
            ))
        else:
            method, route_name = "forget_episode", "delete_episode"
            args = (robot_id, event_id)
        original = getattr(store, method)

        def delayed(*args, **kwargs):
            started.set()
            assert release.wait(8), "Mutation never released"
            return original(*args, **kwargs)

        monkeypatch.setattr(store, method, delayed)
        request = asyncio.create_task(endpoints[route_name](*args))
        try:
            assert await asyncio.to_thread(started.wait, 8)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
        finally:
            release.set()
        await asyncio.wait_for(invalidated.wait(), timeout=8)
        assert revisions == discarded_tools == [robot_id]
        if action.startswith("episode_"):
            assert discarded_heard == [(robot_id, event_id)]
            episode = store.get_episode(robot_id, event_id)
            if action == "episode_patch":
                assert episode is not None and episode.summary == "new episode"
            else:
                assert episode is None
                assert not store.remember(
                    robot_id, event_id, "late transcript", kind="key",
                    source_robot=robot_id, witnessed=True,
                )
        else:
            assert discarded_heard == []
            facts = store.core_facts(robot_id)
            if action == "core_put":
                assert facts[0].value == "new"
            else:
                assert facts == []
        assert store.core_facts("robot-02")[0].value == "peer"
        assert store.get_episode("robot-02", event_id).summary == "peer episode"

    asyncio.run(run())
