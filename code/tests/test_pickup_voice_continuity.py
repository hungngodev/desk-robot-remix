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
