"""A human speaking to one Sense preempts the shared fleet speech floor."""
import asyncio
import threading
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from desk_robot.conversation import Conversation
from desk_robot.pet import PetController
from desk_robot.runtime import Runtime
from desk_robot.simulator import SimulatedChat, SimulatedSpeaker


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
    """VAD fences old camera work and dispatches motion STOP during audio abort."""
    import asyncio
    from io import BytesIO

    from desk_robot.multimodal import MultimodalOrchestrator
    from PIL import Image

    ready, release = asyncio.Event(), asyncio.Event()
    motion_stop_dispatched = asyncio.Event()

    class SlowStopPet:
        async def interrupt(self, robot_id):
            if robot_id == "robot-01":
                ready.set()
                await release.wait()

    class Conversation:
        async def stop(self):
            return None

    class Coordinator:
        async def stop_active_exploration(self):
            motion_stop_dispatched.set()
            return ("robot-02",)

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
    runtime.coordinator = Coordinator()
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
        # The motion owner must receive STOP while the speaker is still blocked.
        # This is software dispatch evidence, not a physical stopping time.
        await asyncio.wait_for(motion_stop_dispatched.wait(), timeout=1)
        assert runtime._voice_stop_unconfirmed is True
        assert heads["robot-01"].captures == 0
        assert not visual._capture_tasks.get("robot-01")
        assert not interrupt.done()
        release.set()
        await asyncio.wait_for(interrupt, timeout=1)
        assert runtime._voice_stop_unconfirmed is False
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
    # Simulation can share mock endpoints and voices; hardware cannot.
    for index, robot in enumerate(fields["robots"], start=1):
        robot["head_url"] = f"http://192.168.1.{100 + index}:8081"
        robot["voice"] = f"test_voice_{index}"
    fields["pet_autostart_enabled"] = True
    with pytest.raises(ValueError, match="Proactive camera autostart"):
        Settings.model_validate(fields)
    fields["voice_vision_tools_enabled"] = True
    with pytest.raises(ValueError, match="Proactive camera autostart"):
        Settings.model_validate(fields)
    fields["vision_model"] = "local-vision-model"
    with pytest.raises(ValueError, match="mapped Xiaozhi device_id"):
        Settings.model_validate(fields)
    fields["robots"][0]["device_id"] = " "
    with pytest.raises(ValueError, match=r"mapped Xiaozhi device_id|String should match pattern"):
        Settings.model_validate(fields)
    fields["robots"][0]["device_id"] = "live-01"
    fields["vision_model"] = " "
    with pytest.raises(ValueError, match="local VLM"):
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
        # This partial fixture does not own hardware shutdown dependencies.
        # Retiring its fake listener explicitly is not a service crash.
        runtime._closed = True
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
    other_head_stopped = asyncio.Event()

    class Pet:
        def set_voice_monitor_ready(self, ready):
            events.append(("ready", ready))

        async def interrupt(self, robot_id):
            events.append(("pet", robot_id))

    class Speaker:
        async def monitor_lost(self, robot):
            events.append(("stop", robot.device_id))
            if robot.device_id == "mac-02":
                other_head_stopped.set()
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
    task = asyncio.create_task(runtime._on_voice_global("stream_unavailable"))
    try:
        # A runnable second head must receive STOP before the stalled head
        # acknowledges anything. This causal check is independent of runner
        # scheduling while the production stop budget stays at 50 ms here.
        await asyncio.wait_for(other_head_stopped.wait(), timeout=2)
        assert not release.is_set()
        with pytest.raises(RuntimeError, match="physical speaker stop unconfirmed"):
            await asyncio.wait_for(task, timeout=2)
        assert ("stop", "mac-01") in events
        assert ("stop", "mac-02") in events
        assert ("pet", "robot-01") in events
        assert ("pet", "robot-02") in events
        assert ("group", "stop") in events
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


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
    # Production always supplies Settings. This isolated shutdown fixture
    # must also supply the existing room observation consent epoch.
    runtime.settings = SimpleNamespace(
        room_station_context_enabled=True,
        room_station_consent_generation=0,
    )
    events = []
    observation = object()
    runtime._closed = False
    def consume(value, *, epoch, grant_generation):
        events.append((value, epoch, grant_generation))

    runtime._on_room_observation = consume

    class Loop:
        def call_soon_threadsafe(self, callback):
            events.append("scheduled")
            callback()

    runtime._queue_room_observation(Loop(), observation)
    assert events == ["scheduled", (observation, 0, 0)]
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
            # One real VAD preempts every pet; only one physical head is
            # blocked per interruption in this test's two STOP barriers.
            if robot_id != "robot-01":
                return
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

