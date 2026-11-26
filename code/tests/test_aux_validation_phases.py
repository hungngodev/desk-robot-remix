"""Preserve AUX validation precedence and independent raw diagnostics."""
from copy import deepcopy

import pytest
from desk_robot.aux import validate_aux


@pytest.fixture
def frame():
    return {
        "robot_id": "robot-01",
        "pulse": {"present": True, "valid": True, "part_id": 21,
                  "red": 200, "ir": 30000, "age_ms": 45, "bpm": None,
                  "medical": False},
        "angles": {"raw": [2000, 4095, 0], "present_mask": 3,
                   "valid_mask": 1, "magnet": [32, 0, 0]},
        "force": {"adc": [1024, -55], "jaw_seq": 100, "valid": True,
                  "calibrated": False},
        "climate": {"temp_centi": 2150, "rh_centi": 4555, "valid": True},
        "power": {"cell_mv": 3900, "soc_centi": 7500, "bus_mv": 5000,
                  "shunt_uv": -100, "fuel_valid": True, "fuel_seq": 10,
                  "monitor_valid": True, "current_calibrated": False},
        "proximity": {"raw": 99, "valid": True, "gesture": 1,
                      "gesture_events": 3, "physically_qualified": False},
    }


@pytest.mark.parametrize("field", [
    "jaw_age_ms", "jaw_valid", "belly_seq", "belly_age_ms", "belly_valid",
])
def test_force_explicit_null_is_not_an_omitted_legacy_field(frame, field):
    assert validate_aux(frame, "robot-01") is frame
    frame["force"][field] = None
    with pytest.raises(ValueError) as error:
        validate_aux(frame, "robot-01")
    assert str(error.value) == "Invalid uncalibrated FSR sample"


@pytest.mark.parametrize("group,field", [
    ("pulse", "seq"), ("climate", "seq"), ("climate", "age_ms"),
    ("bmp280", "seq"), ("bmp280", "age_ms"), ("power", "fuel_seq"),
])
def test_legacy_optional_null_clock_remains_raw_compatible(frame, group, field):
    frame["bmp280"] = {"present": True, "valid": True, "chip_id": 0x58,
                       "temp_centi": 2000, "pressure_pa": 100000,
                       "physically_verified": False}
    frame[group][field] = None
    assert validate_aux(frame, "robot-01") is frame


@pytest.mark.parametrize("first,second,message", [
    (("pulse", "medical", True), ("angles", "valid_mask", 7),
     "Invalid raw MAX30102 paw source"),
    (("angles", "boot_id", 0), ("force", "calibrated", True),
     "Invalid AS5600 acquisition provenance"),
    (("power", "shunt_uv", 81920), ("power", "fuel_seq", 0),
     "Invalid INA226 saturated shunt source"),
    (("power", "fuel_age_ms", None), ("power", "pack_age_ms", None),
     "Invalid MAX17048 fuel acquisition age"),
    (("force", "boot_id", 0), ("proximity", "physically_qualified", True),
     "Invalid APDS9960 source"),
])
def test_first_error_is_stable_when_multiple_groups_fail(frame, first, second, message):
    for group, key, value in (first, second):
        frame[group][key] = value
    original = deepcopy(frame)
    with pytest.raises(ValueError) as error:
        validate_aux(frame, "robot-01")
    assert str(error.value) == message
    assert frame == original


def test_optional_groups_are_checked_before_diagnostic_normalization(frame):
    frame["pulse"]["age_ms"] = 251
    frame["proximity"]["raw"] = 255
    frame["bmp280"] = []
    frame["dock"] = []
    frame["nfc"] = []
    for group, message in (
        ("bmp280", "Invalid optional BMP280 ambient sample"),
        ("dock", "Invalid optional read only dock pin status"),
        ("nfc", "Invalid read only PN532 toy tag evidence"),
    ):
        original = deepcopy(frame)
        with pytest.raises(ValueError) as error:
            validate_aux(frame, "robot-01")
        assert str(error.value) == message
        assert frame == original
        del frame[group]
    original = deepcopy(frame)
    result = validate_aux(frame, "robot-01")
    assert result == {
        **original,
        "pulse": {**original["pulse"], "valid": False},
        "proximity": {**original["proximity"], "valid": False, "saturated": True},
    }
    assert frame == original
    for group in ("angles", "force", "climate", "power"):
        assert result[group] is frame[group]
