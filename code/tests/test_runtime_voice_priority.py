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