class _FailingStopSpeaker(SimulatedSpeaker):
    """Physical speaker fake whose decoder STOP can fail independently."""

    supports_passive_speech_budget = True

    def __init__(self):
        super().__init__()
        self.send_started = asyncio.Event()
        self.block_send = True
        self.fail_stop = True
        self.interruptions = []

    @asynccontextmanager
    async def session(self, robots, *, passive=False):
        del robots, passive
        yield

    async def say(self, robot, text, *, permission_check=None):
        if permission_check is not None and not permission_check():
            raise RuntimeError("Speech permission revoked")
        self.send_started.set()
        if self.block_send:
            await asyncio.Event().wait()
        await super().say(robot, text, permission_check=permission_check)

    async def interrupt(self, robot):
        self.interruptions.append(robot.id)
        if self.fail_stop:
            raise TimeoutError("XIAO decoder STOP timeout")


def _runtime_for_speaker_failure(settings, conversation, pet):
    runtime = Runtime.__new__(Runtime)
    runtime.settings = settings
    runtime.conversation = conversation
    runtime.pet = pet
    runtime.multimodal = None
    runtime.coordinator = None
    runtime.attention = None
    runtime._closed = False
    return runtime


async def test_runtime_vad_failed_group_decoder_stop_blocks_successor_until_recovery(
    settings,
):
    """A cancelled group is not a confirmed physical speaker STOP."""
    settings.mode = "hardware"
    settings.fleet_text_sharing_enabled = True
    for index, robot in enumerate(settings.robots, start=1):
        robot.device_id = f"head-{index:02d}"

    speaker = _FailingStopSpeaker()
    conversation = Conversation(settings, SimulatedChat(), speaker)

    class Pet:
        async def interrupt(self, robot_id):
            settings.robot(robot_id)
            return {"robot_id": robot_id}

    runtime = _runtime_for_speaker_failure(settings, conversation, Pet())
    group = asyncio.create_task(
        conversation.run(["robot-01", "robot-02"], "Check the desk", 1)
    )
    await asyncio.wait_for(speaker.send_started.wait(), timeout=1)

    with pytest.raises(RuntimeError, match="Unable to preempt"):
        await runtime._on_voice_interrupt("robot-01", "normal")
    await asyncio.gather(group, return_exceptions=True)

    assert conversation.active is None
    assert conversation.speaker_stop_unconfirmed is True
    with pytest.raises(RuntimeError, match="speaker STOP unconfirmed"):
        await conversation.run(["robot-01", "robot-02"], "Stale successor", 1)

    speaker.fail_stop = False
    await conversation.stop()
    assert conversation.speaker_stop_unconfirmed is False

    speaker.block_send = False
    transcript = await conversation.run(
        ["robot-01", "robot-02"], "Recovered successor", 1
    )
    assert transcript == [
        {"robot_id": "robot-01", "text": "I see a candy on the desk."}
    ]
    assert speaker.spoken[-1] == ("robot-01", "I see a candy on the desk.")


