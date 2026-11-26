"""Strict read-only VL53L0X optical quality provenance for eight mux lanes.

Uses raw 9.7 fixed point MCPS words from an existing WROOM range conversion.
Never treats an optical sample as motion clearance, charging proof, distance
calibration or a source of instructions.
"""
from __future__ import annotations

from .sensor_event_contract import is_uint


def validate_optics(data: object, robot_id: str) -> dict:
    if not isinstance(data, dict) or data.get("robot_id") != robot_id:
        raise ValueError("Optical diagnostics robot identity mismatch")
    optics = data.get("optics")
    if not isinstance(optics, dict):
        raise ValueError("Missing WROOM optical diagnostics")
    if (optics.get("motor_authorized") is not False
            or optics.get("physical_qualified") is not False):
        raise ValueError("Optical diagnostics cannot authorize motors or qualification")
    present = optics.get("present_mask")
    valid = optics.get("valid_mask")
    if (not is_uint(present, 255) or not is_uint(valid, 255)
            or valid & ~present):
        raise ValueError("Invalid optical mask provenance")
    raw = {}
    for field, max_value in (
        ("ambient_97", 65535), ("signal_97", 65535),
        ("age_ms", 4294967295),
    ):
        values = optics.get(field)
        if (type(values) is not list or len(values) != 8 or
                any(not is_uint(value, max_value) for value in values)):
            raise ValueError(f"Missing or invalid eight channel {field}")
        raw[field] = tuple(values)
    for channel, age in enumerate(raw["age_ms"]):
        if not (present & (1 << channel)) and any(
                raw[field][channel] for field in raw):
            raise ValueError("Absent optical lane contains sample data")
        if (valid & (1 << channel)) and (
                age >= 200 if channel < 5 else age > 350):
            raise ValueError("Stale optical sample marked valid")
        # Match the pinned WROOM driver minimum: 0.25 Mcps in Q9.7.
        if valid & (1 << channel) and raw["signal_97"][channel] < 32:
            raise ValueError("Weak optical sample marked valid")
    return {
        "robot_id": robot_id,
        "optics": {
            **raw,
            "present_mask": present,
            "valid_mask": valid,
            "physical_qualified": False,
            "motor_authorized": False,
            "raw_97_mcps_not_calibrated": True,
        },
    }
