"""Real WROOM to XIAO to Mac dual IR telemetry contract.

No NEC frame, no matter how convincing, independently authorizes a motor
command or charger output.
"""
import copy

import httpx
import pytest

from desk_robot.config import RobotConfig
from desk_robot.dock_ir import validate_ir
from desk_robot.transport import HeadError, HttpHead


def evidence():
    return {
        "robot_id": "robot-01", "left_valid": True, "right_valid": True,
        "match": True, "left_seq": 2, "right_seq": 3,
        "left_age_ms": 15, "right_age_ms": 25,
        "code": 0xcb34ed12, "motor_authorized": False,
        "charging_authorized": False, "physical_qualified": False,
    }


def test_two_verified_receptions_are_only_an_observation():
    assert validate_ir(evidence(), "robot-01")["match"] is True
    missing = evidence()
    missing.update(left_valid=False, right_valid=False, match=False, code=0)
    assert validate_ir(missing, "robot-01")["motor_authorized"] is False


@pytest.mark.parametrize("field,value", [
    ("robot_id", "robot-02"),
    ("left_valid", 1), ("right_valid", "true"),
    ("match", "true"), ("left_seq", -1), ("right_seq", True),
    ("code", 2**32), ("left_age_ms", -1),
    ("motor_authorized", True), ("charging_authorized", True),
    ("physical_qualified", True),
])
def test_spoofed_receiver_or_authority_claim_is_rejected(field, value):
    reading = evidence()
    reading[field] = value
    with pytest.raises(ValueError):
        validate_ir(reading, "robot-01")


def test_mismatched_reception_cannot_report_a_beacon_identity():
    reading = evidence()
    reading["match"] = False
    with pytest.raises(ValueError):
        validate_ir(reading, "robot-01")
    reading["code"] = 0
    assert validate_ir(reading, "robot-01")["match"] is False
    reading = evidence()
    reading["right_valid"] = False
    with pytest.raises(ValueError):
        validate_ir(reading, "robot-01")
    reading = evidence()
    reading["left_seq"] = 0
    with pytest.raises(ValueError):
        validate_ir(reading, "robot-01")
    reading = evidence()
    reading["right_age_ms"] = 201
    with pytest.raises(ValueError):
        validate_ir(reading, "robot-01")


async def test_http_head_uses_existing_auth_and_get_only(monkeypatch):
    monkeypatch.setenv("TEST_ROBOT_NECS", "R" * 48)
    events = []

    def handler(request):
        events.append(request)
        assert request.method == "GET"
        assert request.url.path == "/api/ir"
        assert request.headers["Authorization"] == "Bearer " + "R" * 48
        return httpx.Response(200, json=evidence())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(RobotConfig(
            id="robot-01", name="pet", token_env="TEST_ROBOT_NECS"
        ), client)
        reading = await head.ir_status()
        assert reading == evidence()
    assert len(events) == 1


async def test_http_head_does_not_retry_or_accept_claimed_charging(monkeypatch):
    monkeypatch.setenv("TEST_ROBOT_NECS", "R" * 48)
    calls = []
    bad = evidence()
    bad["charging_authorized"] = True

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=bad)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(RobotConfig(
            id="robot-01", name="pet", token_env="TEST_ROBOT_NECS"
        ), client)
        with pytest.raises(HeadError, match="NEC must not claim"):
            await head.ir_status()
    assert len(calls) == 1