async def test_runtime_vad_failed_proactive_decoder_stop_blocks_successor_until_recovery(
    settings,
):
    """Pet cancellation preserves the same failed decoder STOP latch."""
    settings.mode = "hardware"
    robot = settings.robot("robot-01")
    robot.device_id = "head-01"

    speaker = _FailingStopSpeaker()
    conversation = Conversation(settings, SimulatedChat(), speaker)
    speech = asyncio.create_task(
        conversation.say_proactive(
            robot,
            "A proactive line",
            permission_check=lambda: True,
            deliberate=True,
        )
    )
    await asyncio.wait_for(speaker.send_started.wait(), timeout=1)

    owner = PetController.__new__(PetController)
    owner._speech_task = speech
    owner._speech_participants = {robot.id}
    owner.conversation = conversation

    class Pet:
        async def interrupt(self, robot_id):
            await PetController._cancel_speech(owner, robot_id)
            return {"robot_id": robot_id}

    runtime = _runtime_for_speaker_failure(settings, conversation, Pet())
    with pytest.raises(RuntimeError, match="Unable to preempt"):
        await runtime._on_voice_interrupt(robot.id, "normal")
    await asyncio.gather(speech, return_exceptions=True)

    assert conversation.speaker_stop_unconfirmed is True
    with pytest.raises(RuntimeError, match="speaker STOP unconfirmed"):
        await conversation.say_proactive(
            robot,
            "Must stay blocked",
            permission_check=lambda: True,
            deliberate=True,
        )

    speaker.fail_stop = False
    await conversation.stop()
    assert conversation.speaker_stop_unconfirmed is False

    speaker.block_send = False
    assert await conversation.say_proactive(
        robot,
        "Recovered proactive line",
        permission_check=lambda: True,
        deliberate=True,
    )
    assert speaker.spoken[-1] == ("robot-01", "Recovered proactive line")


async def test_failed_recovered_vad_snapshot_retries_stop_without_restarting_camera():
    """Repeated active VAD is not an ACK for a failed five-pet speaker STOP."""
    from desk_robot.multimodal import CameraFrameHub

    attempts = []
    camera = []
    hub = CameraFrameHub(["robot-01"])

    class Pet:
        async def interrupt(self, robot_id):
            attempts.append(("pet", robot_id))
            if len([x for x in attempts if x[0] == "pet"]) < 3:
                raise RuntimeError("head decoder still playing")

    class Conversation:
        async def stop(self):
            attempts.append(("group", "stop"))

    class Visual:
        def prepare_human_turn(self, robot_id, *, end_expected):
            camera.append(("prepare", robot_id))
            hub.notify(robot_id, "human_voice", time.monotonic())

        def start_speech_frames(self, robot_id):
            camera.append(("camera", robot_id))

        def voice_ended(self, robot_id):
            hub.speech_ended(robot_id, time.monotonic())

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(robots=[SimpleNamespace(id="robot-01")])
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    runtime.multimodal = Visual()
    runtime.multimodal.hub = hub
    for attempt in range(2):
        with pytest.raises(RuntimeError, match="Unable to preempt"):
            await runtime._on_voice_snapshot(frozenset({"robot-01"}))
        assert runtime._voice_stop_unconfirmed is True
        assert hub.voice_until["robot-01"] == float("inf")
        assert len([x for x in attempts if x[0] == "pet"]) == attempt + 1
    assert camera == [("prepare", "robot-01"), ("camera", "robot-01")]
    await runtime._on_voice_snapshot(frozenset({"robot-01"}))
    assert runtime._voice_stop_unconfirmed is False
    assert len([x for x in attempts if x[0] == "pet"]) == 3
    await runtime._on_voice_snapshot(frozenset({"robot-01"}))
    assert len([x for x in attempts if x[0] == "pet"]) == 3
    assert camera == [("prepare", "robot-01"), ("camera", "robot-01")]
    await runtime._on_voice_snapshot(frozenset())
    assert not hub.user_active("robot-01", time.monotonic())


async def test_failed_monitor_outage_stop_requires_retry_before_monitor_recovery():
    from desk_robot.multimodal import CameraFrameHub

    hub = CameraFrameHub(["robot-01"])
    hub.notify("robot-01", "human_voice", time.monotonic())
    calls = []

    class Pet:
        def set_voice_monitor_ready(self, ready):
            calls.append(("monitor", ready))

        async def interrupt(self, robot_id):
            calls.append(("pet", robot_id))
            if len([x for x in calls if x[0] == "pet"]) < 2:
                raise RuntimeError("Xiaozhi STOP failed")

    class Conversation:
        async def stop(self):
            calls.append(("group", "stop"))

    class Visual:
        def __init__(self):
            self.hub = hub
            self._reconnect_needs_sampler = {"robot-01"}

        def voice_transport_unavailable(self):
            calls.append(("visual", "offline"))

        def voice_started(self, robot_id):
            calls.append(("visual", "recovered"))

        def voice_ended(self, robot_id):
            raise AssertionError("Human VAD did not end")

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(
        robots=[SimpleNamespace(id="robot-01")], mode="simulation",
    )
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    runtime.multimodal = Visual()
    with pytest.raises(RuntimeError, match="physical speaker stop unconfirmed"):
        await runtime._on_voice_global("stream_unavailable")
    assert runtime._voice_stop_unconfirmed is True
    await runtime._on_voice_snapshot(frozenset({"robot-01"}))
    assert runtime._voice_stop_unconfirmed is False
    assert len([x for x in calls if x[0] == "pet"]) == 2


