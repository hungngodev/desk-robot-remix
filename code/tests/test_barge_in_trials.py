"""Operator measured double-talk gates, not simulated physical success."""
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

script = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/check_barge_in_trials.py"
))
evaluate = script["evaluate"]
parse_trial_jsonl = script["parse_trial_jsonl"]


def fake_rows():
    rows = [{
        "kind": "human", "id": f"trial{n}",
        "volume": ("low", "medium", "high")[n % 3],
        "human_onset_ms": n * 1000,
        "vad_arrival_ms": n * 1000 + 50,
        "abort_dispatch_ms": n * 1000 + 70,
        "head_queue_clear_ms": n * 1000 + 100,
        "i2s_stop_ms": n * 1000 + 120,
        "audible_stop_ms": n * 1000 + 200,
        "audible_robot_speech_at_onset": True,
        "new_utterance_captured": True,
        "new_intent_correct": True,
        "utterance_beginning_intelligible": True,
        "obsolete_audio_never_resumed": True,
        "interruption_position": ("early", "late")[n % 2],
        "load_profile": (
            "voice_only", "camera_wifi", "motors_servos_stand"
        )[n % 3],
        "speaker_id": ("speaker_a", "speaker_b")[n % 2],
        "conversation_turn": 1 + n // 4,
        "speaker_distance_cm": 50,
        "room_noise_db_a": 32,
        "robot_id": "robot-01",
        "firmware_commit": "sha-of-physically-flashed-build",
        "audio_config_id": "bench-config-1",
        "mic_speaker_placement_id": "prototype-enclosure-a",
    } for n in range(20)]
    return rows + [{
        "kind": "robot_only", "duration_seconds": 600,
        "self_interruptions": 0, "robot_speech_seconds": 120,
        "robot_speech_seconds_by_minute": [12.0] * 10,
        "robot_speech_volumes_observed": ["low", "medium", "high"],
        "audible_robot_speech_observed": True,
        "robot_id": "robot-01",
        "firmware_commit": "sha-of-physically-flashed-build",
        "audio_config_id": "bench-config-1",
        "mic_speaker_placement_id": "prototype-enclosure-a",
    }, {
        "kind": "quiet", "duration_seconds": 600,
        "quiet_mode_enabled": True,
        "unsolicited_speech_events": 0, "unsolicited_motion_events": 0,
        "robot_id": "robot-01",
        "firmware_commit": "sha-of-physically-flashed-build",
        "audio_config_id": "bench-config-1",
        "mic_speaker_placement_id": "prototype-enclosure-a",
    }]


def both_distances():
    near = fake_rows()
    far = []
    for row in near[:-2]:
        trial = {**row, "id": row["id"] + "-far", "speaker_distance_cm": 100}
        for key in (
            "human_onset_ms", "vad_arrival_ms", "abort_dispatch_ms",
            "head_queue_clear_ms", "i2s_stop_ms", "audible_stop_ms",
        ):
            trial[key] += 20000
        far.append(trial)
    return near[:-2] + far + near[-2:]


def test_well_formed_synthetic_rows_only_verify_test_criteria():
    report = evaluate(both_distances())
    assert report["meets_proposed_gate"]
    assert report["human_trials"] == 40
    assert report["distance_results"]["50cm"]["human_trials"] == 20
    assert report["distance_results"]["100cm"]["human_trials"] == 20
    assert report["records_are_operator_supplied_not_independently_attested"]
    assert report["robot_id"] == "robot-01"
    assert report["firmware_commit"] == "sha-of-physically-flashed-build"
    assert report["audio_config_id"] == "bench-config-1"
    assert report["mic_speaker_placement_id"] == "prototype-enclosure-a"
    assert report["quiet_mode_seconds"] == 600
    assert report["robot_speech_seconds"] == 120
    assert report["robot_speech_seconds_by_minute"] == [12.0] * 10
    assert report["robot_speech_volumes_observed"] == [
        "high", "low", "medium",
    ]
    assert report["audible_robot_speech_observed"] is True
    assert report["quiet_mode_enabled"] is True
    assert report["quiet_unsolicited_speech_events"] == 0
    assert report["quiet_unsolicited_motion_events"] == 0
    assert report["coverage"]["human_speakers"] == 2
    assert report["coverage"]["load_profiles"] == [
        "camera_wifi", "motors_servos_stand", "voice_only",
    ]


