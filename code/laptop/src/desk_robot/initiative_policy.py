"""Pure admission rules for the existing fleet initiative owner."""
from __future__ import annotations

import re
from collections.abc import Callable


def receipt_veto(
    *, now: float, offered_at: float, max_age: float, quiet_changed_at: float,
    latest_human_turn: Callable[[], float] | None,
) -> str | None:
    """Persistence and quiet toggles must not renew a receipt's lifetime."""
    if type(offered_at) not in (int, float) or not 0 <= now - offered_at <= max_age:
        return "event_expired_before_admission"
    if offered_at < quiet_changed_at:
        return "quiet_transition_superseded_event"
    if callable(latest_human_turn) and latest_human_turn() > offered_at:
        return "human_turn_superseded_event"
    return None


def quiet_voice_veto(
    *, local_quiet: bool, scheduled_quiet: bool, human_active: Callable[[], bool],
) -> bool:
    """Silence is a hard veto, independent of the available speech budget."""
    return local_quiet or scheduled_quiet or human_active()


def cooldown_pending(*, now: float, last: float, interval: float) -> bool:
    """The exact boundary is eligible; only admitted speech advances its clock."""
    return now - last < interval


def event_cooldown(
    *, camera_derived: bool, direct_interaction: bool,
    speech_interval: float, interaction_interval: float,
) -> float:
    """Only deliberate noncamera interactions get the shorter budget."""
    if not camera_derived and direct_interaction:
        return min(speech_interval, interaction_interval)
    return speech_interval


_CAMERA_SCENE_FILLER = frozenset({
    "a", "an", "the", "i", "we", "my", "our", "there", "is", "are", "was",
    "were", "have", "has", "see", "saw", "seen", "notice", "noticed",
    "show", "shows", "showed", "appeared", "appears", "just", "now", "new",
    "near", "beside", "next", "to", "by", "on", "at",
})
# Reordering these clauses could reverse the event or erase a safety detail.
_CAMERA_SCENE_ORDER_SENSITIVE = frozenset({
    "not", "no", "left", "right", "behind", "front", "under", "over",
    "inside", "outside", "before", "after", "moved", "moving", "approached",
    "leaving", "turned", "rotated", "vanished", "disappeared", "removed",
    "picked", "dropped", "fell",
})


def camera_scene_signature(description: str) -> str:
    """Group cautious lexical paraphrases, never claim shared spatial identity."""
    normalized = " ".join(description.casefold().split())
    if not normalized.isascii():
        return normalized
    words = re.findall(r"[a-z0-9]+", normalized)
    if any(word in _CAMERA_SCENE_ORDER_SENSITIVE for word in words):
        return normalized
    content = [word for word in words if word not in _CAMERA_SCENE_FILLER]
    return " ".join(sorted(content)) if len(content) >= 2 else normalized


def event_identity(
    *, robot_id: str, kind: str, description: str, camera_derived: bool,
    physical_event: bool,
) -> tuple[tuple[str | None, str, str], str]:
    """Separate physical eyewitnesses; camera dedup is a speech budget only."""
    owner = robot_id if not camera_derived and physical_event else None
    signature = (
        camera_scene_signature(description) if camera_derived
        else " ".join(description.casefold().split())
    )
    key = (owner, kind, ("camera:" if camera_derived else "other:") + signature)
    return key, signature