async def test_runtime_shutdown_stops_native_voice_before_optional_worker_joins(monkeypatch):
    """Blocked native vision or USB cleanup must not delay decoder STOP."""
    from unittest.mock import AsyncMock

    calls = []
    monitor_started = asyncio.Event()
    vision_entered = asyncio.Event()
    release = asyncio.Event()

    async def close_motion():
        calls.append("wroom")

    async def stop_native(robot):
        assert robot.id == "robot-01"
        calls.append("native speaker STOP")

    async def close_vision():
        calls.append("vision")
        vision_entered.set()
        await release.wait()

    async def monitor():
        monitor_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            calls.append("voice monitor retired")

    runtime = Runtime.__new__(Runtime)
    configure_room_dispatch(runtime)
    runtime.settings = SimpleNamespace(
        mode="hardware",
        robots=[SimpleNamespace(id="robot-01", device_id="head01")],
    )
    runtime._room_stop = asyncio.Event()

    async def room_reader():
        await runtime._room_stop.wait()
        await release.wait()

    runtime.coordinator = SimpleNamespace(
        close=AsyncMock(side_effect=close_motion),
        shutdown_stop_failures={},
        vision=SimpleNamespace(close=AsyncMock(side_effect=close_vision)),
    )
    runtime.pet = SimpleNamespace(
        close=AsyncMock(), set_voice_monitor_ready=lambda ready: None,
    )
    runtime.conversation = SimpleNamespace(
        stop=AsyncMock(),
        speaker=SimpleNamespace(monitor_lost=AsyncMock(side_effect=stop_native)),
    )
    runtime.client = SimpleNamespace(aclose=AsyncMock())
    runtime.multimodal = None
    monkeypatch.setattr("desk_robot.dock_runtime.close_detector_pool", AsyncMock())
    voice_task = asyncio.create_task(monitor())
    room_task = asyncio.create_task(room_reader())
    runtime._voice_task = voice_task
    runtime._room_task = room_task

    await asyncio.wait_for(monitor_started.wait(), timeout=1)
    shutdown = asyncio.create_task(runtime.close())
    try:
        await asyncio.wait_for(vision_entered.wait(), timeout=1)
        assert calls == [
            "wroom", "native speaker STOP", "voice monitor retired", "vision",
        ]
        assert runtime._room_stop.is_set()
        assert voice_task.cancelled()
        assert runtime._voice_task is None
        assert not room_task.done()
        assert runtime._room_task is room_task
        release.set()
        await asyncio.wait_for(shutdown, timeout=1)
        assert room_task.done() and not room_task.cancelled()
        assert runtime._room_task is None
        runtime.client.aclose.assert_awaited_once()
    finally:
        release.set()
        runtime._room_stop.set()
        await asyncio.gather(shutdown, room_task, voice_task, return_exceptions=True)


