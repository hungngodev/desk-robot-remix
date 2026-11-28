from unittest.mock import patch

import pytest
from desk_robot.command_framing import drive_arguments, drive_duration_ms, expected_ack
from desk_robot.simulator import SimulatedHead


@pytest.mark.parametrize(
    ("command", "arguments"),
    [("drive -40 40", (-40, 40, 250)), ("drive 40 -40 1", (40, -40, 1)),
     ("drive -00 040 025", (0, 40, 25)), ("drive 0 0 250", (0, 0, 250))],
)
async def test_shared_drive_arguments_match_simulator(command, arguments):
    left, right, duration = arguments
    assert drive_arguments(command) == arguments
    assert drive_duration_ms(command) == duration
    head = SimulatedHead("robot-01")
    with patch("desk_robot.simulator.time.monotonic", return_value=1.0):
        await head.command("arm")
        receipt = await head.command(command)
        status = await head.status()
    assert receipt["reply"] == expected_ack(command) == (
        f"OK drive left={left} right={right} ms={duration}"
    )
    assert status["motor"] == {"m0": left, "m1": right}
    assert status["drive_ms"] == duration


@pytest.mark.parametrize(
    "command",
    ["drive -41 0", "drive 0 41", "drive 0 0 0", "drive 0 0 251",
     "drive 0 0 -1", "drive 0  0", "drive 0 nan", "drive +1 0"],
)
async def test_invalid_drive_does_not_refresh_simulator_authority(command):
    with pytest.raises(ValueError):
        drive_arguments(command)
    head = SimulatedHead("robot-01")
    with patch("desk_robot.simulator.time.monotonic", return_value=1.0) as clock:
        await head.command("arm")
        await head.command("drive 20 20 250")
        clock.return_value = 1.199
        before = await head.status()
        with pytest.raises(ValueError):
            await head.command(command)
        assert await head.status() == before
        assert head.commands == ["arm", "drive 20 20 250"]
        clock.return_value = 1.2
        status = await head.status()
        assert not status["armed"]
        assert status["motor"] == {"m0": 0, "m1": 0}
