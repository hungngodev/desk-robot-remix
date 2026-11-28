"""A WROOM ready transition is not a fresh motor permit or a pickup by itself."""

import asyncio
from types import SimpleNamespace

import pytest
from desk_robot.pet import PetController, PetState


@pytest.mark.parametrize(("fault", "lift_evidence", "putdown"), [
    ("front_obstacle", False, False),
    ("bus_failure", False, False),
    ("floor_out_of_range", False, False),
    ("floor_out_of_range", True, True),
])
def test_putdown_requires_prior_possible_lift(fault, lift_evidence, putdown):
    state = PetState(enabled=True, generation=4)
    state.handling_gate.reference = (0.0, 0.0, 1.0)
    events, stops = [], []

    async def stop(robot_id):
        stops.append(robot_id)

    async def store(robot_id, change):
        pass

    pet = SimpleNamespace(
        states={"pet": state}, on_local_fault=stop, _store_observation=store,
        _notify_sensor=lambda _, kind, **kwargs: events.append(kind),
    )

    async def observe(name, ready, at, **extra):
        body = {"safety": {"required": True, "ready": ready, "fault": name}, **extra}
        await PetController._observe_body_safety(pet, "pet", 4, body, received_at=at)

    async def scenario():
        await observe("none", True, 10.0)
        extra = {
            "ranges": {"mm": [200, 200, 35, 35, 100], "valid_mask": 31},
            "imu": {"valid": True, "acc": [0, 0, 16384]},
        } if lift_evidence else {}
        await observe(fault, False, 11.0, **extra)
        await observe("none", True, 10.5)
        assert events == ["safety_fault"]
        await observe("none", True, 12.0)
        await observe("none", True, 13.0)
        assert events == ["safety_fault"] + (["stable_putdown"] if putdown else [])
        assert stops == ["pet"]
        assert not state.last_safety_was_possible_lift

    asyncio.run(scenario())
