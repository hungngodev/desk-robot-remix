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
        "firmware_commit": "sha-of-physically-flashed-build",
        "audio_config_id": "bench-config-1",
        "mic_speaker_placement_id": "prototype-enclosure-a",
    } for n in range(20)]
    return rows + [{
        "kind": "robot_only", "duration_seconds": 600,
        "self_interruptions": 0,
    }]


def test_well_formed_synthetic_rows_only_verify_test_criteria():
    report = evaluate(fake_rows())
    assert report["meets_proposed_gate"]
    assert report["records_are_operator_supplied_not_independently_attested"]
    assert report["coverage"]["human_speakers"] == 2
    assert report["coverage"]["load_profiles"] == [
        "camera_wifi", "motors_servos_stand", "voice_only",
    ]


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
    for row in rows[:-1]:
        row[field] = value
    with pytest.raises(ValueError):
        evaluate(rows)


def test_old_playback_replay_prevents_gate():
    rows = fake_rows()
    rows[0]["obsolete_audio_never_resumed"] = False
    assert not evaluate(rows)["meets_proposed_gate"]


def test_stage_boundary_cannot_precede_human_speech():
    rows = fake_rows()
    rows[0]["vad_arrival_ms"] = rows[0]["human_onset_ms"] - 1
    with pytest.raises(ValueError, match="not monotonic"):
        evaluate(rows)
