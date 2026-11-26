"""A retired observer cannot turn environmental recovery into renewed motion intent."""

import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from desk_robot.config import load_settings
from desk_robot.controller import Coordinator
from desk_robot.conversation import Conversation
from desk_robot.memory import MemoryStore
from desk_robot.pet import PetController
from desk_robot.simulator import (
    SimulatedChat,
    SimulatedHead,
    SimulatedScene,
    SimulatedSpeaker,
    SimulationVision,
)


@pytest.mark.parametrize("restarted", [False, True])
async def test_pause_retires_dock_dispatch_across_environmental_recovery(tmp_path, restarted):
    fleet = load_settings(Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml")
    robot_id = "robot-01"
    heads = {robot.id: SimulatedHead(robot.id) for robot in fleet.robots}
    coordinator = Coordinator(fleet, heads, SimulationVision())
    memory = MemoryStore(tmp_path, list(heads))
    dock = AsyncMock()
    pet = PetController(
        fleet, heads, Conversation(fleet, SimulatedChat(), SimulatedSpeaker(), memory=memory),
        memory, SimulatedScene(), on_local_fault=coordinator.stop,
        on_low_battery_dock=dock,
        on_dock_inhibit_changed=coordinator.set_dock_charge_inhibition,
    )
    state = pet.states[robot_id]
    state.enabled, state.generation = True, 7
    healthy = {"safety": {"required": True, "ready": True, "fault": "none"}}
    cliff = {"safety": {"required": True, "ready": False, "fault": "floor_out_of_range"}}
    try:
        await coordinator.operator_arm(robot_id)
        await pet._observe_body_safety(robot_id, 7, healthy)
        await pet._observe_body_safety(robot_id, 7, cliff)
        assert robot_id not in coordinator.permits
        await coordinator.stop(robot_id)
        await pet.pause(robot_id)
        paused_generation = state.generation

        # Late putdown/ToF receipt and contact transitions are not consent.
        await pet._observe_body_safety(robot_id, 7, healthy)
        pet._notify_dock_inhibit(robot_id, True)
        pet._notify_dock_inhibit(robot_id, False)
        assert not state.enabled
        assert state.generation == paused_generation
        assert robot_id not in coordinator.permits

        if restarted:
            # Simulate a new observer grant without launching background polling.
            state.enabled = True
            state.generation += 1
        await pet._dispatch_aux_changes(robot_id, 7, [], time.monotonic(), True)
        dock.assert_not_awaited()
        assert not any(cmd.split()[0] in {"arm", "drive"} for cmd in heads[robot_id].commands)

        if restarted:
            # Positive control: a fresh grant still admits a fresh request.
            await pet._dispatch_aux_changes(
                robot_id, state.generation, [], time.monotonic(), True,
            )
            dock.assert_awaited_once_with(robot_id, True)
    finally:
        await pet.close()
        await coordinator.close()
