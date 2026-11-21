"""A human speaking to one Sense preempts the shared fleet speech floor."""
import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from desk_robot.runtime import Runtime


def configure_room_dispatch(runtime):
    """A partial Runtime fixture still owns its bounded USB handoff state."""
    runtime._room_dispatch_lock = threading.Lock()
    runtime._room_dispatch_pending = None
    runtime._room_dispatch_enqueued = False


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

    from desk_robot.multimodal import MultimodalOrchestrator
    from PIL import Image

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
        # A snapshot() call started does not mean its JPEG was decoded and
        # committed to the shared hub. Wait for the actual speech receipt.
        async with asyncio.timeout(2):
            while not visual.hub.frames["robot-01"]:
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


async def test_voice_monitor_outage_flushes_native_xiaozhi_without_operator_quiet():
    """A lost Mac VAD stream must stop the separate native head audio owner."""
    events = []

    class Pet:
        def set_voice_monitor_ready(self, ready):
            events.append(("monitor", ready))

        async def interrupt(self, robot_id):
            events.append(("pet", robot_id))

    class Speaker:
        async def monitor_lost(self, robot):
            # Dedicated bridge route suspends initiative without changing
            # the operator's saved quiet and pause choices.
            events.append(("native_stop", robot.device_id))

        async def interrupt(self, robot):
            raise AssertionError("Outage must use the native monitor route")

    class Conversation:
        speaker = Speaker()

        async def stop(self):
            events.append(("group", "stop"))

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(
        mode="hardware",
        robots=[
            SimpleNamespace(id="robot-01", device_id="mac-01"),
            SimpleNamespace(id="robot-02", device_id="mac-02"),
        ],
    )
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    await runtime._on_voice_global("stream_unavailable")
    assert events[0] == ("monitor", False)
    assert set(events[1:]) == {
        ("pet", "robot-01"), ("pet", "robot-02"),
        ("group", "stop"), ("native_stop", "mac-01"),
        ("native_stop", "mac-02"),
    }


async def test_voice_monitor_outage_reports_native_stop_failure_after_mac_abort():
    """A failed head STOP cannot be marked as an acknowledged fleet flush."""
    import pytest

    events = []

    class Pet:
        def set_voice_monitor_ready(self, ready):
            events.append(("monitor", ready))

        async def interrupt(self, robot_id):
            events.append(("pet", robot_id))

    class Speaker:
        async def interrupt(self, robot):
            raise RuntimeError("XIAO refused STOP")

    class Conversation:
        speaker = Speaker()

        async def stop(self):
            events.append(("group", "stop"))

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(
        mode="hardware",
        robots=[SimpleNamespace(id="robot-01", device_id="mac-01")],
    )
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    with pytest.raises(RuntimeError, match="physical speaker stop unconfirmed"):
        await runtime._on_voice_global("stream_unavailable")
    assert ("pet", "robot-01") in events
    assert ("group", "stop") in events


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
        voice_vision_tools_enabled=True,
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
    runtime._room_task = None
    runtime._closed = False
    runtime.multimodal = None
    runtime.pet = Pet()
    runtime.settings.room_station_enabled = False
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


async def test_monitor_loss_stalled_xiao_stop_cannot_starve_other_heads(monkeypatch):
    """Every real head gets its STOP attempt even if one ignores cancellation."""
    import asyncio

    import pytest

    monkeypatch.setattr("desk_robot.runtime._MONITOR_STOP_TIMEOUT_S", 0.05)
    events = []
    release = asyncio.Event()

    class Pet:
        def set_voice_monitor_ready(self, ready):
            events.append(("ready", ready))

        async def interrupt(self, robot_id):
            events.append(("pet", robot_id))

    class Speaker:
        async def monitor_lost(self, robot):
            events.append(("stop", robot.device_id))
            if robot.device_id == "mac-01":
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    await release.wait()

    class Conversation:
        speaker = Speaker()

        async def stop(self):
            events.append(("group", "stop"))

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(
        mode="hardware",
        robots=[
            SimpleNamespace(id="robot-01", device_id="mac-01"),
            SimpleNamespace(id="robot-02", device_id="mac-02"),
        ],
    )
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    try:
        with pytest.raises(RuntimeError, match="physical speaker stop unconfirmed"):
            await asyncio.wait_for(
                runtime._on_voice_global("stream_unavailable"), timeout=0.3
            )
        assert ("stop", "mac-01") in events
        assert ("stop", "mac-02") in events
        assert ("pet", "robot-01") in events
        assert ("pet", "robot-02") in events
        assert ("group", "stop") in events
    finally:
        release.set()
        await asyncio.sleep(0)


