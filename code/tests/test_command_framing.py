"""Exercise the hardware wire contract without opening a transport."""

import pytest
from desk_robot.command_framing import (
    command_ack_matches,
    drive_duration_ms,
    expected_ack,
    validate_command,
)


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


@pytest.mark.parametrize(
    ("command", "duration"),
    [("drive -40 40", 250), ("drive 40 -40 1", 1), ("drive 0 0 250", 250)],
)
def test_drive_duration_matches_ack(command, duration):
    assert drive_duration_ms(command) == duration
    assert expected_ack(command).endswith(f" ms={duration}")


@pytest.mark.parametrize("command", ["halt", "lift 60", "drive 0 0 251"])
def test_drive_duration_rejects_other_operations_and_invalid_pulses(command):
    with pytest.raises(ValueError):
        drive_duration_ms(command)


class _TextAdapter(str):
    """A typed adapter is not a plain wire string."""


class _ReceiptAdapter(dict):
    """A custom mapping is not a decoded JSON receipt."""


@pytest.mark.parametrize("command", [_TextAdapter("halt"), _TextAdapter("drive 0 0 1")])
def test_command_requires_plain_wire_string(command):
    with pytest.raises(ValueError, match="Invalid command"):
        validate_command(command)


@pytest.mark.parametrize(
    "receipt",
    [
        _ReceiptAdapter(ok=True, robot_id="r1", reply="OK halt"),
        {"ok": True, "robot_id": _TextAdapter("r1"), "reply": "OK halt"},
        {"ok": True, "robot_id": "r1", "reply": _TextAdapter("OK halt")},
    ],
)
def test_ack_requires_plain_decoded_receipt_types(receipt):
    assert not command_ack_matches(receipt, "r1", "OK halt")


@pytest.mark.parametrize("length", [94, 95, 96])
def test_command_line_length_boundary(length):
    # A padded in-range servo angle isolates the wire length from numeric bounds.
    command = "lift " + "60".zfill(length - len("lift "))
    assert len(command.encode("ascii")) == length
    if length <= 95:
        assert validate_command(command) == "lift"
        assert expected_ack(command) == "OK lift angle=60"
    else:
        with pytest.raises(ValueError, match="Invalid command"):
            expected_ack(command)


@pytest.mark.parametrize(
    "command",
    [
        "", " ", "\r", "\n", "\x00", b"", b"\xff", b"halt", bytearray(b"halt"),
        "driv", "drive", "drive 0", "drive 0 ", "drive 0 0 ", "lift", "grip ",
        "hal", "st", "halt\t", "halt\nstop", "halt\ufffd",
    ],
)
def test_incomplete_or_non_text_commands_are_rejected(command):
    with pytest.raises(ValueError):
        validate_command(command)
    with pytest.raises(ValueError):
        expected_ack(command)