@pytest.mark.parametrize("change", [
    lambda x: x[-2].update({
        "robot_speech_seconds": 0.001,
        "robot_speech_seconds_by_minute": [0.0001] * 10,
    }),
    lambda x: x[-2].update({
        "robot_speech_seconds_by_minute": [60.0, 60.0] + [0.0] * 8,
    }),
    lambda x: x[-2].update({"robot_speech_seconds_by_minute": [12.0] * 9}),
    lambda x: x[-2].update({"robot_speech_seconds_by_minute": [11.0] * 10}),
    lambda x: x[-2].update({"robot_speech_seconds_by_minute": [12.0] * 9 + [True]}),
    lambda x: x[-2].update({"robot_speech_volumes_observed": ["high"]}),
    lambda x: x[-2].update({
        "robot_speech_volumes_observed": ["low", "medium", []],
    }),
    lambda x: x[-2].update({
        "robot_speech_seconds": 119.99,
        "robot_speech_seconds_by_minute": [11.999] * 10,
    }),
])
def test_robot_only_acoustic_control_rejects_unrepresentative_speech(change):
    rows = both_distances()
    change(rows)
    with pytest.raises(ValueError, match="robot|Robot"):
        evaluate(rows)



@pytest.mark.parametrize("observation", [False, None, "yes", 1])
def test_audible_barge_in_rejects_silent_or_unmeasured_human_trial(observation):
    rows = both_distances()
    if observation is None:
        rows[0].pop("audible_robot_speech_at_onset")
    else:
        rows[0]["audible_robot_speech_at_onset"] = observation
    with pytest.raises(ValueError, match="audible robot speech at onset"):
        evaluate(rows)


def test_near_only_cannot_pass_full_a2_even_when_all_near_trials_pass():
    report = evaluate(fake_rows())
    assert report["distance_results"]["50cm"]["meets_human_gate"]
    assert not report["distance_results"]["100cm"]["meets_human_gate"]
    assert not report["meets_proposed_gate"]


def test_far_only_is_a_partial_valid_trial_not_complete_a2():
    rows = both_distances()[20:]
    assert not evaluate(rows)["meets_proposed_gate"]


@pytest.mark.parametrize(("field", "allowed"), [
    ("audible_stop_ms", 18),
    ("new_intent_correct", 17),
])
def test_far_distance_must_independently_meet_stop_and_intent_thresholds(
    field, allowed,
):
    rows = both_distances()
    failures = 2 if field == "audible_stop_ms" else 3
    for row in rows[20:20 + failures]:
        if field == "audible_stop_ms":
            row[field] = row["human_onset_ms"] + 750
        else:
            row[field] = False
    report = evaluate(rows)
    assert report["distance_results"]["50cm"]["meets_human_gate"]
    metric = (
        "audible_stops_within_500ms" if field == "audible_stop_ms"
        else "new_intents_understood"
    )
    assert report["distance_results"]["100cm"][metric] == allowed
    assert not report["meets_proposed_gate"]


def test_incomplete_far_band_is_rejected_not_rounded_to_twenty():
    rows = both_distances()
    rows.pop(25)
    with pytest.raises(ValueError, match="20 human trials"):
        evaluate(rows)


@pytest.mark.parametrize("second_onset", [100, 200])
def test_overlapping_human_attempts_do_not_count_as_independent_trials(second_onset):
    rows = both_distances()
    second = rows[1]
    delta = second_onset - second["human_onset_ms"]
    for field in (
        "human_onset_ms", "vad_arrival_ms", "abort_dispatch_ms",
        "head_queue_clear_ms", "i2s_stop_ms", "audible_stop_ms",
    ):
        second[field] += delta
    # Distinct onsets and valid per-trial stage order previously passed.
    assert rows[0]["human_onset_ms"] != second["human_onset_ms"]
    assert second["human_onset_ms"] <= rows[0]["audible_stop_ms"]
    with pytest.raises(ValueError, match="Overlapping human interruption"):
        evaluate(rows)


def test_overlapping_near_and_far_attempts_cannot_count_twice():
    rows = both_distances()
    previous = rows[19]
    first_far = rows[20]
    delta = previous["audible_stop_ms"] - 100 - first_far["human_onset_ms"]
    for field in (
        "human_onset_ms", "vad_arrival_ms", "abort_dispatch_ms",
        "head_queue_clear_ms", "i2s_stop_ms", "audible_stop_ms",
    ):
        first_far[field] += delta
    assert first_far["human_onset_ms"] > previous["human_onset_ms"]
    with pytest.raises(ValueError, match="Overlapping human interruption"):
        evaluate(rows)


