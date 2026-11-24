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
