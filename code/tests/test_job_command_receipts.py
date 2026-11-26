"""A transport result is not necessarily an acknowledged body command."""
from __future__ import annotations

import asyncio

import pytest

from desk_robot.command_framing import expected_ack
from desk_robot.operations import OperationError, _bounded_pulse_stop, dispatch_job_command


class ReplyHead:
    def __init__(self, reply, *, supports_dispatch_check):
        self.reply = reply
        self.supports_dispatch_check = supports_dispatch_check
        self.calls = 0

    async def command(self, command, *, dispatch_check=None):
        if dispatch_check is not None:
            dispatch_check()
        self.calls += 1
        return self.reply


@pytest.mark.parametrize("supports_dispatch_check", [False, True])
@pytest.mark.parametrize("command", ["arm", "keepalive", "drive 20 20 100", "grip 90"])
@pytest.mark.parametrize("invalid", ["queued", "failed", "foreign", "wrong", "truthy", "empty"])
def test_unconfirmed_job_command_never_returns_receipt(supports_dispatch_check, command, invalid):
    reply = {"ok": True, "robot_id": "robot-01", "reply": expected_ack(command)}
    if invalid == "queued":
        reply["reply"] = "queued"
    elif invalid == "failed":
        reply["ok"] = False
    elif invalid == "foreign":
        reply["robot_id"] = "robot-02"
    elif invalid == "wrong":
        reply["reply"] = "OK halt"
    elif invalid == "truthy":
        reply["ok"] = 1
    else:
        reply = None
    head = ReplyHead(reply, supports_dispatch_check=supports_dispatch_check)
    with pytest.raises(OperationError, match="command ACK"):
        asyncio.run(dispatch_job_command(head, command, lambda: None, robot_id="robot-01"))
    assert head.calls == 1


@pytest.mark.parametrize("supports_dispatch_check", [False, True])
def test_matching_receipt_remains_command_ack_only(supports_dispatch_check):
    command = "drive 20 20 100"
    reply = {"ok": True, "robot_id": "robot-01", "reply": expected_ack(command)}
    head = ReplyHead(reply, supports_dispatch_check=supports_dispatch_check)
    result = asyncio.run(dispatch_job_command(head, command, lambda: None, robot_id="robot-01"))
    assert result == reply
    assert head.calls == 1
    assert "physical_acceptance_pass" not in result


def test_revoked_authority_rejects_even_matching_late_receipt():
    reply = {"ok": True, "robot_id": "robot-01", "reply": "OK arm"}
    head = ReplyHead(reply, supports_dispatch_check=True)

    def check():
        if head.calls:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(dispatch_job_command(head, "arm", check, robot_id="robot-01"))
    assert head.calls == 1


@pytest.mark.parametrize("reply", [
    None, {}, {"ok": True, "robot_id": "robot-01", "reply": "queued"},
    {"ok": True, "robot_id": "robot-02", "reply": "OK stop"},
    {"ok": False, "robot_id": "robot-01", "reply": "OK stop"},
    {"ok": True, "robot_id": "robot-01", "reply": "OK halt"},
])
def test_unconfirmed_pulse_stop_cannot_continue(reply):
    head = ReplyHead(reply, supports_dispatch_check=False)
    with pytest.raises(OperationError, match="command ACK"):
        asyncio.run(_bounded_pulse_stop(head, "robot-01"))
    assert head.calls == 1


def test_matching_pulse_stop_is_only_a_command_receipt():
    reply = {"ok": True, "robot_id": "robot-01", "reply": "OK stop"}
    head = ReplyHead(reply, supports_dispatch_check=False)
    assert asyncio.run(_bounded_pulse_stop(head, "robot-01")) == reply
    assert head.calls == 1


@pytest.mark.parametrize("command", ["drive 20 20 100", "grip 90", "stop", "halt"])
def test_command_receipts_cannot_forward_adapter_physical_claims(command):
    reply = {"ok": True, "robot_id": "robot-01", "reply": expected_ack(command)}
    head = ReplyHead(
        {**reply, "status": "succeeded", "grasped": True, "charged": True,
         "physical_acceptance_pass": True},
        supports_dispatch_check=False,
    )
    if command == "stop":
        result = asyncio.run(_bounded_pulse_stop(head, "robot-01"))
    else:
        result = asyncio.run(dispatch_job_command(head, command, lambda: None, robot_id="robot-01"))
    assert result == reply
