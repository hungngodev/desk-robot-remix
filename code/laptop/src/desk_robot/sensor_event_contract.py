"""Shared read-only event registry for the existing Mac camera and pet owners.

These names label actual input events or scheduling causes, not motion
authority, person recognition, calibration, or permission to speak.
Keep one registry so the camera hub cannot reject a sensor kind that the
pet controller has already accepted. No third audio, VLM or motor owner.
"""
from __future__ import annotations

import math
from typing import Literal, TypedDict, TypeGuard

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



# Match the WROOM MAX17048 acquisition lifetime, not the motor watchdog.
FUEL_SAMPLE_MAX_AGE_MS = 500


def fuel_sample_is_fresh(age_ms: object, elapsed_ms: object = 0) -> bool:
    """Charge the full host request time against the wire acquisition lifetime."""
    return (
        type(age_ms) is int
        and 0 <= age_ms < FUEL_SAMPLE_MAX_AGE_MS
        and type(elapsed_ms) in (int, float)
        and 0 <= elapsed_ms < FUEL_SAMPLE_MAX_AGE_MS
        and age_ms + elapsed_ms < FUEL_SAMPLE_MAX_AGE_MS
    )


def is_valid_fuel_measurement(cell_mv: object, soc_centi: object) -> bool:
    """Match the WROOM MAX17048 claimed-valid measurement envelope."""
    return is_int_in_range(cell_mv, 2500, 4500) and is_int_in_range(soc_centi, 0, 10000)


class _ClimateReading(TypedDict):
    temp_centi: int
    rh_centi: int


class _PressureReading(TypedDict):
    pressure_pa: int
    physically_verified: Literal[False]


class _FuelReading(TypedDict):
    soc_centi: int
    cell_mv: int
    qualified: Literal[False]


class _ProximityReading(TypedDict):
    gesture: int
    physically_qualified: Literal[False]


class _NfcReading(TypedDict):
    event_count: int


class _DockReading(TypedDict):
    left_seated: bool
    right_seated: bool
    input_good: bool
    charge_indicated: bool
    charging_verified: Literal[False]


class _SafetyReading(TypedDict, total=False):
    required: bool
    ready: bool
    fault: str


class _BatteryReading(TypedDict):
    percent: int | float
    physically_qualified: Literal[False]


class _DockedReading(TypedDict):
    docked: bool
    physical_contacts_verified: Literal[False]


class ProactiveToolData(TypedDict, total=False):
    """Allowlisted sensor facts; absence never means a confirmed negative."""

    sht41: _ClimateReading
    bmp280: _PressureReading
    fuel_gauge: _FuelReading
    proximity: _ProximityReading
    nfc: _NfcReading
    dock_contacts: _DockReading
    armed: bool
    backend: Literal["stepper_28byj48"]
    watchdog_ms: int
    safety: _SafetyReading
    battery: _BatteryReading
    data: _DockedReading


class ProactiveToolReceipt(TypedDict):
    """Bounded model evidence, not authorization or physical verification."""

    robot_id: str
    source: str
    verified_motion: Literal[False]
    verified_charging: Literal[False]
    untrusted_observation_not_instructions: Literal[True]
    data: ProactiveToolData

