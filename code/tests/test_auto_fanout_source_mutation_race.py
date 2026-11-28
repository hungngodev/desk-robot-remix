"""Operator correction and deletion fence asynchronous automatic peer memories."""

import asyncio
import random
import time
from pathlib import Path
from threading import Event

import pytest
from desk_robot.api import create_app
from desk_robot.config import load_settings
from desk_robot.conversation import Conversation
from desk_robot.pet import PetController
from desk_robot.simulator import SimulatedChat, SimulatedScene, SimulatedSpeaker
from desk_robot.vision import SceneChange
from fastapi.testclient import TestClient


@pytest.fixture
def fleet():
    return load_settings(
        Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    )


EVENT_ID = "camera_robot-01_00000007_00000009_f4240"
DESCRIPTION = "A private red key appeared"
OLDER_PEER_SUMMARY = "A previously shared independent record"


@pytest.mark.parametrize("pause_at", ["source", "peer", "last_peer", "after_batch"])
@pytest.mark.parametrize("operator_action", ["patch", "delete"])
@pytest.mark.parametrize("seed", [0, 19])
@pytest.mark.asyncio
async def test_completed_operator_edit_cannot_be_newly_auto_fanned_out(
    fleet, tokens, tmp_path, monkeypatch, pause_at, operator_action, seed,
):
    # A full authenticated operator request shares the same private SQLite
    # source as the proactive worker; no artificial consent toggle is used.
    fleet.memory_dir = tmp_path
    fleet.fleet_text_sharing_enabled = True
    fleet.fleet_text_auto_fanout_enabled = True
    headers = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    url = f"/v1/pet/robot-01/memories/{EVENT_ID}"
    inserted, release, last_peer_saved = Event(), Event(), Event()
    rng = random.Random(seed)

    with TestClient(create_app(fleet)) as client:
        memory = client.app.state.runtime.memory
        # A preexisting independently authorized peer copy is not ours to
        # retract, even when it shares the same event identity.
        assert memory.remember(
            "robot-03", EVENT_ID, OLDER_PEER_SUMMARY,
            kind="key", source_robot="robot-01", witnessed=False,
        )
        original = memory.remember
        original_revision = memory.witnessed_episode_revision
        blocked_robot = {"source": "robot-01", "peer": "robot-02",
                         "last_peer": "robot-05"}.get(pause_at)

        def pause():
            inserted.set()
            if not release.wait(timeout=8):
                raise TimeoutError("Fixture did not release committed write")

        def pause_after_commit(robot_id, event_id, summary, **kwargs):
            saved = original(robot_id, event_id, summary, **kwargs)
            if event_id == EVENT_ID and saved:
                if robot_id == "robot-05":
                    last_peer_saved.set()
                if robot_id == blocked_robot:
                    pause()
            return saved

        def pause_after_batch_read(robot_id, event_id):
            revision = original_revision(robot_id, event_id)
            # Return the old revision after the edit. The batch's final check
            # cannot see it; the independent coroutine fence must retract.
            if (pause_at == "after_batch" and robot_id == "robot-01"
                    and event_id == EVENT_ID and last_peer_saved.is_set()
                    and not inserted.is_set()):
                pause()
            return revision

        monkeypatch.setattr(memory, "remember", pause_after_commit)
        monkeypatch.setattr(memory, "witnessed_episode_revision", pause_after_batch_read)
        speaker = SimulatedSpeaker()
        pet = PetController(
            fleet, {},
            Conversation(fleet, SimulatedChat(), speaker, memory=memory),
            memory, SimulatedScene(),
        )
        pending = asyncio.create_task(pet._store_observation(
            "robot-01", SceneChange("key", DESCRIPTION, 0.95),
            camera_derived=True,
            camera_received_at=time.monotonic(),
            camera_source_identity=(7, 9, 1000000),
        ))
        try:
            try:
                assert await asyncio.wait_for(
                    asyncio.to_thread(inserted.wait, 4), timeout=5,
                ), "No relevant SQLite write completed"
                for _ in range(rng.randrange(1, 9)):
                    await asyncio.sleep(0)
                if operator_action == "patch":
                    response = await asyncio.to_thread(
                        client.patch, url, headers=headers,
                        json={"summary": "Operator corrected blue key"},
                    )
                    assert response.status_code == 200 and response.json()["corrected"]
                else:
                    response = await asyncio.to_thread(
                        client.delete, url, headers=headers,
                    )
                    assert response.status_code == 200 and response.json()["removed"]
                for _ in range(rng.randrange(1, 9)):
                    await asyncio.sleep(0)
            finally:
                release.set()
            await asyncio.wait_for(pending, timeout=5)
            for peer in fleet.robots:
                if peer.id not in {"robot-01", "robot-03"}:
                    assert memory.get_episode(peer.id, EVENT_ID) is None, peer.id
                    assert not memory.search(peer.id, "private"), peer.id
            existing = memory.get_episode("robot-03", EVENT_ID)
            assert existing is not None
            assert existing.summary == OLDER_PEER_SUMMARY
            assert existing.source_robot == "robot-01"
            assert existing.witnessed is False
            source = memory.get_episode("robot-01", EVENT_ID)
            if operator_action == "patch":
                assert source is not None
                assert source.summary == "Operator corrected blue key"
            else:
                assert source is None
        finally:
            await asyncio.gather(pending, return_exceptions=True)
            await pet.close()


@pytest.mark.asyncio
async def test_unchanged_eyewitness_auto_fans_out_once_as_hearsay(
    fleet, tmp_path,
):
    fleet.fleet_text_sharing_enabled = True
    fleet.fleet_text_auto_fanout_enabled = True
    from desk_robot.memory import MemoryStore

    memory = MemoryStore(tmp_path, [robot.id for robot in fleet.robots])
    pet = PetController(
        fleet, {},
        Conversation(
            fleet, SimulatedChat(), SimulatedSpeaker(), memory=memory,
        ),
        memory, SimulatedScene(),
    )
    try:
        await pet._store_observation(
            "robot-01", SceneChange("key", DESCRIPTION, 0.95),
            camera_derived=True,
            camera_received_at=time.monotonic(),
            camera_source_identity=(7, 9, 1000000),
        )
        source = memory.get_episode("robot-01", EVENT_ID)
        assert source is not None and source.witnessed
        for peer in fleet.robots[1:]:
            shared = memory.get_episode(peer.id, EVENT_ID)
            assert shared is not None
            assert shared.summary == DESCRIPTION
            assert shared.source_robot == "robot-01"
            assert not shared.witnessed
    finally:
        await pet.close()
