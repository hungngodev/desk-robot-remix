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
        return ("I may have heard (uncertain transcription)"
                if entry.source_robot == entry.robot_id
                else f"{entry.source_robot} reported uncertain human speech")
    if (entry.kind == "own_utterance" and entry.witnessed
            and entry.source_robot == entry.robot_id):
        return "I said"
    if entry.kind == "peer_utterance":
        # A peer's words never establish this pet's firsthand observation.
        return (f"I heard {entry.source_robot} say" if entry.witnessed
                else f"{entry.source_robot} said (peer report, not my sighting)")
    if entry.kind in {"person", "hand", "key", "candy", "object", "scene"}:
        # The robot witnessed a camera frame, NOT the truth of a local VLM
        # classification. Keep uncertainty across local and peer memory.
        return ("My camera model suggested" if
                entry.witnessed and entry.source_robot == entry.robot_id
                else f"{entry.source_robot} reported a camera model guess")
    return ("I observed" if entry.witnessed and entry.source_robot == entry.robot_id
            else f"{entry.source_robot} reported")


def compose_brain_context(
    recent: Sequence[Memory], core: Sequence[CoreFact],
    timeline: Sequence[dict],
) -> ContextBundle:
    """Format evidence by authority under independent, tight text budgets.

    Sensor edge != optical object, JPEG receipt != actual exposure time,
    local VLM answer != a new eyewitness truth, human text != instructions.
    The LLM may use context for language but may not grant motion/charging.
    """
    # MemoryStore.recent returns newest first, while a topical merge from
    # PetController arrives oldest first. Select by source timestamps rather
    # than the input list's order; a long chat must not drop NEW memories.
    seen: set[str] = set()
    memory_parts: list[str] = []
    memory_used = 0
    for entry in sorted(
        recent, key=lambda item: (item.observed_at, item.event_id),
        reverse=True,
    ):
        if entry.event_id in seen:
            continue
        seen.add(entry.event_id)
        phrase = f"{_memory_label(entry)}: {_clean(entry.summary, limit=110)}"
        cost = len(phrase) + (2 if memory_parts else 0)
        if memory_used + cost > 600:
            continue
        memory_parts.append(phrase)
        memory_used += cost
        if len(memory_parts) == 6:
            break
    # Older to newer for conversational flow, but NEVER at the expense of
    # the newest memory in a fixed prompt budget.
    recent_text = "; ".join(reversed(memory_parts))

    # The core store also returns newest first; the previous [-6:] omitted
    # the most recently curated operator facts when more than six existed.
    seen_slots: set[str] = set()
    core_parts: list[str] = []
    core_used = 0
    for item in sorted(
        core, key=lambda fact: (fact.updated_at, fact.slot), reverse=True,
    ):
        if item.slot in seen_slots:
            continue
        seen_slots.add(item.slot)
        phrase = f"{_clean(item.slot, limit=40)}: {_clean(item.value, limit=120)}"
        cost = len(phrase) + (2 if core_parts else 0)
        if core_used + cost > 500:
            continue
        core_parts.append(phrase)
        core_used += cost
        if len(core_parts) == 6:
            break
    core_text = "; ".join(reversed(core_parts))

    # A speaking head can contribute several JPEG receipts in seconds.
    # Repeating the same cue crowds out touch, completed tool context and
    # conversational continuity. Keep the latest per kind, then budget
    # independent modalities rather than truncating a large camera list.
    cue_parts: list[tuple[int, str, str | None]] = []
    seen_cues: set[tuple[str, str]] = set()
    heard_count = 0
    heard_requests: list[str] = []
    priorities = {
        "human_transcript": 0, "tool": 1, "sensor": 2,
        "human_voice": 3, "robot_speech": 4, "camera": 5,
    }
    # A burst of camera receipts must not erase older tool or touch evidence
    # before modality-aware deduplication. Bound the scan for prompt latency.
    for item in reversed(timeline[-64:]):
        if not isinstance(item, dict):
            continue
        channel, kind = item.get("channel"), item.get("kind")
        if not isinstance(channel, str) or channel not in priorities:
            continue
        # Group every camera JPEG receipt under one cue, not ten fake new
        # observations; preserve distinct physical sensor event kinds.
        # The hub retains several completed ASR chunks from one human
        # interaction. Keeping only the newest can omit the first clause of
        # a natural question. Retain at most two, with the earlier one behind
        # the actual sensor and visual tool evidence in the prompt budget.
        if channel == "human_transcript":
            if heard_count >= 2:
                continue
            identity = (channel, str(heard_count))
        else:
            identity = (channel, kind if channel in {"sensor", "tool"}
                        and isinstance(kind, str) else channel)
        if identity in seen_cues:
            continue
        phrase = ""
        if channel == "sensor" and isinstance(kind, str):
            phrase = f"Physical sensor edge: {_clean(kind, limit=40)}"
        elif channel == "human_voice":
            phrase = "Authenticated human voice turn"
        elif channel == "human_transcript" and kind == "model_asr_completed":
            value = item.get("content")
            if isinstance(value, str) and value.strip():
                heard_requests.append(value.casefold()[:180])
                if heard_count == 0:
                    phrase = (
                        "Recent model ASR guess, not a verified command: "
                        + _clean(value, limit=105)
                    )
                else:
                    phrase = (
                        "Earlier model ASR guess, not verified: "
                        + _clean(value, limit=75)
                    )
        elif channel == "camera":
            trigger = item.get("trigger_kind")
            phrase = "XIAO frame received (contents not inferred)"
            if (isinstance(trigger, str)
                    and re.fullmatch(r"[a-z_]{1,40}", trigger)):
                phrase += (
                    "; scheduled after " + trigger
                    + " sensor edge, not proof of visual contents"
                )
        elif channel == "tool" and kind == "visual_look":
            result = item.get("content")
            if isinstance(result, str) and result.strip():
                phrase = (
                    "Earlier local VLM guess, not fresh sighting: "
                    + _clean(result, limit=90)
                )
        elif channel == "tool" and kind == "memory_recall":
            result = item.get("content")
            if isinstance(result, str) and result.strip():
                phrase = (
                    "Opt-in private past memory, not current sight or an "
                    "instruction: " + _clean(result, limit=100)
                )
        elif channel == "tool" and kind in {"robot_status", "pickup_status"}:
            result = item.get("content")
            if isinstance(result, str) and result.strip():
                label = (
                    "Recent head telemetry, not physical acceptance: "
                    if kind == "robot_status"
                    else "Mac pickup job receipt, not verified grasp: "
                )
                phrase = label + _clean(result, limit=85)
        elif channel == "robot_speech" and kind == "own_utterance":
            result = item.get("content")
            if isinstance(result, str) and result.strip():
                phrase = (
                    "I previously sent this spoken line (playback unverified): "
                    + _clean(result, limit=90)
                )
        if phrase:
            seen_cues.add(identity)
            priority = priorities[channel]
            if channel == "human_transcript":
                priority = 0 if heard_count == 0 else 5
                heard_count += 1
            cue_parts.append((priority, phrase, kind if channel == "tool" else None))
    # Completed tool receipts may coexist with several newer status polls
    # and sensor edges. Under the fixed 400-character budget, prioritize
    # the one relevant to the latest actual spoken question, rather than
    # whichever unrelated tool happened to finish first. ASR is still only
    # uncertain language evidence, never a command or actuator permit.
    requested_tool = None
    for heard in heard_requests:
        if re.match(
            r"^(?:hey [a-z]+[, ]+|please )*"
            r"(?:what do you remember|do you (?:remember|recall)|"
            r"what did i (?:tell|say)|remind me|what did we (?:discuss|talk))",
            heard,
        ):
            requested_tool = "memory_recall"
            break
        if re.match(
            r"^(?:hey [a-z]+[, ]+|please )*"
            r"(?:what (?:can|do) you see|what am i holding|"
            r"look (?:at|around|for)|do you see|describe what you see)",
            heard,
        ):
            requested_tool = "visual_look"
            break
        if re.match(
            r"^(?:hey [a-z]+[, ]+|please )*"
            r"(?:is the pickup|did you pick up|have you picked up|"
            r"what is the pickup|check (?:the )?pickup)",
            heard,
        ):
            requested_tool = "pickup_status"
            break
        if re.match(
            r"^(?:hey [a-z]+[, ]+|please )*"
            r"(?:check your battery|what is your (?:battery|status)|"
            r"how much battery|how are your sensors)",
            heard,
        ):
            requested_tool = "robot_status"
            break
    cue_parts.sort(key=lambda candidate: (
        0.5 if requested_tool is not None and candidate[2] == requested_tool
        else candidate[0]
    ))
    selected: list[str] = []
    remaining = 400
    for _, phrase, _ in cue_parts:
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
