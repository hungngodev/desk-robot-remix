"""Keep the Mac drive duration in sync with the independent WROOM wire contract."""

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from desk_robot.simulator import SimulatedHead
from desk_robot.transport import MAX_DRIVE_DURATION_MS, drive_duration_ms, expected_ack

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