async def test_human_vad_camera_still_starts_when_fleet_audio_stop_fails():
    """Keep input camera live, but propagate uncertain physical audio STOP."""
    import pytest
    events = []

    class Pet:
        async def interrupt(self, robot_id):
            events.append("pet-stop")
            raise RuntimeError("failed pet decoder STOP")

    class Conversation:
        async def stop(self):
            events.append("group-stop")

    class Visual:
        def prepare_human_turn(self, robot_id, *, end_expected):
            events.append("vad-prepared")

        def start_speech_frames(self, robot_id):
            events.append("camera-start")

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(
        robots=[SimpleNamespace(id="robot-01")]
    )
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    runtime.multimodal = Visual()
    with pytest.raises(RuntimeError, match="Unable to preempt"):
        await runtime._on_voice_interrupt("robot-01", "speech_start")
    assert events == ["vad-prepared", "pet-stop", "group-stop", "camera-start"]


async def test_recovered_vad_snapshot_reconciles_camera_despite_failed_audio_stop():
    import pytest
    from desk_robot.multimodal import CameraFrameHub

    events = []
    hub = CameraFrameHub(["robot-01"])

    class Pet:
        async def interrupt(self, robot_id):
            events.append("pet-stop")
            raise RuntimeError("decoder still active")

    class Conversation:
        async def stop(self):
            events.append("group-stop")

    class Visual:
        def __init__(self):
            self.hub = hub

        def prepare_human_turn(self, robot_id, *, end_expected):
            events.append("vad-prepared")
            hub.notify(robot_id, "human_voice", time.monotonic())

        def start_speech_frames(self, robot_id):
            events.append("camera-start")

        def voice_ended(self, robot_id):
            events.append("camera-end")

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(
        robots=[SimpleNamespace(id="robot-01")]
    )
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    runtime.multimodal = Visual()
    with pytest.raises(RuntimeError, match="Unable to preempt"):
        await runtime._on_voice_snapshot(frozenset({"robot-01"}))
    assert events == ["vad-prepared", "pet-stop", "group-stop", "camera-start"]
    assert hub.user_active("robot-01", time.monotonic())
    assert hub.voice_until["robot-01"] == float("inf")


async def test_runtime_shutdown_attempts_other_owners_after_pet_cleanup_failure():
    """One stuck observer never suppresses camera, speaker or client cleanup."""
    events = []

    class Coordinator:
        async def close(self):
            events.append("wroom")

    class Pet:
        async def close(self):
            events.append("pet")
            raise TimeoutError("Pet observer cancellation unconfirmed")

    class Multimodal:
        async def close(self):
            events.append("camera")

    class Conversation:
        async def stop(self):
            events.append("speaker")

    class Client:
        async def aclose(self):
            events.append("client")

    runtime = Runtime.__new__(Runtime)
    configure_room_dispatch(runtime)
    runtime.settings = SimpleNamespace(mode="simulation")
    runtime._voice_task = None
    runtime.coordinator = Coordinator()
    runtime.pet = Pet()
    runtime.multimodal = Multimodal()
    runtime.conversation = Conversation()
    runtime.client = Client()

    with pytest.raises(TimeoutError, match="Pet observer cancellation unconfirmed"):
        await asyncio.wait_for(runtime.close(), timeout=1)
    assert events == ["wroom", "pet", "camera", "speaker", "client"]


