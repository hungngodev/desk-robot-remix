"""Regression coverage for bounded, consented conversation continuity."""
import pytest
from desk_robot.attention import AttentionLedger


def _interrupted_topic(monkeypatch):
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 300.0)
    ledger = AttentionLedger(["pet", "peer"])
    ledger.human_started("pet", 10)
    assert ledger.heard(
        "pet", "omni_" + "a" * 12 + "_" + "b" * 20,
        "PRIVATE_OLD_TOPIC", 11, consent_generation=7,
    )
    assert ledger.sensor("pet", "handling_tilt", 12)
    ledger.human_started("pet", 13)
    assert ledger.heard(
        "pet", "omni_" + "c" * 12 + "_" + "d" * 20,
        "Continue please", 14, consent_generation=7,
    )
    return ledger


@pytest.mark.parametrize(("enabled", "generation", "expected"), [
    (True, 7, True),
    (False, 7, False),
    (True, 8, False),
])
def test_handling_resumption_keeps_only_current_grant(
    monkeypatch, enabled, generation, expected,
):
    ledger = _interrupted_topic(monkeypatch)
    cue = ledger.timeline(
        "pet", 15, live_consent_enabled=enabled,
        live_consent_generation=generation,
    )[0]
    content = cue["content"]
    assert ("PRIVATE_OLD_TOPIC" in content) is expected
    assert ("Continue please" in content) is expected
    if expected:
        assert content.index("Continue please") < content.index("PRIVATE_OLD_TOPIC")
        assert "Earlier ASR (uncertain context)" in content
    assert "handling_tilt" in content
    assert "historical, not current telemetry" in content
    assert len(content) <= 260
    assert cue["motor_authorized"] is False
    assert ledger.timeline("peer", 15) == []
    assert "PRIVATE_OLD_TOPIC" not in str(ledger.timeline("pet", 102))


def test_new_operator_topic_retires_interrupted_asr(monkeypatch):
    ledger = _interrupted_topic(monkeypatch)
    ledger.begin_topic("pet", "Read the clock", 16)
    cue = ledger.timeline("pet", 17, live_consent_generation=7)[0]
    assert "Read the clock" in cue["content"]
    assert "PRIVATE_OLD_TOPIC" not in cue["content"]
    assert "Continue please" not in cue["content"]
    assert "handling_tilt" in cue["content"]
    assert cue["motor_authorized"] is False
    assert not ledger.heard(
        "pet", "omni_" + "e" * 12 + "_" + "f" * 20,
        "Delayed previous topic", 15, consent_generation=7,
    )


def test_new_operator_topic_retires_sent_words_not_safety(monkeypatch):
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 300.0)
    ledger = AttentionLedger(["pet"])
    previous = ledger.begin_topic("pet", "Tell me a story", 10)
    assert ledger.sent("pet", "OLD_STORY_WORDS", 11)
    assert ledger.sensor("pet", "safety_fault", 12)
    assert ledger.finish_topic("pet", previous, 13, interrupted=True)
    assert "OLD_STORY_WORDS" in ledger.timeline("pet", 14)[0]["content"]
    ledger.begin_topic("pet", "Read the clock", 15)
    cue = ledger.timeline("pet", 16)[0]
    assert "Read the clock" in cue["content"]
    assert "OLD_STORY_WORDS" not in cue["content"]
    assert "WROOM safety_fault" in cue["content"]
    assert cue["motor_authorized"] is False
    assert not ledger.sent("pet", "late obsolete words", 14)
    assert ledger.sent("pet", "NEW_CLOCK_WORDS", 17)
    assert "NEW_CLOCK_WORDS" in ledger.timeline("pet", 18)[0]["content"]
