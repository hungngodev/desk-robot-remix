"""Local monotonic initiative budgets must not inherit an obsolete clock epoch."""

import pytest
from desk_robot.initiative_policy import (
    cooldown_pending,
    event_window_has_capacity,
    quiet_voice_veto,
    receipt_veto,
)


@pytest.mark.parametrize("interval", [12.0, 30.0, 90.0, 120.0, 140.0])
def test_future_speech_receipt_does_not_lock_optional_budget(interval):
    assert not cooldown_pending(now=10.0, last=10_000.0, interval=interval)
    assert cooldown_pending(now=10.0, last=10.0, interval=interval)
    assert cooldown_pending(now=10.0 + interval - 0.01, last=10.0, interval=interval)
    assert not cooldown_pending(now=10.0 + interval, last=10.0, interval=interval)


def test_full_event_window_recovers_without_evicting_current_epoch_fences():
    entries = {(None, "scene", str(index)): 1000.0 for index in range(63)}
    recent = (None, "scene", "recent")
    entries[recent] = 9.0
    incoming = (None, "scene", "incoming")
    assert event_window_has_capacity(entries, incoming, now=10.0, window=12.0)
    assert entries == {recent: 9.0}


def test_epoch_recovery_does_not_relax_voice_or_evidence_vetoes():
    assert quiet_voice_veto(local_quiet=False, scheduled_quiet=False, human_active=lambda: True)
    assert quiet_voice_veto(local_quiet=True, scheduled_quiet=False, human_active=lambda: False)
    assert receipt_veto(
        now=10.0, offered_at=1000.0, max_age=12.0,
        quiet_changed_at=0.0, latest_human_turn=None,
    ) == "event_expired_before_admission"
