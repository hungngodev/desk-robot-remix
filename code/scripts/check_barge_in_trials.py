"""Score operator-declared live Xiaozhi interruption records.

The proposed audible A2 gate requires both distance populations and controls.
The 120 ms I2S cutoff is reported separately, not part of that gate.
The checker does not attest physical measurements or actuator-only false VAD.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


def _number(value: object, label: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"Missing or invalid measured {label}")
    try:
        measured = float(value)
    except OverflowError as exc:
        raise ValueError(f"Missing or invalid measured {label}") from exc
    if not math.isfinite(measured):
        raise ValueError(f"Missing or invalid measured {label}")
    return measured


def _unique_json_fields(pairs: list[tuple[str, object]]) -> dict:
    """Reject conflicting or repeated physical evidence at any JSON depth."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON trial field: {key}")
        result[key] = value
    return result


def _finite_json_float(raw: str) -> float:
    return _number(float(raw), "JSON trial number")


def parse_trial_jsonl(contents: str) -> list[dict]:
    """Load operator trial records without JSON's unsafe last-key-wins rule."""
    return [
        json.loads(
            line, object_pairs_hook=_unique_json_fields,
            parse_float=_finite_json_float, parse_constant=_finite_json_float,
        )
        for line in contents.splitlines() if line.strip()
    ]


def _partition_records(records: list[dict]) -> tuple[list[dict], dict, dict]:
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise ValueError("Trial log must contain objects")
    human = [r for r in records if r.get("kind") == "human"]
    alone = [r for r in records if r.get("kind") == "robot_only"]
    quiet = [r for r in records if r.get("kind") == "quiet"]
    if (len(human) not in (20, 40) or len(alone) != 1
            or len(quiet) != 1 or len(records) != len(human) + 2):
        raise ValueError(
            "Need 20 human trials per tested distance and separate robot-only/quiet controls"
        )
    ids = [r.get("id") for r in human]
    if (any(
        type(x) is not str or not 1 <= len(x) <= 64 or not x.strip()
        for x in ids
    ) or len({trial_id.strip() for trial_id in ids}) != len(human)):
        raise ValueError("Need unique nonempty human trial IDs")
    return human, alone[0], quiet[0]


def _human_conditions(r: dict) -> tuple[str, str, str, str, int]:
    volume = r.get("volume")
    if volume not in ("low", "medium", "high"):
        raise ValueError("Record low, medium and high intended speaker volumes")

    position = r.get("interruption_position")
    load = r.get("load_profile")
    speaker = r.get("speaker_id")
    turn = r.get("conversation_turn")
    if position not in ("early", "late"):
        raise ValueError("Record interruption position: early or late")
    if load not in ("voice_only", "camera_wifi", "motors_servos_stand"):
        raise ValueError("Record camera/WiFi and motor/servo stand load trials")
    if type(speaker) is not str or not speaker.strip() or len(speaker) > 64:
        raise ValueError("Record distinct human speaker identities")
    speaker = speaker.strip()
    if type(turn) is not int or not 1 <= turn <= 100:
        raise ValueError("Record numbered consecutive conversation turns")
    return volume, position, load, speaker, turn


def _validate_stages(r: dict) -> list[float]:
    # These fields distinguish measured acoustic success from a synthetic
    # stopwatch-only result. All timestamps share one monotonic timebase.
    stage_names = (
        "human_onset_ms", "vad_arrival_ms", "abort_dispatch_ms",
        "head_queue_clear_ms", "i2s_stop_ms", "audible_stop_ms",
    )
    stages = [_number(r.get(name), name) for name in stage_names]
    if stages[0] < 0:
        raise ValueError("Acoustic monotonic timestamps must be nonnegative")
    if any(later < earlier for earlier, later in zip(stages, stages[1:], strict=False)):
        raise ValueError("Audio stop stage timestamps are not monotonic")
    # Large absolute counters lose millisecond/sub-millisecond precision
    # when converted to float (e.g. 501 ms can become 500 ms). Require
    # a common, rebased trial clock with at least microsecond resolution.
    if any(math.ulp(stage) > 0.001 for stage in stages):
        raise ValueError("Acoustic timestamp precision insufficient; rebase the trial clock")
    if stages[-1] <= stages[0]:
        raise ValueError("Audible interruption requires positive elapsed time")
    return stages


