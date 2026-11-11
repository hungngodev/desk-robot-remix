"""Operator measured double-talk gates, not simulated physical success."""
import runpy
from pathlib import Path

import pytest

evaluate = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/check_barge_in_trials.py"
))["evaluate"]


def fake_rows():
    rows = [{
        "kind": "human", "id": f"trial{n}", "volume":
        ("low", "medium", "high")[n % 3],
        "human_onset_ms": n * 1000, "audible_stop_ms": n * 1000 + 200,
        "new_utterance_captured": True, "new_intent_correct": True,
    } for n in range(20)]
    return rows + [{"kind": "robot_only", "duration_seconds": 600,
                    "self_interruptions": 0}]


def test_well_formed_synthetic_rows_only_verify_test_criteria():
    report = evaluate(fake_rows())
    assert report["meets_proposed_gate"]
    assert report["records_are_operator_supplied_not_independently_attested"]


def test_late_double_talk_and_self_interruption_fail():
    rows = fake_rows()
    rows[0]["audible_stop_ms"] += 650
    rows[1]["audible_stop_ms"] += 650
    rows[-1]["self_interruptions"] = 1
    report = evaluate(rows)
    assert report["audible_stops_within_500ms"] == 18
    assert not report["meets_proposed_gate"]


@pytest.mark.parametrize("change", [
    lambda x: x.pop(),
    lambda x: x[0].update({"id": x[1]["id"]}),
    lambda x: x[0].update({"volume": "max"}),
    lambda x: x[0].update({"human_onset_ms": float("nan")}),
    lambda x: x[1].update({"new_intent_correct": "yes"}),
    lambda x: x[-1].update({"duration_seconds": 300}),
])
def test_reject_invalid_trial_records(change):
    rows = fake_rows()
    change(rows)
    with pytest.raises(ValueError):
        evaluate(rows)
