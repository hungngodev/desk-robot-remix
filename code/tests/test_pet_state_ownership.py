"""Host regressions for immutable policy and explicit fleet state ownership."""

import asyncio
import random
from pathlib import Path

import pytest
from desk_robot.config import load_settings
from desk_robot.conversation import Conversation
from desk_robot.memory import MemoryStore
from desk_robot.pet import (
    _VISUAL_INITIATIVE_MIN_CONFIDENCE,
    PetController,
    _initiative_evidence,
)
from desk_robot.simulator import SimulatedChat, SimulatedScene, SimulatedSpeaker
from desk_robot.vision import SceneChange


def _controller(tmp_path, **kwargs):
    settings = load_settings(
        Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    )
    memory = MemoryStore(tmp_path, [robot.id for robot in settings.robots])
    conversation = Conversation(
        settings, SimulatedChat(), SimulatedSpeaker(), memory=memory
    )
    return PetController(
        settings, {}, conversation, memory, SimulatedScene(), **kwargs
    )


def test_visual_initiative_policy_cannot_be_mutated():
    with pytest.raises(TypeError):
        _VISUAL_INITIATIVE_MIN_CONFIDENCE["person"] = 0.0
    assert not _initiative_evidence(SceneChange("person", "A person appeared", 0.87))
    assert _initiative_evidence(SceneChange("person", "A person appeared", 0.88))


async def test_fleet_activity_loop_uses_owned_rng(tmp_path, monkeypatch):
    seed = 42
    rng = random.Random(seed)
    other = _controller(tmp_path / "other")
    pet = _controller(
        tmp_path / "pet", activity_rng=rng,
        activity_min_interval=0.01, activity_max_interval=0.02,
    )
    expected = random.Random(seed)
    expected.uniform(0.01, 0.02)
    other_state = other._activity_rng.getstate()

    def finish():
        pet._closed = True

    monkeypatch.setattr(pet, "_reconsider_activity", finish)
    try:
        await asyncio.wait_for(pet._activity_loop(), timeout=1)
        assert rng.getstate() == expected.getstate()
        assert other._activity_rng.getstate() == other_state
    finally:
        await pet.close()
        await other.close()


async def test_default_controller_and_pet_state_are_independent(tmp_path):
    first = _controller(tmp_path / "first")
    second = _controller(tmp_path / "second")
    try:
        assert first._activity_rng is not second._activity_rng
        first_state, sibling = list(first.states.values())[:2]
        peer_state = next(iter(second.states.values()))
        assert first_state.camera_habituation.record(("key", "key appeared"), 1.0)
        assert first_state.camera_habituation.record(("key", "key appeared"), 2.0)
        assert first_state.session_habituation.record("key", 1.0)
        assert first_state.session_habituation.record("key", 2.0)
        first_state.retired_touch_boot_ids.add(1)
        assert first_state.camera_habituation.recent_repeats(2.0) == {
            ("key", "key appeared"): 2
        }
        assert first_state.session_habituation.recent_repeats(2.0) == {"key": 2}
        for state in (sibling, peer_state):
            assert state.camera_habituation is not first_state.camera_habituation
            assert not state.camera_habituation.recent_repeats(2.0)
            assert not state.camera_habituation.refresh_if_repeated(
                ("key", "key appeared"), 2.0
            )
            assert state.session_habituation is not first_state.session_habituation
            assert not state.session_habituation.recent_repeats(2.0)
            assert not state.retired_touch_boot_ids
            assert state.gate is not first_state.gate
            assert state.handling_gate is not first_state.handling_gate
            assert state.dock_guard is not first_state.dock_guard
    finally:
        await first.close()
        await second.close()
