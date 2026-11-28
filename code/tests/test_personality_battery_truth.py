"""Keep the shared personality prompt independent of power evidence."""
from __future__ import annotations

from typing import get_args

import pytest
from desk_robot.personality_policy import PersonalityProfile, expression_guidance


@pytest.mark.parametrize("profile", get_args(PersonalityProfile))
def test_personality_cannot_reinterpret_gauge_readings(profile):
    guidance = expression_guidance(profile)
    assert "Personality and OLED mood are expressive only" in guidance
    assert "Never alter reported battery percentages or cell voltage (millivolts)" in guidance
    assert "Never infer battery state from tiredness, energy or personality" in guidance
    assert "preserve the gauge estimate and qualification" in guidance
    assert "Missing or uncertain evidence stays unknown" in guidance


def test_power_truth_instruction_is_identical_across_personalities():
    suffixes = {
        expression_guidance(profile).partition("Personality and OLED mood")[2]
        for profile in get_args(PersonalityProfile)
    }
    assert len(suffixes) == 1
    assert next(iter(suffixes))


@pytest.mark.parametrize(
    ("text", "receipt", "violates"),
    [
        ("My charge is getting low.", None, False),
        ("My battery reads 48 percent.", None, True),
        (
            "My battery reads 48 percent.",
            {
                "source": "authenticated_wroom_read_only_status",
                "data": {"battery": {"percent": 48, "physically_qualified": False}},
            },
            False,
        ),
        (
            "My battery is down to 2%!",
            {
                "source": "authenticated_wroom_read_only_status",
                "data": {"battery": {"percent": 48, "physically_qualified": False}},
            },
            True,
        ),
        (
            "My battery is at two percent.",
            {
                "source": "authenticated_wroom_read_only_status",
                "data": {"battery": {"percent": 48, "physically_qualified": False}},
            },
            True,
        ),
        (
            "Battery is 48% at 3.20 V.",
            {
                "source": "authenticated_wroom_read_only_status",
                "data": {"battery": {"percent": 48, "physically_qualified": False}},
            },
            True,
        ),
        (
            "Gauge estimate is 48% around 3750 mV (unqualified).",
            {
                "source": "authenticated_wroom_read_only_aux_status",
                "data": {
                    "fuel_gauge": {"soc_centi": 4800, "cell_mv": 3750, "qualified": False},
                },
            },
            False,
        ),
        (
            "Cell voltage is 3400 mV at 48%.",
            {
                "source": "authenticated_wroom_read_only_aux_status",
                "data": {
                    "fuel_gauge": {"soc_centi": 4800, "cell_mv": 3750, "qualified": False},
                },
            },
            True,
        ),
        (
            "My battery is calibrated and verified at 48%.",
            {
                "source": "authenticated_wroom_read_only_aux_status",
                "data": {
                    "fuel_gauge": {"soc_centi": 4800, "cell_mv": 3750, "qualified": False},
                },
            },
            True,
        ),
    ],
)
def test_deterministic_battery_claim_gate_validates_against_fresh_receipt(
    text, receipt, violates,
):
    from desk_robot.personality_policy import proactive_battery_claim_violates_receipt

    assert proactive_battery_claim_violates_receipt(text, receipt) is violates


async def test_proactive_speaker_blocks_contradictory_and_unbacked_battery_claims(
    fleet, tmp_path,
):
    """Contradictory, voltage-hallucinating, or stale-receipt battery numbers never reach TTS."""
    import asyncio
    import json

    from desk_robot.conversation import Conversation
    from desk_robot.memory import MemoryStore
    from desk_robot.pet import PetController
    from desk_robot.simulator import SimulatedSpeaker
    from desk_robot.vision import SceneChange

    fuel_age_ms = [20]
    replies = [
        ("status", "My battery is down to 2%!"),
        ("status", "My battery is 48% at 3.10 V."),
        ("aux_status", "My battery is 48% at 4150 mV."),
        ("aux_status", "My battery is 48%."),  # will run with stale fuel_age_ms=900
        ("none", "My battery is 48%."),
        ("aux_status", "Gauge estimate is 48% around 3750 mV."),
    ]

    class Head:
        def __init__(self):
            self.fuel_seq = 0

        async def status(self):
            return {
                "robot_id": "robot-01",
                "battery": {"percent": 48},
                "data": {"docked": False},
            }

        async def aux_status(self):
            self.fuel_seq += 1
            return {
                "robot_id": "robot-01",
                "force": {"boot_id": 19},
                "proximity": {"valid": True, "gesture": 1, "boot_id": 19},
                "power": {
                    "fuel_valid": True,
                    "fuel_seq": self.fuel_seq,
                    "fuel_age_ms": fuel_age_ms[0],
                    "soc_centi": 4800,
                    "cell_mv": 3750,
                },
            }

    class Chat:
        def __init__(self):
            self.step = 0
            self.current: tuple[str, str] | None = None

        async def proactive_decision(self, history):
            if self.current is None:
                self.current = replies[self.step]
                self.step += 1
                tool, text = self.current
                if tool != "none":
                    return {"action": "inspect", "text": "", "tool": tool}
                self.current = None
                return {"action": "speak", "text": text, "tool": "none"}
            _, text = self.current
            self.current = None
            assert json.loads(history[-1]["content"])["robot_id"] == "robot-01"
            return {"action": "speak", "text": text, "tool": "none"}

    class NoScene:
        async def compare(self, before, after):
            raise AssertionError("No camera needed")

    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    pet = PetController(
        fleet, {"robot-01": Head()},
        Conversation(fleet, Chat(), speaker, memory=memory),
        memory, NoScene(), speech_cooldown=0,
    )
    pet.set_voice_monitor_ready(True)
    state = pet.states["robot-01"]
    state.enabled = True
    try:
        for idx in range(5):
            if idx == 3:
                fuel_age_ms[0] = 900  # stale fuel_gauge omitted from aux_status receipt
            else:
                fuel_age_ms[0] = 20
            state.generation = 200 + idx
            pet._consider_speech(
                "robot-01",
                SceneChange("touch_tap", f"Tap {idx}", 1.0),
                state.generation,
            )
            async with asyncio.timeout(2):
                while pet._speech_task is not None:
                    await asyncio.sleep(0.01)
            assert speaker.spoken == []
            assert state.last_initiative_suppression == (
                "unverified_or_contradictory_battery_claim"
            )

        # Final cooperative reply matching fresh 48% / 3750 mV receipt succeeds.
        fuel_age_ms[0] = 20
        state.generation = 210
        pet._consider_speech(
            "robot-01", SceneChange("touch_tap", "Tap valid", 1.0), state.generation,
        )
        async with asyncio.timeout(2):
            while pet._speech_task is not None:
                await asyncio.sleep(0.01)
        assert speaker.spoken == [("robot-01", "Gauge estimate is 48% around 3750 mV.")]
    finally:
        state.enabled = False
        await pet.close()
