"""Real sensor trial selection remains operator supplied, never certified in CI."""
from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

calibrator = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/calibrate_handling.py"
))
analyze = calibrator["analyze"]
load_trial_rows = calibrator["load_trial_rows"]


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


@pytest.mark.parametrize("elapsed", [181, -1, True, None, float("nan"), float("inf")])
def test_calibration_rejects_invalid_or_stale_recorded_transport_age(elapsed):
    rows = trials()
    rows[8]["request_elapsed_ms"] = elapsed
    with pytest.raises(ValueError, match="fresh stationary WROOM"):
        analyze(rows)


def test_calibration_accepts_total_age_at_runtime_boundary():
    rows = trials()
    for row in rows:
        row["request_elapsed_ms"] = 180
    report = analyze(rows)
    assert report["sample_counts"] == {"upright": 8, "tilted": 4, "shaking": 4}
    assert report["thresholds_physically_qualified"] is False


def test_stationary_biased_gyro_and_separated_handling_events():
    report = analyze(trials())
    assert report["gyro_bias_dps"] == [1.0, 0.0, 0.0]
    assert 25 <= report["tilt_threshold_deg_candidate"] <= 50
    assert 300 <= report["shake_delta_mg_candidate"] < 600
    assert report["sample_counts"] == {
        "upright": 8, "tilted": 4, "shaking": 4,
    }
    assert report["physical_measurements_operator_supplied_not_attested"]
    assert report["calibrated"] is False
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


def test_handling_calibration_accepts_same_boot_uint32_rollover():
    rows = trials()
    rollover_stamps = [
        0xfffffff8, 0xfffffff9, 0xfffffffa, 0xfffffffb,
        0xfffffffc, 0xfffffffd, 0xfffffffe, 0xffffffff,
        0, 1, 2, 3, 4, 5, 6, 7,
    ]
    for row, stamp in zip(rows, rollover_stamps, strict=True):
        row["body"]["imu"]["sample_ms"] = stamp
    report = analyze(rows)
    assert report["gyro_bias_dps"] == [1.0, 0.0, 0.0]
    assert 25 <= report["tilt_threshold_deg_candidate"] <= 50
    assert 300 <= report["shake_delta_mg_candidate"] < 600
    assert report["thresholds_physically_qualified"] is False
    assert report["motor_authorization"] is False


def test_handling_calibration_rejects_delayed_pre_wrap_replay_after_rollover():
    rows = trials()
    rollover_stamps = [
        0xfffffff8, 0xfffffff9, 0xfffffffa, 0xfffffffb,
        0xfffffffc, 0xfffffffd, 0xfffffffe, 0xffffffff,
        0, 1, 0xffffffff, 3, 4, 5, 6, 7,
    ]
    for row, stamp in zip(rows, rollover_stamps, strict=True):
        row["body"]["imu"]["sample_ms"] = stamp
    with pytest.raises(ValueError, match="No repeated, reversed or stale IMU conversions"):
        analyze(rows)


def test_handling_calibration_rejects_backward_sample_without_wrap():
    rows = trials()
    rows[9]["body"]["imu"]["sample_ms"] = rows[8]["body"]["imu"]["sample_ms"] - 50
    with pytest.raises(ValueError, match="No repeated, reversed or stale IMU conversions"):
        analyze(rows)


def test_handling_calibration_rejects_device_uptime_jump_without_host_time():
    rows = trials()
    # Consistent per-record seq and fresh age_ms must not hide an impossible
    # source-clock leap while the Mac has seen only 0.8 seconds pass.
    for row in rows[8:]:
        row["body"]["imu"]["sample_ms"] += 30000
    with pytest.raises(ValueError, match="outpaced host receipt"):
        analyze(rows)