def test_out_of_order_nonoverlapping_acoustic_trials_remain_valid():
    rows = both_distances()
    rows[0], rows[20] = rows[20], rows[0]
    loaded = parse_trial_jsonl("\n".join(json.dumps(row) for row in rows))
    assert evaluate(loaded)["meets_proposed_gate"] is True


def test_cross_distance_reused_trial_onset_is_not_new_acoustic_evidence():
    rows = both_distances()
    rows[20].update({
        key: rows[0][key]
        for key in (
            "human_onset_ms", "vad_arrival_ms", "abort_dispatch_ms",
            "head_queue_clear_ms", "i2s_stop_ms", "audible_stop_ms",
        )
    })
    with pytest.raises(ValueError, match="onset timestamp reused"):
        evaluate(rows)


@pytest.mark.parametrize(("kind", "field", "label"), [
    ("human", "human_onset_ms", "human_onset_ms"),
    ("robot_only", "duration_seconds", "robot-only duration"),
])
def test_oversized_numeric_acoustic_evidence_fails_closed(kind, field, label):
    rows = both_distances()
    next(row for row in rows if row["kind"] == kind)[field] = 10**1000
    with pytest.raises(ValueError, match=f"Missing or invalid measured {label}"):
        evaluate(rows)


def test_late_double_talk_and_self_interruption_fail():
    rows = both_distances()
    rows[0]["audible_stop_ms"] += 650
    rows[1]["audible_stop_ms"] += 650
    rows[-2]["self_interruptions"] = 1
    report = evaluate(rows)
    assert report["distance_results"]["50cm"]["audible_stops_within_500ms"] == 18
    assert not report["meets_proposed_gate"]


@pytest.mark.parametrize("change", [
    lambda x: x.pop(),
    lambda x: x[0].update({"id": x[1]["id"]}),
    lambda x: x[0].update({"volume": "max"}),
    lambda x: x[0].update({"human_onset_ms": float("nan")}),
    lambda x: x[1].update({"new_intent_correct": "yes"}),
    lambda x: x[-2].update({"duration_seconds": 300}),
    lambda x: x[-2].update({"robot_speech_seconds": 0}),
    lambda x: x[-2].update({"robot_speech_seconds": 601}),
    lambda x: x[-2].update({"audible_robot_speech_observed": False}),
    lambda x: x[-1].update({"quiet_mode_enabled": False}),
    lambda x: x[-1].update({"duration_seconds": 300}),
    lambda x: x[-1].update({"unsolicited_motion_events": -1}),
    lambda x: x[-1].update({"unsolicited_speech_events": 1.5}),
    lambda x: x[0].pop("vad_arrival_ms"),
    lambda x: x[0].update({"i2s_stop_ms": x[0]["head_queue_clear_ms"] - 1}),
    lambda x: x[0].update({"speaker_distance_cm": 90}),
    lambda x: x[0].update({"firmware_commit": ""}),
    lambda x: x[0].update({"utterance_beginning_intelligible": None}),
    lambda x: x[0].update({"interruption_position": "middle"}),
    lambda x: x[0].update({"load_profile": "simulated"}),
    lambda x: x[0].update({"speaker_id": ""}),
    lambda x: x[0].update({"room_noise_db_a": float("inf")}),
    lambda x: x[0].update({"conversation_turn": 0}),
])
def test_reject_invalid_trial_records(change):
    rows = fake_rows()
    change(rows)
    with pytest.raises(ValueError):
        evaluate(rows)


@pytest.mark.parametrize("field,value", [
    ("interruption_position", "early"),
    ("load_profile", "voice_only"),
    ("speaker_id", "speaker_a"),
    ("conversation_turn", 1),
])
def test_incomplete_acoustic_trial_coverage_fails(field, value):
    rows = fake_rows()
    for row in rows[:-2]:
        row[field] = value
    with pytest.raises(ValueError):
        evaluate(rows)


@pytest.mark.parametrize("field", [
    "firmware_commit", "audio_config_id", "mic_speaker_placement_id",
    "robot_id",
])
def test_mixed_hardware_or_software_setup_cannot_be_certified(field):
    rows = fake_rows()
    rows[10][field] = "different-configuration"
    with pytest.raises(ValueError, match="Do not mix firmware"):
        evaluate(rows)


def test_old_playback_replay_prevents_gate():
    rows = both_distances()
    rows[0]["obsolete_audio_never_resumed"] = False
    assert not evaluate(rows)["meets_proposed_gate"]


