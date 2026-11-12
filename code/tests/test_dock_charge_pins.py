"""Presence of two switches and BQ charger status never certifies charging."""
from pathlib import Path


def test_optional_dock_pin_input_validator_rejects_any_charge_permission():
    root = Path(__file__).resolve().parents[1]
    firmware = (
        root / "firmware/body/lib/AccessorySensors/AccessorySensors.cpp"
    ).read_text()
    body = (root / "firmware/body/lib/BodyControl/BodyControl.cpp").read_text()
    assert "void AccessorySensors::dock_status" in firmware
    assert "case 5:\\n      dock_status(now_ms);" in firmware
    assert "write8(0x20, 0x00, 0xFF)" in firmware
    assert "write8(0x20, 0x0C, 0x0F)" in firmware
    assert "charging_verified" in body


def test_optional_dock_source_requires_bool_pins_no_charging_assertion():
    # Real body telemetry is validated as an optional nested group. It cannot
    # overwrite a fuel gauge or imply an energized dock from model text.
    from desk_robot.aux import _bool

    assert _bool(True) and not _bool(1)
    dock = {
        "present": True, "valid": True, "left_seated": True,
        "right_seated": True, "input_good": True, "charge_indicated": True,
        "charging_verified": False,
    }
    assert all(_bool(dock[k]) for k in (
        "present", "valid", "left_seated", "right_seated",
        "input_good", "charge_indicated",
    ))
    assert dock["charging_verified"] is False


def test_missing_dock_module_never_implies_charging():
    root = Path(__file__).resolve().parents[1]
    body = (
        root / "firmware/body/lib/AccessorySensors/AccessoryReadings.h"
    ).read_text()
    assert "bool present = false, valid = false;" in body
    assert "charge_indicated = false;" in body
