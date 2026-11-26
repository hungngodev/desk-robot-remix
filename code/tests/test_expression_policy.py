"""Pure OLED cue policy, independent of transport and speech ownership."""
from dataclasses import FrozenInstanceError

import pytest
from desk_robot.expression_policy import model_mood_event, reserve_face_cue


@pytest.mark.parametrize("mood", ["neutral", "happy", "thinking", "surprised"])
def test_model_mood_event(mood: str) -> None:
    assert model_mood_event(mood) == "mood:" + mood


@pytest.mark.parametrize("mood", [None, True, 1, {}, [], "none", "Happy", "mood:drive"])
def test_model_mood_rejects_untrusted_values(mood: object) -> None:
    assert model_mood_event(mood) is None


@pytest.mark.parametrize(("cooldown_s", "retry_s"), [(4.0, 1.0), (10.0, 2.0)])
def test_cue_budget_exact_boundaries(cooldown_s: float, retry_s: float) -> None:
    now = 100.0
    assert reserve_face_cue(
        now, last_cue_at=now - cooldown_s + 0.01, last_attempt_at=float("-inf"),
        cooldown_s=cooldown_s, retry_s=retry_s,
    ) is None
    assert reserve_face_cue(
        now, last_cue_at=float("-inf"), last_attempt_at=now - retry_s + 0.01,
        cooldown_s=cooldown_s, retry_s=retry_s,
    ) is None
    reservation = reserve_face_cue(
        now, last_cue_at=now - cooldown_s, last_attempt_at=now - retry_s,
        cooldown_s=cooldown_s, retry_s=retry_s,
    )
    assert reservation is not None
    assert reservation.at == now
    assert reservation.previous_cue_at == now - cooldown_s
    with pytest.raises(FrozenInstanceError):
        reservation.at = 0.0


def test_settlement_preserves_ack_and_newer_reservation() -> None:
    reservation = reserve_face_cue(
        100.0, last_cue_at=float("-inf"), last_attempt_at=float("-inf"),
        cooldown_s=4.0, retry_s=1.0,
    )
    assert reservation is not None
    assert reservation.settled_cue_at(100.0, acknowledged=True) == 100.0
    assert reservation.settled_cue_at(100.0, acknowledged=False) == float("-inf")
    assert reservation.settled_cue_at(101.0, acknowledged=False) == 101.0
    assert reserve_face_cue(
        100.5, last_cue_at=reservation.previous_cue_at, last_attempt_at=reservation.at,
        cooldown_s=4.0, retry_s=1.0,
    ) is None


@pytest.mark.parametrize(("last_cue", "last_attempt"), [
    (1000.0, float("-inf")), (float("-inf"), 1000.0), (1000.0, 1000.0),
])
def test_obsolete_epoch_does_not_freeze_cosmetic_cues(last_cue, last_attempt):
    reservation = reserve_face_cue(
        10.0, last_cue_at=last_cue, last_attempt_at=last_attempt,
        cooldown_s=4.0, retry_s=1.0,
    )
    assert reservation is not None
    assert reserve_face_cue(
        10.5, last_cue_at=reservation.at, last_attempt_at=reservation.at,
        cooldown_s=4.0, retry_s=1.0,
    ) is None
