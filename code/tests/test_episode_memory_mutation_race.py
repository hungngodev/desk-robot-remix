"""Authenticated episode edits remain ordered across delayed SQLite workers."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from desk_robot.api import create_app
from desk_robot.memory import (
    EpisodeMemoryMutationSuperseded,
    MemoryStore,
)
from fastapi.testclient import TestClient


def _remember(store, robot_id, event_id):
    assert store.remember(
        robot_id, event_id, "A silver key appeared", kind="key",
        source_robot=robot_id, witnessed=True,
        observed_at=1234.5, confidence=0.75,
    )


def test_episode_mutation_tokens_are_durable_private_and_checked(tmp_path):
    store = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    _remember(store, "robot-01", "shared_id")
    _remember(store, "robot-02", "shared_id")
    early = store.reserve_episode_mutation("robot-01", "shared_id", "first")
    newer = store.reserve_episode_mutation("robot-01", "shared_id", "final")
    assert newer > early
    assert store.correct_episode(
        "robot-01", "shared_id", "final", mutation_generation=newer,
    )
    with pytest.raises(EpisodeMemoryMutationSuperseded):
        store.correct_episode(
            "robot-01", "shared_id", "first", mutation_generation=early,
        )
    assert store.recent("robot-01")[0].summary == "final"
    assert store.recent("robot-02")[0].summary == "A silver key appeared"
    assert MemoryStore(tmp_path, ["robot-01", "robot-02"]).recent(
        "robot-01"
    )[0].summary == "final"

    for invalid in (0, -1, True, 3.5, "3"):
        with pytest.raises(ValueError, match="generation"):
            store.correct_episode(
                "robot-01", "shared_id", "bad", mutation_generation=invalid,
            )
    with pytest.raises(ValueError, match="Bounded"):
        store.reserve_episode_mutation("robot-01", "shared_id", "\x00")
    old = store.reserve_episode_mutation("robot-01", "shared_id", "old")
    # An internal safety cleanup must retire pending HTTP patch generations.
    assert store.forget_episode("robot-01", "shared_id")
    with pytest.raises(EpisodeMemoryMutationSuperseded):
        store.correct_episode(
            "robot-01", "shared_id", "old", mutation_generation=old,
        )
    assert not store.remember(
        "robot-01", "shared_id", "resurrection", kind="key",
        source_robot="robot-01", witnessed=True,
    )
    assert store.count("robot-02") == 1


@pytest.mark.parametrize("newer_action", ["patch", "delete"])
def test_authenticated_episode_mutation_rejects_stale_patch(
    settings, tokens, tmp_path, monkeypatch, newer_action,
):
    settings.memory_dir = tmp_path
    headers = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    target = "/v1/pet/robot-01/memories/slow_episode"
    peer = "/v1/pet/robot-02/memories/slow_episode"
    started, release = Event(), Event()

    with TestClient(create_app(settings)) as client:
        store = client.app.state.runtime.memory
        _remember(store, "robot-01", "slow_episode")
        _remember(store, "robot-02", "slow_episode")
        original = store.correct_episode

        def delayed_patch(robot_id, event_id, summary, *, mutation_generation=None):
            if robot_id == "robot-01" and summary == "old request":
                started.set()
                assert release.wait(timeout=8), "Old PATCH never released"
            return original(
                robot_id, event_id, summary,
                mutation_generation=mutation_generation,
            )

        monkeypatch.setattr(store, "correct_episode", delayed_patch)
        with ThreadPoolExecutor(max_workers=1) as pool:
            old = pool.submit(
                client.patch, target, headers=headers,
                json={"summary": "old request"},
            )
            try:
                assert started.wait(timeout=8), "Old PATCH not dispatched"
                assert client.patch(
                    peer, headers=headers, json={"summary": "independent peer"},
                ).status_code == 200
                if newer_action == "patch":
                    newer = client.patch(
                        target, headers=headers, json={"summary": "final request"},
                    )
                    assert newer.status_code == 200
                    assert newer.json()["corrected"] is True
                else:
                    newer = client.delete(target, headers=headers)
                    assert newer.status_code == 200
                    assert newer.json()["removed"] is True
            finally:
                release.set()
            assert old.result(timeout=8).status_code == 409

        listed = client.get(
            "/v1/pet/robot-01/memories", headers=headers,
        ).json()["records"]
        if newer_action == "patch":
            assert next(
                r["summary"] for r in listed if r["event_id"] == "slow_episode"
            ) == "final request"
            assert store.search("robot-01", "final")
            assert not store.search("robot-01", "old")
        else:
            assert not any(r["event_id"] == "slow_episode" for r in listed)
            assert store.search("robot-01", "silver") == []
        assert store.recent("robot-02")[0].summary == "independent peer"

    reopened = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    actual = reopened.get_episode("robot-01", "slow_episode")
    if newer_action == "patch":
        assert actual is not None and actual.summary == "final request"
    else:
        assert actual is None
    assert reopened.get_episode("robot-02", "slow_episode").summary == "independent peer"
