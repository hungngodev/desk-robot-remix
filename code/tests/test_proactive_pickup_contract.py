"""Pickup is contextual evidence, never an event-specific speech script."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from desk_robot import pet as pet_module
from desk_robot.brain_context import repeated_spontaneous_line
from desk_robot.sensor_event_contract import PHYSICAL_INITIATIVE_KINDS
from desk_robot.vision import SceneChange


@pytest.mark.parametrize("kind", sorted(
    PHYSICAL_INITIATIVE_KINDS | set(pet_module._VISUAL_INITIATIVE_MIN_CONFIDENCE)
    | {"activity_reconsideration"}
))
@pytest.mark.parametrize("backend", ["structured", "legacy"])
async def test_pickup_context_never_substitutes_a_stock_line(kind, backend):
    """Every trigger must consult the model and honor silence or its exact words."""
    replies = [None, "Shall we finish that chess game?"]
    prompts = []

    class LegacyChat:
        async def reply(self, history):
            prompts.append(history)
            return replies.pop(0)

    class StructuredChat:
        async def proactive_decision(self, history):
            prompts.append(history)
            reply = replies.pop(0)
            if reply is None:
                return {"action": "silence", "mood": "none"}
            return {"action": "speak", "text": reply, "mood": "none"}

    async def cue_face(robot_id, mood, permission):
        assert robot_id == "robot-01"
        assert mood == "none"
        assert permission()

    state = SimpleNamespace(suppressed=0, activity_silences=0)
    robot = SimpleNamespace(persona="A thoughtful companion.", personality_profile="balanced")
    owner = SimpleNamespace(
        states={"robot-01": state},
        settings=SimpleNamespace(robot=lambda _: robot),
        conversation=SimpleNamespace(
            chat=StructuredChat() if backend == "structured" else LegacyChat(),
        ),
        max_observation_age=30.0,
        _cue_decided_face=cue_face,
    )
    context = SimpleNamespace(
        recent="The user and robot were playing chess.",
        core="",
        interaction="Possible upright lift; not confirmed pickup. Chess game unfinished.",
    )
    change = SceneChange(kind, "Fresh contextual evidence", 1.0)
    for expected in (None, "Shall we finish that chess game?"):
        actual = await pet_module.PetController._generate_proactive_line(
            owner, "robot-01", change, context,
            offered_at=time.monotonic(), model_context_permitted=lambda: True,
        )
        assert actual == expected
    assert len(prompts) == 2
    assert all("Possible upright lift" in history[1]["content"] for history in prompts)
    assert not replies


@pytest.mark.parametrize("candidate", [
    "You picked me up!",
    "YOU PICKED ME UP?",
    "  You   picked me up.  ",
])
def test_pickup_line_dedup_is_independent_of_trigger(candidate):
    """The previous transmission may be from any trigger, including native speech."""
    previous = ("You picked me up!",)
    assert repeated_spontaneous_line(
        candidate, (), now_wall=100.0, recent_transmitted=previous,
    )
    assert not repeated_spontaneous_line(
        "Shall we finish that chess game?", (), now_wall=100.0,
        recent_transmitted=previous,
    )
