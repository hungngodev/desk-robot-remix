"""Qualify visual guesses with nearby physical range event receipts."""
from __future__ import annotations

from collections.abc import Sequence

_MAX_RECEIPT_AGE_MS = 8000
_MAX_RECEIPT_GAP_MS = 1000


def _fresh_age(item: dict) -> int | None:
    age = item.get("age_ms")
    if type(age) is int and 0 <= age <= _MAX_RECEIPT_AGE_MS:
        return age
    return None


def visual_range_caveat(visual: dict, timeline: Sequence[dict]) -> str:
    """Compare Mac receipt ages, not exposure times or sensor sample clocks.

    A range edge does not identify a visual object, and a camera guess cannot
    establish physical clearance. Preserve the WROOM fault independently.
    """
    if (visual.get("channel") != "tool" or visual.get("kind") != "visual_look"
            or visual.get("source") != "local_vlm_interpretation"):
        return ""
    visual_age = _fresh_age(visual)
    if visual_age is None:
        return ""
    side_near = False
    for item in timeline:
        if (not isinstance(item, dict) or item.get("channel") != "sensor"
                or item.get("source") != "wroom_event"):
            continue
        age = _fresh_age(item)
        if age is None or abs(age - visual_age) > _MAX_RECEIPT_GAP_MS:
            continue
        kind = item.get("kind")
        if (kind == "safety_fault"
                and item.get("fault_detail") in ("front_obstacle", "front_obstacle_ch4")):
            return "WROOM front obstacle edge near VLM receipt; no clearance inference. "
        if kind == "side_object":
            side_near = True
    if side_near:
        return "WROOM side range edge near VLM receipt; camera coverage uncertain. "
    return ""
