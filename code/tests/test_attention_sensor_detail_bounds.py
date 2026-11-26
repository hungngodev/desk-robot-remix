"""Sensor details are retained only with their corresponding attention edges."""
from string import ascii_lowercase

from desk_robot.attention import AttentionLedger


def test_detail_storage_is_bounded_by_retained_edges(monkeypatch):
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 300.0)
    ledger = AttentionLedger(["pet", "peer"])
    ledger.begin_topic("pet", "observe desk", 1)
    assert ledger.sensor("pet", "safety_fault", 2, detail="floor_out_of_range_upright_lift")
    assert ledger.sensor("pet", "handling_tilt", 3, detail="tilt_detected")
    for index, letter in enumerate(ascii_lowercase, start=4):
        assert ledger.sensor("pet", f"contact_{letter}", index, detail=f"detail_{letter}")
    state = ledger._state("pet")
    assert len(state.sensor_edges) == 6
    assert set(state.sensor_details) == {edge[0] for edge in state.sensor_edges}
    assert state.sensor_details["handling_tilt"] == "tilt_detected"
    assert "possible lift, not confirmed" in ledger.timeline("pet", 40)[0]["content"]
    assert ledger.timeline("peer", 40) == []


def test_topic_change_prunes_details_except_fresh_historical_evidence(monkeypatch):
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 300.0)
    ledger = AttentionLedger(["pet"])
    first = ledger.begin_topic("pet", "observe desk", 1)
    assert ledger.sensor("pet", "handling_shake", 2, detail="old_shake")
    assert ledger.sensor("pet", "touch", 125, detail="routine_contact")
    assert ledger.sensor("pet", "safety_fault", 126, detail="floor_out_of_range_upright_lift")
    assert ledger.finish_topic("pet", first, 127, interrupted=True)
    ledger.begin_topic("pet", "why did you stop?", 128)
    state = ledger._state("pet")
    assert state.sensor_details == {"safety_fault": "floor_out_of_range_upright_lift"}
    context = ledger.timeline("pet", 129)[0]
    assert "possible lift, not confirmed" in context["content"]
    assert "historical, not current telemetry" in context["content"]
    assert context["motor_authorized"] is False
    assert ledger.sensor("pet", "safety_fault", 130)
    assert state.sensor_details == {}
    assert "possible lift" not in ledger.timeline("pet", 131)[0]["content"]
