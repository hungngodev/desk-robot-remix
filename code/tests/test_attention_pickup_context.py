from desk_robot.attention import AttentionLedger


def test_possible_lift_preserves_topic_without_claiming_pickup():
    ledger = AttentionLedger(["pet", "peer"])
    ledger.begin_topic("pet", "Tell me about Saturn", 10)
    assert ledger.sensor("pet", "safety_fault", 11, detail="floor_out_of_range_upright_lift")
    cue = ledger.timeline("pet", 12)[0]
    assert "Tell me about Saturn" in cue["content"]
    assert "floor out of range; possible lift, not confirmed" in cue["content"]
    assert "historical, not current telemetry" in cue["content"]
    assert cue["motor_authorized"] is False
    assert cue["physical_action_verified"] is False
    assert ledger.timeline("peer", 12) == []


def test_plain_floor_fault_is_not_a_lift_and_old_lift_expires(monkeypatch):
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 200)
    ledger = AttentionLedger(["pet"])
    ledger.begin_topic("pet", "Tell me about Saturn", 10)
    assert ledger.sensor("pet", "safety_fault", 11, detail="floor_out_of_range_upright_lift")
    assert ledger.sensor("pet", "safety_fault", 14, detail="floor_out_of_range")
    content = ledger.timeline("pet", 15)[0]["content"]
    assert "floor_out_of_range" in content
    assert "possible lift" not in content
    assert "safety_fault" not in ledger.timeline("pet", 135)[0]["content"]
