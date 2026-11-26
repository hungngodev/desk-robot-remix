"""Focused observation admission and fanout regression checks."""
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from desk_robot.pet import PetController
from desk_robot.vision import SceneChange


def _controller():
    # Exercise the storage boundary without starting background pet tasks.
    pet = PetController.__new__(PetController)
    pet.settings = SimpleNamespace(
        mode="hardware", voice_vision_tools_enabled=True,
        camera_consent_generation=1, fleet_text_sharing_enabled=True,
        fleet_text_auto_fanout_enabled=True, fleet_sharing_consent_generation=1,
        fleet_auto_fanout_consent_generation=1,
        robots=[SimpleNamespace(id=ident) for ident in ("robot-01", "robot-02", "robot-03")],
    )
    pet.memory = Mock()
    pet.memory.remember.return_value = True
    pet.memory.witnessed_episode_revision.return_value = ("A brass key", 0)
    pet.states = {"robot-01": SimpleNamespace(last_error=None)}
    pet.max_observation_age = 10.0
    pet._vision_preemption_epoch = 0
    pet.multimodal = None
    return pet


@pytest.mark.parametrize("camera_derived, has_receipt, has_identity", [
    (False, True, False), (False, False, True), (True, False, True),
])
@pytest.mark.asyncio
async def test_malformed_camera_provenance_is_rejected_before_memory(
    camera_derived, has_receipt, has_identity,
):
    pet = _controller()
    with pytest.raises(ValueError, match="^Camera receipt provenance requires a camera observation$"):
        await pet._store_observation(
            "robot-01", SceneChange("key", "A brass key", 0.95),
            camera_derived=camera_derived,
            camera_received_at=time.monotonic() if has_receipt else None,
            camera_source_identity=(7, 102, 6000000) if has_identity else None,
        )
    pet.memory.remember.assert_not_called()
    pet.memory.witnessed_episode_revision.assert_not_called()


@pytest.mark.parametrize("revision", [None, ("An edited key", 1)])
@pytest.mark.asyncio
async def test_missing_or_edited_source_stops_automatic_fanout(revision):
    pet = _controller()
    pet.memory.witnessed_episode_revision.return_value = revision
    assert not await pet._store_observation(
        "robot-01", SceneChange("key", "A brass key", 0.95),
    )
    pet.memory.remember.assert_called_once()
    assert pet.memory.remember.call_args.kwargs["witnessed"] is True
    pet.memory.forget_episode.assert_not_called()
    pet.memory.retract_peer_copy.assert_not_called()


@pytest.mark.asyncio
async def test_failed_peer_preserves_witness_and_independent_peer():
    pet = _controller()

    def remember(robot_id, *_args, **_kwargs):
        if robot_id == "robot-02":
            raise OSError("peer database unavailable")
        return True

    pet.memory.remember.side_effect = remember
    assert await pet._store_observation(
        "robot-01", SceneChange("key", "A brass key", 0.95),
    )
    calls = pet.memory.remember.call_args_list
    assert [call.args[0] for call in calls] == ["robot-01", "robot-02", "robot-03"]
    assert [call.kwargs["witnessed"] for call in calls] == [True, False, False]
    assert len({call.args[1] for call in calls}) == 1
    assert pet.states["robot-01"].last_error == "Peer memory robot-02: OSError: peer database unavailable"
    pet.memory.forget_episode.assert_not_called()
    pet.memory.retract_peer_copy.assert_not_called()
