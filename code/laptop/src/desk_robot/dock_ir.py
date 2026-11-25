"""Authenticated dual NEC demodulated beacon observations, never a motion permit.

RMT timestamps are read time, not optical exposure time. Without measured
baffle geometry, motor clearance and source timestamp calibration this cannot
estimate steering direction or complete the last centimeter of docking.
"""
from __future__ import annotations


def dock_beacon_code(dock_id: int) -> int:
    """Match the existing Arduino-IRremote classic NEC sender (0x12, 0x30+id).

    No security or power authorization follows from an IR frame. This only
    distinguishes five physical stations during read-only observation.
    """
    if type(dock_id) is not int or not 1 <= dock_id <= 5:
        raise ValueError("An assigned physical dock ID from 1 to 5 is required")
    command = 0x30 + dock_id
    return ((command ^ 0xff) << 24) | (command << 16) | (0xed << 8) | 0x12


# Only five classic NEC transmitters are configured for this fleet.
# An agreed nonzero code is not sufficient evidence of a known dock.
_KNOWN_DOCK_CODES = frozenset(dock_beacon_code(i) for i in range(1, 6))

def validate_ir(data: dict, robot_id: str, *,
                expected_dock_id: int | None = None,
                elapsed_ms: float = 0.0) -> dict:
    if expected_dock_id is not None:
        expected_code = dock_beacon_code(expected_dock_id)
    else:
        expected_code = None
    # The WROOM age is measured when its report is assembled, not when the
    # Mac receives it. Include all subsequent transport/decision latency.
    # Invalid elapsed time never creates a fresher beacon.
    if type(elapsed_ms) not in (int, float) or not 0 <= elapsed_ms <= 1e9:
        raise ValueError("Invalid NEC elapsed request age")
    if not isinstance(data, dict) or data.get("robot_id") != robot_id:
        raise ValueError("Wrong or missing NEC receiver robot identity")
    for key in ("left_valid", "right_valid", "match"):
        if type(data.get(key)) is not bool:
            raise ValueError(f"Invalid NEC boolean {key}")
    for key in ("left_seq", "right_seq", "left_age_ms", "right_age_ms", "code"):
        v = data.get(key)
        if type(v) is not int or not 0 <= v <= 0xffffffff:
            raise ValueError(f"Invalid NEC integer {key}")
    for key in ("motor_authorized", "charging_authorized", "physical_qualified"):
        if data.get(key) is not False:
            raise ValueError(f"NEC must not claim physical authority: {key}")
    for side in ("left", "right"):
        if data[f"{side}_valid"] and (
            data[f"{side}_seq"] == 0
            or data[f"{side}_age_ms"] + elapsed_ms > 200
        ):
            raise ValueError(f"Fresh NEC {side} needs a real hardware frame")
    if data["match"]:
        if (not data["left_valid"] or not data["right_valid"]
                or data["code"] == 0):
            raise ValueError("Two physically independent fresh NEC frames required")
        # WROOM also accounts for receipt-window uncertainty. The Mac only
        # receives the conservative ages, so enforce this necessary bound
        # without claiming it is sufficient to prove simultaneous reception.
        if abs(data["left_age_ms"] - data["right_age_ms"]) > 120:
            raise ValueError("NEC receiver age separation exceeds 120 ms")
    elif data["code"] != 0:
        raise ValueError("Mismatched or stale NEC frames must not identify a beacon")
    if data["match"] and data["code"] not in _KNOWN_DOCK_CODES:
        raise ValueError("Unknown NEC dock beacon code")
    if data["match"] and expected_code is not None and data["code"] != expected_code:
        # A valid code from robot-04's dock is not robot-01's dock.
        # Never let calibration or an observer silently accept a foreign dock.
        raise ValueError("Foreign NEC dock beacon: expected assigned dock")
    side_keys = ("left_code", "right_code")
    if any(key in data for key in side_keys):
        for side in ("left", "right"):
            value = data.get(f"{side}_code")
            if type(value) is not int or (
                value not in _KNOWN_DOCK_CODES if data[f"{side}_valid"] else value != 0
            ):
                raise ValueError(f"Invalid NEC {side} beacon identity")
            if data[f"{side}_valid"] and expected_code is not None and value != expected_code:
                raise ValueError("Foreign NEC dock beacon: expected assigned dock")
        if data["match"] and any(data[key] != data["code"] for key in side_keys):
            raise ValueError("Matched NEC beacon disagrees with receiver identity")
    return data