def test_handling_calibration_rejects_accumulated_small_clock_jumps():
    rows = trials()
    # An attacker could split a huge leap into individually plausible steps.
    # The first accepted host receipt anchors one cumulative timing window.
    for index, row in enumerate(rows):
        row["body"]["imu"]["sample_ms"] = 1000 + index * 1000
    with pytest.raises(ValueError, match="outpaced host receipt"):
        analyze(rows)


def test_handling_calibration_allows_real_elapsed_gaps_between_phases():
    rows = trials()
    # A deliberate operator setup pause advances BOTH independent clocks.
    # It must not invalidate otherwise fresh, ordered physical samples.
    for row in rows[8:]:
        row["time_monotonic_s"] += 10.0
        row["body"]["imu"]["sample_ms"] += 10000
    for row in rows[12:]:
        row["time_monotonic_s"] += 30.0
        row["body"]["imu"]["sample_ms"] += 30000
    report = analyze(rows)
    assert report["thresholds_physically_qualified"] is False
    assert report["motor_authorization"] is False

def test_handling_jsonl_reader_preserves_real_trial_shape(tmp_path):
    rows = trials()
    source = tmp_path / "mounted_imu_trial.jsonl"
    source.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    decoded = load_trial_rows(source)
    assert decoded == rows
    result = analyze(decoded)
    assert result["sample_counts"] == {"upright": 8, "tilted": 4, "shaking": 4}
    assert result["thresholds_physically_qualified"] is False
    assert result["motor_authorization"] is False


@pytest.mark.parametrize("field,earlier", [
    ('"label": "upright"', '"label": "tilted"'),
    ('"firmware_commit": "physically-flashed-sha"',
     '"firmware_commit": "different-flash"'),
    ('"mount_id": "actual-head-mount-revision"',
     '"mount_id": "different-mounted-axis"'),
    ('"boot_id": 123', '"boot_id": 456'),
    ('"sample_ms": 1000', '"sample_ms": 999999'),
    ('"valid": true', '"valid": false'),
])
def test_handling_trial_rejects_conflicting_duplicate_fields(
    tmp_path, field, earlier,
):
    recorded = json.dumps(trials()[0])
    assert recorded.count(field) == 1
    source = tmp_path / "conflicting_handling.jsonl"
    source.write_text(recorded.replace(field, earlier + ", " + field) + "\n")
    with pytest.raises(ValueError, match="Duplicate handling trial JSON field"):
        load_trial_rows(source)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_handling_trial_jsonl_rejects_nonfinite_tokens(tmp_path, constant):
    recorded = json.dumps(trials()[0])
    assert recorded.count('"time_monotonic_s": 100.0') == 1
    source = tmp_path / "nonfinite_handling.jsonl"
    source.write_text(recorded.replace(
        '"time_monotonic_s": 100.0',
        f'"time_monotonic_s": {constant}',
    ) + "\n")
    with pytest.raises(ValueError, match="Nonfinite handling trial JSON constant"):
        load_trial_rows(source)


@pytest.mark.parametrize("low_g_counts", [4096, 8191])
def test_handling_calibration_rejects_runtime_low_g_pose_revocation(low_g_counts):
    rows = trials()
    for row in rows[12:]:
        row["body"]["imu"]["acc"] = [0, 0, low_g_counts]
    with pytest.raises(ValueError, match="Implausible MPU6050 acceleration"):
        analyze(rows)


def test_handling_calibration_accepts_runtime_half_g_boundary():
    rows = trials()
    for row in rows[12:]:
        row["body"]["imu"]["acc"] = [0, 0, 8192]
    report = analyze(rows)
    assert report["shake_delta_mg_candidate"] == 300
    assert report["thresholds_physically_qualified"] is False
    assert report["motor_authorization"] is False


@pytest.mark.parametrize("opposing_count", [1, 4])
def test_handling_calibration_rejects_conflicting_quiet_gravity(opposing_count):
    rows = trials()
    for row in rows[:opposing_count]:
        row["body"]["imu"]["acc"] = [0, 0, -16384]
    with pytest.raises(ValueError, match="conflicting gravity vectors"):
        analyze(rows)


