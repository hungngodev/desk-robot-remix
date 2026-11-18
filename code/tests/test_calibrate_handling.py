"""Real sensor trial selection remains operator supplied, never certified in CI."""
from __future__ import annotations

import runpy
from pathlib import Path

import pytest

analyze = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/calibrate_handling.py"
))["analyze"]


def trials():
    samples = []
    # 50 degree stable tilt, 1.6g + 100 dps shake, and quiet 1g baseline.
    for index, (label, accel, gyro) in enumerate(
        [("upright", (0, 0, 16384), (131, 0, 0))] * 8
        + [("tilted", (12551, 0, 10531), (131, 0, 0))] * 4
        + [("shaking", (0, 0, 26000), (13231, 0, 0))] * 4
    ):
        samples.append({
            "label": label,
            "time_monotonic_s": index / 10 + 100,
            "firmware_commit": "physically-flashed-sha",
            "mount_id": "actual-head-mount-revision",
            "body": {
                "motor": {"m0": 0, "m1": 0},
                "drive_ms": 0,
                "imu": {
                    "family": 4, "gyro_id": 0x68, "valid": True,
                    "age_ms": 20, "boot_id": 123,
                    "sample_ms": 1000 + index * 100,
                    "acc": list(accel), "gyro": list(gyro),
                },
            },
        })
    return samples


def test_stationary_biased_gyro_and_separated_handling_events():
    report = analyze(trials())
    assert report["gyro_bias_dps"] == [1.0, 0.0, 0.0]
    assert 25 <= report["tilt_threshold_deg_candidate"] <= 50
    assert 300 <= report["shake_delta_mg_candidate"] < 600
    assert report["sample_counts"] == {
        "upright": 8, "tilted": 4, "shaking": 4,
    }
    assert report["physical_measurements_operator_supplied_not_attested"]
    assert report["thresholds_physically_qualified"] is False
    assert report["motor_authorization"] is False


@pytest.mark.parametrize("mutation", [
    lambda rows: rows.pop(),
    lambda rows: rows[0].update({"label": "freefall"}),
    lambda rows: rows[0].update({"label": []}),
    lambda rows: rows[0].update({"time_monotonic_s": float("nan")}),
    lambda rows: rows[0].update({"time_monotonic_s": 10 ** 1000}),
    lambda rows: rows[8].update({"time_monotonic_s": 100.0}),
    lambda rows: rows[8]["body"]["imu"].update({"sample_ms": 1000}),
    lambda rows: rows[8]["body"]["imu"].update({"boot_id": 456}),
    lambda rows: rows[8].update({"mount_id": "another-mount"}),
    lambda rows: rows[8].update({"firmware_commit": "new-firmware"}),
    lambda rows: rows[8]["body"]["motor"].update({"m0": 10}),
    lambda rows: rows[8]["body"]["imu"].update({"valid": False}),
    lambda rows: rows[8]["body"]["imu"].update({"age_ms": 999}),
    lambda rows: rows[8]["body"]["imu"].update({"acc": [0, 0, 0]}),
    lambda rows: rows[12]["body"]["imu"].update({"acc": [0, 0, 0]}),
    lambda rows: rows[0]["body"]["imu"].update({"gyro": [5000, 0, 0]}),
    lambda rows: rows[8]["body"]["imu"].update({"gyro": [20000, 0, 0]}),
    lambda rows: rows[12]["body"]["imu"].update({"gyro": [131, 0, 0]}),
])
def test_handling_calibration_rejects_invalid_or_unqualified_sources(mutation):
    rows = trials()
    mutation(rows)
    with pytest.raises(ValueError):
        analyze(rows)


def test_overlapping_tilt_angles_do_not_invent_a_threshold():
    rows = trials()
    for row in rows[8:12]:
        row["body"]["imu"]["acc"] = [1000, 0, 16353]
    with pytest.raises(ValueError, match="do not separate"):
        analyze(rows)


def test_weak_shake_does_not_invent_a_threshold():
    rows = trials()
    for row in rows[12:]:
        row["body"]["imu"]["acc"] = [0, 0, 17000]
    with pytest.raises(ValueError, match="do not separate"):
        analyze(rows)
