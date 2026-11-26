"""Pure admission and settlement for optional OLED cues, not an emotion model."""
from __future__ import annotations

from dataclasses import dataclass

from .initiative_policy import cooldown_pending

_MODEL_MOODS = frozenset({"neutral", "happy", "thinking", "surprised"})


def model_mood_event(mood: object) -> str | None:
    """Accept only an explicit model-selected cosmetic expression."""
    if type(mood) is str and mood in _MODEL_MOODS:
        return "mood:" + mood
    return None


@dataclass(frozen=True, slots=True)
class FaceCueReservation:
    at: float
    previous_cue_at: float

    def settled_cue_at(self, current_cue_at: float, *, acknowledged: bool) -> float:
        """Undo only our own unacknowledged reservation, never a newer one."""
        if not acknowledged and current_cue_at == self.at:
            return self.previous_cue_at
        return current_cue_at


def reserve_face_cue(
    now: float, *, last_cue_at: float, last_attempt_at: float,
    cooldown_s: float, retry_s: float,
) -> FaceCueReservation | None:
    """Reserve both budgets; failed sends still consume the attempt budget."""
    if (cooldown_pending(now=now, last=last_cue_at, interval=cooldown_s)
            or cooldown_pending(now=now, last=last_attempt_at, interval=retry_s)):
        return None
    return FaceCueReservation(at=now, previous_cue_at=last_cue_at)
