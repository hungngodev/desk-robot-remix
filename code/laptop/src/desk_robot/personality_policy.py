"""Cosmetic and optional initiative policy; never physical evidence or authority."""
from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Literal, get_args

from .sensor_event_contract import is_finite_number

PersonalityProfile = Literal["balanced", "calm", "curious", "dramatic"]

_POWER_TERM_RE = re.compile(
    r"\b(?:battery|batteries|charge|charged|charging|soc|cell|cells"
    r"|fuel|voltage|voltages|power|gauge)\b",
    re.IGNORECASE,
)
_QUALIFIED_BATTERY_CLAIM_RE = re.compile(
    r"\b(?:calibrated|qualified|verified)\b",
    re.IGNORECASE,
)
_QUALIFICATION_NEGATION_RE = re.compile(
    r"\b(?:not|never|uncalibrated|unqualified|unverified|unconfirmed"
    r"|estimate|estimated|raw|approx|approximately)\b",
    re.IGNORECASE,
)
_DIGIT_VOLTAGE_RE = re.compile(
    r"(?<![A-Za-z0-9_])(\d+(?:\.\d+)?)\s*(mv|millivolts?|v|volts?)\b",
    re.IGNORECASE,
)
_DIGIT_PERCENT_RE = re.compile(
    r"(?<![A-Za-z0-9_])(\d+(?:\.\d+)?)\s*(?:%|(?:percent|per\s+cent)\b)"
    r"(\s*(?:rh|relative\s+humidity|humidity)\b)?",
    re.IGNORECASE,
)
_WORD_ONES: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_WORD_TENS: dict[str, int] = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_WORD_NUM_PATTERN = (
    r"(?:one\s+hundred|hundred"
    r"|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
    r"(?:[-\s]+(?:one|two|three|four|five|six|seven|eight|nine))?"
    r"|zero|one|two|three|four|five|six|seven|eight|nine|ten"
    r"|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)"
)
_WORD_PERCENT_RE = re.compile(
    rf"\b({_WORD_NUM_PATTERN})\s*(?:percent|per\s+cent)\b"
    r"(\s*(?:rh|relative\s+humidity|humidity)\b)?",
    re.IGNORECASE,
)
_WORD_VOLTAGE_RE = re.compile(
    rf"\b({_WORD_NUM_PATTERN})\s+(mv|millivolts?|volts?)\b",
    re.IGNORECASE,
)


def _parse_word_number(phrase: str) -> float | None:
    tokens = [part for part in re.split(r"[-\s]+", phrase.strip().lower()) if part]
    if tokens in (["hundred"], ["one", "hundred"]):
        return 100.0
    if len(tokens) == 1:
        if tokens[0] in _WORD_ONES:
            return float(_WORD_ONES[tokens[0]])
        if tokens[0] in _WORD_TENS:
            return float(_WORD_TENS[tokens[0]])
        return None
    if len(tokens) == 2 and tokens[0] in _WORD_TENS and tokens[1] in _WORD_ONES:
        ones = _WORD_ONES[tokens[1]]
        if 1 <= ones <= 9:
            return float(_WORD_TENS[tokens[0]] + ones)
    return None


def _validate_profile(profile: object) -> None:
    if type(profile) is not str or profile not in get_args(PersonalityProfile):
        raise ValueError("Invalid personality profile")


def passive_interval(profile: PersonalityProfile, base: float) -> float:
    """Profiles may extend, but never shorten, the fleet speech floor."""
    _validate_profile(profile)
    if not is_finite_number(base) or not 0 <= base <= 3600:
        raise ValueError("Invalid personality base cooldown")
    return base * {"balanced": 1.0, "calm": 1.5, "curious": 1.0, "dramatic": 1.25}[profile]


def fleet_speech_elapsed(now: float, last: float) -> float | None:
    """Return elapsed seconds, +inf for no prior speech, or None for invalid time."""
    if not is_finite_number(now):
        return None
    if type(last) is float and last == -math.inf:
        return math.inf
    if not is_finite_number(last):
        return None
    elapsed = now - last
    if not is_finite_number(elapsed) or elapsed < 0:
        return None
    return elapsed


def profile_waits_beyond_fleet_floor(
    profile: PersonalityProfile,
    *,
    elapsed: float | None,
    base: float,
    wait_elapsed: float | None = None,
) -> bool:
    """Defer invalid clocks; bound extra profile wait across peer speech resets."""
    interval = passive_interval(profile, base)
    if type(elapsed) is float and elapsed == math.inf:  # No-prior-speech sentinel.
        return False
    if not is_finite_number(elapsed) or elapsed < 0:
        return True
    if not (base <= elapsed < interval):
        return False
    if wait_elapsed is None:
        return True
    if not is_finite_number(wait_elapsed) or wait_elapsed < 0:
        return True
    return wait_elapsed < interval