async def test_runtime_shutdown_bounds_uncooperative_voice_monitor_and_continues(
    monkeypatch,
):
    monkeypatch.setattr("desk_robot.runtime._RUNTIME_VOICE_STOP_TIMEOUT_S", 0.05)
    events = []
    release = asyncio.Event()
    started = asyncio.Event()

    async def stubborn_monitor():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()

    class CloseOwner:
        async def close(self):
            events.append("owner")

        async def stop(self):
            events.append("speaker")

        async def aclose(self):
            events.append("client")

    runtime = Runtime.__new__(Runtime)
    configure_room_dispatch(runtime)
    runtime.settings = SimpleNamespace(mode="simulation")
    runtime.coordinator = CloseOwner()
    runtime.pet = CloseOwner()
    runtime.multimodal = CloseOwner()
    runtime.conversation = CloseOwner()
    runtime.client = CloseOwner()
    task = asyncio.create_task(stubborn_monitor())
    runtime._voice_task = task
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        with pytest.raises(TimeoutError, match="voice monitor shutdown unconfirmed"):
            await asyncio.wait_for(runtime.close(), timeout=0.5)
        assert events == ["owner", "owner", "owner", "speaker", "client"]
        assert not task.done()
        assert runtime._closed is True
        assert runtime._voice_task is task
        with pytest.raises(RuntimeError, match="Closed runtime"):
            await runtime.start()
        assert runtime._voice_task is task
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=0.3)


async def test_shutdown_fences_late_human_callbacks_after_blocked_stop():
    """A VAD edge already awaiting audio STOP cannot resurrect camera on close."""
    calls = []
    entered = asyncio.Event()
    release = asyncio.Event()

    class Pet:
        async def interrupt(self, robot_id):
            entered.set()
            await release.wait()

        def set_voice_monitor_ready(self, ready):
            calls.append(("monitor", ready))

    class Conversation:
        async def stop(self):
            calls.append(("speaker", "stop"))

    class Visual:
        def prepare_human_turn(self, robot_id, *, end_expected):
            calls.append(("prepare", robot_id))

        def start_speech_frames(self, robot_id):
            calls.append(("camera", robot_id))

    runtime = Runtime.__new__(Runtime)
    runtime._closed = False
    runtime.settings = SimpleNamespace(robots=[SimpleNamespace(id="robot-01")])
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    runtime.multimodal = Visual()
    interrupt = asyncio.create_task(
        runtime._on_voice_interrupt("robot-01", "speech_start")
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=0.5)
        runtime._closed = True  # Coordinator.close begins; voice task not yet retired.
        release.set()
        await asyncio.wait_for(interrupt, timeout=0.5)
        await runtime._on_voice_monitor_ready(True)
        await runtime._on_voice_interrupt("robot-01", "speech_start")
        await runtime._on_voice_snapshot(frozenset({"robot-01"}))
        await runtime._on_voice_global("stream_unavailable")
        assert calls == [("prepare", "robot-01"), ("speaker", "stop")]
    finally:
        release.set()
        await asyncio.gather(interrupt, return_exceptions=True)


@pytest.mark.parametrize("failed_peer", [None, "robot-01"])
async def test_hardware_runtime_close_stops_all_native_speakers(failed_peer):
    """Native decoders receive an independent shutdown abort, even if one fails."""
    events = []

    class Owner:
        def set_voice_monitor_ready(self, ready):
            events.append(("monitor", ready))

        async def close(self):
            events.append(("close", "owner"))

        async def stop(self):
            events.append(("close", "conversation"))

        async def aclose(self):
            events.append(("close", "http"))

    class Speaker:
        async def monitor_lost(self, robot):
            events.append(("native_stop", robot.id))
            if robot.id == failed_peer:
                raise RuntimeError("decoder STOP failed")

    runtime = Runtime.__new__(Runtime)
    configure_room_dispatch(runtime)
    runtime.settings = SimpleNamespace(mode="hardware", robots=[
        SimpleNamespace(id="robot-01", device_id="head01"),
        SimpleNamespace(id="robot-02", device_id="head02"),
    ])
    runtime._voice_task = None
    runtime.coordinator = Owner()
    runtime.pet = Owner()
    runtime.multimodal = None
    runtime.conversation = Owner()
    runtime.conversation.speaker = Speaker()
    runtime.client = Owner()

    if failed_peer is None:
        await runtime.close()
    else:
        with pytest.raises(RuntimeError, match="Native speaker shutdown STOP unconfirmed"):
            await runtime.close()
    assert runtime._closed
    assert ("native_stop", "robot-01") in events
    assert ("native_stop", "robot-02") in events
    assert events.index(("native_stop", "robot-01")) > events.index(("close", "owner"))
    assert ("close", "conversation") in events
    assert ("close", "http") in events


