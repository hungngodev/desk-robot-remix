"""Read-only three-direction range calibration refuses fabricated acceptance."""
import importlib.util
from pathlib import Path

import pytest


def module():
    path = Path(__file__).resolve().parents[1] / "scripts/calibrate_side_ranges.py"
    spec = importlib.util.spec_from_file_location("calibrate_side_ranges", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def record(side, label, index, distance):
    channel = {"left": 0, "right": 1, "rear": 2}[side]
    mm = [800, 800, 800]
    mm[channel] = distance
    return {
        "robot_id": "robot-01",
        "direction": side, "label": label, "sample_id": index,
        "side_ranges": {
            "mm": mm, "age_ms": [35, 35, 35],
            "present_mask": 7, "valid_mask": 7,
            "motion_certified": False,
        },
    }


def samples(near_base=80, far_base=500):
    rows = []
    for side in ("left", "right", "rear"):
        rows += [record(side, "near", i + 1, near_base + i)
                 for i in range(20)]
        rows += [record(side, "far", i + 21, far_base + i)
                 for i in range(20)]
    return rows


def test_candidate_is_bounded_and_not_fake_physical_acceptance():
    result = module().analyze(samples(), "robot-01")
    assert 120 <= result["suggested_side_near_threshold_mm"] <= 500
    assert result["samples_total"] == 120
    assert set(result["directions"]) == {"left", "right", "rear"}
    assert result["physical_acceptance_pass"] is False
    assert result["human_review_required"] is True
    assert result["independent_sample_provenance_verified"] is False
    assert result["no_motion_authority"] is True


def test_refuses_ambiguous_near_far_and_incomplete_real_trials():
    with pytest.raises(ValueError, match="overlap|separation"):
        module().analyze(samples(near_base=200, far_base=230), "robot-01")
    with pytest.raises(ValueError, match="20"):
        module().analyze(samples()[:-1], "robot-01")


def test_rejects_stale_duplicate_forged_source_and_bad_direction():
    input_rows = samples()
    input_rows[0]["side_ranges"]["age_ms"][0] = 600
    with pytest.raises(ValueError, match="Invalid"):
        module().analyze(input_rows, "robot-01")
    input_rows = samples()
    input_rows[0]["robot_id"] = "robot-02"
    with pytest.raises(ValueError, match="identity"):
        module().analyze(input_rows, "robot-01")
    input_rows = samples()
    input_rows[1]["sample_id"] = input_rows[0]["sample_id"]
    with pytest.raises(ValueError, match="sample_id"):
        module().analyze(input_rows, "robot-01")
    input_rows = samples()
    input_rows[0]["direction"] = "front"
    with pytest.raises(ValueError, match="direction|side|identity"):
        module().analyze(input_rows, "robot-01")


def test_rejects_same_physical_side_sample_counted_as_both_near_and_far():
    rows = samples()
    # Each side's far class attempts to reuse its twenty near acquisition IDs.
    # Different physical lenses sharing an ID across the same sweep remain OK.
    for row in rows:
        if row["label"] == "far":
            row["sample_id"] -= 20
    with pytest.raises(ValueError, match="sample_id.*side direction"):
        module().analyze(rows, "robot-01")


def test_separate_lenses_may_share_a_synchronized_capture_id():
    rows = samples()
    result = module().analyze(rows, "robot-01")
    assert result["samples_total"] == 120
    assert result["independent_sample_provenance_verified"] is False
    assert result["physical_acceptance_pass"] is False
