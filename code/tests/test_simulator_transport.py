import asyncio
from unittest.mock import patch

import pytest
from desk_robot.simulator import SimulatedHead
from desk_robot.transport import HeadError


@pytest.mark.parametrize("terminal", ["stop", "halt", "disarm", "arm"])
def test_simulator_stop_clears_live_drive(terminal):
    async def scenario():
        head = SimulatedHead("robot-01")
        await head.command("arm")
        await head.command("drive 20 20 100")
        assert (await head.status())["motor"] == {"m0": 20, "m1": 20}
        await head.command(terminal)
        status = await head.status()
        assert status["motor"] == {"m0": 0, "m1": 0}
        assert status["drive_ms"] == 0
        assert status["armed"] is (terminal in {"stop", "arm"})

    with patch("desk_robot.simulator.time.monotonic", return_value=1.0):
        asyncio.run(scenario())


def test_simulator_drive_expiry_and_watchdog():
    async def scenario(clock):
        head = SimulatedHead("robot-01")
        await head.command("arm")
        await head.command("drive 20 20 100")
        clock.return_value = 1.05
        await head.command("keepalive")
        assert (await head.status())["motor"] == {"m0": 20, "m1": 20}
        clock.return_value = 1.125
        status = await head.status()
        assert status["motor"] == {"m0": 0, "m1": 0}
        assert status["drive_ms"] == 0
        assert status["armed"]
        clock.return_value = 1.625
        assert not (await head.status())["armed"]
        with pytest.raises(HeadError, match="Body disarmed"):
            await head.command("drive 20 20 100")

    with patch("desk_robot.simulator.time.monotonic", return_value=1.0) as clock:
        asyncio.run(scenario(clock))


def test_simulator_zero_drive_does_not_move_or_keep_old_wheels():
    async def scenario():
        head = SimulatedHead("robot-01")
        await head.command("arm")
        await head.command("drive 20 20 100")
        position = head.position.copy()
        await head.command("drive 0 0 100")
        assert head.position == position
        assert (await head.status())["motor"] == {"m0": 0, "m1": 0}

    with patch("desk_robot.simulator.time.monotonic", return_value=1.0):
        asyncio.run(scenario())
