"""Physical interactions are per-pet; repeated shared camera scenes are not."""
from __future__ import annotations

import asyncio
import time
from io import BytesIO
from types import SimpleNamespace

import pytest
from desk_robot.conversation import Conversation
from desk_robot.memory import MemoryStore
from desk_robot.multimodal import CameraFrameHub
from desk_robot.pet import PetController
from desk_robot.simulator import SimulatedSpeaker
from desk_robot.vision import SceneChange, VisualChangeGate
from PIL import Image, ImageDraw


def isolated_pet(settings):
    pet = PetController(
        settings, {}, SimpleNamespace(active=None), None, None,
        speech_cooldown=0.0, interaction_cooldown=0.0, group_window=3.0,
    )
    for state in pet.states.values():
        state.enabled = True

    async def no_audio(*args, **kwargs):
        return None

    pet._speak = no_audio
    return pet


@pytest.mark.asyncio
async def test_identical_taps_on_two_distinct_heads_are_independent_events(settings):
    pet = isolated_pet(settings)
    touch = SceneChange("touch_tap", "Physical head touched", 1.0)
    first = pet.states["robot-01"]
    second = pet.states["robot-02"]

    pet._consider_speech("robot-01", touch, first.generation)
    assert pet._speech_robot == "robot-01"
    await pet._speech_task
    pet._consider_speech("robot-02", touch, second.generation)
    assert pet._speech_robot == "robot-02"
    assert second.suppressed == 0
    await pet._speech_task
    assert len(pet._event_kinds) == 2


@pytest.mark.asyncio
async def test_identical_camera_guess_across_heads_remains_deduplicated(settings):
    pet = isolated_pet(settings)
    scene = SceneChange("object", "A blue object may be on the desk", 0.99)
    first = pet.states["robot-01"]
    second = pet.states["robot-02"]

    pet._consider_speech(
        "robot-01", scene, first.generation, camera_derived=True,
    )
    await pet._speech_task
    pet._consider_speech(
        "robot-02", scene, second.generation, camera_derived=True,
    )
    assert second.suppressed == 1
    assert second.last_initiative_suppression == "quiet_voice_or_group_budget"
    assert len(pet._event_kinds) == 1


@pytest.mark.asyncio
async def test_real_touch_is_not_silenced_by_passive_120_second_group_budget(settings):
    """Twelve seconds applies to deliberate contact, never passive greetings."""
    pet = PetController(
        settings, {}, SimpleNamespace(active=None), None, None,
        speech_cooldown=120.0, interaction_cooldown=12.0, group_window=3.0,
    )
    for state in pet.states.values():
        state.enabled = True

    async def no_audio(*args, **kwargs):
        return None

    pet._speak = no_audio
    pet._group_last_spoken = time.monotonic() - 20.0
    state = pet.states["robot-01"]

    pet._consider_speech(
        "robot-01", SceneChange("object", "A new blue item appeared", 0.99),
        state.generation, camera_derived=True,
    )
    assert pet._speech_task is None
    assert state.last_initiative_suppression == "quiet_voice_or_group_budget"

    pet._consider_speech(
        "robot-01", SceneChange("touch_tap", "Actual contact", 1.0),
        state.generation,
    )
    assert pet._speech_task is not None
    assert pet._speech_robot == "robot-01"
    await pet._speech_task

    # The shorter physical-interaction window does not let an unrelated
    # passive camera observation bypass the normal 120 second voice budget.
    pet._group_last_spoken = time.monotonic() - 20.0
    pet._consider_speech(
        "robot-01", SceneChange("object", "A second different item", 0.99),
        state.generation, camera_derived=True,
    )
    assert state.last_initiative_suppression == "quiet_voice_or_group_budget"


@pytest.mark.asyncio
@pytest.mark.parametrize("replayed", [False, True])
async def test_authenticated_camera_receipt_to_fleet_and_speaker(
    settings, tmp_path, replayed,
):
    """Replay the normal observer, private memory, peer fanout and audio owner."""
    settings.fleet_text_sharing_enabled = True
    settings.fleet_text_auto_fanout_enabled = True
    ids = [robot.id for robot in settings.robots]
    memory = MemoryStore(tmp_path, ids)
    speaker = SimulatedSpeaker()
    change = SceneChange("key", "A flat key appeared on the desk", 0.96)

    class Chat:
        async def reply(self, history):
            return "That key looks interesting!"

    class Scene:
        async def compare(self, before, after):
            assert before != after
            return change

    conversation = Conversation(settings, Chat(), speaker, memory=memory)
    pet = PetController(
        settings, {}, conversation, memory, Scene(),
        interval=0.01, speech_cooldown=0, group_window=0,
    )
    hub = CameraFrameHub(ids)
    pet.multimodal = SimpleNamespace(
        hub=hub, stream_owns_camera=lambda rid: rid == "robot-01",
    )
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 37

    white = Image.new("RGB", (128, 96), "white")
    red = white.copy()
    ImageDraw.Draw(red).rectangle((40, 26, 78, 65), fill=(220, 20, 20))

    def jpeg(image):
        out = BytesIO()
        image.save(out, "JPEG")
        return out.getvalue()

    images = [jpeg(white), jpeg(red), jpeg(red)]
    received = time.monotonic()
    identity = (5, 13, 1400000)
    event_id = "camera_robot-01_00000005_0000000d_155cc0"
    if replayed:
        # A prior authenticated receipt may survive a Mac restart even
        # though the new controller's in-memory speech window is empty.
        assert await pet._store_observation(
            "robot-01", change, camera_derived=True,
            camera_received_at=received, camera_source_identity=identity,
        )
    for index, image in enumerate(images):
        hub.offer_prepared(
            "robot-01", (image, VisualChangeGate._reduced(image), 0.0),
            time.monotonic(), source="proactive",
            source_identity=(5, 11 + index, 1000000 + 200000 * index),
        )
    observer = asyncio.create_task(pet._observe("robot-01", 37))
    try:
        async with asyncio.timeout(4):
            while not (
                state.suppressed if replayed
                else state.spoken == 1 and pet._speech_task is None
            ):
                await asyncio.sleep(0.01)
        originals = [row for row in memory.recent("robot-01") if row.kind == "key"]
        copies = [row for row in memory.recent("robot-02") if row.kind == "key"]
        assert len(originals) == len(copies) == 1
        assert originals[0].event_id == copies[0].event_id == event_id
        assert originals[0].witnessed and not copies[0].witnessed
        assert originals[0].source_robot == copies[0].source_robot == "robot-01"
        if replayed:
            assert state.last_initiative_suppression == "camera_receipt_not_admitted"
            assert state.events == state.spoken == 0
            assert speaker.spoken == []
            assert not pet._admitted_event_kinds
        else:
            assert state.events == state.spoken == 1
            assert speaker.spoken == [("robot-01", "That key looks interesting!")]
        assert state.last_error is None
    finally:
        state.enabled = False
        observer.cancel()
        await asyncio.gather(observer, return_exceptions=True)
        await pet.close()