def _validate_provenance(r: dict) -> None:
    for label in (
        "firmware_commit", "audio_config_id", "mic_speaker_placement_id",
        "robot_id",
    ):
        value = r.get(label)
        if type(value) is not str or not value.strip() or len(value) > 128:
            raise ValueError(f"Missing physical trial provenance: {label}")
    # Match the robot IDs accepted by the running RobotConfig schema.
    if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", r["robot_id"]) is None:
        raise ValueError("Physical trial robot_id must match configured robot ID format")


def _human_outcome(r: dict) -> tuple[bool, bool]:
    # A separate robot-only control cannot prove that each human trial
    # actually interrupted audible speech. Silence is not barge-in.
    if r.get("audible_robot_speech_at_onset") is not True:
        raise ValueError(
            "Each human interruption requires audible robot speech at onset"
        )
    captured = r.get("new_utterance_captured")
    correct = r.get("new_intent_correct")
    beginning = r.get("utterance_beginning_intelligible")
    no_replay = r.get("obsolete_audio_never_resumed")
    if any(type(value) is not bool for value in (
            captured, correct, beginning, no_replay)):
        raise ValueError("Record speech, start-of-utterance and replay evidence")
    if correct and not (captured and beginning):
        raise ValueError("Correct intent requires captured intelligible utterance start")
    return captured and correct and beginning and no_replay, no_replay


def _distance_results(distance_bands: dict) -> dict:
    distance_results = {}
    for name, band in distance_bands.items():
        varied = (
            band["volumes"] == {"low", "medium", "high"}
            and band["positions"] == {"early", "late"}
            and band["loads"] == {"voice_only", "camera_wifi", "motors_servos_stand"}
            and len(band["speakers"]) >= 2
            and any(turn + 1 in band["turns"] for turn in band["turns"])
        )
        cutoffs = band["i2s_cutoff_ms"]
        timely_cutoffs = sum(0 < elapsed <= 120 for elapsed in cutoffs)
        distance_results[name] = {
            "human_trials": band["count"],
            "audible_stops_within_500ms": band["on_time"],
            "i2s_stops_within_120ms": timely_cutoffs,
            "max_onset_to_i2s_stop_ms": max(cutoffs, default=None),
            "meets_120ms_i2s_cutoff": varied and timely_cutoffs == band["count"] == 20,
            "new_intents_understood": band["understood"],
            "coverage_complete": varied and band["count"] == 20,
            "meets_human_gate": (
                band["count"] == 20 and varied
                and band["on_time"] >= 19 and band["understood"] >= 18
                and band["no_replay"]
            ),
        }
    return distance_results


