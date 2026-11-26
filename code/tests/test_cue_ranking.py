"""Deterministic ranking properties without camera, clocks or mock workers."""
from copy import deepcopy
from itertools import permutations

import pytest
from desk_robot.cue_ranking import rank_cues

DIRECT = frozenset({"touch_tap"})


def cue(stamp, channel, kind):
    return stamp, {"channel": channel, "kind": kind, "source_at": stamp}


def kinds(entries):
    return [entry["kind"] for entry in entries]


@pytest.mark.parametrize("limit", range(1, 9))
def test_priority_is_bounded_chronological_and_independent_of_arrival_order(limit):
    items = [
        cue(1, "sensor", "safety_fault"),
        cue(2, "human_voice", "vad"),
        cue(3, "human_transcript", "asr"),
        cue(4, "tool", "status"),
        cue(5, "sensor", "touch_tap"),
        cue(6, "camera", "frame"),
        cue(7, "camera", "frame2"),
        cue(8, "sensor", "ambient_shift"),
    ]
    original = deepcopy(items)
    expected = rank_cues(items, limit=limit, current_voice_at=2, direct_kinds=DIRECT)
    for order in (items[::-1], items[3:] + items[:3]):
        assert rank_cues(order, limit=limit, current_voice_at=2, direct_kinds=DIRECT) == expected
    assert len(expected) == limit
    assert kinds(expected)[0] == "safety_fault"
    assert [entry["source_at"] for entry in expected] == sorted(
        entry["source_at"] for entry in expected
    )
    assert items == original
    assert set(kinds(expected)) == set([
        "safety_fault", "vad", "asr", "status", "touch_tap", "ambient_shift", "frame2", "frame",
    ][:limit])


def test_distinct_current_receipts_outrank_newer_repeated_and_old_receipts():
    items = [
        cue(1, "tool", "old"), cue(2, "human_voice", "vad"),
        cue(3, "human_transcript", "first_clause"),
        cue(4, "tool", "status"), cue(5, "tool", "visual_look"),
        cue(6, "tool", "visual_look"), cue(7, "human_transcript", "last_clause"),
    ]
    original = deepcopy(items)
    for order in permutations(items):
        result = rank_cues(list(order), limit=4, current_voice_at=2, direct_kinds=DIRECT)
        assert [entry["source_at"] for entry in result] == [2, 4, 6, 7]
    result = rank_cues(items, limit=3, current_voice_at=2, direct_kinds=DIRECT)
    assert result[-1]["omitted_current_tool_kinds"] == ["status"]
    assert items == original


def test_old_receipt_cannot_displace_direct_contact():
    items = [
        cue(1, "tool", "old"), cue(2, "sensor", "touch_tap"),
        cue(3, "human_voice", "vad"), cue(4, "camera", "frame"),
    ]
    assert kinds(rank_cues(items, limit=2, current_voice_at=3, direct_kinds=DIRECT)) == [
        "touch_tap", "vad",
    ]


def test_equal_timestamp_keeps_original_tie_order():
    items = [cue(1, "camera", "first"), cue(1, "camera", "second")]
    assert kinds(rank_cues(items, limit=1, current_voice_at=0, direct_kinds=DIRECT)) == ["second"]
