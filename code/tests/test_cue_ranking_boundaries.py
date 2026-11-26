"""Boundary and ownership regressions for the pure cue selector."""
from copy import deepcopy

import pytest
from desk_robot.cue_ranking import rank_cues

DIRECT = frozenset({"touch_tap"})


def cue(stamp, channel, kind):
    return stamp, {"channel": channel, "kind": kind, "content": {"values": [1]}}


@pytest.mark.parametrize("limit", [False, True, 0, -1, 1.0, float("nan"), float("inf")])
def test_rank_rejects_invalid_limit_even_when_empty(limit):
    with pytest.raises(ValueError, match="limit"):
        rank_cues([], limit=limit, current_voice_at=0, direct_kinds=DIRECT)


@pytest.mark.parametrize("voice_at", [True, None, "1", float("nan"), float("inf"), 10**400])
def test_rank_rejects_invalid_voice_boundary(voice_at):
    with pytest.raises(ValueError, match="voice"):
        rank_cues([], limit=1, current_voice_at=voice_at, direct_kinds=DIRECT)


@pytest.mark.parametrize("limit", [2, 20])
@pytest.mark.parametrize("stamp", [True, None, "1", float("nan"), float("inf"), -float("inf"), 10**400])
def test_malformed_timestamp_cannot_consume_cue_budget(limit, stamp):
    items = [cue(1, "sensor", "safety_fault"), cue(2, "human_voice", "vad"),
             cue(stamp, "tool", "malformed")]
    result = rank_cues(items, limit=limit, current_voice_at=0, direct_kinds=DIRECT)
    assert [entry["kind"] for entry in result] == ["safety_fault", "vad"]


@pytest.mark.parametrize("limit", [1, 20])
def test_rank_result_owns_nested_payload_on_both_paths(limit):
    items = [cue(1, "sensor", "safety_fault"), cue(2, "camera", "frame")]
    before = deepcopy(items)
    result = rank_cues(items, limit=limit, current_voice_at=-float("inf"), direct_kinds=DIRECT)
    assert result[0]["kind"] == "safety_fault"
    result[0]["kind"] = "edited"
    result[0]["content"]["values"].append(2)
    assert items == before


def test_no_voice_sentinel_preserves_tool_priority():
    items = [cue(1, "tool", "status"), cue(2, "sensor", "touch_tap")]
    result = rank_cues(items, limit=1, current_voice_at=-float("inf"), direct_kinds=DIRECT)
    assert [entry["kind"] for entry in result] == ["status"]