@pytest.mark.parametrize("trial_id", [" ", "\t", "\u2003", " \n "])
def test_human_trial_id_requires_visible_identifier(trial_id):
    rows = both_distances()
    rows[0]["id"] = trial_id
    with pytest.raises(ValueError, match="unique nonempty human trial IDs"):
        evaluate(rows)


@pytest.mark.parametrize("wrapper", [
    lambda value: f" {value} ",
    lambda value: f"\t{value}\t",
])
def test_human_trial_id_whitespace_cannot_duplicate_one_measured_attempt(wrapper):
    records = both_distances()
    records[0]["id"] = wrapper(records[1]["id"])
    # Without canonical uniqueness, one attempt could be counted twice
    # under labels differing only in surrounding whitespace.
    loaded = parse_trial_jsonl("\n".join(json.dumps(row) for row in records))
    with pytest.raises(ValueError, match="unique nonempty human trial IDs"):
        evaluate(loaded)


def test_distinct_human_trial_id_with_surrounding_space_remains_valid():
    records = both_distances()
    records[0]["id"] = "  independent-trial  "
    assert evaluate(records)["meets_proposed_gate"] is True


def test_negative_monotonic_audio_stages_cannot_certify_acoustic_stop():
    rows = both_distances()
    # Every stage remains ordered and the stop is only 200 ms after onset;
    # nevertheless a device monotonic clock cannot predate boot.
    for field in (
        "human_onset_ms", "vad_arrival_ms", "abort_dispatch_ms",
        "head_queue_clear_ms", "i2s_stop_ms", "audible_stop_ms",
    ):
        rows[0][field] -= 1000
    with pytest.raises(ValueError, match="monotonic timestamps must be nonnegative"):
        evaluate(rows)


def test_stage_boundary_cannot_precede_human_speech():
    rows = fake_rows()
    rows[0]["vad_arrival_ms"] = rows[0]["human_onset_ms"] - 1
    with pytest.raises(ValueError, match="not monotonic"):
        evaluate(rows)


@pytest.mark.parametrize("field", [
    "robot_id", "firmware_commit", "audio_config_id",
    "mic_speaker_placement_id",
])
def test_echo_only_control_cannot_borrow_another_robots_setup(field):
    records = fake_rows()
    records[-2][field] = "different-physical-setup"
    with pytest.raises(ValueError, match="same robot and setup"):
        evaluate(records)


@pytest.mark.parametrize("field", [
    "robot_id", "firmware_commit", "audio_config_id",
    "mic_speaker_placement_id",
])
def test_quiet_mode_must_match_robot_and_flashing_configuration(field):
    records = fake_rows()
    records[-1][field] = "another-setup"
    with pytest.raises(ValueError, match="Quiet-mode control"):
        evaluate(records)


@pytest.mark.parametrize("field", [
    "unsolicited_speech_events", "unsolicited_motion_events",
])
def test_quiet_mode_unsolicited_activity_prevents_a2_gate(field):
    records = both_distances()
    records[-1][field] = 1
    report = evaluate(records)
    assert report["quiet_mode_seconds"] == 600
    assert not report["meets_proposed_gate"]


def test_human_acoustic_gate_cannot_mix_distinct_robot_identities():
    records = fake_rows()
    records[10]["robot_id"] = "robot-02"
    with pytest.raises(ValueError, match="Do not mix firmware"):
        evaluate(records)


def test_jsonl_parser_preserves_valid_full_acoustic_trial_population():
    rows = both_distances()
    loaded = parse_trial_jsonl("\n".join(json.dumps(row) for row in rows))
    report = evaluate(loaded)
    assert report["meets_proposed_gate"]
    assert report["human_trials"] == 40


@pytest.mark.parametrize("line", [
    '{"kind":"human","audible_stop_ms":900,"audible_stop_ms":200}',
    '{"kind":"human","speaker_distance_cm":100,"speaker_distance_cm":50}',
    '{"kind":"robot_only","self_interruptions":1,"self_interruptions":0}',
    '{"kind":"quiet","quiet_mode_enabled":false,"quiet_mode_enabled":true}',
    '{"kind":"human","id":"trial0","id":"trial0"}',
    '{"kind":"human","diagnostics":{"source":"other","source":"other"}}',
])
def test_jsonl_parser_rejects_duplicate_fields_before_evidence_evaluation(line):
    with pytest.raises(ValueError, match="Duplicate JSON trial field"):
        parse_trial_jsonl(line)


