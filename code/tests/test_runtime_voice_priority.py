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


async def test_hardware_monitor_loss_cancels_pending_pet_or_group_speech():
    """One lost VAD stream must retire an in-flight optional speech task."""
    import asyncio
    from desk_robot.pet import PetController

    started, cleaned = asyncio.Event(), asyncio.Event()

    async def optional_speech():
        started.set()
        try:
            await asyncio.Event().wait()  # A slow model or TTS generation.
        finally:
            cleaned.set()

    pet = PetController.__new__(PetController)
    pet.settings = SimpleNamespace(mode="hardware")
    pet.voice_monitor_ready = True
    pet._speech_task = asyncio.create_task(optional_speech())
    await asyncio.wait_for(started.wait(), timeout=1)
    pet.set_voice_monitor_ready(False)
    assert pet._speech_task.cancelling()
    await asyncio.gather(pet._speech_task, return_exceptions=True)
    assert cleaned.is_set()
    # Repeated loss notifications cannot restart or repeatedly cancel speech.
    pet.set_voice_monitor_ready(False)
    assert pet._speech_task.cancelled()


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


async def test_live_human_turn_fences_camera_before_slow_speaker_stop():
    """Audio stop may block, but old autonomous camera work cannot survive."""
    import asyncio
    from io import BytesIO

    from PIL import Image

    from desk_robot.multimodal import MultimodalOrchestrator

    ready, release = asyncio.Event(), asyncio.Event()

    class SlowStopPet:
        async def interrupt(self, robot_id):
            if robot_id == "robot-01":
                ready.set()
                await release.wait()

    class Conversation:
        async def stop(self):
            return None

    class Camera:
        def __init__(self, blocking=False):
            self.blocking = blocking
            self.started = asyncio.Event()
            self.cancelled = False
            self.captures = 0

        async def snapshot(self):
            self.captures += 1
            if self.blocking:
                self.started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            image = BytesIO()
            Image.new("RGB", (64, 48), "gray").save(image, "JPEG")
            return image.getvalue()

    heads = {"robot-01": Camera(), "robot-02": Camera(blocking=True)}
    settings = SimpleNamespace(
        robots=[SimpleNamespace(id=i) for i in heads],
        voice_vision_tools_enabled=True, vision_model="local-vlm",
    )
    visual = MultimodalOrchestrator(settings, heads, object(), asyncio.Lock())
    runtime = Runtime.__new__(Runtime)
    runtime.settings, runtime.pet = settings, SlowStopPet()
    runtime.conversation, runtime.multimodal = Conversation(), visual
    background = asyncio.create_task(
        visual.capture("robot-02", source="proactive")
    )
    interrupt = None
    try:
        await asyncio.wait_for(heads["robot-02"].started.wait(), timeout=1)
        interrupt = asyncio.create_task(
            runtime._on_voice_interrupt("robot-01", "speech_start")
        )
        await asyncio.wait_for(ready.wait(), timeout=1)
        # The fresh VAD is already active even while Xiaozhi audio STOP is
        # blocked; old optional HTTP must be cancelled immediately.
        assert visual.hub.user_active("robot-01", time.monotonic())
        async with asyncio.timeout(1):
            while not heads["robot-02"].cancelled:
                await asyncio.sleep(.01)
        assert heads["robot-01"].captures == 0
        assert not visual._capture_tasks.get("robot-01")
        assert not interrupt.done()
        release.set()
        await asyncio.wait_for(interrupt, timeout=1)
        async with asyncio.timeout(2):
            while heads["robot-01"].captures < 1:
                await asyncio.sleep(.01)
        assert visual.hub.frames["robot-01"][-1].source == "speech"
    finally:
        release.set()
        if interrupt is not None:
            await asyncio.gather(interrupt, return_exceptions=True)
        await asyncio.gather(background, return_exceptions=True)
        await visual.close()


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


def test_hardware_pet_autostart_needs_real_local_vision_and_camera_consent(settings):
    import pytest
    from desk_robot.config import Settings

    fields = settings.model_dump()
    fields["mode"] = "hardware"
    fields["pet_autostart_enabled"] = True
    with pytest.raises(ValueError, match="Proactive camera autostart"):
        Settings.model_validate(fields)
    fields["voice_vision_tools_enabled"] = True
    with pytest.raises(ValueError, match="Proactive camera autostart"):
        Settings.model_validate(fields)
    fields["vision_model"] = "local-vision-model"
    accepted = Settings.model_validate(fields)
    assert accepted.pet_autostart_enabled is True
    assert accepted.mode == "hardware"
    assert accepted.voice_vision_tools_enabled is True