async def test_api_stop_dispatches_xiao_speaker_stop_while_wroom_stop_is_blocked(
    settings, tokens, monkeypatch,
):
    """Blocked WROOM STOP must never delay urgent XIAO speaker interruption."""
    from unittest.mock import AsyncMock

    from desk_robot.api import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DESK_ROBOT_SPEECH_TOKEN", "s" * 32)
    stop_hold = asyncio.Event()

    class StubVoiceListener:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self):
            await stop_hold.wait()

    monkeypatch.setattr("desk_robot.runtime.VoiceEventListener", StubVoiceListener)
    settings.mode = "hardware"
    settings.robots[0].device_id = "xiao-01"
    wroom_entered = asyncio.Event()
    wroom_release = asyncio.Event()
    speaker_stopped = asyncio.Event()

    async def slow_wroom_stop(robot_id):
        wroom_entered.set()
        await wroom_release.wait()
        return {"robot_id": robot_id, "halted": True}

    async def fast_speaker_stop(robot):
        speaker_stopped.set()

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        runtime.coordinator.stop = slow_wroom_stop
        runtime.coordinator.close = AsyncMock()
        runtime.conversation.speaker.operator_stop = fast_speaker_stop
        runtime.conversation.speaker.monitor_lost = AsyncMock()
        stop_endpoint = next(
            route.endpoint for route in client.app.routes
            if getattr(route, "path", None) == "/v1/robots/{robot_id}/stop"
        )
        task = asyncio.create_task(stop_endpoint("robot-01"))
        try:
            await asyncio.wait_for(wroom_entered.wait(), timeout=0.5)
            await asyncio.wait_for(speaker_stopped.wait(), timeout=0.5)
            assert not task.done()
        finally:
            wroom_release.set()
            await asyncio.wait_for(task, timeout=1.0)
    stop_hold.set()


async def test_voice_blocks_motion_and_dispatches_deferred_fifo_after_speech_end(settings, tmp_path):
    """Active human speech blocks immediate motion and drains deferred FIFO cleanly."""
    from desk_robot.config import Settings

    sim_settings = Settings(
        robots=[settings.robots[0]],
        mode="simulation",
        memory_dir=tmp_path / "mem",
        trials_file=tmp_path / "trials.jsonl",
    )
    sim_settings.robots[0].motion_enabled = True
    sim_settings.robots[0].exploration_qualified = True

    runtime = Runtime(sim_settings)
    commands: list[str] = []
    preflights = 0
    original_command = runtime.coordinator.heads["robot-01"].command
    original_preflight = runtime.coordinator._hardware_preflight

    async def tracked_command(cmd):
        commands.append(cmd)
        return await original_command(cmd)

    async def tracked_preflight(robot_id):
        nonlocal preflights
        preflights += 1
        await original_preflight(robot_id)

    runtime.coordinator.heads["robot-01"].command = tracked_command
    runtime.coordinator._hardware_preflight = tracked_preflight

    try:
        await runtime.coordinator.operator_arm("robot-01")
        roaming = runtime.coordinator.explore("robot-01")
        await asyncio.sleep(0.05)

        await runtime._on_voice_interrupt("robot-01", "speech_start")
        assert roaming.state in {"cancelled", "failed"} or runtime.coordinator.tasks[roaming.id].done()
        commands.clear()

        # Grant a permit in idle gap then immediately activate human speech to prove
        # a pre-existing permit is blocked during speech_start without starting ARM.
        runtime.coordinator.set_voice_state(active_robots=set())
        await runtime.coordinator.operator_arm("robot-01")
        runtime.coordinator.set_voice_state(active_robots={"robot-01"})

        with pytest.raises(Exception, match="Voice priority"):
            runtime.coordinator.manual("robot-01", "drive 10 10 80")
        with pytest.raises(Exception, match="Voice priority"):
            await runtime.coordinator.operator_arm("robot-01")

        # Defer first request using the pre-speech permit (immediately retired).
        req1 = runtime.coordinator.defer_motion(
            "robot-01", "manual",
            submit_fn=lambda: runtime.coordinator.manual("robot-01", "drive 5 5 60"),
        )
        assert "robot-01" not in runtime.coordinator.permits

        runtime.coordinator.set_voice_state(active_robots=set())
        await runtime.coordinator.operator_arm("robot-01")
        runtime.coordinator.set_voice_state(active_robots={"robot-01"})
        req2 = runtime.coordinator.defer_motion(
            "robot-01", "manual",
            submit_fn=lambda: runtime.coordinator.manual("robot-01", "drive 8 8 60"),
        )
        preflights_before_end = preflights
        await runtime._on_voice_interrupt("robot-01", "speech_end")

        async with asyncio.timeout(2.0):
            while req2.state == "queued":
                await asyncio.sleep(0.02)
            while req1.job_id and runtime.coordinator.jobs[req1.job_id].state in {"queued", "running"}:
                await asyncio.sleep(0.02)
            while req2.job_id and runtime.coordinator.jobs[req2.job_id].state in {"queued", "running"}:
                await asyncio.sleep(0.02)

        assert req1.state == "dispatched" and req2.state == "dispatched"
        assert preflights >= preflights_before_end + 2
        drive_cmds = [c for c in commands if c.startswith("drive ")]
        assert drive_cmds == ["drive 5 5 60", "drive 8 8 60"]
        # Canceled roaming before speech never restarted automatically.
        assert not any(
            j.kind == "exploration" and j.id != roaming.id
            for j in runtime.coordinator.jobs.values()
        )
    finally:
        await runtime.close()