def _score_human_trials(human: list[dict]) -> dict:
    on_time = 0
    understood = 0
    volumes, positions, loads, speakers, turns = set(), set(), set(), set(), set()
    firmware_revisions, audio_configs, placements, robot_ids = (
        set(), set(), set(), set()
    )
    # 50 cm and 100 cm are separate 20-trial acceptance populations.
    # One completed population is useful diagnostic evidence, never A2 PASS.
    distance_bands = {
        name: {"count": 0, "on_time": 0, "understood": 0,
               "volumes": set(), "positions": set(), "loads": set(),
               "speakers": set(), "turns": set(), "no_replay": True,
               "i2s_cutoff_ms": []}
        for name in ("50cm", "100cm")
    }
    onset_times = set()
    attempt_intervals = []
    for r in human:
        volume, position, load, speaker, turn = _human_conditions(r)
        volumes.add(volume)
        positions.add(position)
        loads.add(load)
        speakers.add(speaker)
        turns.add(turn)

        stages = _validate_stages(r)
        if stages[0] in onset_times:
            raise ValueError("Human acoustic trial onset timestamp reused")
        onset_times.add(stages[0])
        attempt_intervals.append((stages[0], stages[-1]))
        distance = _number(r.get("speaker_distance_cm"), "speaker distance")
        noise = _number(r.get("room_noise_db_a"), "room background noise")
        if not 0 <= noise <= 100:
            raise ValueError("Record measured room noise")
        if 45 <= distance <= 55:
            band = distance_bands["50cm"]
        elif 95 <= distance <= 105:
            band = distance_bands["100cm"]
        else:
            raise ValueError("Record 50 cm or 100 cm speaking distance")
        band["count"] += 1
        band["i2s_cutoff_ms"].append(stages[4] - stages[0])
        band["volumes"].add(volume)
        band["positions"].add(position)
        band["loads"].add(load)
        band["speakers"].add(speaker)
        band["turns"].add(turn)

        _validate_provenance(r)
        firmware_revisions.add(r["firmware_commit"])
        audio_configs.add(r["audio_config_id"])
        placements.add(r["mic_speaker_placement_id"])
        robot_ids.add(r["robot_id"])
        retained, no_replay = _human_outcome(r)
        stopped = stages[-1] - stages[0] <= 500
        on_time += stopped
        understood += retained
        band["on_time"] += stopped
        band["understood"] += retained
        band["no_replay"] &= no_replay

    # A2 requires independent human interruptions on one physical head.
    # Unique onsets alone can count two simultaneous overlapping attempts.
    ordered_attempts = sorted(attempt_intervals)
    if any(
        next_onset <= prior_stop
        for (_, prior_stop), (next_onset, _) in zip(
            ordered_attempts, ordered_attempts[1:], strict=False
        )
    ):
        raise ValueError("Overlapping human interruption trial intervals")

    if volumes != {"low", "medium", "high"}:
        raise ValueError("Human trials must cover all intended speaker volumes")
    if positions != {"early", "late"}:
        raise ValueError("Need both early and late interruption in a reply")
    if loads != {"voice_only", "camera_wifi", "motors_servos_stand"}:
        raise ValueError("Need audio, camera/WiFi and motor/servo stand conditions")
    if len(speakers) < 2:
        raise ValueError("Need trials with a second human speaker")
    if not any(turn + 1 in turns for turn in turns):
        raise ValueError("Need adjacent conversation turns")
    if any(band["count"] not in (0, 20) for band in distance_bands.values()):
        raise ValueError("Each tested speaking distance requires exactly 20 human trials")

    # A single acceptance result must not mix different firmware builds,
    # AEC settings or microphone/speaker geometry across either distance set.
    # Those require separate complete acoustic trial sets.
    if any(len(values) != 1 for values in (
            firmware_revisions, audio_configs, placements, robot_ids)):
        raise ValueError("Do not mix firmware, audio config or physical mounting trials")

    return {
        "distance_results": _distance_results(distance_bands),
        "audible_stops_within_500ms": on_time,
        "new_intents_understood": understood,
        "coverage": {
            "speaker_volumes": sorted(volumes),
            "interruption_positions": sorted(positions),
            "load_profiles": sorted(loads),
            "human_speakers": len(speakers),
            "conversation_turns": sorted(turns),
        },
    }


def _validate_control_setup(human: dict, control: dict, quiet: dict) -> None:
    # The ten-minute echo-only control must run on the SAME robot and
    # flashed AEC setup as the human barge trials, not a quieter second unit.
    for field in (
        "robot_id", "firmware_commit", "audio_config_id",
        "mic_speaker_placement_id",
    ):
        if control.get(field) != human[field]:
            raise ValueError(
                "Robot-only control must use the same robot and setup as human trials"
            )
        if quiet.get(field) != human[field]:
            raise ValueError(
                "Quiet-mode control must use the same robot and setup as human trials"
            )


