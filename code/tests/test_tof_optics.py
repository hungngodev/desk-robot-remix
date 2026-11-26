"""Same 12-byte VL53L0X raw quality data, never new motion authority."""
from __future__ import annotations

from copy import deepcopy

import pytest
from desk_robot.tof_optics import validate_optics


def sample() -> dict:
    return {
        "robot_id": "robot-01",
        "optics": {
            "ambient_97": [291, 0, 0, 0, 0, 32, 0, 0],
            "signal_97": [17767, 0, 0, 0, 0, 1024, 0, 0],
            "age_ms": [50, 0, 0, 0, 0, 350, 0, 0],
            "present_mask": 0b00100001,
            "valid_mask": 0b00100001,
            "physical_qualified": False,
            "motor_authorized": False,
        },
    }


def test_raw_optics_are_private_unqualified_and_match_the_two_freshness_budgets():
    result = validate_optics(sample(), "robot-01")
    assert result["robot_id"] == "robot-01"
    assert result["optics"]["signal_97"] == (17767, 0, 0, 0, 0, 1024, 0, 0)
    assert result["optics"]["valid_mask"] == 33
    assert result["optics"]["raw_97_mcps_not_calibrated"]
    assert result["optics"]["motor_authorized"] is False
    assert result["optics"]["physical_qualified"] is False


@pytest.mark.parametrize("mutate", [
    lambda x: x.update({"robot_id": "robot-02"}),
    lambda x: x["optics"].update({"motor_authorized": True}),
    lambda x: x["optics"].update({"physical_qualified": True}),
    lambda x: x["optics"].update({"valid_mask": 255}),
    lambda x: x["optics"].update({"present_mask": True}),
    lambda x: x["optics"].update({"ambient_97": [0] * 7}),
    lambda x: x["optics"].update({"signal_97": [0] * 9}),
    lambda x: x["optics"].update({"signal_97": [0] * 7 + [65536]}),
    lambda x: x["optics"].update({"signal_97": [0] * 7 + [False]}),
    lambda x: x["optics"].update({"age_ms": [0] * 7 + [-1]}),
    lambda x: x["optics"].update({"age_ms": [200, 0, 0, 0, 0, 350, 0, 0]}),
    lambda x: x["optics"].update({"age_ms": [50, 0, 0, 0, 0, 351, 0, 0]}),
    lambda x: x["optics"].pop("age_ms"),
    lambda x: x["optics"].pop("motor_authorized"),
])
def test_malformed_or_unqualified_optical_receipt_fails_closed(mutate):
    data = deepcopy(sample())
    mutate(data)
    with pytest.raises(ValueError):
        validate_optics(data, "robot-01")


def test_invalid_or_missing_optics_cannot_be_treated_as_conversation_evidence():
    for raw in (None, {}, [], {"robot_id": "robot-01"}):
        with pytest.raises(ValueError):
            validate_optics(raw, "robot-01")


def test_old_optical_raw_words_can_be_reported_without_fake_validity():
    data = sample()
    data["optics"]["valid_mask"] = 0
    data["optics"]["age_ms"][0] = 4294967295
    data["optics"]["age_ms"][5] = 4294967295
    result = validate_optics(data, "robot-01")
    assert result["optics"]["signal_97"][0] == 17767
    assert result["optics"]["valid_mask"] == 0

@pytest.mark.parametrize("field", ["ambient_97", "signal_97", "age_ms"])
@pytest.mark.parametrize("channel", [1, 2, 3, 4, 6, 7])
def test_absent_optical_lane_cannot_contain_raw_measurement(field, channel):
    data = sample()
    data["optics"][field][channel] = 1
    with pytest.raises(ValueError, match="Absent optical lane contains sample data"):
        validate_optics(data, "robot-01")


@pytest.mark.parametrize("channel", range(8))
@pytest.mark.parametrize("signal", [0, 31, 32, 33])
def test_signal_validity_matches_wroom_minimum(channel, signal):
    data = sample()
    optics = data["optics"]
    for field in ("ambient_97", "signal_97", "age_ms"):
        optics[field] = [0] * 8
    optics["present_mask"] = optics["valid_mask"] = 1 << channel
    optics["ambient_97"][channel] = 65535
    optics["signal_97"][channel] = signal
    if signal < 32:
        with pytest.raises(ValueError, match="Weak optical sample marked valid"):
            validate_optics(data, "robot-01")
        optics["valid_mask"] = 0
    result = validate_optics(data, "robot-01")["optics"]
    assert result["signal_97"][channel] == signal
    assert result["valid_mask"] == (1 << channel if signal >= 32 else 0)
