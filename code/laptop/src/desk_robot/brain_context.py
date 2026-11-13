"""Pure, bounded context composition for the EXISTING Mac pet speech owner.

No model, network, database or hardware here. Pulling prompt assembly out of
PetController prevents separate tools from inventing different notions of
eyewitness, model guesses and remembered words. Inspired by LangGraph's
short-term vs long-term context and Qwen Live Harness's silent tool receipts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Sequence

from .memory import CoreFact, Memory


@dataclass(frozen=True)
class ContextBundle:
    recent: str
    core: str
    interaction: str


def _clean(value: str, *, limit: int) -> str:
    """Single-line untrusted text, never executable instructions or raw media."""
    return " ".join(value.split())[:limit]


def _memory_label(entry: Memory) -> str:
    if entry.kind == "heard_human":
        return "I may have heard (uncertain transcription)"
    if entry.kind == "own_utterance" and entry.witnessed:
        return "I said"
    if entry.kind == "peer_utterance":
        # A peer's words never establish this pet's firsthand observation.
        return (f"I heard {entry.source_robot} say" if not entry.witnessed
                else f"{entry.source_robot} said (peer report, not my sighting)")
    return "I observed" if entry.witnessed else f"{entry.source_robot} reported"


def compose_brain_context(
    recent: Sequence[Memory], core: Sequence[CoreFact],
    timeline: Sequence[dict],
) -> ContextBundle:
    """Format evidence by authority under independent, tight text budgets.

    Sensor edge != optical object, JPEG receipt != actual exposure time,
    local VLM answer != a new eyewitness truth, human text != instructions.
    The LLM may use context for language but may not grant motion/charging.
    """
    seen: set[str] = set()
    memory_parts = []
    for entry in reversed(recent[-6:]):
        if entry.event_id in seen:
            continue
        seen.add(entry.event_id)
        memory_parts.append(
            f"{_memory_label(entry)}: {_clean(entry.summary, limit=110)}"
        )
    recent_text = _clean("; ".join(memory_parts), limit=600)

    core_parts = [
        f"{_clean(item.slot, limit=40)}: {_clean(item.value, limit=120)}"
        for item in core[-6:]
    ]
    core_text = _clean("; ".join(core_parts), limit=500)

    # A speaking head can contribute several JPEG receipts in seconds.
    # Repeating the same cue crowds out touch, completed tool context and
    # conversational continuity. Keep the latest per kind, then budget
    # independent modalities rather than truncating a large camera list.
    cue_parts: list[tuple[int, str]] = []
    seen_cues: set[tuple[str, str]] = set()
    priorities = {
        "tool": 0, "sensor": 1, "human_voice": 2,
        "robot_speech": 3, "camera": 4,
    }
    for item in reversed(timeline[-16:]):
        if not isinstance(item, dict):
            continue
        channel, kind = item.get("channel"), item.get("kind")
        if not isinstance(channel, str) or channel not in priorities:
            continue
        # Group every camera JPEG receipt under one cue, not ten fake new
        # observations; preserve distinct physical sensor event kinds.
        identity = (channel, kind if channel == "sensor"
                    and isinstance(kind, str) else channel)
        if identity in seen_cues:
            continue
        phrase = ""
        if channel == "sensor" and isinstance(kind, str):
            phrase = f"Physical sensor edge: {_clean(kind, limit=40)}"
        elif channel == "human_voice":
            phrase = "Authenticated human voice turn"
        elif channel == "camera":
            phrase = "XIAO frame received (contents not inferred)"
        elif channel == "tool" and kind == "visual_look":
            result = item.get("content")
            if isinstance(result, str) and result.strip():
                phrase = (
                    "Earlier local VLM guess, not fresh sighting: "
                    + _clean(result, limit=90)
                )
        elif channel == "robot_speech" and kind == "own_utterance":
            result = item.get("content")
            if isinstance(result, str) and result.strip():
                phrase = (
                    "I previously sent this spoken line (playback unverified): "
                    + _clean(result, limit=90)
                )
        if phrase:
            seen_cues.add(identity)
            cue_parts.append((priorities[channel], phrase))
    cue_parts.sort(key=lambda candidate: candidate[0])
    selected: list[str] = []
    remaining = 400
    for _, phrase in cue_parts:
        cost = len(phrase) + (2 if selected else 0)
        if cost <= remaining:
            selected.append(phrase)
            remaining -= cost
    interaction = "; ".join(selected)
    return ContextBundle(recent_text, core_text, interaction)



def repeated_spontaneous_line(text: str, recent: Sequence[Memory],
                              *, now_wall: float) -> bool:
    """Suppress a pet repeating itself without running another agent model.

    Only the pet's OWN actually transmitted, recent text matters. Another
    robot's speech or an uncertain user ASR transcript cannot count as this
    pet's previous line. The caller invokes this for unsolicited remarks,
    never for a direct human question or emergency status.
    """
    if not isinstance(text, str):
        return False
    normalized = re.sub(r"\W+", " ", text.casefold()).strip()
    if not normalized:
        return False
    for item in recent:
        if (item.kind != "own_utterance" or not item.witnessed
                or item.source_robot != item.robot_id
                or not 0 <= now_wall - item.observed_at <= 3600):
            continue
        past = re.sub(r"\W+", " ", item.summary.casefold()).strip()
        if normalized == past:
            return True
        if (len(normalized.split()) >= 6 and len(past.split()) >= 6
                and SequenceMatcher(None, normalized, past).ratio() >= 0.91):
            return True
    return False
