import pytest

from desk_robot.attention import AttentionLedger


@pytest.mark.parametrize("stale_at", [21.0, 22.0])
@pytest.mark.parametrize("receipt", ["asr", "speech", "voice", "topic"])
def test_attention_reset_rejects_delayed_receipts(monkeypatch, stale_at, receipt):
    now = 22.0
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: now)
    ledger = AttentionLedger(["pet", "peer"])
    obsolete = ledger.begin_topic("pet", "Old private topic", 10)
    ledger.human_started("pet", 11)
    old_id = "omni_" + "a" * 12 + "_" + "b" * 20
    delayed_id = "omni_" + "a" * 12 + "_" + "c" * 20
    fresh_id = "omni_" + "a" * 12 + "_" + "d" * 20
    assert ledger.heard("pet", old_id, "Old private words", 12)
    assert ledger.sent("pet", "Old speech", 13)
    assert ledger.sensor("pet", "safety_fault", 14)
    ledger.begin_topic("peer", "Independent peer topic", 15)
    ledger.clear("pet")
    now = 25.0

    assert not ledger.finish_topic("pet", obsolete, 23, interrupted=True)
    if receipt == "asr":
        assert not ledger.heard_is_current("pet", stale_at)
        assert not ledger.heard("pet", delayed_id, "Delayed private words", stale_at)
    elif receipt == "speech":
        assert not ledger.sent("pet", "Delayed private speech", stale_at)
    elif receipt == "voice":
        ledger.human_started("pet", stale_at)
        assert not ledger._state("pet").voice_active
    else:
        with pytest.raises(ValueError, match="Topic start"):
            ledger.begin_topic("pet", "Delayed private topic", stale_at)
    assert not ledger.sensor("pet", "handling_tilt", stale_at)
    assert ledger.timeline("pet", 23) == []

    ledger.human_started("pet", 23)
    assert ledger._state("pet").voice_active
    assert ledger.heard("pet", fresh_id, "Fresh question", 23.5)
    current = ledger.begin_topic("pet", "Fresh topic", 24)
    assert current > obsolete
    assert ledger.sent("pet", "Fresh speech", 24.5)
    assert ledger.sensor("pet", "safety_fault", 24.75)
    cue = ledger.timeline("pet", 25)[0]
    assert "Fresh topic" in cue["content"]
    assert "WROOM safety_fault" in cue["content"]
    assert "historical, not current telemetry" in cue["content"]
    assert cue["motor_authorized"] is False
    assert cue["physical_action_verified"] is False
    assert "Old" not in cue["content"] and "Delayed" not in cue["content"]
    assert "Independent peer topic" in ledger.timeline("peer", 25)[0]["content"]
