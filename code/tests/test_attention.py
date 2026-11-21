"""The attention ledger is volatile context, never a second motion or voice owner."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from desk_robot.attention import AttentionLedger
from desk_robot.brain_context import compose_brain_context
from desk_robot.pet import PetController
from desk_robot.runtime import Runtime


def test_concurrent_song_and_motion_survive_sensor_events_without_fixed_speech(monkeypatch):
    # Synthetic event times exercise ordering; the production clock rejects
    # timestamps beyond the actual monotonic clock.
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 300.0)
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


def test_duplicate_asr_is_never_a_second_goal_or_physical_permission(monkeypatch):
    # Keep the synthetic sequence within the new local receipt-clock fence.
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 300.0)
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


def test_new_human_question_preempts_old_topic_in_attention_context(monkeypatch):
    # Explicit synthetic time avoids depending on the CI host uptime.
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 300.0)
    ledger = AttentionLedger(["pet", "peer"])
    token = ledger.begin_topic("pet", "Sing toward the desk edge", 10)
    assert ledger.finish_topic("pet", token, 20, interrupted=True)
    ledger.human_started("pet", 30)
    event = "omni_" + "a" * 12 + "_" + "b" * 20
    assert ledger.heard("pet", event, "What is the temperature now?", 31)
    text = ledger.timeline("pet", 32)[0]["content"]
    assert "Newer uncertain ASR words" in text
    assert "What is the temperature now?" in text
    assert "Earlier interrupted conversation" in text
    assert text.index("What is the temperature now?") < text.index(
        "Earlier interrupted conversation"
    )
    assert ledger.timeline("peer", 32) == []
    assert not ledger.heard(
        "pet", "omni_" + "c" * 12 + "_" + "d" * 20,
        "Old reply from the interrupted topic", 29,
    )
    assert "Old reply from" not in ledger.timeline("pet", 32)[0]["content"]


def test_sensor_buffer_bounds_and_rejects_untrusted_kinds_and_order(monkeypatch):
    # Explicit synthetic time avoids depending on the CI host uptime.
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 300.0)
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


def test_listening_does_not_spuriously_mark_speech_played_or_commanded(monkeypatch):
    # Synthetic receipts extend to 150s; a fresh CI runner may have less
    # monotonic uptime. Preserve the production future-clock rejection.
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 300.0)
    ledger = AttentionLedger(["pet"])
    ledger.human_started("pet", 8)
    ledger.human_started("pet", 8)
    assert not ledger.sent("pet", "old draft", 7)
    ledger.human_ended("pet", 9)
    assert ledger.sent("pet", "The robot said something", 10)
    assert "playback unverified" in ledger.timeline("pet", 15)[0]["content"]
    assert ledger.timeline("pet", 150) == []


def test_composer_handles_current_attention_with_old_sensor_and_active_job(monkeypatch):
    # Explicit synthetic time avoids depending on the CI host uptime.
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 300.0)
    ledger = AttentionLedger(["pet"])
    ledger.begin_topic("pet", "Sing while approaching the desk edge", at=10)
    assert ledger.sensor("pet", "handling_tilt", 20)
    attention = ledger.timeline("pet", 40)
    job = {
        "channel": "mac_activity", "kind": "coordinator_job",
        "job_type": "exploration", "status": "running",
        "source": "mac_coordinator_active_job",
        "physical_action_verified": False, "motor_authorized": False,
    }
    composed = compose_brain_context([], [], [job, *attention])
    assert "Mac operator-submitted exploration" in composed.interaction
    assert "Ongoing conversation topic" in composed.interaction
    assert "handling_tilt" in composed.interaction
    assert len(composed.interaction) <= 400
    # Source spoofing and model-inferred permission never enter the brain.
    fake = dict(attention[0], source="model_claim", motor_authorized=True)
    assert compose_brain_context([], [], [fake]).interaction == ""


def test_confirmed_safety_fault_outweighs_optional_attention_in_small_budget(monkeypatch):
    # Explicit synthetic time avoids depending on the CI host uptime.
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 300.0)
    ledger = AttentionLedger(["pet"])
    ledger.begin_topic("pet", "A longer conversation about exploration", 10)
    ledger.sensor("pet", "handling_tilt", 20)
    transcript = ledger.timeline("pet", 35)
    current_fault = {
        "channel": "sensor", "kind": "safety_fault",
        "source": "wroom_event", "content": None,
        "physical_action_verified": False,
    }
    context = compose_brain_context([], [], [*transcript, current_fault])
    assert "WROOM reported latched safety fault" in context.interaction
    assert "do not drive" in context.interaction


async def test_real_conversation_feeds_attention_receipts_and_finishes(settings):
    """Dialogue lifecycle and transmitted words share the Runtime attention."""
    import time

    from desk_robot.conversation import Conversation
    from desk_robot.simulator import SimulatedChat, SimulatedSpeaker

    # The global fixture has two pets; this test also needs an outsider.
    settings.robots.append(
        settings.robots[0].model_copy(update={"id": "robot-03", "name": "Third"})
    )
    ids = [robot.id for robot in settings.robots]
    ledger = AttentionLedger(ids)
    conversation = Conversation(settings, SimulatedChat(), SimulatedSpeaker())
    conversation.attention = ledger
    result = await conversation.run(
        ids[:2], "Sing while exploring safely near the desk edge", utterances=2
    )
    assert len(result) == 2
    now = time.monotonic()
    first, second = ledger.timeline(ids[0], now), ledger.timeline(ids[1], now)
    assert "Earlier completed conversation" in first[0]["content"]
    assert "Sing while exploring safely" in first[0]["content"]
    assert "Earlier speech transmitted" in first[0]["content"]
    assert "playback unverified" in first[0]["content"]
    assert "Earlier completed conversation" in second[0]["content"]
    assert ledger.timeline(ids[2], now) == []
    assert first[0]["motor_authorized"] is False
    assert conversation.group_activity_timeline(ids[0])[0]["status"] == "completed"


async def test_cancelled_conversation_marks_attention_interrupted_not_played(settings):
    import asyncio
    import time

    import pytest
    from desk_robot.conversation import Conversation
    from desk_robot.simulator import SimulatedChat, SimulatedSpeaker

    ids = [robot.id for robot in settings.robots]
    ledger = AttentionLedger(ids)
    started, release = asyncio.Event(), asyncio.Event()

    class BlockedSpeaker(SimulatedSpeaker):
        async def say(self, robot, text, *, permission_check=None):
            started.set()
            await release.wait()
            await super().say(
                robot, text, permission_check=permission_check,
            )

    conversation = Conversation(settings, SimulatedChat(), BlockedSpeaker())
    conversation.attention = ledger
    task = asyncio.create_task(conversation.run(
        ids[:2], "Continue the song", utterances=2
    ))
    await asyncio.wait_for(started.wait(), timeout=3)
    live = ledger.timeline(ids[0], time.monotonic())
    assert "Ongoing conversation topic" in live[0]["content"]
    assert "Earlier speech transmitted" not in live[0]["content"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    ended = ledger.timeline(ids[0], time.monotonic())
    assert "Earlier interrupted conversation" in ended[0]["content"]
    assert "Earlier speech transmitted" not in ended[0]["content"]
    assert conversation.active_dialogue_timeline(ids[0]) == []
    release.set()


def test_pet_sensor_producer_uses_same_attention_without_second_camera_owner():
    ledger = AttentionLedger(["pet"])
    ledger.begin_topic("pet", "Still discussing the song", 1)
    pet = PetController.__new__(PetController)
    pet.attention = ledger
    pet.multimodal = None
    pet._notify_sensor("pet", "handling_tilt")
    # Only a history cue, no speech, drive or camera request was produced.
    transcript = ledger.timeline("pet", __import__("time").monotonic())
    assert "handling_tilt" in transcript[0]["content"]
    assert transcript[0]["motor_authorized"] is False


@pytest.mark.asyncio
async def test_authenticated_runtime_voice_edge_fences_attention_speech():
    ledger = AttentionLedger(["pet"])
    runtime = Runtime.__new__(Runtime)
    runtime._closed = False
    runtime.settings = SimpleNamespace(robots=[SimpleNamespace(id="pet")])
    runtime.multimodal = None
    runtime.attention = ledger
    runtime._preempt_audio_floor = AsyncMock()
    runtime._stop_autonomous_roaming_for_voice = AsyncMock()
    await runtime._on_voice_interrupt("pet", "speech_start")
    assert ledger._state("pet").human_turns == 1
    assert ledger._state("pet").voice_active is True
    assert not ledger.sent("pet", "A delayed obsolete response", 0)
    await runtime._on_voice_interrupt("pet", "speech_end")
    assert ledger._state("pet").voice_active is False
    runtime._preempt_audio_floor.assert_awaited_once()
    runtime._stop_autonomous_roaming_for_voice.assert_awaited_once()


def test_delayed_old_topic_sensor_and_speech_do_not_enter_new_generation(monkeypatch):
    # Synthetic timestamps must not depend on a fresh CI runner's uptime.
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 300.0)
    ledger = AttentionLedger(["pet1", "pet2"])
    first = ledger.begin_topic("pet1", "Old conversation", at=10)
    assert ledger.sensor("pet1", "handling_tilt", 11)
    assert ledger.finish_topic("pet1", first, 12, interrupted=False)
    next_generation = ledger.begin_topic("pet1", "New song", at=20)
    assert next_generation > first
    # Worker callbacks may arrive now even though their source time is old.
    assert not ledger.sensor("pet1", "side_object", 19)
    assert not ledger.sent("pet1", "obsolete prior speech", 18)
    current = ledger.timeline("pet1", 21)[0]["content"]
    assert "New song" in current
    assert "side_object" not in current
    assert "obsolete prior speech" not in current
    assert "handling_tilt" not in current
    assert ledger.sensor("pet1", "side_object", 22)
    assert ledger.sent("pet1", "New song begins", 23)
    current = ledger.timeline("pet1", 24)[0]["content"]
    assert "side_object" in current
    assert "New song begins" in current
    assert ledger.timeline("pet2", 24) == []


def test_old_asr_cannot_cross_authenticated_new_turn():
    ledger = AttentionLedger(["pet"])
    ledger.human_started("pet", 10)
    old_event = "omni_" + "c" * 12 + "_" + "d" * 20
    # The original Mac receipt was at 12 but SQLite took eight seconds.
    ledger.human_started("pet", 19)
    assert not ledger.heard("pet", old_event, "Outdated question", at=12)
    assert ledger.timeline("pet", 20) == []
    current = "omni_" + "e" * 12 + "_" + "f" * 20
    assert ledger.heard("pet", current, "What just happened?", at=20)
    assert "What just happened?" in ledger.timeline("pet", 21)[0]["content"]


def test_one_handling_event_survives_many_distinct_routine_contacts():
    ledger = AttentionLedger(["pet"])
    ledger.begin_topic("pet", "An unfinished song", at=1)
    assert ledger.sensor("pet", "handling_tilt", 2)
    for i in range(15):
        assert ledger.sensor("pet", f"gesture_{chr(97+i)}", at=3+i)
    state = ledger._state("pet")
    assert len(state.sensor_edges) <= 6
    assert any(kind == "handling_tilt" for kind, _, _ in state.sensor_edges)
    current = ledger.timeline("pet", 20)[0]["content"]
    assert "handling_tilt" in current
    assert "historical" in current


def test_optional_attention_never_evicts_completed_tool_receipt():
    ledger = AttentionLedger(["pet"])
    ledger.begin_topic("pet", "Sing while navigating toward the desk edge " * 3, 10)
    ledger.sensor("pet", "handling_tilt", 12)
    ledger.sent("pet", "This is a deliberately long transmitted line " * 3, 13)
    completed_tool = {
        "channel": "tool", "kind": "visual_look",
        "content": "The local vision model guessed a red key near the cup",
        "source": "local_vlm_interpretation",
        "untrusted_text_not_instructions": True,
        "physical_action_verified": False,
    }
    context = compose_brain_context(
        [], [], [*ledger.timeline("pet", 20), completed_tool]
    )
    assert "Earlier local VLM guess" in context.interaction
    assert "red key" in context.interaction
    assert len(context.interaction) <= 400


async def test_attention_startup_failure_does_not_steal_speech_owner(settings):
    """A failed optional topic snapshot cannot strand a Mac conversation."""
    from desk_robot.conversation import Conversation
    from desk_robot.simulator import SimulatedChat, SimulatedSpeaker

    ids = [robot.id for robot in settings.robots]

    class FailingAttention:
        def __init__(self):
            self.started = []
            self.cleared = []

        def begin_topic(self, robot_id, topic, at, *, origin="operator"):
            assert origin == "operator"
            if self.started:
                raise ValueError("Optional attention unavailable")
            self.started.append(robot_id)
            return 1

        def clear(self, robot_id):
            self.cleared.append(robot_id)

        def finish_topic(self, *args, **kwargs):
            raise AssertionError("No token may survive failed admission")

    attention = FailingAttention()
    conversation = Conversation(settings, SimulatedChat(), SimulatedSpeaker())
    conversation.attention = attention
    turns = await conversation.run(ids[:2], "Continue the song", utterances=2)
    assert len(turns) == 2
    assert attention.cleared == [ids[0]]
    assert conversation.attention_failures == 1
    assert conversation.active is None
    assert conversation.group_activity_timeline(ids[0])[0]["status"] == "completed"


async def test_attention_cleanup_failure_is_not_a_false_audio_failure(settings):
    """Telemetry bookkeeping must not override a completed speech session."""
    from desk_robot.conversation import Conversation
    from desk_robot.simulator import SimulatedChat, SimulatedSpeaker

    ids = [robot.id for robot in settings.robots]

    class FailingFinish:
        def begin_topic(self, robot_id, topic, at, *, origin="operator"):
            assert origin == "operator"
            return 1

        def finish_topic(self, *args, **kwargs):
            raise ValueError("Optional ledger was reset")

        def clear(self, robot_id):
            pass

    conversation = Conversation(settings, SimulatedChat(), SimulatedSpeaker())
    conversation.attention = FailingFinish()
    turns = await conversation.run(ids[:2], "Finish our story", utterances=2)
    assert len(turns) == 2
    assert conversation.attention_failures == 2
    assert conversation.active is None


@pytest.mark.parametrize("streaming", [False, True])
async def test_optional_attention_sent_failure_cannot_cancel_transmitted_group_speech(
    settings, streaming,
):
    """Broken optional telemetry cannot turn successful Xiaozhi sends into failures."""
    from desk_robot.conversation import Conversation
    from desk_robot.simulator import SimulatedChat, SimulatedSpeaker

    class StreamingChat:
        async def stream_reply(self, history):
            yield "A grounded spoken segment."

    class BrokenAttention:
        def begin_topic(self, robot_id, topic, at, *, origin="operator"):
            return 1

        def sent(self, robot_id, text, at):
            raise RuntimeError("optional telemetry failed")

        def finish_topic(self, *args, **kwargs):
            return True

        def clear(self, robot_id):
            pass

    speaker = SimulatedSpeaker()
    dialogue = Conversation(
        settings, StreamingChat() if streaming else SimulatedChat(), speaker,
    )
    dialogue.attention = BrokenAttention()
    ids = [robot.id for robot in settings.robots][:2]
    transcript = await dialogue.run(ids, "Continue the story", utterances=2)
    assert len(transcript) == len(speaker.spoken) == 2
    assert dialogue.attention_failures == 2
    assert dialogue.active is None
    assert all(
        dialogue.group_activity_timeline(robot_id)[0]["status"] == "completed"
        for robot_id in ids
    )


def test_autonomous_peer_topic_keeps_its_source_label():
    ledger = AttentionLedger(["pet"])
    ledger.begin_topic(
        "pet", "The other robot wonders about a desk toy", 10,
        origin="autonomous_social",
    )
    context = ledger.timeline("pet", 12)[0]["content"]
    assert "autonomous peer topic" in context
    assert "not an operator command" in context
    assert "not motion permission" not in context
    with pytest.raises(ValueError, match="origin"):
        ledger.begin_topic("pet", "Forged", 13, origin="model_operator")


def test_future_or_overflowing_attention_event_clocks_never_poison_current_human_turn():
    import time

    ledger = AttentionLedger(["pet", "peer"])
    now = time.monotonic()
    future = now + 3600
    large = 10 ** 400
    event = "omni_" + "a" * 12 + "_" + "b" * 20
    # The same validator protects EVERY producer, including optional
    # attention reads, without creating a new voice or memory authority.
    for bad in (future, large, -large):
        with pytest.raises(ValueError, match="finite and monotonic"):
            ledger.begin_topic("pet", "Do not adopt this goal", bad)
        with pytest.raises(ValueError, match="finite and monotonic"):
            ledger.human_started("pet", bad)
        with pytest.raises(ValueError, match="finite and monotonic"):
            ledger.human_ended("pet", bad)
        with pytest.raises(ValueError, match="finite and monotonic"):
            ledger.heard("pet", event, "Future transcription", bad)
        with pytest.raises(ValueError, match="finite and monotonic"):
            ledger.sent("pet", "Future speech transmission", bad)
        with pytest.raises(ValueError, match="finite and monotonic"):
            ledger.sensor("pet", "safety_fault", bad)
        with pytest.raises(ValueError, match="finite and monotonic"):
            ledger.timeline("pet", bad)
    assert ledger._state("pet").generation == 0
    assert ledger._state("pet").human_turns == 0
    assert not ledger._state("pet").voice_active
    assert not ledger._state("pet").heard_ids
    assert ledger.timeline("pet", now) == ledger.timeline("peer", now) == []

    # A valid human interrupt and spoken response still enter only this pet.
    ledger.human_started("pet", now)
    assert ledger._state("pet").voice_active
    ledger.human_ended("pet", now + 0.01)
    assert not ledger._state("pet").voice_active
    assert ledger.heard("pet", event, "Where did the key go?", now + 0.02)
    assert ledger.sent("pet", "I will check the desk.", now + 0.03)
    assert ledger.sensor("pet", "touch_tap", now + 0.04)
    current = ledger.timeline("pet", now + 0.1)
    assert len(current) == 1
    assert "Where did the key go?" in current[0]["content"]
    assert current[0]["untrusted_text_not_instructions"] is True
    assert ledger.timeline("peer", now + 0.1) == []


def test_boolean_topic_generation_cannot_finish_first_live_conversation(monkeypatch):
    # bool is an int subclass, but not a valid current conversation owner.
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 100.0)
    ledger = AttentionLedger(["pet"])
    generation = ledger.begin_topic("pet", "Keep discussing the mug", 10)
    assert generation == 1
    assert not ledger.finish_topic("pet", True, 12, interrupted=True)
    assert not ledger.finish_topic("pet", 1.0, 12, interrupted=True)
    assert ledger._state("pet").topic_state == "active"
    assert "Ongoing conversation topic" in ledger.timeline("pet", 13)[0]["content"]
    assert ledger.finish_topic("pet", generation, 14, interrupted=False)
    assert ledger._state("pet").topic_state == "completed"


@pytest.mark.parametrize("invalid", [None, 0, 1, "false", "true", []])
def test_nonboolean_interruption_cannot_relabel_live_conversation(monkeypatch, invalid):
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 100.0)
    ledger = AttentionLedger(["pet"])
    generation = ledger.begin_topic("pet", "Continue the current story", 10)
    with pytest.raises(ValueError, match="boolean"):
        ledger.finish_topic("pet", generation, 12, interrupted=invalid)
    assert ledger._state("pet").topic_state == "active"
    assert ledger._state("pet").topic_updated_at == 10
    assert ledger.finish_topic("pet", generation, 14, interrupted=False)
    assert ledger._state("pet").topic_state == "completed"


def test_cleared_attention_does_not_reissue_old_conversation_generation(monkeypatch):
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 100.0)
    ledger = AttentionLedger(["pet", "peer"])
    obsolete = ledger.begin_topic("pet", "Older interrupted topic", 10)
    ledger.sensor("pet", "handling_tilt", 11)
    ledger.clear("pet")
    assert ledger.timeline("pet", 12) == []
    current = ledger.begin_topic("pet", "Fresh conversation", 13)
    assert current > obsolete
    assert not ledger.finish_topic("pet", obsolete, 14, interrupted=True)
    assert ledger._state("pet").topic_state == "active"
    assert ledger.finish_topic("pet", current, 15, interrupted=False)
    assert "Fresh conversation" in ledger.timeline("pet", 16)[0]["content"]
    assert "Older interrupted topic" not in ledger.timeline("pet", 16)[0]["content"]
    assert ledger.timeline("peer", 16) == []


def test_delayed_old_topic_start_cannot_overwrite_newer_activity(monkeypatch):
    monkeypatch.setattr("desk_robot.attention.time.monotonic", lambda: 100.0)
    ledger = AttentionLedger(["pet"])
    first = ledger.begin_topic("pet", "Old topic", 10)
    current = ledger.begin_topic("pet", "Current song", 20)
    assert current > first
    assert ledger.sensor("pet", "handling_tilt", 22)
    with pytest.raises(ValueError, match="Topic start"):
        ledger.begin_topic("pet", "Delayed older callback", 15)
    with pytest.raises(ValueError, match="Topic start"):
        ledger.begin_topic("pet", "Duplicate current callback", 20)
    assert ledger._state("pet").generation == current
    assert ledger._state("pet").topic_state == "active"
    assert "Current song" in ledger.timeline("pet", 23)[0]["content"]
    assert "handling_tilt" in ledger.timeline("pet", 23)[0]["content"]
    assert "Delayed older callback" not in ledger.timeline("pet", 23)[0]["content"]
    assert not ledger.finish_topic("pet", first, 24, interrupted=True)
    assert ledger.finish_topic("pet", current, 25, interrupted=False)


@pytest.mark.parametrize("invalid", [[], {}, ["operator"], {"origin": "operator"}])
def test_attention_topic_origin_unhashable_rejected_without_state(invalid):
    import time
    ledger = AttentionLedger(["robot-01", "robot-02"])
    with pytest.raises(ValueError, match="Unsupported conversation origin"):
        ledger.begin_topic("robot-01", "Discuss a key", time.monotonic(), origin=invalid)
    assert ledger.timeline("robot-01", time.monotonic()) == []
    epoch = ledger.begin_topic("robot-01", "Discuss a key", time.monotonic(), origin="operator")
    assert epoch == 1


def test_attention_retracts_only_deleted_asr_identity():
    import time
    ledger = AttentionLedger(["robot-01", "robot-02"])
    first = "omni_" + "a" * 12 + "_" + "b" * 20
    other = "omni_" + "c" * 12 + "_" + "d" * 20
    stamp = time.monotonic()
    assert ledger.heard("robot-01", first, "Private ASR", stamp)
    assert ledger.heard("robot-02", first, "Independent peer ASR", stamp)
    assert not ledger.discard_heard("robot-01", other)
    assert ledger.discard_heard("robot-01", first)
    assert not ledger.discard_heard("robot-01", first)
    assert not ledger.heard("robot-01", first, "Replayed private ASR", stamp)
    assert not any("Private ASR" in x["content"] for x in ledger.timeline("robot-01", time.monotonic()))
    assert any("Independent peer ASR" in x["content"]
               for x in ledger.timeline("robot-02", time.monotonic()))
