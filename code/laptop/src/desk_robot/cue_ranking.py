"""Pure selection policy for already admitted multimodal timeline evidence."""
from __future__ import annotations

import math
from collections.abc import Callable
from copy import deepcopy
from typing import Any

Cue = tuple[float, dict[str, Any]]


def _finite_stamp(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def rank_cues(
    items: list[Cue], *, limit: int, current_voice_at: float,
    direct_kinds: frozenset[str],
) -> list[dict[str, Any]]:
    """Preserve priority within a bounded timeline, returning chronological cues.

    The caller owns admission, freshness, consent and robot identity. This
    function has no clock or I/O and cannot grant physical or speech authority.
    """
    if type(limit) is not int or limit < 1:
        raise ValueError("Invalid cue ranking limit")
    # The hub uses negative infinity before any human voice event.
    if not _finite_stamp(current_voice_at) and not (
        type(current_voice_at) is float and current_voice_at == -math.inf
    ):
        raise ValueError("Invalid cue ranking voice timestamp")
    # Only routing labels participate in ranking. Never hash payload metadata
    # or let malformed labels consume the budget, even on the fast path.
    ordered = sorted(
        (item for item in items
         if type(item) is tuple and len(item) == 2
         and _finite_stamp(item[0])
         and type(item[1]) is dict
         and type(item[1].get("channel")) is str
         and type(item[1].get("kind")) is str),
        key=lambda item: item[0],
    )
    if len(ordered) <= limit:
        return [deepcopy(entry) for _, entry in ordered]
    selected = _select_indices(ordered, limit, current_voice_at, direct_kinds)
    entries = [deepcopy(ordered[index][1]) for index in sorted(selected)]
    current_tools = {
        entry["kind"] for stamp, entry in ordered
        if entry["channel"] == "tool" and stamp >= current_voice_at
    }
    included_tools = {entry["kind"] for entry in entries if entry["channel"] == "tool"}
    omitted_tools = sorted(current_tools - included_tools)
    if omitted_tools:
        for entry in reversed(entries):
            if entry["channel"] == "human_transcript":
                entry["omitted_current_tool_kinds"] = omitted_tools
                break
    return entries


def _select_indices(
    items: list[Cue], limit: int, voice_at: float, direct_kinds: frozenset[str],
) -> set[int]:
    selected: set[int] = set()
    newest = range(len(items) - 1, -1, -1)

    def reserve(match: Callable[[Cue], bool], *, distinct: bool = False) -> None:
        if len(selected) >= limit:
            return
        for index in newest:
            if (not distinct or index not in selected) and match(items[index]):
                selected.add(index)
                return

    # P0 local fault, P1 human evidence, P2 current tool receipts.
    reserve(lambda cue: cue[1]["channel"] == "sensor" and cue[1]["kind"] == "safety_fault")
    for channel in ("human_voice", "human_transcript"):
        reserve(lambda cue, channel=channel: cue[1]["channel"] == channel)
    seen_tools: set[str] = set()
    for index in newest:
        if len(selected) >= limit:
            break
        stamp, entry = items[index]
        if entry["channel"] == "tool" and stamp >= voice_at and entry["kind"] not in seen_tools:
            selected.add(index)
            seen_tools.add(entry["kind"])
    if any(items[index][1]["channel"] == "human_transcript" for index in selected):
        reserve(lambda cue: cue[1]["channel"] == "human_transcript" and cue[0] >= voice_at,
                distinct=True)
    # P3 deliberate interaction, modality coverage, then latest detail.
    reserve(lambda cue: cue[1]["channel"] == "sensor" and cue[1]["kind"] in direct_kinds)
    for channel in ("tool", "sensor", "room_station", "robot_speech", "sensor_history", "camera"):
        reserve(lambda cue, channel=channel: cue[1]["channel"] == channel)
    for index in newest:
        if len(selected) >= limit:
            break
        selected.add(index)
    return selected