async def test_deferred_motion_discards_on_stop_or_monitor_outage(settings, tmp_path):
    """Explicit STOP or voice monitor outage must discard deferred FIFO requests."""
    from desk_robot.config import Settings

    sim_settings = Settings(
        robots=[settings.robots[0]],
        mode="simulation",
        memory_dir=tmp_path / "mem",
        trials_file=tmp_path / "trials.jsonl",
    )
    sim_settings.robots[0].motion_enabled = True
    runtime = Runtime(sim_settings)
    try:
        await runtime.coordinator.operator_arm("robot-01")
        runtime.coordinator.set_voice_state(
            active_robots={"robot-01"}, monitor_enforced=True, monitor_ready=True,
        )
        req1 = runtime.coordinator.defer_motion(
            "robot-01", "manual",
            submit_fn=lambda: runtime.coordinator.manual("robot-01", "drive 5 5 50"),
        )
        await runtime.coordinator.stop("robot-01")
        assert req1.state == "discarded"

        runtime.coordinator.set_voice_state(active_robots=set(), monitor_ready=True)
        await runtime.coordinator.operator_arm("robot-01")
        runtime.coordinator.set_voice_state(active_robots={"robot-01"}, monitor_ready=True)
        req2 = runtime.coordinator.defer_motion(
            "robot-01", "manual",
            submit_fn=lambda: runtime.coordinator.manual("robot-01", "drive 6 6 50"),
        )
        await runtime._on_voice_monitor_ready(False)
        assert req2.state == "discarded"
        await runtime._on_voice_monitor_ready(True)
        assert req2.state == "discarded"
        assert req2.job_id is None
    finally:
        await runtime.close()


