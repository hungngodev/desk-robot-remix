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
