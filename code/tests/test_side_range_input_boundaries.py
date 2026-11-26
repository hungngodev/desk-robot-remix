"""Malformed calibration evidence cannot produce a threshold candidate."""
import json
import runpy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/calibrate_side_ranges.py"
CAL = runpy.run_path(str(SCRIPT))


def row(direction="left", label="near", stamp=100, sample_id=1):
    return {
        "robot_id": "robot-01", "direction": direction, "label": label,
        "sample_id": sample_id,
        "side_ranges": {
            "mm": [80, 80, 80], "age_ms": [10, 10, 10],
            "sample_ms": [stamp, stamp, stamp], "boot_id": 73,
            "valid_mask": 7, "present_mask": 7, "motion_certified": False,
        },
    }


@pytest.mark.parametrize("field", ["direction", "label"])
@pytest.mark.parametrize("value", [[], {}, 5, None])
def test_corrupt_labels_fail_with_validation_error(field, value):
    record = row()
    record[field] = value
    with pytest.raises(ValueError, match="Labeled robot identity"):
        CAL["analyze"]([record], "robot-01")


@pytest.mark.parametrize("token", ["1e999", "-1e999"])
def test_overflowing_json_number_rejected_even_in_unselected_channel(tmp_path, token):
    path = tmp_path / "ranges.jsonl"
    payload = json.dumps(row()).replace('"mm": [80, 80, 80]', f'"mm": [80, 80, {token}]')
    path.write_text(payload + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Nonfinite side-range trial JSON"):
        CAL["load_trial_rows"](path)


def test_empty_capture_has_no_candidate():
    with pytest.raises(ValueError, match="independent near and far"):
        CAL["analyze"]([], "robot-01")


@pytest.mark.parametrize("stamp", [99, 100])
def test_reordered_or_duplicate_channel_conversion_fails(stamp):
    rows = [row(), row("right", stamp=200), row(stamp=stamp, sample_id=2)]
    with pytest.raises(ValueError, match="Repeated or reversed"):
        CAL["analyze"](rows, "robot-01")


def test_channel_positions_follow_fixed_side_mapping():
    rows = []
    for i in range(40):
        for channel, side in enumerate(("rear", "left", "right")):
            record = row(side, "near" if i < 20 else "far", i + 1, i + 1)
            index = (channel + 2) % 3
            record["side_ranges"]["mm"] = [1300] * 3
            record["side_ranges"]["mm"][index] = 80 if i < 20 else 500
            rows.append(record)
    result = CAL["analyze"](rows, "robot-01")
    assert result["samples_total"] == 120
    assert all(item["near_p95_mm"] == 80 for item in result["directions"].values())
    assert result["no_motion_authority"] is True
    assert result["physical_acceptance_pass"] is False
