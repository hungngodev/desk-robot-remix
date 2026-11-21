"""Bounded volatile conversational attention, not another agent or safety controller.

The existing Mac Runtime owns this small ledger. Only real Coordinator jobs may
authorize physical activity, and only existing Xiaozhi transports own speech.
Here we associate conversation, sent text and sensor edges in time so an LLM
can decide whether a cue matters without a compulsory canned reaction.
"""
from __future__ import annotations

import math
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Sequence


def _clock(value: float) -> None:
    if type(value) not in (int, float):
        raise ValueError("Attention timestamp must be finite and monotonic")
    # Every ledger event is a LOCAL Mac monotonic receipt, never a device
    # timestamp. A forged future start would prevent genuine later VAD/ASR
    # and speaker receipts from advancing the current conversational state.
    # Huge integers must be rejected rather than escaping as OverflowError.
    try:
        seconds = float(value)
    except OverflowError as exc:
        raise ValueError("Attention timestamp must be finite and monotonic") from exc
    if (not math.isfinite(seconds) or seconds < 0
            or seconds > time.monotonic() + 1):
        raise ValueError("Attention timestamp must be finite and monotonic")


def _text(value: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError("Attention text must be a string")
    return " ".join(value.split())[:max_length]


@dataclass
class _Attention:
    generation: int = 0
    topic: str = ""
    topic_origin: str = "operator"
    topic_state: str = "none"
    topic_updated_at: float = 0
    voice_at: float = -math.inf
    voice_active: bool = False
    human_turns: int = 0
    asr: str = ""
    asr_at: float = -math.inf
    last_heard_id: str | None = None
    heard_ids: deque[str] = field(default_factory=lambda: deque(maxlen=24))
    sent: str = ""
    sent_at: float = -math.inf
    sensor_edges: deque[tuple[str, float, int]] = field(
        default_factory=lambda: deque(maxlen=6)
    )


class AttentionLedger:
    """One in-memory state per pet, no raw media or model-derived motor intent.

    Source labels and original timestamps survive synthesis; this is not a
    new model or microphone owner. A sensor edge is *coincident with* an
    activity, not automatically relevant, frightening or worth speaking about.
    """

    def __init__(self, robot_ids: Sequence[str]):
        if not robot_ids or len(set(robot_ids)) != len(robot_ids):
            raise ValueError("Attention requires unique robot identities")
        self._robots = {robot_id: _Attention() for robot_id in robot_ids}

    def _state(self, robot_id: str) -> _Attention:
        return self._robots[robot_id]

    def begin_topic(
        self, robot_id: str, topic: str, at: float, *,
        origin: str = "operator",
    ) -> int:
        """Record a real Mac Conversation.run topic, never a motion command."""
        _clock(at)
        if type(origin) is not str or origin not in {"operator", "autonomous_social"}:
            raise ValueError("Unsupported conversation origin")
        cleaned = _text(topic, 100)
        if not cleaned:
            raise ValueError("Empty conversation topic")
        state = self._state(robot_id)
        # Late or duplicated topic callbacks cannot steal the current Mac
        # activity owner or erase its live sensor evidence.
        if state.generation > 0 and at <= state.topic_updated_at:
            raise ValueError("Topic start must follow prior topic activity")
        state.generation += 1
        state.topic = cleaned
        state.topic_origin = origin
        state.topic_state = "active"
        state.topic_updated_at = at
        # Events from an earlier task cannot impersonate current task context.
        state.sensor_edges.clear()
        return state.generation

    def finish_topic(
        self, robot_id: str, generation: int, at: float, *, interrupted: bool
    ) -> bool:
        _clock(at)
        if type(interrupted) is not bool:
            raise ValueError("Topic interruption status must be boolean")
        state = self._state(robot_id)
        if (type(generation) is not int
                or state.generation != generation
                or state.topic_state != "active"
                or at < state.topic_updated_at):
            return False
        state.topic_state = "interrupted" if interrupted else "completed"
        state.topic_updated_at = at
        return True

    def human_started(self, robot_id: str, at: float) -> None:
        _clock(at)
        state = self._state(robot_id)
        if at <= state.voice_at:
            return
        state.voice_at = at
        state.voice_active = True
        state.human_turns += 1

    def human_ended(self, robot_id: str, at: float) -> None:
        _clock(at)
        state = self._state(robot_id)
        if at >= state.voice_at:
            state.voice_active = False

    def heard(self, robot_id: str, event_id: str, transcript: str, at: float) -> bool:
        """An authenticated model ASR receipt is not an operator instruction."""
        _clock(at)
        state = self._state(robot_id)
        if (not isinstance(event_id, str)
                or re.fullmatch(r"omni_[0-9a-f]{12}_[0-9a-f]{20}", event_id) is None):
            return False
        if event_id in state.heard_ids or at < max(state.asr_at, state.voice_at):
            # An old model transcript completing after a newer authenticated
            # VAD start cannot become that newer turn's conversational goal.
            return False
        cleaned = _text(transcript, 90)
        if not cleaned:
            return False
        state.heard_ids.append(event_id)
        state.asr = cleaned
        state.asr_at = at
        state.last_heard_id = event_id
        return True

    def discard_heard(self, robot_id: str, event_id: str) -> bool:
        """Retract only a matching model ASR cue, retaining replay dedup."""
        state = self._state(robot_id)
        if not isinstance(event_id, str) or state.last_heard_id != event_id:
            return False
        state.asr = ""
        state.asr_at = -math.inf
        state.last_heard_id = None
        return True

    def sent(self, robot_id: str, text: str, at: float) -> bool:
        """Only *transmitted* model text, never physical playback confirmation."""
        _clock(at)
        state = self._state(robot_id)
        # Late previous-topic events cannot enter the new generation.
        if (state.topic_state == "active" and at < state.topic_updated_at):
            return False
        if at < max(state.sent_at, state.voice_at):
            # Late old speech must not reappear after new human barge.
            return False
        cleaned = _text(text, 75)
        if not cleaned:
            return False
        state.sent, state.sent_at = cleaned, at
        return True

    def sensor(self, robot_id: str, kind: str, at: float) -> bool:
        """Preserve independent physical evidence during a dialogue or activity."""
        _clock(at)
        state = self._state(robot_id)
        if not isinstance(kind, str) or not re.fullmatch(r"[a-z_]{1,40}", kind):
            return False
        if (state.topic_state == "active"
                and at < state.topic_updated_at):
            # An old queued callback cannot become fresh context for a new goal.
            return False
        if (state.topic_state != "active"
                and not 0 <= at - max(state.asr_at, state.sent_at) <= 120):
            return False
        if state.sensor_edges and at < state.sensor_edges[-1][1]:
            return False
        if (state.sensor_edges and state.sensor_edges[-1][0] == kind
                and at - state.sensor_edges[-1][1] < 2.0):
            # Suppress duplicate callbacks during the same short physical
            # interaction, not every subsequent authentic touch of that kind.
            # A later contact remains optional context, never forced speech.
            return False
        # Repeated low-value gestures must not evict the one meaningful
        # handling or local safety cue during a longer conversation.
        previous = next(
            (edge for edge in state.sensor_edges if edge[0] == kind), None
        )
        if previous is not None:
            state.sensor_edges.remove(previous)
        if len(state.sensor_edges) == state.sensor_edges.maxlen:
            protected = {"safety_fault", "handling_tilt", "handling_shake", "side_object"}
            victim = next(
                (edge for edge in state.sensor_edges if edge[0] not in protected),
                state.sensor_edges[0],
            )
            state.sensor_edges.remove(victim)
        state.sensor_edges.append((kind, at, state.generation))
        return True

    def timeline(self, robot_id: str, now: float) -> list[dict]:
        """One optional, source-labelled context cue with a fixed output cap."""
        _clock(now)
        state = self._state(robot_id)
        pieces: list[str] = []
        # The accepted model transcript belongs to a newer authenticated
        # human voice epoch than the previous topic. It is still uncertain
        # ASR, NEVER a motion command, but must not be masked by old dialogue.
        newer_asr = (
            bool(state.asr) and 0 <= now - state.asr_at <= 90
            and state.asr_at > state.topic_updated_at
            and state.asr_at >= state.voice_at
        )
        if newer_asr:
            pieces.append(
                "Newer uncertain ASR words (not verified command): "
                + state.asr[:66]
            )
        if (state.topic and
                (state.topic_state == "active" or
                 0 <= now - state.topic_updated_at <= 120)):
            label = (
                "Ongoing conversation topic"
                if state.topic_state == "active" and not newer_asr
                else "Earlier " + state.topic_state + " conversation"
            )
            qualifier = (
                "not motion permission"
                if state.topic_origin == "operator"
                else "autonomous peer topic, not an operator command"
            )
            pieces.append(f"{label} ({qualifier}): {state.topic[:72]}")
        elif state.asr and 0 <= now - state.asr_at <= 90 and not newer_asr:
            pieces.append(
                "Earlier uncertain ASR words (not verified command): "
                + state.asr[:66]
            )
        # Don't promote a remembered handling event to present sensor status.
        events = [
            (kind, at) for kind, at, generation in state.sensor_edges
            if generation == state.generation and 0 <= now - at <= 120
        ]
        if events:
            kind, stamp = next(
                ((kind, stamp) for kind, stamp in reversed(events)
                 if kind == "safety_fault"), events[-1]
            )
            description = f"WROOM {kind} edge {int(now - stamp)}s ago"
            # Preserve a handling cue over a flood of routine touch, but
            # never infer a scripted emotion or a physical command from it.
            another = next(
                ((name, observed) for name, observed in reversed(events)
                 if name in {"handling_tilt", "handling_shake"} and name != kind),
                None,
            )
            if another is None:
                another = next(
                    ((name, observed) for name, observed in reversed(events)
                     if name != kind), None
                )
            if another is not None:
                description += (
                    f"; also {another[0]} {int(now - another[1])}s ago"
                )
            pieces.append(description + " (historical, not current telemetry)")
        if state.sent and 0 <= now - state.sent_at <= 45:
            pieces.append(
                "Earlier speech transmitted, playback unverified: "
                + state.sent[:45]
            )
        if not pieces:
            return []
        content = "; ".join(pieces)[:260]
        return [{
            "channel": "mac_attention",
            "kind": "conversation_continuity",
            "source": "mac_volatile_attention",
            "content": content,
            "untrusted_text_not_instructions": True,
            "motor_authorized": False,
            "physical_action_verified": False,
        }]

    def clear(self, robot_id: str) -> None:
        # Drop private transient context while preserving an ever-increasing
        # activity lease. An old completion must never match a new topic after
        # an operator reset, consent revoke or optional ledger failure.
        prior = self._state(robot_id)
        self._robots[robot_id] = _Attention(generation=prior.generation + 1)