@pytest.mark.parametrize("floor", ["silent", "human", "tool"])
async def test_background_context_preserves_speaker_floor(settings, tmp_path, floor):
    """Room and fictional memory writes must not acquire or revoke speech authority."""
    import json

    from desk_robot.memory import MemoryStore
    from desk_robot.multimodal import CameraFrameHub
    from desk_robot.room_station import RoomStationDecoder

    settings.mode = "hardware"
    settings.fleet_text_sharing_enabled = True
    settings.room_station_context_enabled = True
    for index, robot in enumerate(settings.robots, start=1):
        robot.device_id = f"head-{index:02d}"
    ids = [robot.id for robot in settings.robots]
    memory = MemoryStore(tmp_path, ids)
    speaker = _FailingStopSpeaker()
    speaker.fail_stop = False
    conversation = Conversation(settings, SimulatedChat(), speaker, memory=memory)
    runtime = _runtime_for_speaker_failure(settings, conversation, SimpleNamespace())
    configure_room_dispatch(runtime)
    runtime.room_context_failures = 0
    runtime._room_connection_epoch = 0
    hub = CameraFrameHub(ids, room_settings=settings)
    runtime.multimodal = SimpleNamespace(hub=hub)
    now = time.monotonic()
    group = None
    try:
        if floor == "human":
            hub.notify(ids[0], "human_voice", now)
        elif floor == "tool":
            # Model a completed tool cue alongside an occupied real Mac speech lease.
            hub.remember_tool(ids[0], "robot_status", "Status received", now)
            group = asyncio.create_task(conversation.run(ids[:2], "Read the status", 1))
            await asyncio.wait_for(speaker.send_started.wait(), timeout=1)
            assert conversation.session_lock.locked()
            assert conversation.speaker_lock.locked()

        voice_before = dict(hub.voice_until)
        quiet_before = dict(hub.quiet_until)
        urgent_before = dict(hub.urgent)
        events_before = {key: tuple(value) for key, value in hub.event_history.items()}
        tools_before = {key: tuple(value) for key, value in hub.tool_history.items()}
        active_before = conversation.active
        generation_before = conversation.stop_generation
        session_before = conversation.session_lock.locked()
        speaker_before = conversation.speaker_lock.locked()
        busy_before = hub.spontaneous_floor_busy(now)

        payload = {
            "v": 1, "station": "room-pod-01", "seq": 1, "at_ms": 1000,
            "readings": {
                "scd40": {"valid": True, "sample_ms": 1000, "co2_ppm": 900,
                          "temp_c": 25.0, "humidity_pct": 45.0},
                "bme688": {"valid": False}, "ld2410c": {"valid": False},
                "soil": {"valid": False}, "amg8833": {"valid": False},
            },
        }
        observation = RoomStationDecoder().accept(json.dumps(payload), now=now)
        runtime._queue_room_observation(asyncio.get_running_loop(), observation)
        # Exercise the storage boundary for a background fictional memory.
        assert await asyncio.to_thread(
            memory.remember, ids[0], "dream785", "An imagined room adventure",
            kind="fictional_dream", source_robot=ids[0], witnessed=True,
        )
        await asyncio.sleep(0)
        assert hub.shared_room == observation
        assert hub.shared_room is not observation
        assert runtime.room_context_failures == 0
        assert memory.get_episode(ids[0], "dream785").kind == "fictional_dream"
        assert memory.get_episode(ids[1], "dream785") is None
        assert hub.voice_until == voice_before
        assert hub.quiet_until == quiet_before
        assert hub.urgent == urgent_before
        assert {key: tuple(value) for key, value in hub.event_history.items()} == events_before
        assert {key: tuple(value) for key, value in hub.tool_history.items()} == tools_before
        assert hub.spontaneous_floor_busy(now) is busy_before
        assert conversation.active is active_before
        assert conversation.stop_generation == generation_before
        assert conversation.session_lock.locked() is session_before
        assert conversation.speaker_lock.locked() is speaker_before
        assert not speaker.interruptions
        assert not speaker.spoken
        if group is not None:
            assert not group.done() and not group.cancelling()
    finally:
        if group is not None:
            group.cancel()
            await asyncio.gather(group, return_exceptions=True)


@pytest.mark.parametrize(
    ("reason", "generation", "new_turn"),
    [("stream_unavailable", 7, False), ("gap", 7, False),
     ("gap", 8, True), ("reset", 7, True)],
)
async def test_reconnect_preserves_same_turn_but_fences_missed_turn(
    reason, generation, new_turn,
):
    from desk_robot.attention import AttentionLedger
    from desk_robot.multimodal import CameraFrameHub

    calls = []
    starts = []

    async def interrupt(robot_id):
        calls.append(robot_id)

    async def stop():
        calls.append("group_stop")

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(robots=[SimpleNamespace(id="p")])
    runtime.pet = SimpleNamespace(
        interrupt=interrupt, set_voice_monitor_ready=lambda ready: None,
    )
    runtime.conversation = SimpleNamespace(stop=stop)
    runtime.attention = AttentionLedger(["p"])
    hub = CameraFrameHub(["p"])

    def voice_started(robot_id):
        starts.append(robot_id)
        hub.notify(robot_id, "human_voice", time.monotonic())

    runtime.multimodal = SimpleNamespace(hub=hub, voice_started=voice_started)
    configure_room_dispatch(runtime)
    before = time.monotonic() - 3
    runtime.attention.human_started("p", before)
    assert runtime.attention.heard(
        "p", "omni_123456789abc_123456789abcdef01234", "keep discussing the key",
        before + 0.1,
    )
    hub.notify("p", "human_voice", before)
    runtime._voice_speech_active = {"p"}
    runtime._on_voice_generations({"p": 7})
    runtime._on_voice_generations(None)
    await runtime._on_voice_global(reason)
    runtime._on_room_disconnect()
    assert runtime._voice_turn_generations is None
    assert "keep discussing the key" in runtime.attention.timeline(
        "p", time.monotonic(),
    )[0]["content"]

    runtime._on_voice_generations({"p": generation})
    await runtime._on_voice_snapshot(frozenset({"p"}))
    await runtime._on_voice_snapshot(frozenset({"p"}))
    context = runtime.attention.timeline("p", time.monotonic())
    assert any("keep discussing the key" in item["content"] for item in context) is (
        not new_turn
    )
    assert starts == (["p"] if new_turn else [])
    assert calls.count("group_stop") == (2 if new_turn else 1)


