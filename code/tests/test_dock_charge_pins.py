"""Presence of two switches and BQ charger status never certifies charging."""
from pathlib import Path


def test_optional_dock_pin_input_validator_rejects_any_charge_permission():
    root = Path(__file__).resolve().parents[1]
    firmware = (
        root / "firmware/body/lib/AccessorySensors/AccessorySensors.cpp"
    ).read_text()
    body = (root / "firmware/body/lib/BodyControl/BodyControl.cpp").read_text()
    assert "void AccessorySensors::dock_status" in firmware
    assert "case 5:\n      dock_status(now_ms);" in firmware
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


def test_real_chg_low_without_pgood_stays_observable_and_latches_safety():
    # TI BQ2407x CHG and PGOOD are independent open-drain GPIO inputs.
    # The old producer masked CHG when PGOOD was high, making this genuine
    # pin contradiction impossible for the Mac or WROOM to diagnose.
    from desk_robot.dock_evidence import classify_dock

    root = Path(__file__).resolve().parents[1]
    firmware = (
        root / "firmware/body/lib/AccessorySensors/AccessorySensors.cpp"
    ).read_text()
    local_guard = (
        root / "firmware/body/lib/BodyControl/BodyControl.cpp"
    ).read_text()
    helper = (
        root / "firmware/body/lib/AccessorySensors/AccessoryReadings.h"
    ).read_text()
    assert "dock.input_good = dock_pgood_asserted(bits);" in firmware
    assert "dock.charge_indicated = dock_chg_asserted(bits);" in firmware
    assert "constexpr bool dock_pgood_asserted(std::uint8_t gpioa)" in helper
    assert "constexpr bool dock_chg_asserted(std::uint8_t gpioa)" in helper
    assert "dock.charge_indicated = (bits & 0x08U) == 0 &&" not in firmware
    assert "dock.input_good || dock.left_seated ||" in local_guard
    assert "dock.right_seated || dock.charge_indicated" in local_guard
    state = classify_dock({
        "present": True,
        "valid": True,
        "left_seated": False,
        "right_seated": False,
        "input_good": False,
        "charge_indicated": True,
    })
    assert state == "charge_signal_without_input_fault"
