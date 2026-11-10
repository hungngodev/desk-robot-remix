"""Strict read-only source validation for one robot's optional sensor telemetry.

Raw samples are never evidence of medical data, a real grasp force, charging,
calibrated locomotion, or authorization to move motors.
"""
from __future__ import annotations


def _uint(value, upper: int) -> bool:
    return type(value) is int and 0 <= value <= upper


def _sint(value, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _bool(value) -> bool:
    return type(value) is bool


def _array(value, length: int, predicate) -> bool:
    return isinstance(value, list) and len(value) == length and all(
        predicate(v) for v in value
    )


def validate_aux(data: dict, robot_id: str) -> dict:
    if not isinstance(data, dict) or data.get("robot_id") != robot_id:
        raise ValueError("Aux sensor identity mismatch")
    pulse, angles = data.get("pulse"), data.get("angles")
    force, climate = data.get("force"), data.get("climate")
    power, proximity = data.get("power"), data.get("proximity")
    if not all(isinstance(group, dict) for group in (
        pulse, angles, force, climate, power, proximity,
    )):
        raise ValueError("Incomplete auxiliary sensor payload")

    if (not _bool(pulse.get("present")) or not _bool(pulse.get("valid"))
            or not _uint(pulse.get("part_id"), 255)
            or not _uint(pulse.get("red"), 262143)
            or not _uint(pulse.get("ir"), 262143)
            or not _uint(pulse.get("age_ms"), 0xffffffff)
            or pulse.get("bpm", "missing") is not None
            or pulse.get("medical") is not False
            or (pulse["valid"] and not pulse["present"])):
        raise ValueError("Invalid raw MAX30102 paw source")

    present, valid = angles.get("present_mask"), angles.get("valid_mask")
    if (not _uint(present, 7) or not _uint(valid, 7)
            or valid & ~present
            or not _array(angles.get("raw"), 3, lambda n: _uint(n, 4095))
            or not _array(angles.get("magnet"), 3, lambda n: _uint(n, 0x38))
            or any(valid & (1 << i) and angles["magnet"][i] != 0x20
                   for i in range(3))):
        raise ValueError("Invalid AS5600 magnetic angle source")

    if (not _array(force.get("adc"), 2, lambda n: _sint(n, -32768, 32767))
            or not _bool(force.get("valid"))
            or force.get("calibrated") is not False):
        raise ValueError("Invalid uncalibrated FSR sample")

    if (not _sint(climate.get("temp_centi"), -4500, 13000)
            or not _uint(climate.get("rh_centi"), 10000)
            or not _bool(climate.get("valid"))):
        raise ValueError("Invalid SHT41 climate sample")

    if (not _uint(power.get("cell_mv"), 4500)
            or not _uint(power.get("soc_centi"), 10000)
            or not _uint(power.get("bus_mv"), 40959)
            or not _sint(power.get("shunt_uv"), -81920, 81920)
            or not _bool(power.get("fuel_valid"))
            or not _bool(power.get("monitor_valid"))
            or power.get("current_calibrated") is not False):
        raise ValueError("Invalid uncalibrated battery or shunt source")

    if (not _uint(proximity.get("raw"), 255)
            or not _bool(proximity.get("valid"))
            or proximity.get("gesture", "missing") is not None):
        raise ValueError("Invalid APDS9960 source")
    return data
