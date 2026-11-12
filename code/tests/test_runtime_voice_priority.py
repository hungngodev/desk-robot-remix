"""A human speaking to one Sense preempts the shared fleet speech floor."""
import time
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


async def test_slow_pet_abort_does_not_delay_group_audio_stop():
    import asyncio

    started = asyncio.Event()
    release = asyncio.Event()
    group_stopped = asyncio.Event()

    class Pet:
        async def interrupt(self, robot_id):
            if robot_id == "robot-01":
                started.set()
                await release.wait()

    class Conversation:
        async def stop(self):
            group_stopped.set()

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(robots=[
        SimpleNamespace(id="robot-01"), SimpleNamespace(id="robot-02"),
    ])
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    task = asyncio.create_task(runtime._preempt_audio_floor())
    try:
        await asyncio.wait_for(started.wait(), timeout=0.2)
        # The other Xiaozhi social head gets its stop request immediately
        # even though one pet's HTTP cleanup is still blocked.
        await asyncio.wait_for(group_stopped.wait(), timeout=0.2)
        assert not task.done()
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=1)


async def test_failed_group_stop_is_not_silently_accepted_as_preemption():
    import pytest

    class Pet:
        async def interrupt(self, robot_id):
            return None

    class Conversation:
        async def stop(self):
            raise RuntimeError("Xiaozhi group audio abort failed")

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(robots=[
        SimpleNamespace(id="robot-01"),
    ])
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    with pytest.raises(RuntimeError, match="Unable to preempt"):
        await runtime._preempt_audio_floor()


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

    class Visual:
        def __init__(self):
            self.hub = hub
            self.edges = []

        def voice_started(self, robot_id):
            self.edges.append(("start", robot_id))
            self.hub.notify(robot_id, "human_voice", time.monotonic())

        def voice_ended(self, robot_id):
            self.edges.append(("end", robot_id))
            self.hub.speech_ended(robot_id, time.monotonic())

    visual = Visual()
    runtime.multimodal = visual
    await runtime._on_voice_snapshot(frozenset({"robot-02"}))
    assert visual.edges == [("start", "robot-02")]
    assert hub.user_active("robot-02", time.monotonic())
    assert calls == [
        ("pet", "robot-01"), ("pet", "robot-02"), ("speaker", "stop"),
    ]
    await runtime._on_voice_snapshot(frozenset({"robot-02"}))
    assert len(calls) == 3  # Identical snapshot is not another interruption.
    await runtime._on_voice_snapshot(frozenset())
    assert visual.edges == [("start", "robot-02"), ("end", "robot-02")]
    assert not hub.user_active("robot-02", time.monotonic())


async def test_missing_vad_start_reuses_real_multimodal_camera_preemption():
    import asyncio
    from desk_robot.multimodal import MultimodalOrchestrator

    class SlowHead:
        def __init__(self):
            self.started = asyncio.Event()
            self.cancelled = False

        async def snapshot(self):
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    class Pet:
        async def interrupt(self, robot_id):
            return None

    class Conversation:
        async def stop(self):
            return None

    slow = SlowHead()
    settings = SimpleNamespace(
        robots=[SimpleNamespace(id="robot-01"), SimpleNamespace(id="robot-02")],
        voice_vision_tools_enabled=False,
        vision_model="",
    )
    visual = MultimodalOrchestrator(
        settings, {"robot-01": slow, "robot-02": slow},
        SimpleNamespace(), asyncio.Lock(),
    )
    runtime = Runtime.__new__(Runtime)
    runtime.settings = settings
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    runtime.multimodal = visual
    optional = asyncio.create_task(visual.capture("robot-02", source="proactive"))
    try:
        await asyncio.wait_for(slow.started.wait(), timeout=1)
        # An authenticated reconnect discovers speech on the OTHER pet.
        # It must cancel the old optional HTTP request before new work starts.
        await runtime._on_voice_snapshot(frozenset({"robot-01"}))
        result = await asyncio.gather(optional, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert slow.cancelled
        assert visual.hub.user_active("robot-01", time.monotonic())
        assert not visual.hub.frames["robot-02"]
        assert visual._turn_epoch["robot-02"] == 1
        await runtime._on_voice_snapshot(frozenset())
        assert not visual.hub.user_active("robot-01", time.monotonic())
    finally:
        await visual.close()
