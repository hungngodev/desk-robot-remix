"""Operator correction and deletion fence asynchronous automatic peer memories."""

import asyncio
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


@pytest.mark.parametrize("pause_at", ["source", "peer"])
@pytest.mark.parametrize("operator_action", ["patch", "delete"])
@pytest.mark.asyncio
async def test_completed_operator_edit_cannot_be_newly_auto_fanned_out(
    fleet, tokens, tmp_path, monkeypatch, pause_at, operator_action,
):
    # A full authenticated operator request shares the same private SQLite
    # source as the proactive worker; no artificial consent toggle is used.
    fleet.memory_dir = tmp_path
    fleet.fleet_text_sharing_enabled = True
    fleet.fleet_text_auto_fanout_enabled = True
    headers = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    url = f"/v1/pet/robot-01/memories/{EVENT_ID}"
    inserted, release = Event(), Event()

    with TestClient(create_app(fleet)) as client:
        memory = client.app.state.runtime.memory
        # A preexisting independently authorized peer copy is not ours to
        # retract, even when it shares the same event identity.
        assert memory.remember(
            "robot-03", EVENT_ID, OLDER_PEER_SUMMARY,
            kind="key", source_robot="robot-01", witnessed=False,
        )
        original = memory.remember
        blocked_robot = "robot-01" if pause_at == "source" else "robot-02"

        def pause_after_commit(robot_id, event_id, summary, **kwargs):
            saved = original(robot_id, event_id, summary, **kwargs)
            if robot_id == blocked_robot and event_id == EVENT_ID and saved:
                inserted.set()
                if not release.wait(timeout=8):
                    raise TimeoutError("Fixture did not release committed write")
            return saved

        monkeypatch.setattr(memory, "remember", pause_after_commit)
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
            assert await asyncio.wait_for(
                asyncio.to_thread(inserted.wait, 4), timeout=5,
            ), "No relevant SQLite write completed"
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
        finally:
            release.set()
        try:
            await asyncio.wait_for(pending, timeout=5)
            assert memory.get_episode("robot-02", EVENT_ID) is None
            existing = memory.get_episode("robot-03", EVENT_ID)
            assert existing is not None
            assert existing.summary == OLDER_PEER_SUMMARY
            assert existing.source_robot == "robot-01"
            assert existing.witnessed is False
            source = memory.get_episode("robot-01", EVENT_ID)
            if operator_action == "patch":
                assert source is not None
                assert source.summary == "Operator corrected blue key"
                assert not memory.search("robot-02", "private")
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
