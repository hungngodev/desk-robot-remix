"""Exercise the hardware wire contract without opening a transport."""

import pytest
from desk_robot.command_framing import command_ack_matches, expected_ack, validate_command


@pytest.mark.parametrize(
    ("command", "ack"),
    [
        ("drive -40 40", "OK drive left=-40 right=40 ms=250"),
        ("drive 40 -40 1", "OK drive left=40 right=-40 ms=1"),
        ("drive 0 0 250", "OK drive left=0 right=0 ms=250"),
        ("lift 60", "OK lift angle=60"),
        ("grip 120", "OK grip angle=120"),
        ("halt", "OK halt"),
        ("stop", "OK stop"),
    ],
)
def test_command_wire_boundaries(command, ack):
    assert validate_command(command) == command.split()[0]
    assert expected_ack(command) == ack
    assert command_ack_matches({"ok": True, "robot_id": "r1", "reply": ack}, "r1", ack)


@pytest.mark.parametrize(
    "command",
    [
        "drive -41 0", "drive 0 41", "drive 0 0 0", "drive 0 0 251",
        "drive 0 0 -1", "drive 0 0 1\r\n", "drive 0 0 1\x00", "drive  0 0",
        "drive 0 0 1 2", "lift 59", "grip 121", "halt ", "STOP", "status\n",
        "drive ０ 0", "lift " + "0" * 96, None, 42,
    ],
)
def test_invalid_commands_never_produce_ack(command):
    with pytest.raises(ValueError):
        expected_ack(command)


@pytest.mark.parametrize(
    "receipt",
    [
        None, [], {},
        {"ok": 1, "robot_id": "r1", "reply": "OK halt"},
        {"ok": False, "robot_id": "r1", "reply": "OK halt"},
        {"ok": True, "robot_id": "r2", "reply": "OK halt"},
        {"ok": True, "robot_id": "r1", "reply": "OK stop"},
        {"ok": True, "robot_id": "r1", "reply": "OK halt\r\n"},
        {"ok": True, "robot_id": "r1"},
    ],
)
def test_unmatched_terminal_ack_is_never_accepted(receipt):
    assert not command_ack_matches(receipt, "r1", "OK halt")
