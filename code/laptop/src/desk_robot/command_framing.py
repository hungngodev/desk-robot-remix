"""Pure Mac/Sense command grammar and WROOM acknowledgement matching."""

from __future__ import annotations

import re

# Wire contract: omitted duration uses the same bound as WROOM kMaxDriveMs.
MAX_DRIVE_DURATION_MS = 250


def _drive_arguments(args: list[str]) -> tuple[int, int, int]:
    left, right = map(int, args[:2])
    duration = int(args[2]) if len(args) == 3 else MAX_DRIVE_DURATION_MS
    return left, right, duration


def validate_command(command: str) -> str:
    if (
        type(command) is not str
        or len(command) > 95
        or not re.fullmatch(r"[a-z0-9 -]+", command)
    ):
        raise ValueError("Invalid command")
    tokens = command.split(" ")
    op = tokens[0]
    if op in {"ping", "status", "arm", "disarm", "stop", "halt", "keepalive"} and len(tokens) == 1:
        return op
    if op == "drive" and len(tokens) in (3, 4):
        values = tokens[1:]
        if not all(re.fullmatch(r"-?[0-9]{1,3}", x) for x in values):
            raise ValueError("drive arguments must be integers")
        left, right, duration = _drive_arguments(values)
        if -40 <= left <= 40 and -40 <= right <= 40 and 1 <= duration <= MAX_DRIVE_DURATION_MS:
            return op
    if op in {"lift", "grip"} and len(tokens) == 2 and tokens[1].isdigit():
        if 60 <= int(tokens[1]) <= 120:
            return op
    raise ValueError("Command exceeds conservative bounds")


def drive_arguments(command: str) -> tuple[int, int, int]:
    """Return validated left, right and explicit or default drive duration (ms)."""
    if validate_command(command) != "drive":
        raise ValueError("Expected a drive command")
    return _drive_arguments(command.split()[1:])


def drive_duration_ms(command: str) -> int:
    """Return the validated explicit or default wire duration of a drive command."""
    return drive_arguments(command)[2]


def expected_ack(command: str) -> str:
    op = validate_command(command)
    args = command.split()[1:]
    if op == "drive":
        left, right, ms = _drive_arguments(args)
        return f"OK drive left={left} right={right} ms={ms}"
    if op in {"lift", "grip"}:
        return f"OK {op} angle={int(args[0])}"
    return f"OK {op}"


def command_ack_matches(data: object, robot_id: str, expected: str) -> bool:
    """Match a decoded receipt exactly; an ACK is not physical stop evidence."""
    return (
        type(robot_id) is str
        and type(expected) is str
        and type(data) is dict
        and data.get("ok") is True
        and type(data.get("robot_id")) is str
        and data.get("robot_id") == robot_id
        and type(data.get("reply")) is str
        and data.get("reply") == expected
    )