@pytest.mark.parametrize("invalid_robot_id", [
    "robot/01", "robot.01", "robot 01", "robot:01",
    "robot\u200b01", "x" * 41,
])
def test_a2_rejects_noncanonical_robot_identity(invalid_robot_id):
    """Matching invalid labels across controls cannot certify a nonexistent pet."""
    rows = both_distances()
    for row in rows:
        row["robot_id"] = invalid_robot_id
    loaded = parse_trial_jsonl("\n".join(json.dumps(row) for row in rows))
    with pytest.raises(ValueError, match="robot_id"):
        evaluate(loaded)


@pytest.mark.parametrize("valid_robot_id", [
    "r", "robot-01", "robot_2", "X" * 40,
])
def test_a2_accepts_canonical_robot_identity(valid_robot_id):
    """All runtime-valid robot identifiers retain the positive A2 trial path."""
    rows = both_distances()
    for row in rows:
        row["robot_id"] = valid_robot_id
    loaded = parse_trial_jsonl("\n".join(json.dumps(row) for row in rows))
    result = evaluate(loaded)
    assert result["robot_id"] == valid_robot_id
    assert result["meets_proposed_gate"] is True


@pytest.mark.parametrize("distance", [50, 100, None])
def test_speaker_whitespace_aliases_cannot_supply_second_human(distance):
    rows = both_distances()
    for index, row in enumerate(rows[:-2]):
        if distance is None or row["speaker_distance_cm"] == distance:
            row["speaker_id"] = ("speaker_a", " \tspeaker_a\u2003")[index % 2]
    loaded = parse_trial_jsonl("\n".join(json.dumps(row) for row in rows))
    if distance is None:
        with pytest.raises(ValueError, match="second human speaker"):
            evaluate(loaded)
    else:
        report = evaluate(loaded)
        assert not report["distance_results"][f"{distance}cm"]["coverage_complete"]
        assert not report["meets_proposed_gate"]


def test_distinct_speaker_ids_with_whitespace_preserve_a2_coverage():
    rows = both_distances()
    for index, row in enumerate(rows[:-2]):
        if index % 4 < 2:
            row["speaker_id"] = f" \t{row['speaker_id']}\u2003"
    report = evaluate(parse_trial_jsonl("\n".join(json.dumps(row) for row in rows)))
    assert report["coverage"]["human_speakers"] == 2
    assert report["meets_proposed_gate"] is True


def test_echo_only_failure_independently_blocks_a2():
    rows = both_distances()
    rows[-2]["self_interruptions"] = 1
    report = evaluate(rows)
    assert report["self_interruptions"] == 1
    assert all(
        band["meets_human_gate"] for band in report["distance_results"].values()
    )
    assert report["meets_proposed_gate"] is False


@pytest.mark.parametrize(("latency_ms", "trials", "expected_stops", "passes"), [
    (499.999, 2, 20, True),
    (500, 2, 20, True),
    (500.001, 1, 19, True),
    (500.001, 2, 18, False),
])
def test_acoustic_stop_threshold_is_inclusive_and_per_distance(
    latency_ms, trials, expected_stops, passes,
):
    rows = both_distances()
    for row in rows[20:20 + trials]:
        row["audible_stop_ms"] = row["human_onset_ms"] + latency_ms
    report = evaluate(parse_trial_jsonl("\n".join(json.dumps(row) for row in rows)))
    near = report["distance_results"]["50cm"]
    far = report["distance_results"]["100cm"]
    assert near["meets_human_gate"] is True
    assert far["audible_stops_within_500ms"] == expected_stops
    assert far["new_intents_understood"] == 20
    assert far["meets_human_gate"] is passes
    assert report["meets_proposed_gate"] is passes


@pytest.mark.parametrize(("lost_starts", "passes"), [(2, True), (3, False)])
def test_lost_utterance_start_fails_intent_without_failing_stop(lost_starts, passes):
    rows = both_distances()
    for row in rows[20:20 + lost_starts]:
        row["utterance_beginning_intelligible"] = False
        row["new_intent_correct"] = False
    report = evaluate(rows)
    near = report["distance_results"]["50cm"]
    far = report["distance_results"]["100cm"]
    assert near["meets_human_gate"] is True
    assert far["audible_stops_within_500ms"] == 20
    assert far["new_intents_understood"] == 20 - lost_starts
    assert far["meets_human_gate"] is passes
    assert report["meets_proposed_gate"] is passes


