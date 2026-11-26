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
    # At most one recent operator topic survives when voluntary peer play
    # starts; it is historical data, never a second active task owner.
    prior_operator_topic: str = ""
    prior_operator_at: float = -math.inf
    prior_operator_state: str = ""
    voice_at: float = -math.inf
    voice_active: bool = False
    human_turns: int = 0
    asr: str = ""
    asr_at: float = -math.inf
    # Ordering fence survives retraction of the associated private text.
    asr_order_at: float = -math.inf
    asr_consent_generation: int | None = None
    last_heard_id: str | None = None
    # One previous ASR fragment, with its original receipt and consent grant.
    # Only a handling interruption can carry it into the next voice epoch.
    interrupted_asr: tuple[str, str, float, int | None] | None = None
    heard_ids: deque[str] = field(default_factory=lambda: deque(maxlen=24))
    sent: str = ""
    sent_at: float = -math.inf
    sensor_edges: deque[tuple[str, float, int]] = field(
        default_factory=lambda: deque(maxlen=6)
    )
    sensor_details: dict[str, str] = field(default_factory=dict)


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
        if origin == "autonomous_social":
            # Social banter may replace the current activity owner, but
            # never silently delete the recent human topic. Only retain a
            # completed/interrupted operator topic within its original
            # continuity window. Active human work requires its own priority
            # lease rather than a silently competing second task owner.
            if (state.topic_origin == "operator"
                    and state.topic_state in {"completed", "interrupted"}
                    and state.topic
                    and 0 <= at - state.topic_updated_at <= 120):
                state.prior_operator_topic = state.topic
                state.prior_operator_at = state.topic_updated_at
                state.prior_operator_state = state.topic_state
        else:
            state.prior_operator_topic = ""
            state.prior_operator_at = -math.inf
            state.prior_operator_state = ""
        state.generation += 1
        state.topic = cleaned
        state.topic_origin = origin
        state.topic_state = "active"
        state.topic_updated_at = at
        # Recent safety and handling observations remain useful when the
        # next human question is "why did you stop?". Carry only factual
        # historical evidence, not routine contacts or source task authority.
        # Keep the ORIGINAL generation so a late callback cannot impersonate
        # a new observation or grant movement.
        carry = [
            edge for edge in state.sensor_edges
            if edge[0] in {"safety_fault", "handling_tilt", "handling_shake"}
            and 0 <= at - edge[1] <= 120
        ]
        state.sensor_edges.clear()
        state.sensor_edges.extend(carry)
        # Details share the lifetime of their corresponding retained edge.
        state.sensor_details = {
            kind: state.sensor_details[kind]
            for kind, _, _ in carry if kind in state.sensor_details
        }
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

    def heard_is_current(self, robot_id: str, at: float) -> bool:
        """Source time must not precede a newer voice start or ASR cue."""
        _clock(at)
        state = self._state(robot_id)
        return at >= max(state.voice_at, state.asr_order_at)

    def human_started(self, robot_id: str, at: float) -> None:
        _clock(at)
        state = self._state(robot_id)
        if at <= state.voice_at:
            return
        state.interrupted_asr = None
        if (state.asr and state.last_heard_id is not None
                and 0 <= at - state.asr_at <= 90
                and any(
                    max(state.voice_at, state.asr_at - 90) <= stamp <= at
                    and (kind in {"handling_tilt", "handling_shake"}
                         or (kind == "safety_fault" and state.sensor_details.get(kind)
                             == "floor_out_of_range_upright_lift"))
                    for kind, stamp, _ in state.sensor_edges
                )):
            state.interrupted_asr = (
                state.last_heard_id, state.asr, state.asr_at, state.asr_consent_generation,
            )
        state.voice_at = at
        state.voice_active = True
        state.human_turns += 1
        # The new human has priority even if their next words are too short
        # for a finished ASR transcript. Do not keep the previous model guess
        # labelled as the current task during that silence.
        if state.asr_at < at:
            state.asr = ""
            state.asr_consent_generation = None
            state.last_heard_id = None

    def human_ended(self, robot_id: str, at: float) -> None:
        _clock(at)
        state = self._state(robot_id)
        if at >= state.voice_at:
            state.voice_active = False

    def heard(
        self, robot_id: str, event_id: str, transcript: str, at: float, *,
        consent_generation: int | None = None,
    ) -> bool:
        """An authenticated model ASR receipt is not an operator instruction."""
        _clock(at)
        state = self._state(robot_id)
        if (not isinstance(event_id, str)
                or re.fullmatch(r"omni_[0-9a-f]{12}_[0-9a-f]{20}", event_id) is None):
            return False
        if (consent_generation is not None
                and (type(consent_generation) is not int or consent_generation < 0)):
            return False
        if event_id in state.heard_ids or not self.heard_is_current(robot_id, at):
            # An old model transcript completing after a newer authenticated
            # VAD start cannot become that newer turn's conversational goal.
            return False
        cleaned = _text(transcript, 90)
        if not cleaned:
            return False
        state.heard_ids.append(event_id)
        state.asr = cleaned
        state.asr_at = at
        state.asr_order_at = at
        state.asr_consent_generation = consent_generation
        state.last_heard_id = event_id
        return True

    def discard_heard(self, robot_id: str, event_id: str) -> bool:
        """Retract matching ASR text, retaining replay and ordering fences."""
        state = self._state(robot_id)
        if not isinstance(event_id, str):
            return False
        if state.interrupted_asr is not None and state.interrupted_asr[0] == event_id:
            state.interrupted_asr = None
            return True
        if state.last_heard_id != event_id:
            return False
        state.asr = ""
        state.asr_at = -math.inf
        state.asr_consent_generation = None
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

    def sensor(
        self, robot_id: str, kind: str, at: float, *, detail: str | None = None,
    ) -> bool:
        """Preserve independent physical evidence during a dialogue or activity."""
        _clock(at)
        state = self._state(robot_id)
        if not isinstance(kind, str) or not re.fullmatch(r"[a-z_]{1,40}", kind):
            return False
        if detail is not None and (
            not isinstance(detail, str)
            or not re.fullmatch(r"[a-z0-9_]{1,64}", detail)
        ):
            detail = None
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
                and state.sensor_edges[-1][2] == state.generation
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
            state.sensor_details.pop(victim[0], None)
        state.sensor_edges.append((kind, at, state.generation))
        if detail is not None:
            state.sensor_details[kind] = detail
        else:
            state.sensor_details.pop(kind, None)
        return True

    def timeline(
        self, robot_id: str, now: float, *,
        live_consent_enabled: bool = True,
        live_consent_generation: int | None = None,
    ) -> list[dict]:
        """One optional, source-labelled context cue with a fixed output cap."""
        _clock(now)
        state = self._state(robot_id)
        pieces: list[str] = []
        # The accepted model transcript belongs to a newer authenticated
        # human voice epoch than the previous topic. It is still uncertain
        # ASR, NEVER a motion command, but must not be masked by old dialogue.
        asr_permitted = (
            live_consent_enabled is True
            and (live_consent_generation is None
                 or state.asr_consent_generation == live_consent_generation)
        )
        newer_asr = (
            asr_permitted and bool(state.asr) and 0 <= now - state.asr_at <= 90
            and state.asr_at > state.topic_updated_at
            and state.asr_at >= state.voice_at
        )
        if newer_asr:
            pieces.append(
                "Newer uncertain ASR words (not verified command): "
                + state.asr[:66]
            )
        if state.interrupted_asr is not None:
            _, fragment, stamp, grant = state.interrupted_asr
            if (live_consent_enabled is True and 0 <= now - stamp <= 90
                    and (live_consent_generation is None or grant == live_consent_generation)):
                pieces.append("Earlier ASR (uncertain context): " + fragment[:40])
        # A voluntary social topic has lower conversational priority than
        # the recent user's completed/interrupted topic. Preserve that fact
        # as attributed past context, never an active instruction or permit.
        if (state.topic_origin == "autonomous_social"
                and state.prior_operator_topic
                and 0 <= now - state.prior_operator_at <= 120):
            pieces.append(
                "Earlier " + state.prior_operator_state
                + " operator topic (historical, no motion authority): "
                + state.prior_operator_topic[:55]
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
        elif (asr_permitted and state.asr
              and 0 <= now - state.asr_at <= 90 and not newer_asr):
            pieces.append(
                "Earlier uncertain ASR words (not verified command): "
                + state.asr[:66]
            )
        # Don't promote a remembered handling event to present sensor status.
        safety_piece: str | None = None
        events = [
            (kind, at) for kind, at, generation in state.sensor_edges
            if 0 <= now - at <= 120 and (
                generation == state.generation
                or (generation < state.generation and kind in {
                    "safety_fault", "handling_tilt", "handling_shake"
                })
            )
        ]
        if events:
            kind, stamp = next(
                ((kind, stamp) for kind, stamp in reversed(events)
                 if kind == "safety_fault"), events[-1]
            )
            detail = state.sensor_details.get(kind)
            description = f"WROOM {kind} edge {int(now - stamp)}s ago"
            if kind == "safety_fault" and detail == "floor_out_of_range_upright_lift":
                description += " (floor out of range; possible lift, not confirmed)"
            elif detail:
                description += f" ({detail[:20]})"
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
            event_piece = description + " (historical, not current telemetry)"
            pieces.append(event_piece)
            if kind == "safety_fault":
                safety_piece = event_piece
        if state.sent and 0 <= now - state.sent_at <= 45:
            pieces.append(
                "Earlier speech transmitted, playback unverified: "
                + state.sent[:45]
            )
        if not pieces:
            return []
        content = "; ".join(pieces)
        if len(content) > 260:
            # Bound every attention timeline, not only explicit safety faults.
            # Keep the freshest human words and the complete historical
            # sensor qualifier ahead of older topic and transmitted speech.
            # Never slice a qualifier into a misleading current observation.
            mandatory = [pieces[0]] if newer_asr else []
            event_to_keep = (
                safety_piece if safety_piece is not None
                else event_piece if events else None
            )
            if event_to_keep is not None:
                mandatory.append(event_to_keep)
                if len("; ".join(mandatory)) > 260:
                    # A secondary sensor edge is optional; the primary event
                    # and its "historical" qualifier are not.
                    primary_event = event_to_keep.split("; also ", 1)[0]
                    if " (historical, not current telemetry)" not in primary_event:
                        primary_event += " (historical, not current telemetry)"
                    mandatory[-1] = primary_event
            for optional in pieces:
                if (optional == event_to_keep
                        or (newer_asr and optional == pieces[0])):
                    continue
                candidate = "; ".join([*mandatory, optional])
                if len(candidate) <= 260:
                    mandatory.append(optional)
            content = "; ".join(mandatory)
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
        # Retraction is not a new VAD epoch. Preserve only bounded opaque
        # receipt identities and ordering metadata, never the private words.
        self._robots[robot_id] = _Attention(
            generation=prior.generation + 1,
            voice_at=prior.voice_at,
            asr_order_at=prior.asr_order_at,
            heard_ids=deque(prior.heard_ids, maxlen=prior.heard_ids.maxlen),
        )
