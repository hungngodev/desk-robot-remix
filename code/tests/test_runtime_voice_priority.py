"""A human speaking to one Sense preempts the shared fleet speech floor."""
from types import SimpleNamespace

from desk_robot.runtime import Runtime


async def test_one_human_interrupt_preempts_other_pet_audio_too():
    calls = []

    class Pet:
        async def interrupt(self, robot_id):
            calls.append(("pet", robot_id))

    class Conversation:
        async def stop(self):
            calls.append(("group", "stop"))

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(robots=[
        SimpleNamespace(id="robot-01"),
        SimpleNamespace(id="robot-02"),
        SimpleNamespace(id="robot-03"),
    ])
    runtime.pet = Pet()
    runtime.conversation = Conversation()

    await runtime._on_voice_interrupt("robot-01", "normal")

    assert calls == [
        ("pet", "robot-01"),
        ("pet", "robot-02"),
        ("pet", "robot-03"),
        ("group", "stop"),
    ]


async def test_unknown_voice_source_cannot_interrupt_the_fleet():
    import pytest

    events = []

    class Pet:
        async def interrupt(self, robot_id):
            events.append(robot_id)

    class Conversation:
        async def stop(self):
            events.append("stop")

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(robots=[SimpleNamespace(id="robot-01")])
    runtime.pet = Pet()
    runtime.conversation = Conversation()

    with pytest.raises(KeyError):
        await runtime._on_voice_interrupt("forged-robot", "normal")
    assert events == []


async def test_initial_human_speech_primes_video_only_after_urgent_audio_stop():
    events = []

    class Pet:
        async def interrupt(self, robot_id):
            events.append(("stop_pet", robot_id))

    class Conversation:
        async def stop(self):
            events.append(("stop_audio", None))

    class Visual:
        def voice_started(self, robot_id):
            events.append(("start_camera", robot_id))

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(robots=[
        SimpleNamespace(id="robot-01"), SimpleNamespace(id="robot-02")
    ])
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    runtime.multimodal = Visual()
    await runtime._on_voice_interrupt("robot-02", "speech_start")
    assert events == [
        ("stop_pet", "robot-01"),
        ("stop_pet", "robot-02"),
        ("stop_audio", None),
        ("start_camera", "robot-02"),
    ]


async def test_speech_end_only_stops_video_sampling_not_live_xiaozhi_audio():
    events = []
    class Pet:
        async def interrupt(self, robot_id):
            events.append("pet_interrupted")
    class Chat:
        async def stop(self):
            events.append("audio_stopped")
    class Visual:
        def voice_ended(self, robot_id):
            events.append(("video_idle", robot_id))
    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(
        robots=[SimpleNamespace(id="robot-01")]
    )
    runtime.pet = Pet()
    runtime.conversation = Chat()
    runtime.multimodal = Visual()
    await runtime._on_voice_interrupt("robot-01", "speech_end")
    assert events == [("video_idle", "robot-01")]


async def test_lost_voice_transport_blocks_proactive_before_audio_cancel():
    events = []

    class Pet:
        def set_voice_monitor_ready(self, ready):
            events.append(("monitor", ready))

        async def interrupt(self, robot_id):
            events.append(("pet", robot_id))

    class Conversation:
        async def stop(self):
            events.append(("speaker", "stop"))

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(robots=[SimpleNamespace(id="robot-01")])
    runtime.pet = Pet()
    runtime.conversation = Conversation()

    await runtime._on_voice_global("stream_unavailable")
    assert events == [
        ("monitor", False), ("pet", "robot-01"), ("speaker", "stop"),
    ]
    await runtime._on_voice_monitor_ready(True)
    assert events[-1] == ("monitor", True)


async def test_aec_barge_uses_bounded_video_lease_not_unended_speech_start():
    events = []

    class Pet:
        async def interrupt(self, robot_id):
            events.append(("pet", robot_id))

    class Conversation:
        async def stop(self):
            events.append(("audio", "stopped"))

    class Visual:
        def voice_started(self, robot_id):
            raise AssertionError("AEC interruption is not an idle VAD start")

        def voice_interrupted(self, robot_id):
            events.append(("aec_video", robot_id))

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(
        robots=[SimpleNamespace(id="robot-01")],
    )
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    runtime.multimodal = Visual()
    await runtime._on_voice_interrupt("robot-01", "normal")
    assert events == [
        ("pet", "robot-01"), ("audio", "stopped"),
        ("aec_video", "robot-01"),
    ]


async def test_server_vad_snapshot_preempts_missing_start_and_releases_missing_end():
    import time
    from desk_robot.multimodal import CameraFrameHub

    calls = []

    class Pet:
        async def interrupt(self, robot_id):
            calls.append(("pet", robot_id))

    class Conversation:
        async def stop(self):
            calls.append(("speaker", "stop"))

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(robots=[
        SimpleNamespace(id="robot-01"), SimpleNamespace(id="robot-02"),
    ])
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    hub = CameraFrameHub(["robot-01", "robot-02"])
    runtime.multimodal = SimpleNamespace(hub=hub)
    await runtime._on_voice_snapshot(frozenset({"robot-02"}))
    assert hub.user_active("robot-02", time.monotonic())
    assert calls == [
        ("pet", "robot-01"), ("pet", "robot-02"), ("speaker", "stop"),
    ]
    await runtime._on_voice_snapshot(frozenset({"robot-02"}))
    assert len(calls) == 3  # Identical snapshot is not another interruption.
    await runtime._on_voice_snapshot(frozenset())
    assert not hub.user_active("robot-02", time.monotonic())