def test_handling_calibration_preserves_identified_robot():
    rows = trials()
    for row in rows:
        row["body"]["robot_id"] = "robot-01"
    report = analyze(rows)
    assert report["robot_id"] == "robot-01"
    assert report["thresholds_physically_qualified"] is False
    assert report["motor_authorization"] is False


def test_handling_calibration_legacy_unidentified_log_remains_unattested():
    report = analyze(trials())
    assert report["robot_id"] is None
    assert report["thresholds_physically_qualified"] is False


@pytest.mark.parametrize("other_id", ["robot-02", None, "../robot-01", ""])
def test_handling_calibration_rejects_mixed_or_invalid_robot_identity(other_id):
    rows = trials()
    for row in rows:
        row["body"]["robot_id"] = "robot-01"
    rows[8]["body"]["robot_id"] = other_id
    with pytest.raises(ValueError, match="robot identit"):
        analyze(rows)


@pytest.mark.parametrize("missing_index", [0, 8])
def test_handling_calibration_rejects_partial_robot_identity(missing_index):
    rows = trials()
    for row in rows:
        row["body"]["robot_id"] = "robot-01"
    del rows[missing_index]["body"]["robot_id"]
    with pytest.raises(ValueError, match="Do not mix robot identities"):
        analyze(rows)


def native_trial_rows():
    rows = trials()
    for row in rows:
        row["body"]["imu"].update(low_g_valid=True, low_g_irq=False, low_g_seq=3)
    return rows


@pytest.mark.parametrize("update", [
    {"low_g_irq": True},
    {"low_g_valid": False},
    {"low_g_seq": True},
    {"low_g_seq": 4},
])
def test_native_trial_rejects_invalid_or_changed_low_g_evidence(update):
    rows = native_trial_rows()
    rows[8]["body"]["imu"].update(update)
    with pytest.raises(ValueError, match="low-g"):
        analyze(rows)


def test_native_trial_rejects_mixed_low_g_capability():
    rows = native_trial_rows()
    for key in ("low_g_valid", "low_g_irq", "low_g_seq"):
        del rows[8]["body"]["imu"][key]
    with pytest.raises(ValueError, match="low-g"):
        analyze(rows)


def test_native_trial_allows_unchanged_counter_without_qualification():
    report = analyze(native_trial_rows())
    assert report["thresholds_physically_qualified"] is False
    assert report["motor_authorization"] is False

@pytest.mark.parametrize("payload, message", [
    (b'{"label":"upright"}', "Incomplete"),
    (b'{"label":"upright"}\n\n', "Blank"),
    (b'[]\n', "must be an object"),
    (b'', "Incomplete"),
    (b' ' * 300001, "Oversized"),
    (b'{"label":"upright"}\n{"label":', "Incomplete"),
])
def test_corrupt_capture(tmp_path, payload, message):
    source = tmp_path / "trial.jsonl"
    source.write_bytes(payload)
    with pytest.raises(ValueError, match=message):
        load_trial_rows(source)


def test_valid_capture_crlf(tmp_path):
    source = tmp_path / "trial.jsonl"
    source.write_bytes(b'{"label":"upright"}\r\n{"label":"tilted"}\r\n')
    assert load_trial_rows(source) == [{"label": "upright"}, {"label": "tilted"}]


def test_complete_sample_counts_do_not_excuse_unterminated_capture(tmp_path):
    source = tmp_path / "trial.jsonl"
    source.write_text("\n".join(json.dumps(row) for row in trials()), encoding="utf-8")
    with pytest.raises(ValueError, match="Incomplete"):
        load_trial_rows(source)


@pytest.mark.parametrize("axis", ["acc", "gyro"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_handling_calibration_rejects_nonfinite_axes(axis, value):
    rows = trials()
    rows[8]["body"]["imu"][axis][0] = value
    with pytest.raises(ValueError, match="fresh stationary WROOM"):
        analyze(rows)
