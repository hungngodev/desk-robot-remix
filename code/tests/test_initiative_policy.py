"""Boundary regressions for the real proactive admission policy."""
import math

import pytest
from desk_robot.initiative_policy import (
    cooldown_pending,
    event_cooldown,
    event_identity,
    quiet_voice_veto,
    receipt_veto,
)


@pytest.mark.parametrize(
    ("offered", "quiet_at", "human_at", "expected"),
    [
        (90.0, 90.0, 90.0, None),
        (89.99, 0.0, 0.0, "event_expired_before_admission"),
        (100.01, 0.0, 0.0, "event_expired_before_admission"),
        (math.nan, 0.0, 0.0, "event_expired_before_admission"),
        (True, 0.0, 0.0, "event_expired_before_admission"),
        (95.0, 96.0, 97.0, "quiet_transition_superseded_event"),
        (95.0, 95.0, 96.0, "human_turn_superseded_event"),
    ],
)
def test_receipt_veto_preserves_age_and_precedence(offered, quiet_at, human_at, expected):
    assert receipt_veto(
        now=100.0, offered_at=offered, max_age=10.0,
        quiet_changed_at=quiet_at, latest_human_turn=lambda: human_at,
    ) == expected


@pytest.mark.parametrize("local", [False, True])
@pytest.mark.parametrize("scheduled", [False, True])
@pytest.mark.parametrize("human", [False, True])
def test_quiet_voice_is_independent_of_cooldown(local, scheduled, human):
    assert quiet_voice_veto(
        local_quiet=local, scheduled_quiet=scheduled, human_active=lambda: human,
    ) is (local or scheduled or human)


def test_quiet_does_not_query_human_floor():
    def unexpected():
        pytest.fail("local quiet must short-circuit the human-floor probe")

    assert quiet_voice_veto(local_quiet=True, scheduled_quiet=False, human_active=unexpected)


@pytest.mark.parametrize(
    ("camera", "direct", "interaction", "expected"),
    [(False, True, 12.0, 12.0), (True, True, 12.0, 120.0),
     (False, False, 12.0, 120.0), (False, True, 150.0, 120.0)],
)
def test_event_cooldown_uses_only_deliberate_physical_interaction(
    camera, direct, interaction, expected,
):
    interval = event_cooldown(
        camera_derived=camera, direct_interaction=direct,
        speech_interval=120.0, interaction_interval=interaction,
    )
    assert interval == expected
    assert cooldown_pending(now=interval - 0.01, last=0.0, interval=interval)
    assert not cooldown_pending(now=interval, last=0.0, interval=interval)
    assert not cooldown_pending(now=0.0, last=-math.inf, interval=interval)


def test_camera_paraphrases_share_budget_but_never_physical_identity():
    def identity(robot, description, camera):
        return event_identity(
            robot_id=robot, kind="key", description=description,
            camera_derived=camera, physical_event=True,
        )[0]

    first = identity("a", "A red key appeared", True)
    assert first == identity("b", "I noticed the red key", True)
    assert first != identity("a", "A blue key appeared", True)
    assert first != identity("a", "A red key appeared", False)
    assert identity("a", "Touch", False) != identity("b", "Touch", False)
    assert identity("a", "Touch", False) == identity("a", "  TOUCH  ", False)


@pytest.mark.parametrize("left,right", [
    ("key left of candy", "candy left of key"),
    ("key moved near candy", "candy moved near key"),
    ("key not beside candy", "candy not beside key"),
    ("钥匙 糖果", "糖果 钥匙"),
])
def test_camera_signature_preserves_order_sensitive_evidence(left, right):
    def identity(description):
        return event_identity(
            robot_id="a", kind="scene", description=description,
            camera_derived=True, physical_event=False,
        )[0]

    assert identity(left) != identity(right)
