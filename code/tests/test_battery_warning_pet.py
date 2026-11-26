"""Integration regression for battery-only optional speech admission."""
import asyncio
import math
from pathlib import Path

from desk_robot.config import load_settings
from desk_robot.conversation import Conversation
from desk_robot.memory import MemoryStore
from desk_robot.pet import PetController
from desk_robot.simulator import SimulatedSpeaker
from desk_robot.vision import SceneChange


async def test_battery_warning_cooldown_survives_description_and_generation_changes(tmp_path):
    class BatteryChat:
        async def proactive_decision(self, _history):
            return {"action": "speak", "text": "My charge is getting low."}

    class NoScene:
        async def compare(self, before, after):
            raise AssertionError("Battery speech does not require a camera")

    fleet = load_settings(
        Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    )
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    pet = PetController(
        fleet, {}, Conversation(fleet, BatteryChat(), speaker, memory=memory),
        memory, NoScene(), speech_cooldown=0,
    )
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 95
    try:
        pet._consider_speech(
            "robot-01", SceneChange("battery_low", "Fuel gauge started low", 1.0), 95,
        )
        async with asyncio.timeout(2):
            while pet._speech_task is not None:
                await asyncio.sleep(0.01)
        assert speaker.spoken == [("robot-01", "My charge is getting low.")]
        assert math.isfinite(state.last_battery_warning_at)
        assert pet.states["robot-02"].last_battery_warning_at == -math.inf

        # A new episode or observer restart can change the description.
        # Neither the wording nor a zero general cooldown may refund this budget.
        state.generation += 1
        pet._consider_speech(
            "robot-01", SceneChange("battery_low", "Fuel gauge remains low", 1.0), 96,
        )
        assert pet._speech_task is None
        assert state.last_initiative_gate_reason == "battery_warning_cooldown"
        assert len(speaker.spoken) == 1
    finally:
        state.enabled = False
        await pet.close()