def _echo_control(control: dict) -> dict:
    duration = _number(control.get("duration_seconds"), "robot-only duration")
    echoes = control.get("self_interruptions")
    speech_seconds = _number(control.get("robot_speech_seconds"), "robot speech seconds")
    if (duration < 600 or type(echoes) is not int or echoes < 0
            or not 0 < speech_seconds <= duration
            or control.get("audible_robot_speech_observed") is not True):
        raise ValueError(
            "Need 600s robot-only observation with actual audible robot speech"
        )
    # The first 600 seconds must contain meaningful self-echo exposure.
    # A single millisecond of speech during a ten-minute stopwatch run
    # cannot establish that the AEC avoids false self-interruption.
    # This checker still only validates operator-supplied measurements.
    per_minute = control.get("robot_speech_seconds_by_minute")
    if type(per_minute) is not list or len(per_minute) != 10:
        raise ValueError("Need ten measured robot-only speech minute exposures")
    minute_seconds = [
        _number(value, f"robot speech minute {index + 1}")
        for index, value in enumerate(per_minute)
    ]
    if (
        any(not 5 <= seconds <= 60 for seconds in minute_seconds)
        or speech_seconds < 120
        or math.fsum(minute_seconds) < 120
        or not math.isclose(
            math.fsum(minute_seconds), speech_seconds,
            rel_tol=0.0, abs_tol=0.01,
        )
    ):
        raise ValueError(
            "Need 120s cumulative robot speech, at least 5s in each "
            "of ten minutes, and a matching measured total"
        )
    robot_volumes = control.get("robot_speech_volumes_observed")
    if (
        type(robot_volumes) is not list
        or len(robot_volumes) != 3
        or any(type(volume) is not str for volume in robot_volumes)
        or set(robot_volumes) != {"low", "medium", "high"}
    ):
        raise ValueError(
            "Robot-only control must exercise low, medium and high intended volumes"
        )
    return {
        "robot_only_seconds": duration,
        "self_interruptions": echoes,
        "robot_speech_seconds": speech_seconds,
        "robot_speech_seconds_by_minute": minute_seconds,
        "robot_speech_volumes_observed": sorted(robot_volumes),
        "audible_robot_speech_observed": True,
    }


def _quiet_control(quiet: dict) -> dict:
    if quiet.get("quiet_mode_enabled") is not True:
        raise ValueError("Quiet-mode control must confirm enabled quiet mode")
    quiet_duration = _number(quiet.get("duration_seconds"), "quiet duration")
    unsolicited_speech = quiet.get("unsolicited_speech_events")
    unsolicited_motion = quiet.get("unsolicited_motion_events")
    if (quiet_duration < 600 or type(unsolicited_speech) is not int
            or type(unsolicited_motion) is not int
            or unsolicited_speech < 0 or unsolicited_motion < 0):
        raise ValueError("Need 600s real quiet-mode speech and motion counts")
    return {
        "quiet_mode_enabled": True,
        "quiet_mode_seconds": quiet_duration,
        "quiet_unsolicited_speech_events": unsolicited_speech,
        "quiet_unsolicited_motion_events": unsolicited_motion,
    }


def evaluate(records: list[dict]) -> dict:
    human, control, quiet = _partition_records(records)
    human_report = _score_human_trials(human)
    _validate_control_setup(human[0], control, quiet)
    echo_report = _echo_control(control)
    quiet_report = _quiet_control(quiet)
    distance_results = human_report["distance_results"]
    return {
        # Bind the result to one measured assembly, not the fleet.
        "robot_id": human[0]["robot_id"],
        "firmware_commit": human[0]["firmware_commit"],
        "audio_config_id": human[0]["audio_config_id"],
        "mic_speaker_placement_id": human[0]["mic_speaker_placement_id"],
        "human_trials": len(human),
        "required_distances_cm": [50, 100],
        "distance_results": distance_results,
        "audible_stops_within_500ms": human_report["audible_stops_within_500ms"],
        "meets_120ms_i2s_cutoff": all(
            band["meets_120ms_i2s_cutoff"] for band in distance_results.values()
        ),
        "new_intents_understood": human_report["new_intents_understood"],
        **echo_report,
        **quiet_report,
        "coverage": human_report["coverage"],
        "meets_proposed_gate": (
            all(b["meets_human_gate"] for b in distance_results.values())
            and echo_report["self_interruptions"] == 0
            and quiet_report["quiet_unsolicited_speech_events"] == 0
            and quiet_report["quiet_unsolicited_motion_events"] == 0
            and all(r["obsolete_audio_never_resumed"] for r in human)
        ),
        "records_are_operator_supplied_not_independently_attested": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    path = parser.parse_args().file
    if not path.is_file() or path.stat().st_size > 200000:
        raise ValueError("Missing or oversized physical audio trial log")
    records = parse_trial_jsonl(path.read_text(encoding="utf-8"))
    print(json.dumps(evaluate(records), indent=2))


if __name__ == "__main__":
    main()
