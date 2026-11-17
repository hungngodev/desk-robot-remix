"""Real WROOM to XIAO to Mac dual IR telemetry contract.

No NEC frame, no matter how convincing, independently authorizes a motor
command or charger output.
"""

import httpx
import pytest
from desk_robot.config import RobotConfig, Settings
from desk_robot.dock_ir import dock_beacon_code, validate_ir
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



@pytest.mark.parametrize(("dock_id", "raw"), [
    (1, 0xce31ed12), (2, 0xcd32ed12), (3, 0xcc33ed12),
    (4, 0xcb34ed12), (5, 0xca35ed12),
])
def test_exact_five_dock_codes_match_pinned_nec_transmitter(dock_id, raw):
    assert dock_beacon_code(dock_id) == raw
    data = evidence()
    data["code"] = raw
    assert validate_ir(data, "robot-01", expected_dock_id=dock_id) == data


@pytest.mark.parametrize("wrong", [True, 0, -1, 6, 1.0, "1"])
def test_invalid_physical_dock_assignment_fails_closed(wrong):
    with pytest.raises(ValueError):
        dock_beacon_code(wrong)


def test_foreign_physical_dock_rejected_even_when_both_receivers_agree():
    data = evidence()  # valid dock 4 code, not robot 1's assigned dock
    assert validate_ir(data, "robot-01") == data  # old passive API
    with pytest.raises(ValueError, match="Foreign NEC dock beacon"):
        validate_ir(data, "robot-01", expected_dock_id=1)
    data["code"] = dock_beacon_code(1)
    assert validate_ir(data, "robot-01", expected_dock_id=1) == data
    data.update(match=False, code=0, right_valid=False)
    assert validate_ir(data, "robot-01", expected_dock_id=1) == data


def test_two_robots_cannot_claim_one_physical_dock():
    a = RobotConfig(id="robot-01", name="Pip", token_env="T1", dock_beacon_id=1)
    b = RobotConfig(id="robot-02", name="Dot", token_env="T2", dock_beacon_id=1)
    with pytest.raises(ValueError, match="only one robot"):
        Settings(robots=[a, b], mode="hardware")


def test_qualified_hardware_docking_cannot_omit_beacon_assignment():
    with pytest.raises(ValueError, match="requires assigned beacon"):
        Settings(robots=[RobotConfig(
            id="robot-01", name="Pip", token_env="T1",
            dock_motion_qualified=True
        )], mode="hardware")


async def test_http_head_rejects_foreign_dock_using_existing_get_boundary(monkeypatch):
    monkeypatch.setenv("TEST_ROBOT_NECS", "R" * 48)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=evidence())  # dock 4

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(RobotConfig(
            id="robot-01", name="pet", token_env="TEST_ROBOT_NECS",
            dock_beacon_id=1,
        ), client)
        with pytest.raises(HeadError, match="Foreign NEC dock beacon"):
            await head.ir_status()
    assert len(calls) == 1


@pytest.mark.parametrize("code", [
    0x00000001, 0xffffffff, 0xcf30ed12, 0xc936ed12,
    0xce31ef12, 0xce31ed13,
])
def test_matched_beacon_rejects_unknown_or_malformed_nec_codes(code):
    # Agreement between two receivers cannot legitimize a non-fleet code.
    reading = evidence()
    reading["code"] = code
    with pytest.raises(ValueError, match="Unknown NEC dock beacon code"):
        validate_ir(reading, "robot-01")
