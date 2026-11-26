"""Keep the Mac drive duration in sync with the independent WROOM wire contract."""

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from desk_robot.simulator import (
    BODY_ACTIVE_WHEEL_WATCHDOG_MS,
    BODY_IDLE_WATCHDOG_MS,
    SimulatedHead,
)
from desk_robot.transport import MAX_DRIVE_DURATION_MS, HeadError, drive_duration_ms, expected_ack

ROOT = Path(__file__).resolve().parents[2]


def test_drive_duration_matches_wroom_source_contract():
    header = (ROOT / "code/firmware/body/lib/BodyControl/BodyControl.h").read_text()
    match = re.search(r"\bconstexpr\s+std::uint32_t\s+kMaxDriveMs\s*=\s*(\d+)\s*;", header)
    assert match is not None
    assert MAX_DRIVE_DURATION_MS == int(match.group(1)) == 250


@pytest.mark.parametrize(
    ("command", "ms"),
    [("drive 20 -20", 250), ("drive 20 -20 1", 1), ("drive 20 -20 250", 250)],
)
def test_validated_duration_and_ack_agree(command, ms):
    assert drive_duration_ms(command) == ms
    assert expected_ack(command) == f"OK drive left=20 right=-20 ms={ms}"


@pytest.mark.parametrize(
    "command",
    ["drive 20 -20 0", "drive 20 -20 251", "drive 41 0", "stop",
     "drive 20  -20", "drive 20 -20 nan"],
)
def test_duration_helper_rejects_unvalidated_commands(command):
    with pytest.raises(ValueError):
        drive_duration_ms(command)


@pytest.mark.parametrize(("command", "ms"), [("drive 20 20", 250), ("drive 20 20 1", 1)])
async def test_simulator_duration_matches_its_wire_ack(command, ms):
    head = SimulatedHead("robot-01")
    with patch("desk_robot.simulator.time.monotonic", return_value=1.0):
        await head.command("arm")
        response = await head.command(command)
        status = await head.status()
    assert response["reply"] == f"OK drive left=20 right=20 ms={ms}"
    assert status["drive_ms"] == ms


def test_simulator_watchdog_limits_match_guarded_wroom():
    owner = ROOT / "code/firmware/body/lib/BodyControl"
    for path, name, simulated, required in (
        ("BodyControl.h", "kWatchdogMs", BODY_IDLE_WATCHDOG_MS, 500),
        ("BodyControl.cpp", "kActiveWheelHostTimeoutMs", BODY_ACTIVE_WHEEL_WATCHDOG_MS, 200),
    ):
        match = re.search(
            rf"\bconstexpr\s+std::uint32_t\s+{name}\s*=\s*(\d+)\s*;",
            (owner / path).read_text(),
        )
        assert match is not None
        assert simulated == int(match.group(1)) == required


@pytest.mark.parametrize(
    ("duration", "poll_time", "armed", "moving"),
    [
        (250, 1.199, True, True),
        (250, 1.2, False, False),
        (250, 1.3, False, False),  # delayed poll cannot hide prior watchdog expiry
        (200, 1.2, False, False),  # body watchdog wins at a simultaneous expiry
        (100, 1.3, True, False),   # pulse ended before the active watchdog
    ],
)
async def test_simulator_active_and_idle_watchdog_order(duration, poll_time, armed, moving):
    head = SimulatedHead("robot-01")
    with patch("desk_robot.simulator.time.monotonic", return_value=1.0) as clock:
        await head.command("arm")
        assert (await head.status())["watchdog_ms"] == 500
        await head.command(f"drive 20 20 {duration}")
        assert (await head.status())["watchdog_ms"] == 200
        clock.return_value = poll_time
        status = await head.status()
        assert status["armed"] is armed
        assert status["motor"] == ({"m0": 20, "m1": 20} if moving else {"m0": 0, "m1": 0})
        if not armed:
            assert status["watchdog_ms"] == 0
            assert status["drive_ms"] == 0
            with pytest.raises(HeadError, match="Body disarmed"):
                await head.command("keepalive")


async def test_simulator_keepalive_extends_watchdog_without_extending_pulse():
    head = SimulatedHead("robot-01")
    with patch("desk_robot.simulator.time.monotonic", return_value=1.0) as clock:
        await head.command("arm")
        await head.command("drive 20 20")
        clock.return_value = 1.15
        await head.command("keepalive")
        clock.return_value = 1.249
        assert (await head.status())["motor"] == {"m0": 20, "m1": 20}
        clock.return_value = 1.25
        status = await head.status()
        assert status["armed"]
        assert status["motor"] == {"m0": 0, "m1": 0}
        assert status["drive_ms"] == 0


async def test_overlapping_drive_replaces_pending_pulse():
    head = SimulatedHead("robot-01")
    with patch("desk_robot.simulator.time.monotonic", return_value=1.0) as clock:
        await head.command("arm")
        for now in (1.0, 1.025, 1.050, 1.075):
            clock.return_value = now
            await head.command("drive 20 20 250")
            assert (await head.status())["drive_ms"] == 250
        clock.return_value = 1.175
        await head.command("keepalive")
        clock.return_value = 1.324
        assert (await head.status())["drive_ms"] == 1
        clock.return_value = 1.325
        status = await head.status()
        assert status["armed"]
        assert status["motor"] == {"m0": 0, "m1": 0}
        assert status["drive_ms"] == 0


async def test_shorter_overlapping_drive_replaces_longer_pulse():
    head = SimulatedHead("robot-01")
    with patch("desk_robot.simulator.time.monotonic", return_value=1.0) as clock:
        await head.command("arm")
        await head.command("drive 20 20 250")
        clock.return_value = 1.050
        await head.command("drive 10 10 1")
        assert (await head.status())["drive_ms"] == 1
        clock.return_value = 1.051
        status = await head.status()
        assert status["motor"] == {"m0": 0, "m1": 0}
        assert status["drive_ms"] == 0
