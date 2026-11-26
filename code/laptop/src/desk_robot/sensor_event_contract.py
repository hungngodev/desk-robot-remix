"""Shared read-only event registry for the existing Mac camera and pet owners.

These names label actual input events or scheduling causes, not motion
authority, person recognition, calibration, or permission to speak.
Keep one registry so the camera hub cannot reject a sensor kind that the
pet controller has already accepted. No third audio, VLM or motor owner.
"""
from __future__ import annotations

import math
from typing import TypeGuard

PHYSICAL_INITIATIVE_KINDS = frozenset({
    "touch", "touch_tap", "touch_double", "touch_hold", "petting_zone",
    "squeeze", "hand_wave", "nose_twist", "nearby_object", "battery_low",
    "magnet", "pir", "bumper", "handling_tilt", "handling_shake",
    "side_object", "paw_contact", "ambient_shift", "nfc_tag",
})

DIRECT_INTERACTION_KINDS = frozenset({
    "touch", "touch_tap", "touch_double", "petting_zone", "squeeze",
    "hand_wave", "nose_twist", "paw_contact", "nfc_tag", "magnet",
})

# Human VAD and a safety fault can schedule a corroborating camera look,
# but neither is a candidate for an unsolicited physical-sensor story.
TRIGGERS = PHYSICAL_INITIATIVE_KINDS | {"human_voice", "safety_fault", "stable_putdown"}

assert DIRECT_INTERACTION_KINDS <= PHYSICAL_INITIATIVE_KINDS
assert PHYSICAL_INITIATIVE_KINDS <= TRIGGERS


def is_finite_number(value: object) -> bool:
    """Accept only native int/float values representable as finite floats."""
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def is_int_in_range(value: object, low: int, high: int) -> TypeGuard[int]:
    """Accept an exact wire integer, excluding booleans and numeric coercion."""
    return type(value) is int and low <= value <= high


def is_uint(value: object, upper: int) -> TypeGuard[int]:
    """Accept a nonnegative wire integer with an inclusive upper bound."""
    return is_int_in_range(value, 0, upper)
