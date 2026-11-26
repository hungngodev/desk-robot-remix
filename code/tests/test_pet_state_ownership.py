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
        assert pet._activity_rng.getstate() == expected.getstate()
        assert rng.getstate() == random.Random(seed).getstate()
        assert other._activity_rng.getstate() == other_state
    finally:
        await pet.close()
        await other.close()



async def test_shared_injected_rng_is_only_a_state_snapshot(tmp_path, monkeypatch):
    rng = random.Random(42)
    rng.random()
    initial_state = rng.getstate()
    first = _controller(
        tmp_path / "first", activity_rng=rng,
        activity_min_interval=0.01, activity_max_interval=0.02,
    )
    second = _controller(tmp_path / "second", activity_rng=rng)
    expected = random.Random()
    expected.setstate(initial_state)
    expected.uniform(0.01, 0.02)

    def finish():
        first._closed = True

    monkeypatch.setattr(first, "_reconsider_activity", finish)
    try:
        await asyncio.wait_for(first._activity_loop(), timeout=1)
        assert first._activity_rng.getstate() == expected.getstate()
        assert second._activity_rng.getstate() == initial_state
        assert rng.getstate() == initial_state
        assert first._activity_rng is not second._activity_rng
        assert first._activity_rng is not rng
        assert second._activity_rng is not rng
        rng.random()
        assert second._activity_rng.getstate() == initial_state
        assert first._activity_rng.getstate() == expected.getstate()
    finally:
        await first.close()
        await second.close()


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


async def test_registry_and_status_snapshot_resist_caller_mutation(tmp_path):
    pet = _controller(tmp_path)
    try:
        first_id, second_id = list(pet.states)[:2]
        first = pet.states[first_id]
        with pytest.raises(TypeError):
            pet.states[first_id] = pet.states[second_id]
        with pytest.raises(TypeError):
            del pet.states[first_id]
        with pytest.raises(AttributeError):
            pet.states = {}
        assert pet.states[first_id] is first
        first.enabled = True
        assert pet.states[first_id].enabled
        assert not pet.states[second_id].enabled

        snapshot = pet.status(first_id)
        snapshot["enabled"] = False
        snapshot["robot_id"] = second_id
        snapshot.clear()
        assert pet.status(first_id)["enabled"] is True
        assert pet.status(first_id)["robot_id"] == first_id
        assert pet.status(second_id)["enabled"] is False
    finally:
        await pet.close()


@pytest.mark.parametrize("social_peer", [False, True])
async def test_restart_waits_for_retired_speech_owner(tmp_path, monkeypatch, social_peer):
    """A timed-out speech cancellation cannot overlap a new pet generation."""
    monkeypatch.setattr("desk_robot.pet._PET_SPEECH_ABORT_TIMEOUT_S", 0.05)
    pet = _controller(tmp_path)
    first, second = list(pet.states)[:2]
    robot_id = second if social_peer else first
    state = pet.states[robot_id]
    state.enabled = True
    pet.heads[robot_id] = object()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def old_speech():
        entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await release.wait()

    async def idle_observer(_robot_id, _generation):
        await asyncio.Future()

    monkeypatch.setattr(pet, "_observe", idle_observer)
    task = asyncio.create_task(old_speech())
    pet._speech_task = task
    pet._speech_robot = first
    pet._speech_participants = frozenset({first, second} if social_peer else {first})
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        with pytest.raises(TimeoutError, match="Pet speaker cancellation unconfirmed"):
            await pet.pause(robot_id)
        generation = state.generation
        assert not state.enabled
        assert not task.done()
        with pytest.raises(RuntimeError, match="Previous pet task still shutting down"):
            pet.start(robot_id)
        assert state.generation == generation
        assert not state.enabled
        release.set()
        await asyncio.wait_for(task, timeout=1)
        assert pet.start(robot_id)["enabled"]
        assert state.generation == generation + 1
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=1)
        await pet.close()


async def test_native_pet_speech_policy_reads_immutable_pet_states_mapping(
    tmp_path, monkeypatch,
):
    """API policy helper must inspect MappingProxyType pet.states, not only dict."""
    from types import SimpleNamespace

    from desk_robot.api import create_app
    from desk_robot.multimodal import CameraFrameHub
    from fastapi.testclient import TestClient

    settings = load_settings(
        Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    )
    monkeypatch.setenv(
        settings.coordinator_token_env, "test-operator-token-at-least-32-characters"
    )
    monkeypatch.setenv(
        settings.tools_token_env, "test-tools-token-at-least-32-characters-01"
    )
    pet = _controller(tmp_path)
    first_id = settings.robots[0].id
    pet.states[first_id].enabled = True
    pet.states[first_id].quiet = False
    runtime = SimpleNamespace(
        settings=settings,
        pet=pet,
        coordinator=SimpleNamespace(jobs={}),
        conversation=SimpleNamespace(_private_memory_generation={first_id: 0}),
        multimodal=SimpleNamespace(hub=CameraFrameHub([r.id for r in settings.robots])),
        attention=None,
        close=lambda: asyncio.sleep(0),
    )
    app = create_app(settings, runtime)
    try:
        with TestClient(app) as client:
            res = client.get(
                f"/v1/pet/{first_id}/interaction-context",
                headers={"Authorization": "Bearer test-tools-token-at-least-32-characters-01"},
            )
        assert res.status_code == 200
        body = res.json()
        assert body["pet_autonomy_enabled"] is True
        assert body["pet_quiet"] is False
    finally:
        await pet.close()
