"""Synthetic cliff and command-boundary checks, not physical qualification."""
from types import SimpleNamespace

import pytest
from desk_robot import simulator
from desk_robot.transport import HeadError


@pytest.mark.asyncio
@pytest.mark.parametrize("lane", range(4))
async def test_one_unsafe_floor_sample_stops_and_latches_until_local_rearm(monkeypatch, lane):
    clock = [10.0]
    monkeypatch.setattr(simulator, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    head = simulator.SimulatedHead("robot-01")
    await head.command("arm")
    await head.command("drive 40 40 250")
    clock[0] = 10.001
    head.inject_cliff_sample(lane, safe=False)
    assert head.armed is False
    assert head._motor == (0, 0)
    assert head._drive_deadline_ms == 0
    status = await head.status()
    assert status["armed"] is False
    assert status["motor"] == {"m0": 0, "m1": 0}
    assert status["drive_ms"] == status["watchdog_ms"] == 0
    assert status["safety"] == {
        "required": True, "ready": False, "fault": "floor_out_of_range", "sensor": lane,
    }
    with pytest.raises(HeadError, match="interlock"):
        head.local_rearm()
    other_lane = (lane + 1) % 4
    head.inject_cliff_sample(other_lane, safe=False)
    head.inject_cliff_sample(lane, safe=True)
    assert (await head.status())["safety"]["sensor"] == lane
    with pytest.raises(HeadError, match="interlock"):
        head.local_rearm()
    head.inject_cliff_sample(other_lane, safe=True)
    for command in ("stop", "halt", "disarm"):
        await head.command(command)
        with pytest.raises(HeadError, match="latched"):
            await head.command("arm")
        with pytest.raises(HeadError, match="disarmed"):
            await head.command("drive 40 40")
    head.local_rearm()
    status = await head.status()
    assert status["safety"]["ready"] is True
    assert status["armed"] is False
    assert status["motor"] == {"m0": 0, "m1": 0}
    await head.command("arm")
    assert (await head.status())["drive_ms"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lane,safe",
    [(4, False), (5, False), (7, False), (-1, False), (True, False), (0, 0), (0, None)],
)
async def test_non_floor_or_malformed_samples_do_not_change_cliff_state(lane, safe):
    head = simulator.SimulatedHead("robot-01")
    await head.command("arm")
    with pytest.raises(ValueError, match="floor lane"):
        head.inject_cliff_sample(lane, safe=safe)
    assert (await head.status())["armed"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    ["drive 41 40", "drive -41 0", "drive 40 40 251", "drive 40 40 0", "drive 40 40 -1"],
)
async def test_invalid_drive_cannot_renew_or_change_motor_permit(monkeypatch, command):
    clock = [10.0]
    monkeypatch.setattr(simulator, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    head = simulator.SimulatedHead("robot-01")
    await head.command("arm")
    await head.command("drive 40 40")
    clock[0] = 10.1
    before = await head.status()
    with pytest.raises(ValueError):
        await head.command(command)
    assert await head.status() == before
    clock[0] = 10.2
    assert (await head.status())["armed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["drive 40 40", "drive 40 40 250"])
async def test_maximum_permit_expires_at_250_ms_even_after_keepalive(monkeypatch, command):
    clock = [10.0]
    monkeypatch.setattr(simulator, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    head = simulator.SimulatedHead("robot-01")
    await head.command("arm")
    assert (await head.command(command))["reply"] == "OK drive left=40 right=40 ms=250"
    clock[0] = 10.125
    await head.command("keepalive")
    clock[0] = 10.249
    status = await head.status()
    assert status["motor"] == {"m0": 40, "m1": 40}
    assert status["drive_ms"] == 1
    clock[0] = 10.25
    status = await head.status()
    assert status["motor"] == {"m0": 0, "m1": 0}
    assert status["drive_ms"] == 0
    assert status["armed"] is True