def _validated_receipt_power_bounds(
    receipt: Mapping[str, object] | None,
) -> tuple[float | None, int | None, float | None]:
    if not isinstance(receipt, Mapping):
        return None, None, None
    if receipt.get("source") not in (
        "authenticated_wroom_read_only_status",
        "authenticated_wroom_read_only_aux_status",
    ):
        return None, None, None
    data = receipt.get("data")
    if not isinstance(data, Mapping):
        return None, None, None
    expected_pct: float | None = None
    expected_mv: int | None = None
    expected_rh: float | None = None
    battery = data.get("battery")
    if isinstance(battery, Mapping):
        pct = battery.get("percent")
        if is_finite_number(pct) and 0 <= float(pct) <= 100:
            expected_pct = float(pct)
    fuel = data.get("fuel_gauge")
    if isinstance(fuel, Mapping):
        soc = fuel.get("soc_centi")
        cell_mv = fuel.get("cell_mv")
        if type(soc) is int and 0 <= soc <= 10000:
            expected_pct = soc / 100.0
        if type(cell_mv) is int and 2500 <= cell_mv <= 4500:
            expected_mv = cell_mv
    sht41 = data.get("sht41")
    if isinstance(sht41, Mapping):
        rh = sht41.get("rh_centi")
        if type(rh) is int and 0 <= rh <= 10000:
            expected_rh = rh / 100.0
    return expected_pct, expected_mv, expected_rh


def proactive_battery_claim_violates_receipt(
    text: str, receipt: Mapping[str, object] | None,
) -> bool:
    """Reject spoken battery/voltage numbers that lack or contradict a fresh receipt."""
    if not isinstance(text, str):
        return True
    normalized = " ".join(text.split())
    if not normalized:
        return False
    expected_pct, expected_mv, expected_rh = _validated_receipt_power_bounds(receipt)
    has_power_term = bool(_POWER_TERM_RE.search(normalized))
    if (
        has_power_term
        and _QUALIFIED_BATTERY_CLAIM_RE.search(normalized)
        and not _QUALIFICATION_NEGATION_RE.search(normalized)
    ):
        return True

    voltage_claims: list[tuple[float, str]] = []
    for match in _DIGIT_VOLTAGE_RE.finditer(normalized):
        val = float(match.group(1))
        if not math.isfinite(val):
            return True
        voltage_claims.append((val, match.group(2).lower()))
    for match in _WORD_VOLTAGE_RE.finditer(normalized):
        parsed = _parse_word_number(match.group(1))
        if parsed is None:
            return True
        voltage_claims.append((parsed, match.group(2).lower()))
    for val, unit in voltage_claims:
        if expected_mv is None:
            return True
        if unit.startswith("m"):
            if abs(val - expected_mv) > 0.5:
                return True
        elif abs(val * 1000.0 - expected_mv) > 10.0:
            return True

    percent_claims: list[tuple[float, bool]] = []
    for match in _DIGIT_PERCENT_RE.finditer(normalized):
        val = float(match.group(1))
        if not math.isfinite(val):
            return True
        percent_claims.append((val, bool(match.group(2))))
    for match in _WORD_PERCENT_RE.finditer(normalized):
        parsed = _parse_word_number(match.group(1))
        if parsed is None:
            return True
        percent_claims.append((parsed, bool(match.group(2))))
    for val, explicit_humidity in percent_claims:
        if explicit_humidity and expected_rh is not None and abs(val - expected_rh) <= 0.55:
            continue
        if (
            not has_power_term
            and expected_rh is not None
            and abs(val - expected_rh) <= 0.55
        ):
            continue
        if expected_pct is None or abs(val - expected_pct) > 0.55:
            return True
    return False


def expression_guidance(profile: PersonalityProfile) -> str:
    _validate_profile(profile)
    style = {
        "balanced": "Follow your configured persona naturally.",
        "calm": "Prefer measured, understated expression and patient silence.",
        "curious": "Prefer gentle curiosity and relevant questions when useful.",
        "dramatic": "Use playful theatrical expression without exaggerating facts.",
    }[profile]
    return (
        f"{style} Personality and OLED mood are expressive only. "
        "Never alter reported battery percentages or cell voltage (millivolts), "
        "ToF ranges, safety faults, stop acknowledgments, or tool results "
        "to match a mood. Never infer battery state from tiredness, energy "
        "or personality; preserve the gauge estimate and qualification. "
        "Missing or uncertain evidence stays unknown; safety always takes priority."
    )
