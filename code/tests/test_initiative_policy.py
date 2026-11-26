"""Boundary regressions for the real proactive admission policy."""
import math

import pytest
from desk_robot.initiative_policy import (
    battery_warning_pending,
    camera_scene_signature,
    cooldown_pending,
    event_budget_reason,
    event_cooldown,
    event_identity,
    event_window_has_capacity,
    quiet_voice_reason,
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


def test_event_window_bounds_one_thousand_fresh_candidates_without_evicting_fences():
    entries = {}
    for index in range(1000):
        key, _ = event_identity(
            robot_id="robot-01", kind="key", description=f"Key {index}",
            camera_derived=True, physical_event=False,
        )
        if event_window_has_capacity(entries, key, now=100.0, window=5.0):
            entries[key] = 100.0
        assert len(entries) <= 64
    first = (None, "key", "camera:0 key")
    assert len(entries) == 64
    assert entries[first] == 100.0
    assert event_window_has_capacity(entries, first, now=104.99, window=5.0)
    new_key = (None, "key", "camera:new")
    assert not event_window_has_capacity(entries, new_key, now=104.99, window=5.0)
    assert event_window_has_capacity(entries, new_key, now=105.0, window=5.0)
    assert not entries


@pytest.mark.parametrize(
    ("elapsed", "pending"),
    [(-0.01, False), (0.0, True), (119.99, True), (120.0, False)],
)
def test_battery_warning_has_its_own_exact_floor(elapsed, pending):
    assert battery_warning_pending(now=200.0 + elapsed, last=200.0) is pending


@pytest.mark.parametrize(
    ("event_at", "fleet_at", "expected"),
    [
        (100.0, 100.0, "duplicate_event_cooldown"),
        (95.0, 100.0, "fleet_speech_cooldown"),
        (95.0, 88.0, None),
        (101.0, 101.0, None),
    ],
)
def test_event_budget_reason_preserves_order_and_boundaries(event_at, fleet_at, expected):
    assert event_budget_reason(
        now=100.0, previous_event_at=event_at, fleet_spoken_at=fleet_at,
        event_window=5.0, speech_interval=12.0,
    ) == expected


@pytest.mark.parametrize(
    ("local", "scheduled", "human", "expected"),
    [
        (True, True, True, "manual_quiet"),
        (False, True, True, "scheduled_quiet_hours"),
        (False, False, True, "human_floor_busy"),
        (False, False, False, None),
    ],
)
def test_quiet_reason_preserves_precedence(local, scheduled, human, expected):
    def human_active():
        assert not local and not scheduled, "quiet must short-circuit human-floor access"
        return human

    assert quiet_voice_reason(
        local_quiet=local, scheduled_quiet=scheduled, human_active=human_active,
    ) == expected


def test_receipt_without_optional_human_turn_callback():
    assert receipt_veto(
        now=100.0, offered_at=100.0, max_age=10.0,
        quiet_changed_at=100.0, latest_human_turn=None,
    ) is None


def test_single_content_word_preserves_original_signature():
    assert camera_scene_signature("  A KEY appeared  ") == "a key appeared"
    assert camera_scene_signature(" THE ") == "the"


def test_nonphysical_noncamera_event_does_not_claim_eyewitness():
    expected = ((None, "activity", "other:idle play"), "idle play")
    for robot_id in ("pet1", "pet2"):
        assert event_identity(
            robot_id=robot_id, kind="activity", description=" Idle PLAY ",
            camera_derived=False, physical_event=False,
        ) == expected


@pytest.mark.parametrize("interval", [3.0, 12.0, 120.0])
def test_cooldown_exact_monotonic_edges(interval):
    last = 1000.0
    expiry = last + interval
    assert not cooldown_pending(now=math.nextafter(last, -math.inf), last=last, interval=interval)
    assert cooldown_pending(now=last, last=last, interval=interval)
    assert cooldown_pending(now=math.nextafter(expiry, -math.inf), last=last, interval=interval)
    assert not cooldown_pending(now=expiry, last=last, interval=interval)
    assert not cooldown_pending(now=math.nextafter(expiry, math.inf), last=last, interval=interval)


def test_zero_interval_never_consumes_optional_budget():
    for now in (999.0, 1000.0, 1001.0):
        assert not cooldown_pending(now=now, last=1000.0, interval=0.0)


@pytest.mark.parametrize("interval", [12.0, 120.0])
@pytest.mark.parametrize("quiet", ["manual", "scheduled", "human"])
def test_expired_speech_budget_does_not_override_quiet(interval, quiet):
    assert event_budget_reason(
        now=1000.0 + interval, previous_event_at=-math.inf,
        fleet_spoken_at=1000.0, event_window=3.0, speech_interval=interval,
    ) is None
    assert quiet_voice_veto(
        local_quiet=quiet == "manual", scheduled_quiet=quiet == "scheduled",
        human_active=lambda: quiet == "human",
    )
