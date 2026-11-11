"""Check measured live Xiaozhi interruptions, not a synthetic audio success claim."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def evaluate(records: list[dict]) -> dict:
    human = [r for r in records if r.get("kind") == "human"]
    alone = [r for r in records if r.get("kind") == "robot_only"]
    if len(human) != 20 or len(alone) != 1:
        raise ValueError("Need exactly 20 human interruptions and one robot-only trial")
    ids = [r.get("id") for r in human]
    if (any(type(x) is not str or not 1 <= len(x) <= 64 for x in ids)
            or len(set(ids)) != 20):
        raise ValueError("Need unique nonempty human trial IDs")
    on_time = 0
    understood = 0
    volumes = set()
    for r in human:
        volume = r.get("volume")
        if volume not in ("low", "medium", "high"):
            raise ValueError("Record low, medium and high speaker volumes")
        volumes.add(volume)
        start, end = r.get("human_onset_ms"), r.get("audible_stop_ms")
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end) or end < start):
            raise ValueError("Need physically measured human onset and audible stop times")
        captured, correct = r.get("new_utterance_captured"), r.get("new_intent_correct")
        if type(captured) is not bool or type(correct) is not bool:
            raise ValueError("Record measured captured speech and intent correctness")
        if correct and not captured:
            raise ValueError("New intent cannot be correct when audio was not captured")
        on_time += end - start <= 500
        understood += captured and correct
    if volumes != {"low", "medium", "high"}:
        raise ValueError("Human trials must cover all three speaker volumes")
    control = alone[0]
    duration, echoes = control.get("duration_seconds"), control.get("self_interruptions")
    if (type(duration) not in (float, int) or not math.isfinite(duration)
            or duration < 600 or type(echoes) is not int or echoes < 0):
        raise ValueError("Need 600s real robot-only control and self-interrupt count")
    return {
        "human_trials": 20,
        "audible_stops_within_500ms": on_time,
        "new_intents_understood": understood,
        "robot_only_seconds": duration,
        "self_interruptions": echoes,
        "meets_proposed_gate": on_time >= 19 and understood >= 18 and echoes == 0,
        "records_are_operator_supplied_not_independently_attested": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    path = parser.parse_args().file
    if not path.is_file() or path.stat().st_size > 200000:
        raise ValueError("Missing or oversized physical audio trial log")
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in records):
        raise ValueError("Every trial must be an object")
    print(json.dumps(evaluate(records), indent=2))


if __name__ == "__main__":
    main()
