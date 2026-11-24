"""Synthetic motion and control lease regressions; not physical qualification."""
from types import SimpleNamespace

import pytest
from desk_robot import simulator
from desk_robot.transport import HeadError


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["drive 0 0", "drive 0 0 100"])
async def test_zero_drive_does_not_change_simulated_scene(command):
    head = simulator.SimulatedHead("robot-01")
    await head.command("arm")
    before = await head.snapshot()
    await head.command(command)
    assert await head.snapshot() == before


@pytest.mark.asyncio
async def test_stop_renews_only_an_armed_control_lease(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(simulator, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    head = simulator.SimulatedHead("robot-01")
    await head.command("arm")
    clock[0] = 10.4
    await head.command("stop")
    clock[0] = 10.6
    assert (await head.status())["armed"] is True
    clock[0] = 11.0
    await head.command("stop")
    assert (await head.status())["armed"] is False
    with pytest.raises(HeadError, match="disarmed"):
        await head.command("drive 20 20")


@pytest.mark.asyncio
async def test_watchdog_reports_remaining_lease_and_expires_at_boundary(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(simulator, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    head = simulator.SimulatedHead("robot-01")
    await head.command("arm")
    assert (await head.status())["watchdog_ms"] == 500
    clock[0] = 10.25
    assert (await head.status())["watchdog_ms"] == 250
    clock[0] = 10.5
    with pytest.raises(HeadError, match="disarmed"):
        await head.command("drive 20 20")
    status = await head.status()
    assert status["armed"] is False
    assert status["watchdog_ms"] == 0


@pytest.mark.asyncio
async def test_status_failure_does_not_suspend_simulated_watchdog(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(simulator, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    head = simulator.SimulatedHead("robot-01")
    await head.command("arm")
    head.fail_status = True
    clock[0] = 10.5
    with pytest.raises(HeadError, match="status failure"):
        await head.status()
    assert head.armed is False
    head.fail_status = False
    assert (await head.status())["armed"] is False


@pytest.mark.asyncio
async def test_simulated_status_outage_disables_real_pet_poller(settings, tmp_path):
    """Synthetic transport failure through the existing hardware-mode policy."""
    import asyncio

    from desk_robot.conversation import Conversation
    from desk_robot.memory import MemoryStore
    from desk_robot.pet import PetController

    settings.mode = "hardware"
    robot_id = settings.robots[0].id
    head = simulator.SimulatedHead(robot_id)
    speaker = simulator.SimulatedSpeaker()
    memory = MemoryStore(tmp_path, [robot.id for robot in settings.robots])
    pet = PetController(
        settings, {robot_id: head},
        Conversation(settings, simulator.SimulatedChat(), speaker, memory=memory),
        memory, simulator.SimulatedScene(), interval=.01, touch_interval=.01,
    )
    state = pet.states[robot_id]
    state.enabled, state.generation = True, 1
    head.fail_status = True
    try:
        await asyncio.wait_for(pet._poll_touch(robot_id, 1), timeout=5)
        assert state.enabled is False
        assert "Pet WROOM body status unavailable" in (state.last_error or "")
        assert state.events == 0
        assert memory.recent(robot_id) == []
        assert speaker.spoken == []
        head.fail_status = False
        assert (await head.status())["robot_id"] == robot_id
        assert state.enabled is False
    finally:
        await pet.close()


@pytest.mark.asyncio
async def test_body_replay_is_snapshot_isolated_and_has_no_motion_authority():
    head = simulator.SimulatedHead("robot-01")
    await head.command("arm")
    sample = {"robot_id": "robot-01", "touch": {"count": 1}}
    head.replay_body_status(sample)
    assert head.armed is False
    sample["touch"]["count"] = 2
    receipt = await head.status()
    assert receipt["touch"]["count"] == 1
    receipt["touch"]["count"] = 3
    assert (await head.status())["touch"]["count"] == 1
    with pytest.raises(ValueError, match="status dictionary"):
        head.replay_body_status(None)
    with pytest.raises(HeadError, match="replay"):
        await head.command("arm")
    with pytest.raises(HeadError, match="replay"):
        await head.command("drive 20 20")
    assert (await head.command("halt"))["reply"] == "OK halt"


@pytest.mark.asyncio
async def test_body_replay_feeds_existing_sensor_fusion_and_rejects_foreign_identity(
    settings, tmp_path, monkeypatch,
):
    """Exercise one real body receipt path without creating another brain."""
    from desk_robot.conversation import Conversation
    from desk_robot.memory import MemoryStore
    from desk_robot.pet import PetController

    settings.mode = "hardware"
    robot_id = settings.robots[0].id
    head = simulator.SimulatedHead(robot_id)
    speaker = simulator.SimulatedSpeaker()
    memory = MemoryStore(tmp_path, [robot.id for robot in settings.robots])
    order = []

    async def stop(robot):
        order.append(("stop", robot))

    pet = PetController(
        settings, {robot_id: head},
        Conversation(settings, simulator.SimulatedChat(), speaker, memory=memory),
        memory, simulator.SimulatedScene(), on_local_fault=stop,
    )
    state = pet.states[robot_id]
    state.enabled, state.generation, state.quiet = True, 1, True
    monkeypatch.setattr(pet, "_notify_sensor", lambda robot, kind: order.append((kind, robot)))
    body = {
        "robot_id": robot_id,
        "touch": {"active": False, "count": 0},
        "safety": {"required": True, "ready": True, "fault": "none", "sensor": 255},
        "extras": {
            "mask": 2, "bumper": False, "bumps": 0, "reed": False,
            "reed_count": 0, "pir": False, "pir_count": 0,
            "cap": 0, "cap_ok": True, "cap_events": 0,
        },
    }
    try:
        head.replay_body_status(body)
        await pet._touch_from_body(robot_id, 1)
        body["safety"].update(ready=False, fault="floor_out_of_range", sensor=2)
        body["touch"]["count"] = 1
        body["extras"].update(cap=1, cap_events=1, reed=True, reed_count=1)
        head.replay_body_status(body)
        await pet._touch_from_body(robot_id, 1)
        await pet._touch_from_body(robot_id, 1)
        assert order[:2] == [("stop", robot_id), ("safety_fault", robot_id)]
        events = memory.recent(robot_id)
        assert sorted(event.kind for event in events) == [
            "magnet", "petting_zone", "safety_fault", "touch",
        ]
        assert all(event.witnessed and event.source_robot == robot_id for event in events)
        body["robot_id"] = "foreign-robot"
        body["touch"]["count"] = 2
        head.replay_body_status(body)
        with pytest.raises(HeadError, match="identity mismatch"):
            await pet._touch_from_body(robot_id, 1)
        assert len(memory.recent(robot_id)) == 4
        assert speaker.spoken == []
    finally:
        state.enabled = False
        await pet.close()
