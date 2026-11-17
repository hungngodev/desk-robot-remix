"""Physical interactions are per-pet; repeated shared camera scenes are not."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from desk_robot.pet import PetController
from desk_robot.vision import SceneChange


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
