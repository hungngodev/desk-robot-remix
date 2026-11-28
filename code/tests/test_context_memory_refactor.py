"""Regression coverage for bounded prompt selection and FTS ranking."""

from desk_robot.brain_context import _budget_interaction
from desk_robot.memory import _rank_search_rows


def test_budget_preserves_safety_and_current_receipt_before_prior_turn():
    safety = "fault " + "s" * 100
    current = "current " + "c" * 140
    prior = "prior " + "p" * 180
    cues = [(1, prior, "visual_look", False), (-1, safety, None, False),
            (1, current, "robot_status", True)]
    result = _budget_interaction(cues, {"visual_look", "robot_status"}, set())
    assert result == f"{safety}; {current}"
    assert len(result) <= 400


def test_budget_discloses_current_requested_omission():
    safety = "fault " + "s" * 100
    current = "current " + "c" * 140
    omitted = "omitted " + "o" * 180
    cues = [(-1, safety, None, False), (1, current, "robot_status", True),
            (1, omitted, "visual_look", True)]
    result = _budget_interaction(cues, {"visual_look", "robot_status"}, set())
    assert result.startswith(f"{safety}; {current}; ")
    assert "Some requested tool results did not fit" in result
    assert len(result) <= 400


def test_rank_keeps_topical_relevance_and_peer_provenance():
    rows = [
        ("peer", "robot-02", 0, "peer_report", "peer", 100, 0.8, -1.0),
        ("own", "robot-01", 1, "object", "own", 100, 0.8, -1.0),
        ("topical", "robot-02", 0, "peer_report", "topical", 100, 0.1, -2.0),
    ]
    result = _rank_search_rows("robot-01", rows, now=100, limit=3)
    assert [m.event_id for m in result] == ["topical", "own", "peer"]
    assert [m.witnessed for m in result] == [False, True, False]
    assert all(m.robot_id == "robot-01" for m in result)