def test_room_usb_thread_callback_does_not_schedule_after_mac_shutdown():
    """A late read-only USB frame cannot reopen a closed Mac event loop."""
    runtime = Runtime.__new__(Runtime)
    configure_room_dispatch(runtime)
    events = []
    observation = object()
    runtime._closed = False
    runtime._on_room_observation = lambda value: events.append(value)

    class Loop:
        def call_soon_threadsafe(self, callback):
            events.append("scheduled")
            callback()

    runtime._queue_room_observation(Loop(), observation)
    assert events == ["scheduled", observation]
    events.clear()

    class ClosedLoop:
        def call_soon_threadsafe(self, callback):
            events.append("called_after_close")
            raise RuntimeError("Event loop is closed")

    runtime._closed = True
    runtime._queue_room_observation(ClosedLoop(), observation)
    assert not events  # do not call the dead event loop at all

    # A loop can close between checking the flag and scheduling. Ignore only
    # that genuine committed-shutdown race, not arbitrary active failures.
    class RacingLoop:
        def call_soon_threadsafe(self, callback):
            runtime._closed = True
            raise RuntimeError("Event loop is closed")

    runtime._closed = False
    runtime._queue_room_observation(RacingLoop(), observation)
    assert not events
    runtime._closed = False
    with pytest.raises(RuntimeError, match="Event loop is closed"):
        runtime._queue_room_observation(ClosedLoop(), observation)


async def test_human_voice_requests_roaming_stop_before_slow_audio_abort_finishes():
    """One real VAD edge dispatches the existing local motor stop concurrently.

    Slow Xiaozhi stop or another pet's audio cleanup must not defer WROOM
    exploration cancellation until AFTER voice playback teardown.
    """
    audio_started = asyncio.Event()
    release_audio = asyncio.Event()
    motor_stopped = asyncio.Event()

    class Pet:
        async def interrupt(self, robot_id):
            audio_started.set()
            await release_audio.wait()

    class Conversation:
        async def stop(self):
            await release_audio.wait()

    class Coordinator:
        async def stop_active_exploration(self):
            motor_stopped.set()
            return ("robot-01",)

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(robots=[
        SimpleNamespace(id="robot-01"), SimpleNamespace(id="robot-02"),
    ])
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    runtime.coordinator = Coordinator()
    task = asyncio.create_task(
        runtime._on_voice_interrupt("robot-02", "speech_start")
    )
    try:
        await asyncio.wait_for(audio_started.wait(), timeout=0.3)
        await asyncio.wait_for(motor_stopped.wait(), timeout=0.3)
        assert not task.done()
    finally:
        release_audio.set()
        await asyncio.wait_for(task, timeout=1)


async def test_voice_monitor_unready_stops_autonomous_roaming_only():
    motor_stopped = []
    monitor = []

    class Pet:
        def set_voice_monitor_ready(self, ready):
            monitor.append(ready)

    class Coordinator:
        async def stop_active_exploration(self):
            motor_stopped.append(True)

    runtime = Runtime.__new__(Runtime)
    runtime.pet = Pet()
    runtime.coordinator = Coordinator()
    await runtime._on_voice_monitor_ready(False)
    assert monitor == [False]
    assert motor_stopped == [True]
    await runtime._on_voice_monitor_ready(True)
    assert monitor == [False, True]
    assert motor_stopped == [True]


async def test_roaming_stop_transport_failure_is_not_silent():
    class Pet:
        async def interrupt(self, robot_id):
            return None

    class Conversation:
        async def stop(self):
            return None

    class Coordinator:
        async def stop_active_exploration(self):
            raise RuntimeError("WROOM physical STOP unconfirmed")

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(robots=[SimpleNamespace(id="robot-01")])
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    runtime.coordinator = Coordinator()
    with pytest.raises(RuntimeError, match="physical STOP unconfirmed"):
        await runtime._on_voice_interrupt("robot-01", "normal")


