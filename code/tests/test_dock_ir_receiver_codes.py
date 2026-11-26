"""The optional NEC receiver identities must not weaken aggregate validation."""

import pytest
from desk_robot.dock_ir import dock_beacon_code, validate_ir


@pytest.fixture
def receipt():
    code = dock_beacon_code(4)
    return {
        "robot_id": "robot-01", "left_valid": True, "right_valid": True,
        "match": True, "left_seq": 2, "right_seq": 3,
        "left_age_ms": 15, "right_age_ms": 25, "code": code,
        "motor_authorized": False, "charging_authorized": False,
        "physical_qualified": False, "left_code": code, "right_code": code,
    }


def test_receivers_agree_with_aggregate_and_keep_read_only_receipt(receipt):
    assert validate_ir(receipt, "robot-01", expected_dock_id=4) is receipt
    assert receipt["motor_authorized"] is False
    assert receipt["charging_authorized"] is False
    assert receipt["physical_qualified"] is False


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("value", [None, True, 0, 1, []])
def test_valid_receiver_requires_known_integer_identity(receipt, side, value):
    receipt[f"{side}_code"] = value
    with pytest.raises(ValueError, match=f"Invalid NEC {side} beacon identity"):
        validate_ir(receipt, "robot-01")


@pytest.mark.parametrize("side", ["left", "right"])
def test_partial_receiver_identity_is_rejected(receipt, side):
    del receipt[f"{side}_code"]
    with pytest.raises(ValueError, match=f"Invalid NEC {side} beacon identity"):
        validate_ir(receipt, "robot-01")


@pytest.mark.parametrize("side", ["left", "right"])
def test_receiver_cannot_disagree_with_matched_aggregate(receipt, side):
    receipt[f"{side}_code"] = dock_beacon_code(1)
    with pytest.raises(ValueError, match="Matched NEC beacon disagrees"):
        validate_ir(receipt, "robot-01")
    with pytest.raises(ValueError, match="Foreign NEC dock beacon"):
        validate_ir(receipt, "robot-01", expected_dock_id=4)


@pytest.mark.parametrize("side", ["left", "right"])
def test_invalid_receiver_requires_zero_code(receipt, side):
    receipt.update(match=False, code=0)
    receipt[f"{side}_valid"] = False
    with pytest.raises(ValueError, match=f"Invalid NEC {side} beacon identity"):
        validate_ir(receipt, "robot-01")
    receipt[f"{side}_code"] = 0
    assert validate_ir(receipt, "robot-01", expected_dock_id=4) is receipt


def test_legacy_receipt_without_either_receiver_code_remains_supported(receipt):
    del receipt["left_code"]
    del receipt["right_code"]
    assert validate_ir(receipt, "robot-01", expected_dock_id=4) is receipt


@pytest.mark.parametrize("side", ["left", "right"])
def test_unmatched_fresh_receiver_must_still_belong_to_assigned_dock(receipt, side):
    receipt.update(match=False, code=0)
    other = "right" if side == "left" else "left"
    receipt[f"{other}_valid"] = False
    receipt[f"{other}_code"] = 0
    receipt[f"{side}_code"] = dock_beacon_code(1)
    assert validate_ir(receipt, "robot-01") is receipt
    with pytest.raises(ValueError, match="Foreign NEC dock beacon"):
        validate_ir(receipt, "robot-01", expected_dock_id=4)
    receipt[f"{side}_code"] = dock_beacon_code(4)
    assert validate_ir(receipt, "robot-01", expected_dock_id=4) is receipt


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("value", [False, 0.0])
def test_invalid_receiver_zero_identity_must_be_integer(receipt, side, value):
    receipt.update(match=False, code=0)
    receipt[f"{side}_valid"] = False
    receipt[f"{side}_code"] = value
    with pytest.raises(ValueError, match=f"Invalid NEC {side} beacon identity"):
        validate_ir(receipt, "robot-01")
