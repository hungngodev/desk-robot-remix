"""Handling may interrupt speech without granting motion or reviving commands."""

import pytest
from desk_robot.attention import AttentionLedger


@pytest.mark.parametrize("edge,detail", [
    ("handling_tilt", None),
    ("safety_fault", "floor_out_of_range_upright_lift"),
])
def test_pickup_pause_putdown_keeps_previous_words_as_history(monkeypatch, edge, detail):
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 300.0)
    ledger = AttentionLedger(["pet", "peer"])
    previous = "omni_" + "a" * 12 + "_" + "b" * 20
    current = "omni_" + "a" * 12 + "_" + "c" * 20
    ledger.human_started("pet", 10)
    assert ledger.heard("pet", previous, "the red mug", 11, consent_generation=7)
    assert ledger.sensor("pet", edge, 12, detail=detail)
    ledger.human_ended("pet", 13)
    assert ledger.sensor("pet", "stable_putdown", 14)
    ledger.human_started("pet", 15)
    assert ledger.heard("pet", current, "and the blue cup", 16, consent_generation=7)
    cue = ledger.timeline("pet", 17, live_consent_generation=7)[0]
    assert "and the blue cup" in cue["content"]
    assert "Earlier ASR (uncertain context): the red mug" in cue["content"]
    assert edge in cue["content"]
    assert cue["motor_authorized"] is False
    assert cue["physical_action_verified"] is False
    assert cue["untrusted_text_not_instructions"] is True
    assert len(cue["content"]) <= 260
    assert ledger.timeline("peer", 17) == []
    for enabled, grant in ((False, 7), (True, 8)):
        assert "the red mug" not in str(ledger.timeline(
            "pet", 17, live_consent_enabled=enabled, live_consent_generation=grant,
        ))
    assert ledger.discard_heard("pet", previous)
    assert "the red mug" not in str(ledger.timeline("pet", 17, live_consent_generation=7))
    assert "and the blue cup" in str(ledger.timeline("pet", 17, live_consent_generation=7))
    assert not ledger.heard("pet", previous, "the red mug", 18, consent_generation=7)


def test_handling_history_expires_and_ordinary_voice_does_not_keep_old_words(monkeypatch):
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 300.0)
    ledger = AttentionLedger(["pet"])
    previous = "omni_" + "a" * 12 + "_" + "b" * 20
    ledger.human_started("pet", 10)
    assert ledger.heard("pet", previous, "private fragment", 11)
    assert ledger.sensor("pet", "handling_tilt", 12)
    ledger.human_ended("pet", 13)
    ledger.human_started("pet", 14)
    assert "private fragment" in str(ledger.timeline("pet", 15))
    assert "private fragment" not in str(ledger.timeline("pet", 102))
    ledger.human_started("pet", 16)
    assert "private fragment" not in str(ledger.timeline("pet", 17))
    current = "omni_" + "a" * 12 + "_" + "c" * 20
    assert ledger.heard("pet", current, "ordinary words", 17)
    assert ledger.sensor("pet", "touch_tap", 18)
    ledger.human_started("pet", 19)
    assert "ordinary words" not in str(ledger.timeline("pet", 20))


@pytest.mark.parametrize("edge,detail", [
    ("handling_tilt", None),
    ("safety_fault", "floor_out_of_range_upright_lift"),
])
@pytest.mark.parametrize("heard_before_sensor", [False, True])
def test_vad_before_pickup_sensor_reconciles_with_consent_and_retraction_fences(
    monkeypatch, edge, detail, heard_before_sensor,
):
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 300.0)
    ledger = AttentionLedger(["pet", "peer"])
    previous = "omni_" + "a" * 12 + "_" + "b" * 20
    current = "omni_" + "a" * 12 + "_" + "c" * 20
    ledger.human_started("pet", 10)
    assert ledger.heard("pet", previous, "the red mug", 11, consent_generation=7)
    ledger.human_ended("pet", 13)
    # Reverse callback order: VAD resumes before WROOM status delivers handling edge.
    ledger.human_started("pet", 15)
    assert "the red mug" not in str(ledger.timeline("pet", 15, live_consent_generation=7))
    if heard_before_sensor:
        assert ledger.heard("pet", current, "and the blue cup", 16, consent_generation=7)
        assert ledger.sensor("pet", edge, 16.5, detail=detail)
    else:
        assert ledger.sensor("pet", edge, 15.5, detail=detail)
        assert ledger.heard("pet", current, "and the blue cup", 16, consent_generation=7)
    cue = ledger.timeline("pet", 17, live_consent_generation=7)[0]
    assert "and the blue cup" in cue["content"]
    assert "Earlier ASR (uncertain context): the red mug" in cue["content"]
    assert edge in cue["content"]
    assert cue["motor_authorized"] is False
    assert cue["physical_action_verified"] is False
    for enabled, grant in ((False, 7), (True, 8)):
        assert "the red mug" not in str(ledger.timeline(
            "pet", 17, live_consent_enabled=enabled, live_consent_generation=grant,
        ))
    assert ledger.discard_heard("pet", previous)
    assert "the red mug" not in str(ledger.timeline("pet", 17, live_consent_generation=7))
    assert "and the blue cup" in str(ledger.timeline("pet", 17, live_consent_generation=7))
    assert not ledger.heard("pet", previous, "the red mug", 18, consent_generation=7)


def test_retracted_or_stale_pending_candidate_cannot_promote_on_later_sensor(monkeypatch):
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 300.0)
    ledger = AttentionLedger(["pet"])
    previous = "omni_" + "a" * 12 + "_" + "d" * 20
    ledger.human_started("pet", 10)
    assert ledger.heard("pet", previous, "secret phrase", 11, consent_generation=7)
    ledger.human_ended("pet", 12)
    ledger.human_started("pet", 13)
    assert ledger.discard_heard("pet", previous)
    assert not ledger.sensor("pet", "handling_tilt", 13.5)
    assert "secret phrase" not in str(ledger.timeline("pet", 14, live_consent_generation=7))

    second = "omni_" + "a" * 12 + "_" + "e" * 20
    ledger.human_started("pet", 20)
    assert ledger.heard("pet", second, "older phrase", 21, consent_generation=7)
    ledger.human_ended("pet", 22)
    ledger.human_started("pet", 23)
    # Non-handling edge or late edge outside the 5 s reconciliation window must not promote.
    assert ledger.sensor("pet", "touch_tap", 23.5)
    assert ledger._state("pet").interrupted_asr is None
    assert "older phrase" not in str(ledger.timeline("pet", 24, live_consent_generation=7))
    assert ledger.sensor("pet", "handling_tilt", 30.0)
    assert ledger._state("pet").interrupted_asr is None
    assert "older phrase" not in str(ledger.timeline("pet", 31, live_consent_generation=7))
