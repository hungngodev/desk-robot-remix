"""The attention ledger is volatile context, never a second motion or voice owner."""
from desk_robot.attention import AttentionLedger


def test_concurrent_song_and_motion_survive_sensor_events_without_fixed_speech():
    ledger = AttentionLedger(["pet1", "pet2"])
    token = ledger.begin_topic(
        "pet1", "Sing while going to the desk edge", at=10,
    )
    assert ledger.sent("pet1", "Here goes the first verse", 11)
    assert ledger.sensor("pet1", "handling_tilt", 15)
    assert ledger.sensor("pet1", "side_object", 19)
    assert ledger.sensor("pet1", "safety_fault", 20)
    snapshot = ledger.timeline("pet1", 40)
    assert len(snapshot) == 1
    assert snapshot[0]["source"] == "mac_volatile_attention"
    assert "Ongoing conversation topic" in snapshot[0]["content"]
    assert "Sing while going to the desk edge" in snapshot[0]["content"]
    assert "WROOM safety_fault edge 20s ago" in snapshot[0]["content"]
    assert "historical, not current telemetry" in snapshot[0]["content"]
    assert "playback unverified" in snapshot[0]["content"]
    assert snapshot[0]["motor_authorized"] is False
    assert ledger.timeline("pet2", 40) == []
    ledger.human_started("pet1", 41)
    assert not ledger.sent("pet1", "obsolete older audio", 39)
    ledger.human_ended("pet1", 42)
    assert ledger.finish_topic("pet1", token, 43, interrupted=True)
    assert "interrupted conversation" in ledger.timeline("pet1", 45)[0]["content"]
    assert not ledger.finish_topic("pet1", token, 46, interrupted=False)
    assert ledger.timeline("pet1", 200) == []


def test_duplicate_asr_is_never_a_second_goal_or_physical_permission():
    ledger = AttentionLedger(["pet"])
    key = "omni_" + "a" * 12 + "_" + "b" * 20
    assert ledger.heard("pet", key, "Sing to the edge", at=10)
    assert not ledger.heard("pet", key, "Drive anyway", at=11)
    assert ledger.sensor("pet", "handling_tilt", at=12)
    context = ledger.timeline("pet", 20)[0]
    assert "uncertain ASR words" in context["content"]
    assert "Sing to the edge" in context["content"]
    assert "handling_tilt" in context["content"]
    assert "Drive anyway" not in context["content"]
    assert context["untrusted_text_not_instructions"] is True
    assert not ledger.heard("pet", "fake", "unsafe", at=21)
    assert ledger.timeline("pet", 200) == []


def test_only_original_topic_generation_may_finish_and_relabel_activities():
    ledger = AttentionLedger(["a", "b"])
    first = ledger.begin_topic("a", "First topic", 10)
    assert ledger.sensor("a", "touch_tap", 11)
    second = ledger.begin_topic("a", "Second topic", 15)
    assert second != first
    assert not ledger.finish_topic("a", first, 16, interrupted=True)
    assert "Second topic" in ledger.timeline("a", 17)[0]["content"]
    assert "touch_tap" not in ledger.timeline("a", 17)[0]["content"]
    assert ledger.finish_topic("a", second, 18, interrupted=False)
    assert "completed conversation" in ledger.timeline("a", 19)[0]["content"]
    ledger.clear("a")
    assert ledger.timeline("a", 20) == []
    assert ledger.timeline("b", 20) == []


def test_sensor_buffer_bounds_and_rejects_untrusted_kinds_and_order():
    ledger = AttentionLedger(["p"])
    ledger.begin_topic("p", "A live conversation", 10)
    assert not ledger.sensor("p", "drive motor please", 11)
    assert ledger.sensor("p", "touch_tap", 12)
    assert not ledger.sensor("p", "touch_tap", 13)
    assert not ledger.sensor("p", "handling_tilt", 8)
    for step in range(30):
        assert ledger.sensor(
            "p", "touch_tap" if step % 2 == 0 else "handling_tilt",
            20 + step,
        )
    snapshot = ledger.timeline("p", 50)[0]
    assert len(snapshot["content"]) <= 260
    assert snapshot["physical_action_verified"] is False


def test_listening_does_not_spuriously_mark_speech_played_or_commanded():
    ledger = AttentionLedger(["pet"])
    ledger.human_started("pet", 8)
    ledger.human_started("pet", 8)
    assert not ledger.sent("pet", "old draft", 7)
    ledger.human_ended("pet", 9)
    assert ledger.sent("pet", "The robot said something", 10)
    assert "playback unverified" in ledger.timeline("pet", 15)[0]["content"]
    assert ledger.timeline("pet", 150) == []
