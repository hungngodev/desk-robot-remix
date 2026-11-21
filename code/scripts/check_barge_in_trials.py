"""Check measured live Xiaozhi interruptions, not synthetic audio success claims."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def _number(value: object, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"Missing or invalid measured {label}")
    return float(value)


def evaluate(records: list[dict]) -> dict:
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise ValueError("Trial log must contain objects")
    human = [r for r in records if r.get("kind") == "human"]
    alone = [r for r in records if r.get("kind") == "robot_only"]
    if len(human) != 20 or len(alone) != 1 or len(records) != 21:
        raise ValueError("Need exactly 20 human interruptions and one robot-only trial")
    ids = [r.get("id") for r in human]
    if (any(type(x) is not str or not 1 <= len(x) <= 64 for x in ids)
            or len(set(ids)) != 20):
        raise ValueError("Need unique nonempty human trial IDs")

    on_time = 0
    understood = 0
    volumes, positions, loads, speakers, turns = set(), set(), set(), set(), set()
    firmware_revisions, audio_configs, placements, robot_ids = (
        set(), set(), set(), set()
    )
    for r in human:
        volume = r.get("volume")
        if volume not in ("low", "medium", "high"):
            raise ValueError("Record low, medium and high intended speaker volumes")
        volumes.add(volume)

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
        if type(turn) is not int or not 1 <= turn <= 100:
            raise ValueError("Record numbered consecutive conversation turns")
        positions.add(position)
        loads.add(load)
        speakers.add(speaker)
        turns.add(turn)

        # These fields distinguish measured acoustic success from a synthetic
        # stopwatch-only result. All timestamps share one monotonic timebase.
        stage_names = (
            "human_onset_ms", "vad_arrival_ms", "abort_dispatch_ms",
            "head_queue_clear_ms", "i2s_stop_ms", "audible_stop_ms",
        )
        stages = [_number(r.get(name), name) for name in stage_names]
        if any(later < earlier for earlier, later in zip(stages, stages[1:], strict=False)):
            raise ValueError("Audio stop stage timestamps are not monotonic")
        distance = _number(r.get("speaker_distance_cm"), "speaker distance")
        noise = _number(r.get("room_noise_db_a"), "room background noise")
        if not 45 <= distance <= 55 or not 0 <= noise <= 100:
            raise ValueError("Record 50 cm speaking distance and measured room noise")

        for label in (
            "firmware_commit", "audio_config_id", "mic_speaker_placement_id",
            "robot_id",
        ):
            value = r.get(label)
            if type(value) is not str or not value.strip() or len(value) > 128:
                raise ValueError(f"Missing physical trial provenance: {label}")
        firmware_revisions.add(r["firmware_commit"])
        audio_configs.add(r["audio_config_id"])
        placements.add(r["mic_speaker_placement_id"])
        robot_ids.add(r["robot_id"])
        captured = r.get("new_utterance_captured")
        correct = r.get("new_intent_correct")
        beginning = r.get("utterance_beginning_intelligible")
        no_replay = r.get("obsolete_audio_never_resumed")
        if any(type(value) is not bool for value in (
                captured, correct, beginning, no_replay)):
            raise ValueError("Record speech, start-of-utterance and replay evidence")
        if correct and not (captured and beginning):
            raise ValueError("Correct intent requires captured intelligible utterance start")
        on_time += stages[-1] - stages[0] <= 500
        understood += captured and correct and beginning and no_replay

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

    # A single acceptance result must not mix different firmware builds,
    # AEC settings or microphone/speaker geometry across its twenty trials.
    # Those require separate complete acoustic trial sets.
    if any(len(values) != 1 for values in (
            firmware_revisions, audio_configs, placements, robot_ids)):
        raise ValueError("Do not mix firmware, audio config or physical mounting trials")

    control = alone[0]
    # The ten-minute echo-only control must run on the SAME robot and
    # flashed AEC setup as the human barge trials, not a quieter second unit.
    for field in (
        "robot_id", "firmware_commit", "audio_config_id",
        "mic_speaker_placement_id",
    ):
        if control.get(field) != human[0][field]:
            raise ValueError(
                "Robot-only control must use the same robot and setup as human trials"
            )
    duration = _number(control.get("duration_seconds"), "robot-only duration")
    echoes = control.get("self_interruptions")
    if duration < 600 or type(echoes) is not int or echoes < 0:
        raise ValueError("Need 600s real robot-only control and self-interrupt count")
    return {
        # Bind the result to the one measured assembly; never present a
        # twenty-trial pass as a generic fleet or firmware certification.
        "robot_id": human[0]["robot_id"],
        "firmware_commit": human[0]["firmware_commit"],
        "audio_config_id": human[0]["audio_config_id"],
        "mic_speaker_placement_id": human[0]["mic_speaker_placement_id"],
        "human_trials": 20,
        "audible_stops_within_500ms": on_time,
        "new_intents_understood": understood,
        "robot_only_seconds": duration,
        "self_interruptions": echoes,
        "coverage": {
            "speaker_volumes": sorted(volumes),
            "interruption_positions": sorted(positions),
            "load_profiles": sorted(loads),
            "human_speakers": len(speakers),
            "conversation_turns": sorted(turns),
        },
        "meets_proposed_gate": (
            on_time >= 19 and understood >= 18 and echoes == 0
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
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    print(json.dumps(evaluate(records), indent=2))


if __name__ == "__main__":
    main()
