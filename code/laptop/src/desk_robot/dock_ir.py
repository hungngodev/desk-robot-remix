"""Authenticated dual NEC demodulated beacon observations, never a motion permit.

RMT timestamps are read time, not optical exposure time. Without measured
baffle geometry, motor clearance and source timestamp calibration this cannot
estimate steering direction or complete the last centimeter of docking.
"""
from __future__ import annotations


def validate_ir(data: dict, robot_id: str) -> dict:
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
            data[f"{side}_seq"] == 0 or data[f"{side}_age_ms"] > 200
        ):
            raise ValueError(f"Fresh NEC {side} needs a real hardware frame")
    if data["match"]:
        if (not data["left_valid"] or not data["right_valid"]
                or data["code"] == 0):
            raise ValueError("Two physically independent fresh NEC frames required")
    elif data["code"] != 0:
        raise ValueError("Mismatched or stale NEC frames must not identify a beacon")
    return data
