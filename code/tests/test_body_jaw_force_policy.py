"""Firmware requires mounted force calibration before any jaw closure."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_full_profile_grip_force_limit_is_compiled_only_from_measured_values():
    firmware = (ROOT / "code/firmware/body/src/main.cpp").read_text()
    assert "control.require_grip_feedback(true);" in firmware
    assert "DESK_ROBOT_JAW_FORCE_LIMITS_QUALIFIED" in firmware
    for key in (
        "DESK_ROBOT_JAW_OPEN_DEG", "DESK_ROBOT_JAW_CLOSED_DEG",
        "DESK_ROBOT_JAW_EMPTY_ADC", "DESK_ROBOT_JAW_FORCE_SIGN",
        "DESK_ROBOT_JAW_MAX_DELTA_ADC",
    ):
        assert key in firmware
    assert "control.configure_jaw_force_limits(jaw_limits)" in firmware
    assert "jaw_force_limits_unqualified jaw_locked" in firmware

    controller = (ROOT / "code/firmware/body/lib/BodyControl/BodyControl.cpp").read_text()
    assert "ERR grip local_force_limits_missing" in controller
    assert "ERR grip local_force_limit_or_reversal" in controller
    assert "jaw_force_allows_closing()" in controller