@pytest.mark.parametrize("lock_name", ["session_lock", "speaker_lock"])
@pytest.mark.parametrize("with_caller_permission", [False, True])
async def test_p1_barge_in_invalidates_proactive_waiting_for_audio_lock(
    settings, lock_name, with_caller_permission,
):
    """An old optional remark cannot cross STOP even with a permissive caller."""
    robot = settings.robot("robot-01")
    speaker = SimulatedSpeaker()
    conversation = Conversation(settings, SimulatedChat(), speaker)

    class ObservedLock(asyncio.Lock):
        def __init__(self):
            super().__init__()
            self.waiting = asyncio.Event()

        async def acquire(self):
            if self.locked():
                self.waiting.set()
            return await super().acquire()

    class Pet:
        async def interrupt(self, robot_id):
            settings.robot(robot_id)

    runtime = _runtime_for_speaker_failure(settings, conversation, Pet())
    lock = ObservedLock()
    setattr(conversation, lock_name, lock)
    queued = None
    try:
        async with lock:
            queued = asyncio.create_task(conversation.say_proactive(
                robot, "Stale optional line",
                permission_check=(lambda: True) if with_caller_permission else None,
            ))
            await asyncio.wait_for(lock.waiting.wait(), timeout=1)
            assert not queued.done()
            await asyncio.wait_for(
                runtime._on_voice_interrupt(robot.id, "speech_start"), timeout=1,
            )
            assert conversation.stop_generation == 1
            assert not speaker.spoken
        assert await asyncio.wait_for(queued, timeout=1) is False
        assert not speaker.spoken
        await runtime._on_voice_interrupt(robot.id, "speech_end")
        assert await conversation.say_proactive(robot, "Fresh optional line")
        assert speaker.spoken == [(robot.id, "Fresh optional line")]
    finally:
        if queued is not None and not queued.done():
            queued.cancel()
            await asyncio.gather(queued, return_exceptions=True)


async def test_p1_barge_in_drops_late_peer_reply(settings):
    """Even a model returning after cancellation cannot relay another peer turn."""
    ids = ["robot-01", "robot-02"]
    speaker = SimulatedSpeaker()

    class LatePeerChat:
        def __init__(self):
            self.second_turn = asyncio.Event()
            self.calls = 0

        async def reply(self, history):
            self.calls += 1
            if self.calls == 1:
                return "I saw the candy."
            assert any("I saw the candy." in item["content"] for item in history)
            self.second_turn.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return "Obsolete peer response."

    class Pet:
        async def interrupt(self, robot_id):
            settings.robot(robot_id)

    chat = LatePeerChat()
    conversation = Conversation(settings, chat, speaker)
    runtime = _runtime_for_speaker_failure(settings, conversation, Pet())
    group = asyncio.create_task(conversation.run(
        ids, "Talk about the candy", 2,
        origin="autonomous_social", permission_check=lambda: True,
    ))
    try:
        await asyncio.wait_for(chat.second_turn.wait(), timeout=1)
        assert speaker.spoken == [(ids[0], "I saw the candy.")]
        await asyncio.wait_for(
            runtime._on_voice_interrupt(ids[0], "speech_start"), timeout=1,
        )
        with pytest.raises(RuntimeError, match="Group conversation consent revoked"):
            await asyncio.wait_for(group, timeout=1)
        assert conversation.active is None
        assert speaker.spoken == [(ids[0], "I saw the candy.")]
    finally:
        if not group.done():
            group.cancel()
        await asyncio.gather(group, return_exceptions=True)
