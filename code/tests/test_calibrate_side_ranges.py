"""Read-only three-direction range calibration refuses fabricated acceptance."""
import importlib.util
import json
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
    acquisition_ms = [0, 0, 0]
    acquisition_ms[channel] = index * 20
    return {
        "robot_id": "robot-01",
        "direction": side, "label": label, "sample_id": index,
        "side_ranges": {
            "mm": mm, "age_ms": [35, 35, 35],
            "sample_ms": acquisition_ms, "boot_id": 73,
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


def test_new_operator_id_cannot_relabel_cached_side_conversion_as_new():
    rows = samples()
    # The capture IDs and range readings are distinct, but the hardware
    # reports exactly the same left-lens acquisition for two HTTP reads.
    rows[1]["side_ranges"]["sample_ms"][0] = rows[0]["side_ranges"]["sample_ms"][0]
    with pytest.raises(ValueError, match="Repeated or reversed"):
        module().analyze(rows, "robot-01")


def test_reversed_sensor_acquisition_and_mixed_boot_are_rejected():
    rows = samples()
    rows[1]["side_ranges"]["sample_ms"][0] = 1
    with pytest.raises(ValueError, match="Repeated or reversed"):
        module().analyze(rows, "robot-01")
    rows = samples()
    rows[-1]["side_ranges"]["boot_id"] = 74
    with pytest.raises(ValueError, match="boot identities"):
        module().analyze(rows, "robot-01")


def test_real_uint32_side_conversion_rollover_is_not_a_replay():
    rows = samples()
    for item in rows:
        channel = {"left": 0, "right": 1, "rear": 2}[item["direction"]]
        # Each lens crosses millis wrap mid-run without a WROOM reboot.
        item["side_ranges"]["sample_ms"][channel] = (
            0xfffffff0 + item["sample_id"]
        ) & 0xffffffff
    assert module().analyze(rows, "robot-01")["samples_total"] == 120
    rows[18]["side_ranges"]["sample_ms"][0] = 0xfffffff0
    with pytest.raises(ValueError, match="Repeated or reversed"):
        module().analyze(rows, "robot-01")


@pytest.mark.parametrize("invalid", [None, True, -1, 0x100000000])
def test_missing_forged_or_unrepresentable_sensor_conversion_is_rejected(invalid):
    rows = samples()
    rows[0]["side_ranges"]["sample_ms"][0] = invalid
    with pytest.raises(ValueError, match="Invalid"):
        module().analyze(rows, "robot-01")


@pytest.mark.parametrize("boot", [None, True, 0, 0x100000000])
def test_missing_or_uninitialized_wroom_boot_identity_is_rejected(boot):
    rows = samples()
    rows[0]["side_ranges"]["boot_id"] = boot
    with pytest.raises(ValueError, match="Invalid"):
        module().analyze(rows, "robot-01")


def test_separate_lenses_may_share_a_synchronized_capture_id():
    rows = samples()
    result = module().analyze(rows, "robot-01")
    assert result["samples_total"] == 120
    assert result["independent_sample_provenance_verified"] is False
    assert result["physical_acceptance_pass"] is False

def test_real_side_range_jsonl_preserves_current_candidate_result(tmp_path):
    rows = samples()
    path = tmp_path / "three_direction_near_far.jsonl"
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    actual = module().load_trial_rows(path)
    assert actual == rows
    result = module().analyze(actual, "robot-01")
    assert result["samples_total"] == 120
    assert result["physical_acceptance_pass"] is False
    assert result["no_motion_authority"] is True


@pytest.mark.parametrize("field,earlier", [
    ('"robot_id": "robot-01"', '"robot_id": "robot-02"'),
    ('"direction": "left"', '"direction": "right"'),
    ('"label": "near"', '"label": "far"'),
    ('"sample_id": 1', '"sample_id": 2'),
    ('"valid_mask": 7', '"valid_mask": 0'),
    ('"motion_certified": false', '"motion_certified": true'),
])
def test_ambiguous_side_range_jsonl_cannot_change_physical_evidence(
    tmp_path, field, earlier,
):
    line = json.dumps(samples()[0])
    assert line.count(field) == 1
    path = tmp_path / "ambiguous_three_range_samples.jsonl"
    path.write_text(line.replace(field, earlier + ", " + field) + "\n")
    with pytest.raises(ValueError, match="Duplicate side-range trial JSON field"):
        module().load_trial_rows(path)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_side_range_jsonl_never_reaches_threshold_fitter(
    tmp_path, constant,
):
    line = json.dumps(samples()[0])
    assert line.count('"sample_id": 1') == 1
    path = tmp_path / "nonfinite_side_range_samples.jsonl"
    path.write_text(line.replace('"sample_id": 1', f'"sample_id": {constant}') + "\n")
    with pytest.raises(ValueError, match="Nonfinite side-range trial JSON constant"):
        module().load_trial_rows(path)
