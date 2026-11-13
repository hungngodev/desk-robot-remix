"""Pure, bounded context composition for the EXISTING Mac pet speech owner.

No model, network, database or hardware here. Pulling prompt assembly out of
PetController prevents separate tools from inventing different notions of
eyewitness, model guesses and remembered words. Inspired by LangGraph's
short-term vs long-term context and Qwen Live Harness's silent tool receipts.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Sequence
import re

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
    if entry.kind == "peer_utterance" and not entry.witnessed:
        return f"I heard {entry.source_robot} say"
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

    cue_parts = []
    for item in timeline[-10:]:
        if not isinstance(item, dict):
            continue
        channel, kind = item.get("channel"), item.get("kind")
        if channel == "sensor" and isinstance(kind, str):
            cue_parts.append(f"Physical sensor edge: {_clean(kind, limit=40)}")
        elif channel == "human_voice":
            cue_parts.append("Authenticated human voice turn")
        elif channel == "camera":
            # A frame receipt does NOT assert anything visible in that photo.
            cue_parts.append("XIAO frame received (contents not inferred)")
        elif channel == "tool" and kind == "visual_look":
            result = item.get("content")
            if isinstance(result, str) and result.strip():
                cue_parts.append(
                    "Earlier local VLM guess, not fresh sighting: "
                    + _clean(result, limit=120)
                )
        elif channel == "robot_speech" and kind == "own_utterance":
            result = item.get("content")
            if isinstance(result, str) and result.strip():
                cue_parts.append(
                    "I previously sent this spoken line (playback unverified): "
                    + _clean(result, limit=120)
                )
    interaction = _clean("; ".join(cue_parts), limit=400)
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