def test_correct_intent_cannot_be_claimed_if_utterance_start_was_lost():
    rows = both_distances()
    rows[0]["utterance_beginning_intelligible"] = False
    with pytest.raises(ValueError, match="Correct intent requires captured"):
        evaluate(rows)


@pytest.mark.parametrize("echoes", [0, 1])
def test_cli_reports_gate_without_claiming_physical_attestation(tmp_path, echoes, monkeypatch):
    rows = both_distances()
    rows[-2]["self_interruptions"] = echoes
    for row in rows:
        row["audio_config_id"] = "bàn thử"
    # Exercise actual UTF-8 JSONL under a non-UTF-8 process locale.
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("PYTHONUTF8", "0")
    monkeypatch.setenv("PYTHONCOERCECLOCALE", "0")
    path = tmp_path / "trials.jsonl"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
                    encoding="utf-8")
    checker = Path(__file__).resolve().parents[1] / "scripts/check_barge_in_trials.py"
    completed = subprocess.run(
        [sys.executable, str(checker), str(path)],
        check=True, capture_output=True, text=True, timeout=10,
    )
    report = json.loads(completed.stdout)
    assert report["meets_proposed_gate"] is (echoes == 0)
    assert report["records_are_operator_supplied_not_independently_attested"] is True
    assert report["audio_config_id"] == "bàn thử"


@pytest.mark.parametrize("base", [2**53, 2**54, 2**62])
def test_huge_clock_cannot_round_late_stops_into_pass(base):
    rows = both_distances()
    for row in rows[:-2]:
        for field in (
            "human_onset_ms", "vad_arrival_ms", "abort_dispatch_ms",
            "head_queue_clear_ms", "i2s_stop_ms", "audible_stop_ms",
        ):
            row[field] += base
    for row in rows[:2]:
        row["audible_stop_ms"] = row["human_onset_ms"] + 501
    loaded = parse_trial_jsonl("\n".join(json.dumps(row) for row in rows))
    with pytest.raises(ValueError, match="timestamp precision"):
        evaluate(loaded)


def test_zero_elapsed_cannot_be_audible_stop():
    rows = both_distances()
    for field in (
        "human_onset_ms", "vad_arrival_ms", "abort_dispatch_ms",
        "head_queue_clear_ms", "i2s_stop_ms", "audible_stop_ms",
    ):
        rows[0][field] = rows[0]["human_onset_ms"]
    with pytest.raises(ValueError, match="positive elapsed"):
        evaluate(rows)


def test_actual_echo_exposure_cannot_round_up_to_minimum():
    rows = both_distances()
    rows[-2]["robot_speech_seconds_by_minute"] = [12.0] * 9 + [11.995]
    with pytest.raises(ValueError, match="120s cumulative"):
        evaluate(rows)


@pytest.mark.parametrize(("latency_ms", "passes"), [
    (499.999, True), (500, True), (500.001, False),
])
def test_large_valid_clock_preserves_stop_boundary(latency_ms, passes):
    rows = both_distances()
    for row in rows[:-2]:
        for field in (
            "human_onset_ms", "vad_arrival_ms", "abort_dispatch_ms",
            "head_queue_clear_ms", "i2s_stop_ms", "audible_stop_ms",
        ):
            row[field] += 1_800_000_000_000
    for row in rows[:2]:
        row["audible_stop_ms"] = row["human_onset_ms"] + latency_ms
    assert evaluate(rows)["meets_proposed_gate"] is passes


@pytest.mark.parametrize("elapsed, expected", [(120, True), (120.001, False), (0, False)])
def test_i2s_cutoff_is_separate_from_audible_gate(elapsed, expected):
    records = both_distances()
    if not elapsed:
        for name in ("vad_arrival_ms", "abort_dispatch_ms", "head_queue_clear_ms"):
            records[0][name] = 0
    records[0]["i2s_stop_ms"] = elapsed
    report = evaluate(records)
    assert report["meets_proposed_gate"] is True
    assert report["meets_120ms_i2s_cutoff"] is expected
    near = report["distance_results"]["50cm"]
    assert near["i2s_stops_within_120ms"] == (20 if expected else 19)
    assert near["max_onset_to_i2s_stop_ms"] == max(120, elapsed)


def test_i2s_cutoff_requires_both_distances():
    report = evaluate(fake_rows())
    assert report["distance_results"]["50cm"]["meets_120ms_i2s_cutoff"] is True
    assert report["distance_results"]["100cm"]["max_onset_to_i2s_stop_ms"] is None
    assert report["meets_120ms_i2s_cutoff"] is False
