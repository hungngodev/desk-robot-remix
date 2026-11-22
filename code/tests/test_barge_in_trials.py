"""Operator measured double-talk gates, not simulated physical success."""
import runpy
from pathlib import Path

import pytest

evaluate = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/check_barge_in_trials.py"
))["evaluate"]


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
    assert report["audible_robot_speech_observed"] is True
    assert report["quiet_mode_enabled"] is True
    assert report["quiet_unsolicited_speech_events"] == 0
    assert report["quiet_unsolicited_motion_events"] == 0
    assert report["coverage"]["human_speakers"] == 2
    assert report["coverage"]["load_profiles"] == [
        "camera_wifi", "motors_servos_stand", "voice_only",
    ]


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