async def test_older_voice_stop_cannot_start_newer_turn_camera_early():
    """Two overlapping authenticated starts must each own their STOP barrier."""
    from desk_robot.multimodal import MultimodalOrchestrator

    entered = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]

    class DelayedPet:
        def __init__(self):
            self.calls = 0

        async def interrupt(self, robot_id):
            index = self.calls
            self.calls += 1
            entered[index].set()
            await release[index].wait()

    class Conversation:
        async def stop(self):
            pass

    class Head:
        async def snapshot(self):
            # A real capture is unnecessary: the test checks whether a camera
            # task was started before the current turn's device STOP completed.
            await asyncio.Event().wait()

    settings = SimpleNamespace(
        robots=[SimpleNamespace(id="robot-01")],
        voice_vision_tools_enabled=True, vision_model="local-vlm",
    )
    visual = MultimodalOrchestrator(
        settings, {"robot-01": Head()}, object(), asyncio.Lock(),
    )
    runtime = Runtime.__new__(Runtime)
    runtime.settings = settings
    runtime.pet = DelayedPet()
    runtime.conversation = Conversation()
    runtime.multimodal = visual
    first = asyncio.create_task(
        runtime._on_voice_interrupt("robot-01", "speech_start")
    )
    second = None
    try:
        await asyncio.wait_for(entered[0].wait(), timeout=1)
        first_epoch = visual._turn_epoch["robot-01"]
        second = asyncio.create_task(
            runtime._on_voice_interrupt("robot-01", "speech_start")
        )
        await asyncio.wait_for(entered[1].wait(), timeout=1)
        assert visual._turn_epoch["robot-01"] > first_epoch
        # The earlier STOP finishes first. It must not begin sampling camera
        # frames while the newer human request is still preempting the head.
        release[0].set()
        await asyncio.wait_for(first, timeout=1)
        assert visual._capture_tasks.get("robot-01") is None
        release[1].set()
        await asyncio.wait_for(second, timeout=1)
        assert visual._capture_tasks.get("robot-01") is not None
    finally:
        for event in release:
            event.set()
        await asyncio.gather(
            *([first] + ([second] if second is not None else [])),
            return_exceptions=True,
        )
        await visual.close()


async def test_late_recovered_vad_stop_cannot_sample_newer_turn():
    """A slow recovered snapshot must not bypass a later start's STOP barrier."""
    from desk_robot.multimodal import MultimodalOrchestrator

    entered = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]

    class Pet:
        def __init__(self):
            self.count = 0

        async def interrupt(self, robot_id):
            index = self.count
            self.count += 1
            entered[index].set()
            await release[index].wait()

    class Conversation:
        async def stop(self):
            pass

    class Head:
        async def snapshot(self):
            await asyncio.Event().wait()

    settings = SimpleNamespace(
        robots=[SimpleNamespace(id="robot-01")],
        voice_vision_tools_enabled=True, vision_model="local-vlm",
    )
    visual = MultimodalOrchestrator(
        settings, {"robot-01": Head()}, object(), asyncio.Lock(),
    )
    runtime = Runtime.__new__(Runtime)
    runtime.settings, runtime.pet = settings, Pet()
    runtime.conversation, runtime.multimodal = Conversation(), visual
    earlier = asyncio.create_task(runtime._on_voice_snapshot(frozenset({"robot-01"})))
    newer = None
    try:
        await asyncio.wait_for(entered[0].wait(), timeout=1)
        old_generation = visual._turn_epoch["robot-01"]
        newer = asyncio.create_task(
            runtime._on_voice_interrupt("robot-01", "speech_start")
        )
        await asyncio.wait_for(entered[1].wait(), timeout=1)
        assert visual._turn_epoch["robot-01"] > old_generation
        release[0].set()
        await asyncio.wait_for(earlier, timeout=1)
        assert visual._capture_tasks.get("robot-01") is None
        release[1].set()
        await asyncio.wait_for(newer, timeout=1)
        assert visual._capture_tasks.get("robot-01") is not None
    finally:
        for event in release:
            event.set()
        await asyncio.gather(
            *([earlier] + ([newer] if newer is not None else [])),
            return_exceptions=True,
        )
        await visual.close()


