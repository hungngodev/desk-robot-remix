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


@pytest.mark.parametrize("limit", [3, 20])
@pytest.mark.parametrize("bad_kind", [[], {"nested": []}, None, 42])
@pytest.mark.parametrize("channel", ["tool", "sensor"])
def test_malformed_kind_cannot_displace_admitted_evidence(limit, bad_kind, channel):
    items = [
        cue(1, "sensor", "safety_fault"),
        cue(2, "human_transcript", "asr"),
        cue(3, "tool", "status"),
        cue(4, channel, bad_kind),
    ]
    original = deepcopy(items)
    assert kinds(rank_cues(items, limit=limit, current_voice_at=2, direct_kinds=DIRECT)) == [
        "safety_fault", "asr", "status",
    ]
    assert items == original


@pytest.mark.parametrize("limit", [2, 10])
def test_missing_or_malformed_routing_labels_are_not_ranked(limit):
    items = [
        cue(1, "sensor", "safety_fault"),
        cue(2, "human_voice", "vad"),
        (3, {"channel": "tool"}),
        (4, {"kind": "status"}),
        cue(5, ["sensor"], "safety_fault"),
    ]
    assert kinds(rank_cues(items, limit=limit, current_voice_at=0, direct_kinds=DIRECT)) == [
        "safety_fault", "vad",
    ]


def test_equal_timestamp_priority_and_nested_metadata_keep_input_order():
    items = [
        cue(1, "camera", "frame"),
        cue(1, "tool", "status"),
        cue(1, "sensor", "touch_tap"),
        cue(1, "human_transcript", "asr"),
        cue(1, "sensor", "safety_fault"),
        cue(1, "tool", "status"),
        cue(1, "human_voice", "vad"),
    ]
    items[1][1]["content"] = {"values": [1, {"nested": []}]}
    items[5][1]["content"] = {"values": [2, {"nested": []}]}
    original = deepcopy(items)
    result = rank_cues(items, limit=4, current_voice_at=1, direct_kinds=DIRECT)
    assert result == [items[i][1] for i in (3, 4, 5, 6)]
    result = rank_cues(items[::-1], limit=4, current_voice_at=1, direct_kinds=DIRECT)
    assert result == [items[i][1] for i in (6, 4, 3, 1)]
    assert items == original
    assert rank_cues(items, limit=7, current_voice_at=1, direct_kinds=DIRECT) == [
        entry for _, entry in items
    ]


def test_malformed_kind_does_not_crash_direct_sensor_membership():
    items = [cue(1, "sensor", "touch_tap"), cue(2, "sensor", []), cue(3, "camera", "frame")]
    assert kinds(rank_cues(items, limit=1, current_voice_at=0, direct_kinds=DIRECT)) == [
        "touch_tap",
    ]