async def test_autonomous_observation_starts_without_voice_or_motor_authority(
    monkeypatch,
):
    import asyncio

    events = []
    hold = asyncio.Event()

    class VoiceListener:
        def __init__(self, *args, **kwargs):
            events.append("voice monitor registered")

        async def run(self):
            await hold.wait()

    class Pet:
        def start(self, robot_id):
            events.append(("pet observed", robot_id))
            return {"enabled": True}

    monkeypatch.setattr("desk_robot.runtime.VoiceEventListener", VoiceListener)
    monkeypatch.setattr("desk_robot.runtime.secret", lambda name: "s" * 32)
    runtime = Runtime.__new__(Runtime)
    runtime.client = object()
    runtime.settings = SimpleNamespace(
        mode="hardware",
        speech_bridge_url="http://127.0.0.1:8766",
        speech_bridge_token_env="DESK_ROBOT_SPEECH_TOKEN",
        pet_autostart_enabled=True,
        robots=[
            SimpleNamespace(id="robot-01", device_id="live-01"),
            SimpleNamespace(id="robot-02", device_id=""),
        ],
    )
    runtime._voice_task = None
    runtime.voice_events = None
    runtime.pet = Pet()
    try:
        await runtime.start()
        assert events == [
            "voice monitor registered",
            ("pet observed", "robot-01"),
        ]
        assert runtime._voice_task is not None
    finally:
        hold.set()
        if runtime._voice_task is not None:
            runtime._voice_task.cancel()
            await asyncio.gather(runtime._voice_task, return_exceptions=True)


async def test_authenticated_vad_recovery_restarts_existing_live_camera_only_when_ready():
    from desk_robot.multimodal import CameraFrameHub

    hub = CameraFrameHub(["robot-01"])
    hub.notify("robot-01", "human_voice", time.monotonic())
    starts = []

    class Visual:
        _reconnect_needs_sampler = {"robot-01"}

        def voice_started(self, robot_id):
            starts.append(robot_id)

        def voice_ended(self, robot_id):
            raise AssertionError("Active human VAD may not be released")

    visual = Visual()
    visual.hub = hub
    pet = SimpleNamespace(voice_monitor_ready=False)
    runtime = Runtime.__new__(Runtime)
    runtime.multimodal = visual
    runtime.pet = pet
    await runtime._on_voice_snapshot(frozenset({"robot-01"}))
    assert starts == []
    assert visual._reconnect_needs_sampler == {"robot-01"}
    pet.voice_monitor_ready = True
    await runtime._on_voice_snapshot(frozenset({"robot-01"}))
    assert starts == ["robot-01"]
    assert not visual._reconnect_needs_sampler
    assert hub.user_active("robot-01", time.monotonic())


async def test_voice_outage_invalidates_camera_before_concurrent_audio_abort():
    events = []

    class Pet:
        def set_voice_monitor_ready(self, ready):
            events.append(("monitor", ready))

        async def interrupt(self, robot_id):
            events.append(("audio", robot_id))

    class Talk:
        async def stop(self):
            events.append(("audio", "group"))

    class Visual:
        def voice_transport_unavailable(self):
            events.append(("camera", "invalidated"))

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(robots=[
        SimpleNamespace(id="robot-01"),
    ])
    runtime.pet = Pet()
    runtime.conversation = Talk()
    runtime.multimodal = Visual()
    await runtime._on_voice_global("stream_unavailable")
    assert events == [
        ("monitor", False),
        ("camera", "invalidated"),
        ("audio", "robot-01"),
        ("audio", "group"),
    ]

async def test_authenticated_vad_snapshot_upgrades_finite_aec_barge_hold():
    """A short AEC lease must not hide a genuine missed VAD start."""
    from desk_robot.multimodal import CameraFrameHub

    now = time.monotonic()
    hub = CameraFrameHub(["robot-01"])
    hub.barge_in("robot-01", now)
    assert hub.user_active("robot-01", now)
    assert hub.voice_until["robot-01"] != float("inf")

    events = []

    class Pet:
        async def interrupt(self, robot_id):
            events.append(("pet", robot_id))

    class Conversation:
        async def stop(self):
            events.append(("speaker", "stop"))

    class Visual:
        def __init__(self):
            self.hub = hub

        def voice_started(self, robot_id):
            events.append(("camera", "start"))
            hub.notify(robot_id, "human_voice", time.monotonic())

        def voice_ended(self, robot_id):
            events.append(("camera", "end"))
            hub.speech_ended(robot_id, time.monotonic())

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(
        robots=[SimpleNamespace(id="robot-01")],
    )
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    runtime.multimodal = Visual()

    await runtime._on_voice_snapshot(frozenset({"robot-01"}))
    assert events == [
        ("pet", "robot-01"), ("speaker", "stop"),
        ("camera", "start"),
    ]
    assert hub.voice_until["robot-01"] == float("inf")
    await runtime._on_voice_snapshot(frozenset({"robot-01"}))
    assert len(events) == 3
    await runtime._on_voice_snapshot(frozenset())
    assert events[-1] == ("camera", "end")
    assert not hub.user_active("robot-01", time.monotonic())