async def test_recovered_two_pet_vad_snapshot_starts_both_current_cameras():
    """A second recovered start invalidates peer epochs within one snapshot."""
    from desk_robot.multimodal import MultimodalOrchestrator

    class Pet:
        async def interrupt(self, robot_id):
            pass

    class Conversation:
        async def stop(self):
            pass

    class Head:
        async def snapshot(self):
            await asyncio.Event().wait()

    ids = ["robot-01", "robot-02"]
    settings = SimpleNamespace(
        robots=[SimpleNamespace(id=robot_id) for robot_id in ids],
        voice_vision_tools_enabled=True, vision_model="local-vlm",
    )
    visual = MultimodalOrchestrator(
        settings, {robot_id: Head() for robot_id in ids},
        object(), asyncio.Lock(),
    )
    runtime = Runtime.__new__(Runtime)
    runtime.settings, runtime.pet = settings, Pet()
    runtime.conversation, runtime.multimodal = Conversation(), visual
    try:
        await runtime._on_voice_snapshot(frozenset(ids))
        assert set(visual._capture_tasks) == set(ids)
        assert all(
            visual._capture_tasks[robot_id] is not None for robot_id in ids
        )
    finally:
        await visual.close()


async def test_recovered_snapshot_does_not_release_newer_human_voice():
    """Stale snapshot end for one pet must not clear a later real VAD start."""
    from desk_robot.multimodal import MultimodalOrchestrator

    entered = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]

    class Pet:
        def __init__(self):
            self.calls = 0

        async def interrupt(self, robot_id):
            index = self.calls
            self.calls += 1
            entered[index].set()
            await release[index].wait()

    class Conversation:
        async def stop(self):
            pass

    class Head:
        async def snapshot(self):
            await asyncio.Event().wait()

    ids = ("robot-01", "robot-02")
    settings = SimpleNamespace(
        robots=[SimpleNamespace(id=robot_id) for robot_id in ids],
        voice_vision_tools_enabled=True, vision_model="local-vlm",
    )
    visual = MultimodalOrchestrator(
        settings, {robot_id: Head() for robot_id in ids},
        object(), asyncio.Lock(),
    )
    runtime = Runtime.__new__(Runtime)
    runtime.settings, runtime.pet = settings, Pet()
    runtime.conversation, runtime.multimodal = Conversation(), visual
    # A prior real start owns robot-01, but the delayed snapshot says only
    # robot-02 is speaking and will try to release robot-01.
    visual.hub.notify("robot-01", "human_voice", time.monotonic())
    older = asyncio.create_task(runtime._on_voice_snapshot(frozenset({"robot-02"})))
    newer = None
    try:
        await asyncio.wait_for(entered[0].wait(), timeout=1)
        newer = asyncio.create_task(
            runtime._on_voice_interrupt("robot-01", "speech_start")
        )
        await asyncio.wait_for(entered[1].wait(), timeout=1)
        release[0].set()
        await asyncio.wait_for(older, timeout=1)
        assert visual.hub.user_active("robot-01", time.monotonic())
        assert visual._capture_tasks.get("robot-02") is None
        release[1].set()
        await asyncio.wait_for(newer, timeout=1)
        assert visual.hub.user_active("robot-01", time.monotonic())
    finally:
        for event in release:
            event.set()
        await asyncio.gather(
            *([older] + ([newer] if newer is not None else [])),
            return_exceptions=True,
        )
        await visual.close()


async def test_recovered_snapshot_does_not_revive_newer_speech_end():
    """A real end during slow STOP supersedes an old active snapshot."""
    from desk_robot.multimodal import CameraFrameHub

    ready, release = asyncio.Event(), asyncio.Event()

    class Pet:
        async def interrupt(self, robot_id):
            ready.set()
            await release.wait()

    class Conversation:
        async def stop(self):
            pass

    hub = CameraFrameHub(["robot-01"])

    class Visual:
        def __init__(self):
            self.hub = hub

        def voice_started(self, robot_id):
            self.hub.notify(robot_id, "human_voice", time.monotonic())

        def voice_ended(self, robot_id):
            self.hub.speech_ended(robot_id, time.monotonic())

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(
        robots=[SimpleNamespace(id="robot-01")]
    )
    runtime.pet = Pet()
    runtime.conversation, runtime.multimodal = Conversation(), Visual()
    older = asyncio.create_task(runtime._on_voice_snapshot(frozenset({"robot-01"})))
    try:
        await asyncio.wait_for(ready.wait(), timeout=1)
        await runtime._on_voice_interrupt("robot-01", "speech_end")
        assert not hub.user_active("robot-01", time.monotonic())
        release.set()
        await asyncio.wait_for(older, timeout=1)
        assert not hub.user_active("robot-01", time.monotonic())
    finally:
        release.set()
        await asyncio.gather(older, return_exceptions=True)
