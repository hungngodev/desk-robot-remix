"""Voice-first, motion-aware desk camera orchestration, all offline mocks."""
import asyncio
import json
import time
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from desk_robot.multimodal import (
    CameraFrameHub,
    MultimodalOrchestrator,
    _prepare,
    change_fraction,
)
from desk_robot.vision import OllamaScene
from PIL import Image, ImageDraw


def image(color="gray", square=False):
    im = Image.new("RGB", (160, 120), color)
    if square:
        ImageDraw.Draw(im).rectangle((35, 25, 68, 58), fill=(0, 0, 0))
    out = BytesIO()
    im.save(out, "JPEG", quality=92)
    return out.getvalue()


def test_mac_camera_timeline_keeps_device_clock_separate_from_receipt():
    """The Sense completion clock is provenance, not an exposure age."""
    hub = CameraFrameHub(["robot-01"])
    now = time.monotonic()
    jpg = image()
    valid = (jpg, bytes(64 * 48), 0.5)
    frame = hub.offer_prepared(
        "robot-01", valid, now, source="proactive",
        source_identity=(19, 42, 2000000),
    )
    assert frame.source_identity == (19, 42, 2000000)
    timeline = hub.interaction_timeline("robot-01", now + 0.2)
    camera = next(event for event in timeline if event["channel"] == "camera")
    assert camera["source_boot"] == 19
    assert camera["source_frame_sequence"] == 42
    assert camera["source_capture_complete_us"] == 2000000
    assert camera["source_clock_not_aligned_to_mac"] is True
    assert camera["exposure_timestamp_verified"] is False
    assert 0 <= camera["age_ms"] <= 250
    with pytest.raises(ValueError, match="completion identity"):
        hub.offer_prepared(
            "robot-01", valid, now + 0.05, source="proactive",
            source_identity=(19, True, 2000100),
        )


def test_legacy_camera_source_has_no_invented_device_timestamp():
    hub = CameraFrameHub(["robot-01"])
    now = time.monotonic()
    hub.offer_prepared(
        "robot-01", (image(), bytes(64 * 48), 0.5), now,
        source="proactive",
    )
    timeline = hub.interaction_timeline("robot-01", now + 0.1)
    camera = next(event for event in timeline if event["channel"] == "camera")
    assert "source_capture_complete_us" not in camera
    assert camera["exposure_timestamp_verified"] is False


def test_oversized_jpeg_header_rejected_before_pixel_decompression():
    """A JPEG may advertise huge dimensions in a tiny source byte stream."""
    frame = bytearray(image())
    sof = frame.find(b"\xff\xc0")
    assert sof > 0  # PIL's default generated RGB JPEG is baseline SOF0.
    frame[sof + 5:sof + 9] = (5000).to_bytes(2, "big") * 2
    with pytest.raises(ValueError, match="Camera dimensions invalid"):
        _prepare(bytes(frame))


class Head:
    def __init__(self):
        self.captures = 0
        self.commands = []

    async def snapshot(self):
        self.captures += 1
        return image(square=self.captures > 1)

    async def command(self, cmd):
        self.commands.append(cmd)


class Vision:
    def __init__(self):
        self.calls = []

    async def answer(self, question, frames):
        self.calls.append((question, frames))
        return "I can see a dark square on the table."


def config(enabled=True):
    return SimpleNamespace(
        robots=[SimpleNamespace(id="robot-01"), SimpleNamespace(id="robot-02")],
        voice_vision_tools_enabled=enabled,
        vision_model="local-vlm" if enabled else "",
    )



async def test_synthetic_camera_observer_keeps_simulation_without_weakening_hardware_consent():
    """Simulation uses fake images; real head capture still needs explicit opt-in."""
    synthetic = config(enabled=False)
    synthetic.mode = "simulation"
    head = Head()
    sim = MultimodalOrchestrator(
        synthetic, {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        first = await sim.capture("robot-01", source="proactive")
        assert first.source == "proactive"
        assert head.captures == 1
        sim.sensor_event("robot-01", "petting_zone")
        async with asyncio.timeout(2):
            while head.captures < 3:
                await asyncio.sleep(.01)
        assert any(frame.source == "sensor"
                   for frame in sim.hub.frames["robot-01"])
    finally:
        await sim.close()

    hardware = config(enabled=False)
    hardware.mode = "hardware"
    physical = Head()
    hw = MultimodalOrchestrator(
        hardware, {"robot-01": physical, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        with pytest.raises(RuntimeError, match="Camera consent revoked"):
            await hw.capture("robot-01", source="proactive")
        hw.sensor_event("robot-01", "petting_zone")
        await asyncio.sleep(.05)
        assert physical.captures == 0
        assert not hw.hub.frames["robot-01"]
    finally:
        await hw.close()


async def test_authenticated_stream_propagates_device_clock_without_snapshot():
    class SourceClockHead(Head):
        async def stream_frames(self):
            self._last_camera = (71, 4, 1234567)
            yield image(square=True), time.monotonic()
            await asyncio.Event().wait()

    head = SourceClockHead()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    visual.start_streams()
    try:
        async with asyncio.timeout(3):
            while not visual.hub.frames["robot-01"]:
                await asyncio.sleep(0.02)
        frame = visual.hub.frames["robot-01"][-1]
        assert frame.source_identity == (71, 4, 1234567)
        latest = visual.hub.interaction_timeline("robot-01", time.monotonic())
        camera = next(item for item in latest if item["channel"] == "camera")
        assert camera["source_capture_complete_us"] == 1234567
        assert camera["exposure_timestamp_verified"] is False
        assert head.captures == 0
    finally:
        await visual.close()


async def test_invalid_live_frame_receipts_cannot_poison_sampling_cursor():
    """Future, stale, NaN, and duplicate receipts never starve fresh frames."""
    class BadClockHead(Head):
        async def stream_frames(self):
            frame = image(square=True)
            timestamp = time.monotonic()
            yield frame, float("nan")
            yield frame, timestamp + 3600
            yield frame, timestamp - 30
            yield frame, timestamp
            yield frame, timestamp  # Replay of the already accepted frame.
            await asyncio.sleep(0.56)
            yield frame, time.monotonic()
            await asyncio.Event().wait()

    head = BadClockHead()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    visual.start_streams()
    try:
        async with asyncio.timeout(2):
            while visual.status("robot-01")["software_timings"][
                "stream_frames_selected"
            ] < 2:
                await asyncio.sleep(0.02)
        metrics = visual.status("robot-01")["software_timings"]
        assert metrics["stream_frames_received"] >= 6
        assert metrics["stream_frames_skipped"] >= 4
        assert metrics["stream_frames_selected"] == 2
        assert metrics["stream_reconnects"] == 0
        assert head.captures == 0
    finally:
        await visual.close()


async def test_stream_frame_aging_out_during_jpeg_decode_is_not_published():
    """A slow native decode must not resurrect an obsolete visual scene."""
    allow_next_frame = asyncio.Event()

    class SlowThenFreshHead(Head):
        async def stream_frames(self):
            yield image(square=True), time.monotonic() - 0.9
            await allow_next_frame.wait()
            yield image(square=False), time.monotonic()
            await asyncio.Event().wait()

    head = SlowThenFreshHead()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    calls = 0

    async def delayed_first_decode(jpeg, *, priority=False):
        nonlocal calls
        calls += 1
        if calls == 1:
            await asyncio.sleep(0.2)
        return _prepare(jpeg)

    visual._prepare_bounded = delayed_first_decode
    visual.start_streams()
    try:
        async with asyncio.timeout(3):
            while visual.status("robot-01")["software_timings"][
                "stream_frames_skipped"
            ] < 1:
                await asyncio.sleep(0.01)
        assert not visual.hub.frames["robot-01"]
        assert head.captures == 0
        allow_next_frame.set()
        async with asyncio.timeout(3):
            while visual.status("robot-01")["software_timings"][
                "stream_frames_selected"
            ] < 1:
                await asyncio.sleep(0.01)
        metrics = visual.status("robot-01")["software_timings"]
        assert metrics["stream_frames_received"] == 2
        assert metrics["stream_frames_selected"] == 1
        assert metrics["stream_reconnects"] == 0
        assert len(visual.hub.frames["robot-01"]) == 1
    finally:
        await visual.close()


@pytest.mark.parametrize("malformed", [True, False])
async def test_corrupt_live_jpeg_drops_frame_without_restarting_camera_stream(malformed):
    """Malformed bytes and deceptive JPEG dimensions must not break video."""
    bad_frame = b"not a JPEG"
    if not malformed:
        oversized = bytearray(image())
        sof = oversized.find(b"\xff\xc0")
        assert sof > 0
        oversized[sof + 5:sof + 9] = (5000).to_bytes(2, "big") * 2
        bad_frame = bytes(oversized)

    class CorruptThenHealthy(Head):
        async def stream_frames(self):
            yield bad_frame, time.monotonic()
            await asyncio.sleep(0.56)  # Preserve the normal 500ms sample gate.
            yield image(square=True), time.monotonic()
            await asyncio.Event().wait()

    head = CorruptThenHealthy()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    visual.start_streams()
    try:
        async with asyncio.timeout(2):
            while visual.status("robot-01")["software_timings"][
                "stream_frames_selected"
            ] < 1:
                await asyncio.sleep(0.02)
        metrics = visual.status("robot-01")["software_timings"]
        assert metrics["stream_frames_received"] >= 2
        assert metrics["stream_frames_skipped"] >= 1
        assert metrics["stream_frames_selected"] == 1
        assert metrics["stream_reconnects"] == 0
        assert head.captures == 0
    finally:
        await visual.close()


async def test_continuous_camera_feed_populates_proactive_hub_without_snapshot_polls():
    """Streaming perception runs independently of VAD and single-shot pulls."""
    class LiveHead(Head):
        def __init__(self):
            super().__init__()
            self.emitted = 0

        async def stream_frames(self):
            for index in range(7):
                self.emitted += 1
                yield image(square=index > 2), time.monotonic()
                await asyncio.sleep(0.26)

    head, vision = LiveHead(), Vision()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        vision, asyncio.Lock(),
    )
    visual.start_streams()
    try:
        async with asyncio.timeout(3):
            while (head.emitted < 7 or
                   visual.status("robot-01")["software_timings"][
                       "stream_frames_selected"] < 4):
                await asyncio.sleep(0.02)
        metrics = visual.status("robot-01")["software_timings"]
        # A new object requires one stable FOLLOWUP even though the latest
        # frame matches the new scene. Otherwise the pet's two-confirmation
        # semantic gate never reaches its VLM and its eyewitness memory.
        retained = tuple(visual.hub.frames["robot-01"])
        assert retained[-2].motion_fraction > .01
        assert retained[-1].motion_fraction < .01
        assert metrics["stream_frames_received"] >= 7
        # The sampler must not go blind for 3+ seconds after the first
        # two frames. An object appearing one second into the continuous
        # video must reach the cheap motion gate without a new request.
        assert 3 <= metrics["stream_frames_selected"] < 7
        assert metrics["stream_frames_skipped"] >= 1
        assert len(visual.hub.frames["robot-01"]) >= 2
        assert any(frame.motion_fraction > .01
                   for frame in visual.hub.frames["robot-01"])
        assert all(frame.source == "proactive"
                   for frame in visual.hub.frames["robot-01"])
        assert head.captures == 0  # No calls to /api/camera.jpg
        assert vision.calls == []  # No expensive VLM per streaming JPEG
    finally:
        await visual.close()
    assert not visual._stream_tasks





@pytest.mark.parametrize("primed_frames", [0, 2])
async def test_stream_consent_revoked_during_frame_preparation_cannot_publish_jpeg(
    primed_frames,
):
    """An in-flight image worker cannot outlive operator visual opt out."""
    entered, release = asyncio.Event(), asyncio.Event()
    stream_closed = asyncio.Event()
    policy = config(enabled=True)

    class LiveHead(Head):
        async def stream_frames(self):
            try:
                yield image(square=True), time.monotonic()
                await asyncio.Event().wait()
            finally:
                # The head camera lease must be released before a revoked
                # consumer reports completion, not by eventual GC.
                stream_closed.set()

    head = LiveHead()
    visual = MultimodalOrchestrator(
        policy, {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )

    async def slow_prepare(jpeg, *, priority):
        assert not priority
        entered.set()
        await release.wait()
        return _prepare(jpeg)

    # Cover both a first-frame opt-out and a late static third frame.
    # The static novelty skip must never bypass the consent fence and
    # leave a prior camera buffer or an open MJPEG lease after revoke.
    if primed_frames:
        at = time.monotonic() - 1
        for index in range(primed_frames):
            visual.hub.offer(
                "robot-01", image(square=True), at + index * .1,
                source="proactive",
            )
    visual._prepare_bounded = slow_prepare
    visual.start_streams()
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert visual.status("robot-01")["software_timings"][
            "stream_frames_selected"
        ] == 0
        policy.voice_vision_tools_enabled = False
        release.set()
        await asyncio.wait_for(visual._stream_tasks["robot-01"], timeout=1)
        assert stream_closed.is_set()
        assert not visual.hub.frames["robot-01"]
        assert visual.status("robot-01")["software_timings"][
            "stream_frames_selected"
        ] == 0
        assert head.captures == 0
    finally:
        release.set()
        await visual.close()



async def test_native_subscriber_gets_quiet_room_frames_from_live_stream_not_vad():
    class ContinuousHead(Head):
        async def stream_frames(self):
            for index in range(10):
                yield image(square=index >= 3), time.monotonic()
                await asyncio.sleep(0.26)

    head = ContinuousHead()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    visual.start_streams()
    frames = visual.native_live_frames("robot-01")
    try:
        first = await asyncio.wait_for(anext(frames), timeout=2)
        second = await asyncio.wait_for(anext(frames), timeout=2)
        assert first.source == second.source == "proactive"
        assert first.received_at < second.received_at
        assert first.jpeg.startswith(b"\xff\xd8")
        assert second.jpeg.endswith(b"\xff\xd9")
        assert head.captures == 0
        assert visual.status("robot-01")["software_timings"][
            "stream_frames_received"
        ] > 1
    finally:
        await frames.aclose()
        await visual.close()


async def test_proactive_pet_can_wake_on_pushed_frame_without_camera_poll():
    """A native selected stream frame wakes perception without waiting 1.2s."""
    allow_next = asyncio.Event()

    class LiveHead(Head):
        async def stream_frames(self):
            yield image(), time.monotonic()
            await allow_next.wait()
            yield image(square=True), time.monotonic()
            await asyncio.Event().wait()

    head = LiveHead()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    visual.start_streams()
    try:
        async with asyncio.timeout(2):
            while not visual.hub.frames["robot-01"]:
                await asyncio.sleep(.005)
        previous = visual.hub.frames["robot-01"][-1].received_at
        wake = asyncio.create_task(
            visual.wait_for_proactive_frame(
                "robot-01", previous, timeout_s=1.2
            )
        )
        await asyncio.sleep(.55)  # actual 2 FPS stream sample gate
        assert not wake.done()
        allow_next.set()
        assert await asyncio.wait_for(wake, timeout=.45)
        latest = visual.hub.frames["robot-01"][-1]
        assert latest.received_at > previous
        assert latest.source == "proactive"
        assert head.captures == 0
        # Another already consumed frame may not generate a fake event.
        assert not await visual.wait_for_proactive_frame(
            "robot-01", latest.received_at, timeout_s=.04
        )
    finally:
        allow_next.set()
        await visual.close()


async def test_proactive_wait_refuses_cached_frame_after_camera_consent_revoke():
    """An earlier selected JPEG is not usable after visual opt out."""
    visual = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        observed_at = time.monotonic()
        visual.hub.offer("robot-01", image(), observed_at, source="proactive")
        assert await visual.wait_for_proactive_frame(
            "robot-01", observed_at - 0.1, timeout_s=.05,
        )
        visual.settings.voice_vision_tools_enabled = False
        # The original frame remains cached and the condition is already true,
        # but consent must still prevent a positive result.
        assert not await visual.wait_for_proactive_frame(
            "robot-01", observed_at - 0.1, timeout_s=.05,
        )
    finally:
        await visual.close()


async def test_other_pets_keep_streaming_passive_vision_during_human_conversation():
    """One person's speech owns audible inference, not all camera lenses."""
    class LiveHead(Head):
        async def stream_frames(self):
            for index in range(12):
                yield image(square=index >= 3), time.monotonic()
                await asyncio.sleep(.26)
            await asyncio.Event().wait()

    head = LiveHead()
    scene = Vision()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": head},
        scene, asyncio.Lock(),
    )
    visual.voice_started("robot-01")
    visual.start_streams()
    try:
        assert visual.hub.user_active("robot-01", time.monotonic())
        async with asyncio.timeout(3):
            while visual.status("robot-02")["software_timings"][
                "stream_frames_selected"
            ] < 2:
                await asyncio.sleep(.03)
        metrics = visual.status("robot-02")["software_timings"]
        assert metrics["stream_frames_received"] >= 5
        assert metrics["stream_frames_selected"] >= 2
        assert all(f.source == "proactive"
                   for f in visual.hub.frames["robot-02"])
        assert scene.calls == []  # no stolen VLM slot during another VAD
        assert head.captures == 0  # one real stream, zero snapshot pulls
    finally:
        visual.voice_ended("robot-01")
        await visual.close()


async def test_continuous_camera_stream_supplies_voice_frames_without_new_poller():
    class LiveHead(Head):
        async def stream_frames(self):
            for index in range(10):
                yield image(square=index > 5), time.monotonic()
                await asyncio.sleep(0.25)

    head = LiveHead()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    visual.start_streams()
    try:
        async with asyncio.timeout(3):
            while visual.status("robot-01")["software_timings"][
                "stream_frames_selected"
            ] == 0:
                await asyncio.sleep(0.02)
        visual.voice_started("robot-01")
        assert "robot-01" not in visual._capture_tasks
        async with asyncio.timeout(3):
            while not any(
                frame.source == "speech"
                for frame in visual.hub.frames["robot-01"]
            ):
                await asyncio.sleep(0.02)
        assert head.captures == 0
        visual.voice_ended("robot-01")
        assert "robot-01" not in visual._capture_tasks
    finally:
        await visual.close()



async def test_persistent_stream_adapts_static_sampling_after_two_baselines():
    """Keep draining the existing feed while skipping idle JPEG decoding."""
    class StaticFeed(Head):
        def __init__(self):
            super().__init__()
            self.emitted = 0
            self.drained = asyncio.Event()
            self.release = asyncio.Event()

        async def stream_frames(self):
            frame = image()
            for _ in range(17):
                self.emitted += 1
                # This represents a live camera, not a four-second backlog.
                # Production must reject pre-aged frames during JPEG decode.
                yield frame, time.monotonic()
                await asyncio.sleep(0.25)
            self.drained.set()
            await self.release.wait()

    head = StaticFeed()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    visual.start_streams()
    try:
        await asyncio.wait_for(head.drained.wait(), timeout=8)
        stats = visual.status("robot-01")["software_timings"]
        assert head.emitted == stats["stream_frames_received"] == 17
        # Two warmup samples at 0 and 0.5 seconds; one more at 4 seconds.
        assert stats["stream_frames_selected"] == 3
        assert stats["stream_frames_skipped"] == 14
        assert head.captures == 0
    finally:
        head.release.set()
        await visual.close()


async def test_reconnect_restarts_two_frame_motion_bootstrap():
    class ReconnectedHead(Head):
        def __init__(self):
            super().__init__()
            self.attempts = 0
            self.ready = asyncio.Event()
            self.release = asyncio.Event()

        async def stream_frames(self):
            self.attempts += 1
            still = image()
            for _ in range(4):
                # A reconnect starts with current capture receipts. An old
                # camera backlog must never serve as the new visual baseline.
                yield still, time.monotonic()
                await asyncio.sleep(0.25)
            if self.attempts > 1:
                self.ready.set()
                await self.release.wait()

    head = ReconnectedHead()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    visual.start_streams()
    try:
        await asyncio.wait_for(head.ready.wait(), timeout=8)
        assert head.attempts >= 2
        assert len(visual.hub.frames["robot-01"]) == 2
        assert visual.status("robot-01")["software_timings"][
            "stream_frames_selected"
        ] == 4
        assert head.captures == 0
    finally:
        head.release.set()
        await visual.close()


def test_all_new_physical_interactions_trigger_camera_without_extra_sensor_drivers():
    hub = CameraFrameHub(["robot-01", "robot-02"], idle_fps=0.3)
    hub.offer("robot-01", image(), 100.0, source="proactive")
    hub.offer("robot-02", image(), 100.0, source="proactive")
    assert not hub.due("robot-01", 100.2)
    for kind in ("paw_contact", "ambient_shift", "nfc_tag"):
        hub.notify("robot-01", kind, 100.25)
    assert hub.due("robot-01", 100.3)
    assert not hub.due("robot-02", 100.3)
    assert [x["kind"] for x in hub.recent_events("robot-01", 100.3)] == [
        "paw_contact", "ambient_shift", "nfc_tag",
    ]
    assert hub.recent_events("robot-02", 100.3) == []


def test_brightness_shift_not_mistaken_for_localized_motion():
    a = bytes([90] * (64 * 48))
    b = bytes([130] * (64 * 48))
    assert change_fraction(a, b) == 0
    c = bytearray(a)
    for i in range(120, 180):
        c[i] = 0
    assert change_fraction(a, bytes(c)) > 0.01


def test_multiplicative_light_shift_preserves_real_camera_occlusion():
    fingerprint = bytes(
        40 if (i // 64 + i % 64) % 2 else 110
        for i in range(64 * 48)
    )
    doubled = bytes(2 * value for value in fingerprint)
    assert change_fraction(fingerprint, doubled) == 0
    assert change_fraction(fingerprint, bytes([20] * len(fingerprint))) > 0.9
    changed = bytearray(doubled)
    changed[120:320] = bytes([0] * 200)
    assert change_fraction(fingerprint, bytes(changed)) > 0.05


@pytest.mark.parametrize("cancel", [False, True])
async def test_direct_visual_request_reserves_fleet_vlm_and_camera_until_finished(cancel):
    """No new speculative JPEG/VLM may overtake the entire human look."""
    class HeldHead(Head):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def snapshot(self):
            self.captures += 1
            self.entered.set()
            await self.release.wait()
            return image()

    head, scene = HeldHead(), Vision()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        scene, asyncio.Lock(),
    )
    reservation = []
    visual.begin_direct_vision = lambda: reservation.append("begin")
    visual.end_direct_vision = lambda: reservation.append("end")
    try:
        task = asyncio.create_task(
            visual.look("robot-01", "What is on the desk?")
        )
        await asyncio.wait_for(head.entered.wait(), timeout=1)
        assert reservation == ["begin"]
        # A new optional pet sample must fail BEFORE acquiring the same
        # XIAO camera lock, instead of queuing behind the direct question.
        with pytest.raises(RuntimeError, match="Explicit human look"):
            await asyncio.wait_for(
                visual.capture("robot-01", source="proactive"), timeout=.5
            )
        assert head.captures == 1
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            head.release.set()
            result = await asyncio.wait_for(task, timeout=2)
            assert result["frames_used"] == 1
            assert len(scene.calls) == 1
        assert reservation == ["begin", "end"]
        assert not visual._look_tasks
    finally:
        head.release.set()
        await visual.close()


async def test_live_sensor_edge_reuses_stream_and_never_starts_competing_snapshot():
    """A pet touch may wake the observer but must not fight live MJPEG ownership.

    Pipecat/LiveKit-inspired source sampling: only the existing continuous
    XIAO stream delivers frames. The real WROOM event remains a distinct
    provenance cue, not an instruction to start another physical capture.
    """
    class LiveHead(Head):
        def __init__(self):
            super().__init__()
            self.frames_to_send = asyncio.Queue()

        async def stream_frames(self):
            while True:
                frame = await self.frames_to_send.get()
                yield frame, time.monotonic()

    head = LiveHead()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    visual.start_streams()
    try:
        assert visual.stream_owns_camera("robot-01")
        visual.sensor_event("robot-01", "paw_contact")
        visual.sensor_event("robot-01", "petting_zone")
        assert not visual.sensor_burst_pending("robot-01")
        assert "robot-01" not in visual._sensor_tasks
        assert visual._metrics["robot-01"]["sensor_stream_reuses"] == 2
        # A selected video frame arrives AFTER the actual touch, without
        # querying /api/camera.jpg or relabelling stream vision as a cliff.
        await head.frames_to_send.put(image(square=True))
        async with asyncio.timeout(2):
            while not visual.hub.frames["robot-01"]:
                await asyncio.sleep(.01)
        assert visual.hub.frames["robot-01"][-1].source == "proactive"
        assert visual._metrics["robot-01"]["stream_sensor_priority_frames"] == 1
        # Second independent sensor event arrives before the usual 500ms
        # idle sample interval: select the NEXT existing 4 FPS stream frame
        # immediately rather than an on-demand camera capture.
        visual.sensor_event("robot-01", "nfc_tag")
        await head.frames_to_send.put(image())
        async with asyncio.timeout(2):
            while visual._metrics["robot-01"]["stream_frames_selected"] < 2:
                await asyncio.sleep(.01)
        assert visual._metrics["robot-01"]["stream_sensor_priority_frames"] == 2
        assert head.captures == 0
        assert [event["kind"] for event in visual.hub.recent_events(
            "robot-01", time.monotonic()
        )][-3:] == ["paw_contact", "petting_zone", "nfc_tag"]
        # No stream frame or reconnection is a license to fall back to
        # an incompatible single-shot capture path.
        visual.sensor_event("robot-01", "paw_contact")
        await asyncio.sleep(.04)
        assert head.captures == 0
        assert not visual.sensor_burst_pending("robot-01")
    finally:
        await visual.close()


async def test_sensor_burst_uses_existing_camera_owner_and_coalesces_requests():
    heads = {"robot-01": Head(), "robot-02": Head()}
    visual = MultimodalOrchestrator(config(), heads, Vision(), asyncio.Lock())
    try:
        for kind in ("paw_contact", "ambient_shift", "nfc_tag", "petting_zone"):
            visual.sensor_event("robot-01", kind)
        async with asyncio.timeout(2):
            while not visual.hub.frames["robot-01"]:
                await asyncio.sleep(0.01)
        assert heads["robot-01"].captures == 1
        assert heads["robot-02"].captures == 0
        assert visual.hub.frames["robot-01"][-1].source == "sensor"
        assert visual._metrics["robot-01"]["camera_successes"] == 1
        assert len(visual.hub.recent_events("robot-01", time.monotonic())) == 4
        # A second burst during the 800ms budget cannot allocate more JPEGs.
        visual.sensor_event("robot-01", "nfc_tag")
        await asyncio.sleep(0.02)
        assert heads["robot-01"].captures == 1
    finally:
        await visual.close()


async def test_sensor_events_keep_wroom_context_without_camera_consent():
    """Touch and cliff sensing continue, but cannot start JPEG snapshots."""
    heads = {"robot-01": Head(), "robot-02": Head()}
    visual = MultimodalOrchestrator(
        config(enabled=False), heads, Vision(), asyncio.Lock(),
    )
    try:
        visual.sensor_event("robot-01", "touch_tap")
        visual.sensor_event("robot-01", "safety_fault")
        await asyncio.sleep(0.04)
        assert heads["robot-01"].captures == 0
        assert not visual.sensor_burst_pending("robot-01")
        assert not visual.hub.frames["robot-01"]
        assert {"touch_tap", "safety_fault"} <= {
            item["kind"] for item in visual.hub.recent_events(
                "robot-01", time.monotonic()
            )
        }
        with pytest.raises(RuntimeError, match="Camera consent revoked"):
            await visual.capture(
                "robot-01", source="sensor", trigger_kind="touch_tap"
            )
        assert heads["robot-01"].captures == 0
    finally:
        await visual.close()


async def test_sensor_capture_revoked_during_jpeg_preparation_never_publishes():
    """Consent can disappear after the real JPEG, before Mac publication."""
    entered, release = asyncio.Event(), asyncio.Event()
    policy = config(enabled=True)
    head = Head()
    visual = MultimodalOrchestrator(
        policy, {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )

    async def blocked_prepare(jpeg, *, priority):
        entered.set()
        await release.wait()
        return _prepare(jpeg)

    visual._prepare_bounded = blocked_prepare
    task = asyncio.create_task(
        visual.capture("robot-01", source="sensor", trigger_kind="touch_tap")
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        policy.voice_vision_tools_enabled = False
        release.set()
        with pytest.raises(RuntimeError, match="Camera consent revoked"):
            await asyncio.wait_for(task, timeout=1)
        assert head.captures == 1  # Captured before revocation, NOT published.
        assert not visual.hub.frames["robot-01"]
        assert visual.status("robot-01")["software_timings"]["camera_errors"] >= 1
    finally:
        release.set()
        await visual.close()


async def test_sensor_two_frame_burst_never_blocks_human_speech_priority():
    heads = {"robot-01": Head(), "robot-02": Head()}
    visual = MultimodalOrchestrator(
        config(enabled=True), heads, Vision(), asyncio.Lock()
    )
    # This test isolates sensor preemption, not the separate VAD camera sampler.
    visual.start_speech_frames = lambda _robot_id: None
    try:
        visual.sensor_event("robot-01", "petting_zone")
        async with asyncio.timeout(2):
            while heads["robot-01"].captures < 1:
                await asyncio.sleep(.01)
        # A real VAD begins during the deliberately short second-frame gap.
        visual.voice_started("robot-01")
        await asyncio.sleep(.55)
        assert heads["robot-01"].captures == 1
        assert visual.hub.user_active("robot-01", time.monotonic())
        visual.voice_ended("robot-01")
    finally:
        await visual.close()


async def test_one_human_vad_preempts_all_five_pet_optional_camera_captures():
    class SlowHead(Head):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.cancelled = False

        async def snapshot(self):
            self.captures += 1
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    first, second = SlowHead(), SlowHead()
    visual = MultimodalOrchestrator(
        config(enabled=True),
        {"robot-01": first, "robot-02": second},
        Vision(), asyncio.Lock(),
    )
    visual.start_speech_frames = lambda _robot_id: None
    task = asyncio.create_task(
        visual.capture("robot-02", source="proactive")
    )
    try:
        await asyncio.wait_for(second.started.wait(), timeout=1)
        visual.voice_started("robot-01")
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert second.cancelled
        visual.sensor_event("robot-02", "petting_zone")
        await asyncio.sleep(.02)
        assert second.captures == 1
        assert visual.status("robot-02")["software_timings"]["sensor_deferred_human"] == 1
        assert not visual.hub.frames["robot-02"]
        assert visual.hub.user_active("robot-01", time.monotonic())
        visual.voice_ended("robot-01")
    finally:
        await visual.close()


async def test_other_pets_sensor_bursts_yield_to_one_fleet_human_turn():
    heads = {"robot-01": Head(), "robot-02": Head()}
    visual = MultimodalOrchestrator(
        config(enabled=True), heads, Vision(), asyncio.Lock()
    )
    # This test isolates sensor preemption, not the separate VAD camera sampler.
    visual.start_speech_frames = lambda _robot_id: None
    try:
        visual.sensor_event("robot-02", "nfc_tag")
        async with asyncio.timeout(2):
            while heads["robot-02"].captures < 1:
                await asyncio.sleep(.01)
        visual.voice_started("robot-01")
        await asyncio.sleep(.55)
        assert heads["robot-02"].captures == 1
        assert visual.hub.user_active("robot-01", time.monotonic())
        assert not visual.hub.user_active("robot-02", time.monotonic())
        visual.voice_ended("robot-01")
    finally:
        await visual.close()


async def test_human_voice_preempts_only_the_background_snapshot():
    class SlowHead(Head):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.cancelled = False

        async def snapshot(self):
            self.captures += 1
            if self.captures == 1:
                self.started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            return image(square=True)

    head = SlowHead()
    visual = MultimodalOrchestrator(
        config(enabled=True), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    visual.start_speech_frames = lambda _robot_id: None
    pending = asyncio.create_task(visual.capture("robot-01", source="proactive"))
    try:
        await asyncio.wait_for(head.started.wait(), timeout=1)
        visual.voice_started("robot-01")
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, timeout=1)
        assert head.cancelled
        assert not visual.hub.frames["robot-01"]
        assert visual.hub.user_active("robot-01", time.monotonic())
        visual.voice_ended("robot-01")
        evidence = await visual.capture("robot-01", source="voice_question")
        assert evidence.source == "voice_question"
        assert head.captures == 2
    finally:
        await visual.close()


async def test_direct_visual_question_preempts_background_camera_request():
    class SlowHead(Head):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.cancelled = False

        async def snapshot(self):
            self.captures += 1
            if self.captures == 1:
                self.started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            return image(square=True)

    head = SlowHead()
    visual = MultimodalOrchestrator(
        config(enabled=True), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    pending = asyncio.create_task(visual.capture("robot-01", source="proactive"))
    try:
        await asyncio.wait_for(head.started.wait(), timeout=1)
        response = await asyncio.wait_for(
            visual.look("robot-01", "What object is now visible?"), timeout=3
        )
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert head.cancelled
        assert visual.status("robot-01")["software_timings"]["proactive_camera_preemptions"] == 1
        assert response["source"] == "authenticated_xiao_camera_and_local_vlm"
        assert response["frames_used"] == 1
        assert head.captures == 2
    finally:
        await visual.close()


async def test_direct_visual_question_preempts_busy_optional_model_without_extra_owner():
    lock = asyncio.Lock()
    entered = asyncio.Event()

    async def slow_speculation():
        async with lock:
            entered.set()
            await asyncio.Event().wait()

    pending = asyncio.create_task(slow_speculation())
    visual = MultimodalOrchestrator(
        config(enabled=True),
        {"robot-01": Head(), "robot-02": Head()},
        Vision(), lock,
    )
    visual.preempt_background_vision = pending.cancel
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        answer = await asyncio.wait_for(
            visual.look("robot-01", "What is on the table?"), timeout=2
        )
        assert answer["frames_used"] == 1
        assert answer["motor_authorized"] is False
        assert pending.cancelled()
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await visual.close()


async def test_sensor_two_frame_burst_is_bounded_and_camera_serial():
    head = Head()
    visual = MultimodalOrchestrator(
        config(enabled=True),
        {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        visual.sensor_event("robot-01", "paw_contact")
        assert visual.sensor_burst_pending("robot-01")
        assert not visual.sensor_burst_pending("robot-02")
        async with asyncio.timeout(3):
            while len(visual.hub.frames["robot-01"]) != 2:
                await asyncio.sleep(.01)
        async with asyncio.timeout(1):
            while visual.sensor_burst_pending("robot-01"):
                await asyncio.sleep(.01)
        frames = list(visual.hub.frames["robot-01"])
        assert frames[0].source == frames[1].source == "sensor"
        assert frames[0].trigger_kind == frames[1].trigger_kind == "paw_contact"
        timeline = visual.hub.interaction_timeline("robot-01", time.monotonic())
        camera = [cue for cue in timeline if cue["channel"] == "camera"]
        assert len(camera) == 2
        assert all(cue["trigger_kind"] == "paw_contact" for cue in camera)
        assert all(cue["exposure_timestamp_verified"] is False for cue in camera)
        assert frames[0].received_at < frames[1].received_at
        assert head.captures == 2
        assert visual._metrics["robot-01"]["camera_successes"] == 2
        stats = visual.status("robot-01")["software_timings"]
        assert stats["sensor_triggers"] == 1
        assert stats["sensor_bursts"] == 1
        assert stats["sensor_followup_frames"] == 1
        assert isinstance(stats["sensor_trigger_to_first_jpeg_last_ms"], int)
        assert stats["sensor_trigger_to_first_jpeg_last_ms"] >= 0
        assert head.captures <= 2
    finally:
        await visual.close()


async def test_immediate_new_speech_after_end_replaces_cancelling_camera_worker():
    visual = MultimodalOrchestrator(
        config(enabled=True),
        {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        visual.voice_started("robot-01")
        first = visual._capture_tasks["robot-01"]
        visual.voice_ended("robot-01")
        assert first.cancelling()
        visual.voice_started("robot-01")  # no event-loop yield between edges
        second = visual._capture_tasks["robot-01"]
        assert second is not first
        async with asyncio.timeout(2):
            while not visual.hub.frames["robot-01"]:
                await asyncio.sleep(0.01)
        assert visual.hub.frames["robot-01"][-1].source == "speech"
        assert visual.hub.user_active("robot-01", time.monotonic())
        visual.voice_ended("robot-01")
    finally:
        await visual.close()


async def test_human_vad_cancels_pending_sensor_camera_before_speech_frames():
    class BlockedFirstCamera(Head):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.sensor_cancelled = False

        async def snapshot(self):
            self.captures += 1
            if self.captures == 1:
                self.entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.sensor_cancelled = True
                    raise
            return image(square=True)

    first = BlockedFirstCamera()
    visual = MultimodalOrchestrator(
        config(enabled=True), {"robot-01": first, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        visual.sensor_event("robot-01", "paw_contact")
        await asyncio.wait_for(first.entered.wait(), timeout=1)
        visual.voice_started("robot-01")
        async with asyncio.timeout(2):
            while (first.captures < 2
                   or not visual.hub.frames["robot-01"]):
                await asyncio.sleep(0.01)
        assert first.sensor_cancelled
        assert visual.hub.frames["robot-01"][-1].source == "speech"
        assert visual.hub.user_active("robot-01", time.monotonic())
        visual.voice_ended("robot-01")
    finally:
        await visual.close()


def test_sensor_camera_trigger_cannot_be_forged_on_voice_or_idle_capture():
    hub = CameraFrameHub(["robot-01"])
    prepared = _prepare(image())
    with pytest.raises(ValueError, match="Only a real sensor burst"):
        hub.offer_prepared(
            "robot-01", prepared, 100.0,
            source="speech", trigger_kind="touch_tap",
        )
    with pytest.raises(ValueError, match="Only a real sensor burst"):
        hub.offer_prepared(
            "robot-01", prepared, 100.0,
            source="sensor", trigger_kind="nonexistent_vision",
        )


def test_frame_hub_speech_adaptive_priority_and_identity():
    hub = CameraFrameHub(["robot-01"], idle_fps=0.3, speaking_fps=1)
    now = 100.0
    assert hub.due("robot-01", now)
    hub.offer("robot-01", image(), now, source="proactive")
    assert not hub.due("robot-01", 100.8)
    assert not hub.due("robot-01", 101.4)
    assert hub.due("robot-01", 103.4)
    hub.notify("robot-01", "human_voice", 103.4)
    assert hub.user_active("robot-01", 108)
    assert hub.due("robot-01", 103.4)
    hub.offer("robot-01", image(), 103.5, source="speech")
    assert not hub.due("robot-01", 104.1)
    assert hub.due("robot-01", 104.6)
    hub.notify("robot-01", "petting_zone", 104.7)
    assert hub.due("robot-01", 104.7)
    events = hub.recent_events("robot-01", 105)
    assert [x["kind"] for x in events] == ["human_voice", "petting_zone"]
    assert events[0]["source"] == "xiaozhi_vad"
    assert events[1]["source"] == "wroom_sensed_event"
    with pytest.raises(ValueError):
        hub.notify("robot-99", "human_voice", 110)
    with pytest.raises(ValueError):
        hub.offer("robot-01", image(), 103, source="speech")
    hub.close()
    assert not hub.frames["robot-01"]


def test_speech_floor_requires_real_end_not_a_seven_second_guess(monkeypatch):
    # Synthetic VAD times must not trip the production future receipt fence
    # on a newly started CI runner with less than 180 seconds of uptime.
    monkeypatch.setattr("desk_robot.multimodal.time.monotonic", lambda: 300.0)
    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.notify("robot-01", "human_voice", 100.0)
    # Long human questions must never free the spontaneous speaker floor.
    assert hub.user_active("robot-01", 108.0)
    assert hub.user_active("robot-01", 170.0)
    assert not hub.user_active("robot-02", 170.0)
    hub.speech_ended("robot-01", 170.0)
    assert not hub.user_active("robot-01", 170.0)
    hub.notify("robot-01", "human_voice", 180.0)
    hub.clear("robot-01")  # Explicit disconnect/operator reset is also release.
    assert not hub.user_active("robot-01", 180.1)


def test_aec_barge_has_finite_lease_but_never_shortens_explicit_vad(monkeypatch):
    # This is a simulated VAD timeline, not an actual future Mac receipt.
    # Keep the local monotonic-clock safety fence enabled in production.
    monkeypatch.setattr("desk_robot.multimodal.time.monotonic", lambda: 1000.0)
    hub = CameraFrameHub(["robot-01"])
    hub.barge_in("robot-01", 100.0)
    assert hub.user_active("robot-01", 106.9)
    assert not hub.user_active("robot-01", 107.0)
    hub.notify("robot-01", "human_voice", 108.0)
    hub.barge_in("robot-01", 110.0)
    assert hub.user_active("robot-01", 300.0)
    hub.speech_ended("robot-01", 301.0)
    assert not hub.user_active("robot-01", 301.0)


def test_authenticated_snapshot_reconciles_missed_vad_without_losing_aec_hold():
    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.notify("robot-01", "human_voice", 100.0)
    hub.barge_in("robot-02", 101.0)
    hub.reconcile_speech_snapshot(frozenset({"robot-01"}), 103.0)
    assert hub.user_active("robot-01", 300.0)
    assert hub.user_active("robot-02", 107.0)
    hub.reconcile_speech_snapshot(frozenset(), 104.0)
    assert not hub.user_active("robot-01", 105.0)
    assert hub.user_active("robot-02", 107.0)
    assert not hub.user_active("robot-02", 108.0)


def test_temporal_question_selects_older_and_latest_in_same_robot():
    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.offer("robot-01", image(), 10.0, source="proactive")
    hub.offer("robot-01", image(square=True), 10.5, source="sensor")
    hub.offer("robot-01", image(square=True), 11.0, source="proactive")
    hub.offer("robot-02", image("red"), 11.0, source="proactive")
    chosen = hub.selected("robot-01", "What changed just now?", 11.1)
    assert len(chosen) == 2
    # The object appeared between 10.0 and 10.5. The camera did not move
    # between 10.5 and 11.0, so comparing those latter two would be wrong.
    assert chosen[0].received_at == 10.0
    assert chosen[1].received_at == 11.0
    assert chosen[0].jpeg != chosen[1].jpeg
    assert len(hub.selected("robot-01", "What is on the desk?", 11.1)) == 1
    assert hub.selected("robot-01", "What is it?", 18.0) == []


async def test_voice_vision_tool_gets_real_authenticated_head_frames_without_actuation():
    head = Head()
    model = Vision()
    service = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        model, asyncio.Lock(),
    )
    try:
        result = await service.look("robot-01", "What is on the table?")
        assert result["frames_used"] == 1
        assert result["answer"] == "I can see a dark square on the table."
        assert result["source"] == "authenticated_xiao_camera_and_local_vlm"
        assert not result["motor_authorized"] and not result["charging_authorized"]
        assert head.captures == 1 and head.commands == []
        assert len(model.calls[0][1]) == 1
        assert model.calls[0][1][0].startswith(b"\xff\xd8")
        assert result["latest_frame_age_ms"] >= 0
        assert result["recent_sensor_events"] == []
        timing = service.status("robot-01")["software_timings"]
        assert timing["camera_requests"] == 1
        assert timing["camera_successes"] == 1
        assert timing["visual_questions"] == 1
        assert timing["visual_answers"] == 1
        assert timing["camera_latency_last_ms"] >= 0
        assert timing["model_latency_last_ms"] >= 0
    finally:
        await service.close()





@pytest.mark.parametrize("regrant", [False, True])
async def test_new_visual_question_only_reuses_same_grant_camera_media(
    settings, regrant,
):
    """OFF/ON between requests cannot revive a still-fresh old-grant JPEG."""
    settings.voice_vision_tools_enabled = True
    settings.vision_model = "local-vlm"
    robot_id = settings.robots[0].id
    head, scene = Head(), Vision()
    visual = MultimodalOrchestrator(
        settings, {robot_id: head}, scene, asyncio.Lock(),
    )
    try:
        old = await visual.capture(robot_id, source="speech")
        assert head.captures == 1
        if regrant:
            previous_grant = settings.camera_consent_generation
            settings.voice_vision_tools_enabled = False
            settings.voice_vision_tools_enabled = True
            assert settings.camera_consent_generation > previous_grant
        result = await visual.look(robot_id, "What is on the desk?")
        assert result["answer"] == "I can see a dark square on the table."
        assert head.captures == (2 if regrant else 1)
        assert scene.calls
        assert (scene.calls[-1][1][-1] != old.jpeg) is regrant
    finally:
        await visual.close()

@pytest.mark.parametrize("revoke_and_regrant", [False, True])
async def test_visual_model_regrant_during_inference_cannot_restore_old_grant(
    settings, revoke_and_regrant,
):
    """A new camera grant cannot revive an answer begun on revoked frames."""
    settings.voice_vision_tools_enabled = True
    settings.vision_model = "local-vlm"
    entered, release = asyncio.Event(), asyncio.Event()
    robot_id = settings.robots[0].id

    class HeldVision:
        async def answer(self, question, frames):
            assert frames and question == "What is on the desk?"
            entered.set()
            await release.wait()
            return "old private scene"

    service = MultimodalOrchestrator(
        settings, {robot_id: Head()}, HeldVision(), asyncio.Lock(),
    )
    try:
        task = asyncio.create_task(service.look(robot_id, "What is on the desk?"))
        await asyncio.wait_for(entered.wait(), timeout=1)
        before = settings.camera_consent_generation
        if revoke_and_regrant:
            settings.voice_vision_tools_enabled = False
            settings.voice_vision_tools_enabled = True
            assert settings.camera_consent_generation > before
        release.set()
        if revoke_and_regrant:
            with pytest.raises(RuntimeError, match="Camera consent revoked"):
                await asyncio.wait_for(task, timeout=2)
            assert service.hub.recent_tool_context(robot_id, time.monotonic()) == []
            assert service._metrics[robot_id]["visual_answers"] == 0
        else:
            response = await asyncio.wait_for(task, timeout=2)
            assert response["answer"] == "old private scene"
            assert len(service.hub.recent_tool_context(robot_id, time.monotonic())) == 1
    finally:
        release.set()
        await service.close()


async def test_visual_model_revoke_during_inference_cannot_publish_answer_or_receipt():
    policy = config()

    class RevokingVision:
        async def answer(self, question, frames):
            assert frames and question == "What is on the desk?"
            policy.voice_vision_tools_enabled = False
            return "private visual scene"

    service = MultimodalOrchestrator(
        policy, {"robot-01": Head(), "robot-02": Head()},
        RevokingVision(), asyncio.Lock(),
    )
    try:
        with pytest.raises(RuntimeError, match="consent revoked"):
            await service.look("robot-01", "What is on the desk?")
        assert not service.hub.tool_history["robot-01"]
        assert service._metrics["robot-01"]["visual_answers"] == 0
    finally:
        await service.close()



async def test_actual_human_vad_schedules_camera_without_awaiting_jpeg():
    head = Head()
    service = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        service.voice_started("robot-01")  # synchronous, urgent audio comes first
        async with asyncio.timeout(1):
            while head.captures == 0:
                await asyncio.sleep(0.01)
        assert service.hub.user_active("robot-01", time.monotonic())
        assert service.status("robot-01")["frames_in_ram"] >= 1
        assert service.status("robot-01")["motor_authorized"] is False
    finally:
        await service.close()
        assert not service.hub.frames["robot-01"]


async def test_external_pet_jpeg_with_consent_off_never_decodes():
    visual = MultimodalOrchestrator(
        config(enabled=False), {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )

    async def forbidden_decode(*_args, **_kwargs):
        raise AssertionError("Preprocessing started without camera consent")

    visual._prepare_bounded = forbidden_decode
    try:
        await visual.offer_proactive("robot-01", image(), time.monotonic())
        assert not visual.hub.frames["robot-01"]
    finally:
        await visual.close()


async def test_external_pet_jpeg_revoke_while_decoding_never_publishes():
    entered, release = asyncio.Event(), asyncio.Event()
    policy = config(enabled=True)
    visual = MultimodalOrchestrator(
        policy, {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )

    async def blocked_prepare(jpeg, *, priority=False):
        entered.set()
        await release.wait()
        return _prepare(jpeg)

    visual._prepare_bounded = blocked_prepare
    task = asyncio.create_task(
        visual.offer_proactive("robot-01", image(), time.monotonic())
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        policy.voice_vision_tools_enabled = False
        release.set()
        await asyncio.wait_for(task, timeout=1)
        assert not visual.hub.frames["robot-01"]
    finally:
        release.set()
        await visual.close()


@pytest.mark.parametrize("source", ["sensor", "proactive", "speech", "voice_question"])
async def test_direct_capture_sources_fail_closed_without_vision_consent(source):
    head = Head()
    visual = MultimodalOrchestrator(
        config(enabled=False), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        with pytest.raises(RuntimeError, match="Camera consent revoked"):
            await visual.capture("robot-01", source=source)
        assert head.captures == 0
        assert not visual.hub.frames["robot-01"]
    finally:
        await visual.close()


async def test_camera_is_off_without_explicit_voice_vision_opt_in():
    head = Head()
    service = MultimodalOrchestrator(
        config(False), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        service.voice_started("robot-01")
        await asyncio.sleep(0)
        assert head.captures == 0
        with pytest.raises(ValueError, match="Enable"):
            await service.look("robot-01", "What is there?")
    finally:
        await service.close()


@pytest.mark.parametrize(("answer", "expected"), [
    ({"answer": "A blue cup is on the desk.", "visually_supported": True,
      "confidence": 0.93}, "A blue cup is on the desk."),
    ({"answer": "Maybe a cup.", "visually_supported": True,
      "confidence": 0.22}, "I can't tell from my camera right now."),
    ({"answer": "Unclear.", "visually_supported": False,
      "confidence": 0.9}, "I can't tell from my camera right now."),
])
async def test_local_vlm_speaks_from_visual_evidence_and_not_confidence_guess(answer, expected):
    def handler(req):
        body = json.loads(req.content)
        assert body["stream"] is False
        assert body["format"] == "json"
        assert body["messages"][0]["images"][0]
        assert "motion" not in body["messages"][0].get("tools", [])
        return httpx.Response(200, json={"message": {"content": json.dumps(answer)}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = OllamaScene(client, url="http://local:11434", model="local-vlm")
        assert await model.answer("What is there?", [image()]) == expected


@pytest.mark.parametrize("kind", ["oversized", "fake_header"])
async def test_direct_visual_question_rejects_corrupt_source_before_network(kind):
    """A visual question must not forward malformed JPEG bytes to the VLM."""
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"message": {"content": "{}"}})

    if kind == "oversized":
        frame = bytearray(image())
        sof = frame.find(bytes([255, 192]))
        assert sof > 0
        frame[sof + 5:sof + 9] = (5000).to_bytes(2, "big") * 2
        bad = bytes(frame)
    else:
        bad = bytes([255, 216]) + b"fake camera image contents"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = OllamaScene(client, url="http://local:11434", model="local-vlm")
        with pytest.raises((ValueError, OSError)):
            await model.answer("What is in front of me?", [bad])
    assert requests == []


async def test_vlm_two_frames_for_human_temporal_question():
    observed = []
    def handler(req):
        body = json.loads(req.content)
        observed.append(body)
        return httpx.Response(200, json={
            "message": {"content": json.dumps({
                "answer": "A small object appeared.",
                "visually_supported": True, "confidence": 0.91,
            })}
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = OllamaScene(client, url="http://local:11434", model="local-vlm")
        answer = await model.answer("What just changed?", [image(), image(square=True)])
        assert answer == "A small object appeared."
        assert len(observed[0]["messages"][0]["images"]) == 2


@pytest.mark.parametrize("out", [
    {"answer": "hi", "visually_supported": 1, "confidence": 0.8},
    {"answer": "hi", "visually_supported": True, "confidence": float("nan")},
    {"answer": "x" * 401, "visually_supported": True, "confidence": 0.9},
])
async def test_vlm_rejects_invalid_or_unbounded_multimodal_result(out):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(
            200, json={"message": {"content": json.dumps(out)}}
        )
    )) as client:
        model = OllamaScene(client, url="http://local:11434", model="local-vlm")
        with pytest.raises(ValueError):
            await model.answer("Tell me what you see", [image()])


async def test_new_real_human_utterance_cancels_old_vlm_image_answer():
    entered = asyncio.Event()
    class SlowVision:
        async def answer(self, question, frames):
            entered.set()
            await asyncio.Event().wait()
            return "STALE visual answer"

    head = Head()
    service = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        SlowVision(), asyncio.Lock(),
    )
    try:
        task = asyncio.create_task(service.look("robot-01", "What is this?"))
        await asyncio.wait_for(entered.wait(), timeout=1)
        service.voice_started("robot-01")
        with pytest.raises(RuntimeError, match="newer speech"):
            await task
        assert not service._look_tasks
    finally:
        await service.close()


async def test_visual_question_uses_current_spoken_turn_not_recent_idle_photo():
    head = Head()
    service = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )

    async def paused_automatic_speech_camera(_robot_id, _turn):
        await asyncio.Event().wait()

    # Prevent the background VAD sampler from being the source of this frame;
    # only the user's explicit visual tool may request a new one here.
    service._speech_frames = paused_automatic_speech_camera
    try:
        previous_idle_at = time.monotonic()
        service.hub.offer(
            "robot-01", image(), previous_idle_at, source="proactive"
        )
        service.voice_started("robot-01")
        assert previous_idle_at < service._voice_turn_at["robot-01"]
        response = await service.look("robot-01", "What can you see now?")
        assert head.captures == 1
        assert response["robot_id"] == "robot-01"
        assert service.hub.frames["robot-01"][-1].received_at >= (
            service._voice_turn_at["robot-01"]
        )
        service.voice_ended("robot-01")
    finally:
        await service.close()


async def test_fresh_frame_from_current_spoken_turn_is_reused_without_duplication():
    head = Head()
    service = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )

    async def paused_automatic_speech_camera(_robot_id, _turn):
        await asyncio.Event().wait()

    service._speech_frames = paused_automatic_speech_camera
    try:
        service.voice_started("robot-01")
        service.hub.offer(
            "robot-01", image(), time.monotonic(), source="speech"
        )
        response = await service.look("robot-01", "What is on the table?")
        assert head.captures == 0
        assert response["frames_used"] == 1
        service.voice_ended("robot-01")
    finally:
        await service.close()


async def test_real_vad_during_jpeg_cpu_prepare_suppresses_late_idle_frame(monkeypatch):
    import threading

    import desk_robot.multimodal as media

    entered = threading.Event()
    release = threading.Event()
    real_prepare = media._prepare

    def slow_prepare(jpeg):
        entered.set()
        release.wait(timeout=2)
        return real_prepare(jpeg)

    monkeypatch.setattr(media, "_prepare", slow_prepare)
    service = MultimodalOrchestrator(
        config(enabled=True),
        {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    service.start_speech_frames = lambda _robot_id: None
    task = asyncio.create_task(
        service.capture("robot-02", source="proactive")
    )
    try:
        assert await asyncio.wait_for(
            asyncio.to_thread(entered.wait, 0.8), timeout=1
        )
        service.voice_started("robot-01")
        release.set()
        with pytest.raises(RuntimeError, match="superseded"):
            await asyncio.wait_for(task, timeout=1)
        assert not service.hub.frames["robot-02"]
        assert service.hub.user_active("robot-01", time.monotonic())
        service.voice_ended("robot-01")
    finally:
        release.set()
        await service.close()


async def test_prepare_from_external_pet_cannot_add_frame_during_human_voice(monkeypatch):
    import threading

    import desk_robot.multimodal as media

    entered = threading.Event()
    release = threading.Event()
    real_prepare = media._prepare

    def slow_prepare(jpeg):
        entered.set()
        release.wait(timeout=2)
        return real_prepare(jpeg)

    monkeypatch.setattr(media, "_prepare", slow_prepare)
    service = MultimodalOrchestrator(
        config(enabled=True),
        {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    service.start_speech_frames = lambda _robot_id: None
    task = asyncio.create_task(
        service.offer_proactive("robot-02", image(), time.monotonic())
    )
    try:
        assert await asyncio.wait_for(
            asyncio.to_thread(entered.wait, 0.8), timeout=1
        )
        service.voice_started("robot-01")
        release.set()
        await asyncio.wait_for(task, timeout=1)
        assert not service.hub.frames["robot-02"]
        assert service.hub.user_active("robot-01", time.monotonic())
        service.voice_ended("robot-01")
    finally:
        release.set()
        await service.close()


async def test_new_human_on_one_head_cancels_other_heads_stale_visual_answer():
    entered = asyncio.Event()

    class SlowVision:
        async def answer(self, question, frames):
            entered.set()
            await asyncio.Event().wait()
            return "stale cross-head visual answer"

    service = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        SlowVision(), asyncio.Lock(),
    )
    task = asyncio.create_task(service.look("robot-02", "What is next to me?"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        service.voice_started("robot-01")
        with pytest.raises(RuntimeError, match="newer speech"):
            await asyncio.wait_for(task, timeout=1)
        assert service.hub.user_active("robot-01", time.monotonic())
        assert not service._look_tasks
        service.voice_ended("robot-01")
    finally:
        await service.close()


async def test_cross_head_visual_tools_wait_for_current_human_floor():
    heads = {"robot-01": Head(), "robot-02": Head()}
    model = Vision()
    service = MultimodalOrchestrator(config(), heads, model, asyncio.Lock())
    try:
        service.voice_started("robot-01")
        with pytest.raises(RuntimeError, match="Another human turn"):
            await service.look("robot-02", "What is on the table?")
        assert heads["robot-02"].captures == 0
        assert model.calls == []
        service.voice_ended("robot-01")
        answer = await service.look("robot-02", "What is on the table?")
        assert answer["robot_id"] == "robot-02"
    finally:
        await service.close()


async def test_second_visual_tool_call_replaces_previous_stale_question():
    first = asyncio.Event()
    class TwoVision:
        async def answer(self, question, frames):
            if question == "What did I first show?":
                first.set()
                await asyncio.Event().wait()
            return "The newest object."

    service = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        TwoVision(), asyncio.Lock(),
    )
    try:
        earlier = asyncio.create_task(
            service.look("robot-01", "What did I first show?")
        )
        await asyncio.wait_for(first.wait(), timeout=1)
        latest = await service.look("robot-01", "What is there now?")
        assert latest["answer"] == "The newest object."
        with pytest.raises(RuntimeError, match="newer visual question"):
            await earlier
        assert latest["motor_authorized"] is False
    finally:
        await service.close()


async def test_speech_end_preserves_visual_evidence_and_stops_capture_task():
    head = Head()
    service = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        service.voice_started("robot-01")
        async with asyncio.timeout(1):
            while not service.hub.frames["robot-01"]:
                await asyncio.sleep(0.005)
        frames = len(service.hub.frames["robot-01"])
        service.voice_ended("robot-01")
        assert not service.hub.user_active("robot-01", time.monotonic())
        await asyncio.sleep(0)
        assert len(service.hub.frames["robot-01"]) == frames
        assert service.hub.selected(
            "robot-01", "What do you see?", time.monotonic()
        )
    finally:
        await service.close()


async def test_camera_failure_does_not_release_authenticated_human_speech():
    class UnpluggedCamera(Head):
        async def snapshot(self):
            raise RuntimeError("XIAO camera unavailable")

    service = MultimodalOrchestrator(
        config(), {"robot-01": UnpluggedCamera(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        service.voice_started("robot-01")
        await asyncio.wait_for(service._capture_tasks["robot-01"], timeout=1)
        assert service.hub.user_active("robot-01", time.monotonic())
        assert not service.hub.frames["robot-01"]
        # The original authenticated voice event was not erased by a JPEG fault.
        assert any(event["kind"] == "human_voice" for event in
                   service.hub.recent_events("robot-01", time.monotonic()))
        service.voice_ended("robot-01")
        assert not service.hub.user_active("robot-01", time.monotonic())
    finally:
        await service.close()


async def test_jpeg_resize_worker_cannot_block_new_vad_on_event_loop(monkeypatch):
    import threading

    import desk_robot.multimodal as module

    entered = threading.Event()
    release = threading.Event()
    original = module._prepare

    def slow_decode(jpeg):
        entered.set()
        if not release.wait(2):
            raise AssertionError("test JPEG thread blocked")
        return original(jpeg)

    monkeypatch.setattr(module, "_prepare", slow_decode)
    service = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        pending = asyncio.create_task(
            service.capture("robot-01", source="speech")
        )
        assert await asyncio.to_thread(entered.wait, 1)
        # This MUST run immediately while another worker decodes JPEG;
        # it only changes VAD state, never waits on a Pillow worker.
        service.voice_started("robot-02")
        assert service.hub.user_active("robot-02", time.monotonic())
        release.set()
        # A human on another pet preempts the entire acoustic floor. The
        # old camera worker may finish decoding but MUST NOT publish its
        # obsolete frame into a later conversational generation.
        with pytest.raises(RuntimeError, match="Camera capture superseded"):
            await asyncio.wait_for(pending, 1)
        assert not service.hub.frames["robot-01"]
    finally:
        release.set()
        await service.close()


async def test_preprocessing_finishing_after_pause_cannot_republish_frame(monkeypatch):
    import threading

    import desk_robot.multimodal as module

    entered = threading.Event()
    release = threading.Event()
    original = module._prepare

    def slow_decode(jpeg):
        entered.set()
        if not release.wait(2):
            raise AssertionError("test JPEG thread blocked")
        return original(jpeg)

    monkeypatch.setattr(module, "_prepare", slow_decode)
    service = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        pending = asyncio.create_task(service.offer_proactive(
            "robot-01", image(), time.monotonic()
        ))
        assert await asyncio.to_thread(entered.wait, 1)
        service.hub.clear("robot-01")
        release.set()
        with pytest.raises(RuntimeError, match="Old camera generation"):
            await pending
        assert not service.hub.frames["robot-01"]
    finally:
        release.set()
        await service.close()


async def test_never_speak_delayed_live_scene_after_vlm_timeout():
    class HangingModel:
        async def answer(self, question, frames):
            await asyncio.Event().wait()
            return "An old scene falsely described as current."

    service = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        HangingModel(), asyncio.Lock(),
    )
    service._vision_timeout_s = 0.02
    try:
        with pytest.raises(RuntimeError, match="timed out"):
            await service.look("robot-01", "What do you see right now?")
        stats = service.status("robot-01")["software_timings"]
        assert stats["visual_questions"] == 1
        assert stats["visual_answers"] == 0
        assert stats["visual_errors"] == 1
        assert not service._look_tasks
        assert service.hub.frames["robot-01"]  # no fake model answer added
    finally:
        await service.close()


async def test_cancelled_preprocess_retains_native_worker_slot_until_it_exits(monkeypatch):
    """The Pillow thread must own admission until its actual completion."""
    import threading

    import desk_robot.multimodal as media

    started = threading.Event()
    release = threading.Event()
    original = media._prepare

    def stalled_decode(jpeg):
        started.set()
        if not release.wait(2):
            raise RuntimeError("stalled native decoder fixture timed out")
        return original(jpeg)

    monkeypatch.setattr(media, "_prepare", stalled_decode)
    visual = MultimodalOrchestrator(config(), {}, Vision(), asyncio.Lock())
    visual._preprocess_slots = threading.BoundedSemaphore(1)
    pending = asyncio.create_task(visual._prepare_bounded(image()))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        with pytest.raises(RuntimeError, match="JPEG preprocessing busy"):
            await visual._prepare_bounded(image())
        release.set()
        for _ in range(100):
            if visual._preprocess_slots.acquire(blocking=False):
                visual._preprocess_slots.release()
                break
            await asyncio.sleep(.01)
        else:
            pytest.fail("native decoder exit did not release preprocess budget")
        result = await visual._prepare_bounded(image())
        assert result[0].startswith(b"\xff\xd8")
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await visual.close()


async def test_preprocess_submission_failure_releases_native_budget(monkeypatch):
    """A stopped executor cannot consume all future image capacity."""
    import threading
    visual = MultimodalOrchestrator(config(), {}, Vision(), asyncio.Lock())
    visual._preprocess_slots = threading.BoundedSemaphore(1)
    visual._preprocess_pool.shutdown(wait=False, cancel_futures=True)
    try:
        with pytest.raises(RuntimeError):
            await visual._prepare_bounded(image())
        assert visual._preprocess_slots.acquire(blocking=False)
        visual._preprocess_slots.release()
    finally:
        await visual.close()


async def test_optional_jpeg_worker_cannot_starve_live_human_visual_preprocess(monkeypatch):
    """A blocked low priority decode cannot occupy both native worker slots."""
    import threading

    import desk_robot.multimodal as media

    started = threading.Event()
    release = threading.Event()

    def decode(jpeg):
        if jpeg == b"background":
            started.set()
            if not release.wait(2):
                raise RuntimeError("background fixture stalled")
        return jpeg, b"fingerprint", 100.0

    monkeypatch.setattr(media, "_prepare", decode)
    visual = MultimodalOrchestrator(config(), {}, Vision(), asyncio.Lock())
    pending = asyncio.create_task(visual._prepare_bounded(b"background"))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        with pytest.raises(RuntimeError, match="Background JPEG preprocessing busy"):
            await visual._prepare_bounded(b"another background")
        # The genuine speech/request owner keeps a native slot even when an
        # optional five-pet camera worker is stuck in decoder I/O.
        assert (await visual._prepare_bounded(
            b"voice", priority=True
        ))[0] == b"voice"
        release.set()
        assert (await pending)[0] == b"background"
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await visual.close()


async def test_native_duplex_reuses_current_speech_jpeg_instead_of_second_xiao_capture():
    """Native PCM and the Mac VAD JPEG sampler share one physical camera."""
    head = Head()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()}, Vision(),
        asyncio.Lock(),
    )
    try:
        visual._voice_turn_at["robot-01"] = time.monotonic() - 0.1
        first = await visual.capture("robot-01", source="speech")
        assert head.captures == 1
        assert await visual.native_frame("robot-01") is first
        assert head.captures == 1
        # A prior-turn speech JPEG must never be reclassified as live video.
        visual._voice_turn_at["robot-01"] = time.monotonic()
        second = await visual.native_frame("robot-01")
        assert second is not first
        assert head.captures == 2
        assert second.received_at > first.received_at
    finally:
        await visual.close()


async def test_native_duplex_does_not_borrow_background_idle_camera_frame():
    head = Head()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()}, Vision(),
        asyncio.Lock(),
    )
    try:
        idle = await visual.capture("robot-01", source="proactive")
        assert head.captures == 1
        frame = await visual.native_frame("robot-01")
        assert head.captures == 2
        assert frame is not idle
        assert frame.source == "speech"
    finally:
        await visual.close()


async def test_native_camera_racing_with_voice_sampler_has_one_real_xiao_capture():
    """Recheck frame freshness after both tasks contend for one camera lock."""
    started, release = asyncio.Event(), asyncio.Event()

    class SlowHead(Head):
        async def snapshot(self):
            started.set()
            await release.wait()
            return await super().snapshot()

    head = SlowHead()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()}, Vision(),
        asyncio.Lock(),
    )
    try:
        visual._voice_turn_at["robot-01"] = time.monotonic()
        sampler = asyncio.create_task(
            visual.capture("robot-01", source="speech",
                           reuse_if_recent_s=0.65)
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        native = asyncio.create_task(visual.native_frame("robot-01"))
        await asyncio.sleep(0.005)
        release.set()
        first, second = await asyncio.wait_for(
            asyncio.gather(sampler, native), timeout=3
        )
        assert first is second
        assert head.captures == 1
        assert visual.status("robot-01")["software_timings"][
            "native_speech_camera_reuses"
        ] == 1
    finally:
        release.set()
        await visual.close()


async def test_lost_xiaozhi_voice_transport_cancels_old_visual_turns_without_unmuting():
    visual = MultimodalOrchestrator(
        config(enabled=False),
        {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    now = time.monotonic()
    visual.hub.notify("robot-01", "human_voice", now)
    visual.hub.offer("robot-01", image(), now, source="speech")
    visual.hub.remember_heard("robot-01", "asr_before_reset", "A red key", now)
    pending = asyncio.Event()
    task = asyncio.create_task(pending.wait())
    visual._look_tasks["robot-01"] = task
    try:
        visual.voice_transport_unavailable()
        await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled()
        assert not visual.hub.frames["robot-01"]
        assert not visual.hub.heard_history["robot-01"]
        assert visual.hub.user_active("robot-01", time.monotonic())
        assert visual._reconnect_needs_sampler == {"robot-01", "robot-02"}
    finally:
        await visual.close()


async def test_readonly_vision_tool_interpretation_is_ephemeral_per_pet_and_fenced():
    """No raw photo persisted and new voice transport drops previous tool text."""
    heads = {"robot-01": Head(), "robot-02": Head()}
    visual = MultimodalOrchestrator(config(enabled=True), heads, Vision(),
                                    asyncio.Lock())
    try:
        response = await visual.look("robot-01", "What is on my desk?")
        assert response["motor_authorized"] is False
        cues = visual.hub.recent_tool_context("robot-01", time.monotonic())
        assert len(cues) == 1
        assert cues[0]["kind"] == "visual_look"
        assert cues[0]["source"] == "local_vlm_interpretation_not_physical_measurement"
        assert cues[0]["untrusted_text_not_instructions"] is True
        assert cues[0]["motor_authorized"] is False
        assert "dark square" in cues[0]["summary"]
        assert visual.hub.recent_tool_context("robot-02", time.monotonic()) == []
        # The successful local model description is not a durable eyewitness
        # memory. It may be referenced briefly but expires without persistence.
        now = time.monotonic()
        assert visual.hub.recent_tool_context("robot-01", now + 9) == []
        visual.voice_transport_unavailable()
        assert visual.hub.recent_tool_context("robot-01", now + 0.1) == []
        assert not visual.hub.frames["robot-01"]
    finally:
        await visual.close()


def test_readonly_tool_context_rejects_untrusted_shapes():
    hub = CameraFrameHub(["robot-01", "robot-02"])
    for kind, summary, when in (
        ("drive", "forward", 5.0),
        ("visual_look", "", 5.0),
        ("visual_look", "large" * 501, 5.0),
        ("visual_look", "summary", float("nan")),
    ):
        with pytest.raises(ValueError):
            hub.remember_tool("robot-01", kind, summary, when)
    with pytest.raises(ValueError):
        hub.remember_tool("robot-99", "visual_look", "some object", 5.0)


def test_repeated_status_tools_preserve_distinct_job_and_visual_context():
    hub = CameraFrameHub(["robot-01"])
    hub.remember_tool("robot-01", "visual_look", "Maybe a key", 100.0)
    hub.remember_tool("robot-01", "pickup_status", "job queued", 100.1)
    for i in range(10):
        hub.remember_tool(
            "robot-01", "robot_status", f"armed=False seq={i}", 100.2 + i * .1
        )
    context = hub.recent_tool_context("robot-01", 102.0)
    assert len(context) == 3
    assert {entry["kind"] for entry in context} == {
        "visual_look", "pickup_status", "robot_status"
    }
    assert any("seq=9" in entry["summary"] for entry in context)
    assert not any("seq=0" in entry["summary"] for entry in context)


def test_interaction_timeline_orders_camera_sensor_and_tool_without_raw_media():
    """One chronological context view, unlike three unsorted agent memories."""
    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.offer("robot-01", image(), 100.0, source="proactive")
    hub.notify("robot-01", "touch_tap", 100.3)
    hub.remember_tool("robot-01", "visual_look", "Maybe a red book", 100.6)
    timeline = hub.interaction_timeline("robot-01", 101)
    assert [entry["channel"] for entry in timeline] == [
        "camera", "sensor", "tool",
    ]
    assert timeline[0]["content"] is None
    assert timeline[0]["exposure_timestamp_verified"] is False
    assert timeline[1]["kind"] == "touch_tap"
    assert timeline[2]["content"] == "Maybe a red book"
    assert timeline[2]["untrusted_text_not_instructions"] is True
    assert all(item["physical_action_verified"] is False for item in timeline)
    assert hub.interaction_timeline("robot-02", 101) == []
    # Routine taps have an eight-second conversational TTL, not a
    # sixty-second historical warning. Meaningful handling cues use the
    # separate situation history instead.
    aged = hub.interaction_timeline("robot-01", 109)
    assert aged == []
    assert hub.interaction_timeline("robot-01", 161) == []
    assert len(hub.interaction_timeline("robot-01", 101, limit=2)) == 2
    with pytest.raises(ValueError):
        hub.interaction_timeline("robot-01", float("nan"))
    with pytest.raises(ValueError):
        hub.interaction_timeline("robot-01", 101, limit=99)


async def test_new_human_voice_resets_prior_interpretation_across_fleet():
    visual = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        now = time.monotonic()
        visual.hub.remember_tool("robot-01", "visual_look", "old scene guess", now)
        visual.hub.remember_tool("robot-02", "visual_look", "other old guess", now)
        visual.voice_started("robot-02")
        assert visual.hub.recent_tool_context("robot-01", time.monotonic()) == []
        assert visual.hub.recent_tool_context("robot-02", time.monotonic()) == []
        assert visual.hub.user_active("robot-02", time.monotonic())
        visual.voice_ended("robot-02")
    finally:
        await visual.close()


def test_qwen_style_quiet_window_silences_only_optional_fleet_remarks():
    """Human owns conversation for 800ms after real speech_end, not motors."""
    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.notify("robot-02", "human_voice", 100.0)
    assert hub.spontaneous_floor_busy(100.5)
    hub.speech_ended("robot-02", 101.0)
    assert hub.spontaneous_floor_busy(101.79)
    assert not hub.spontaneous_floor_busy(101.81)
    # Camera sampling remains independently available in that short pause.
    assert hub.due("robot-01", 101.2)
    hub.notify("robot-01", "human_voice", 102.0)
    assert hub.spontaneous_floor_busy(103.0)
    hub.clear("robot-01")
    assert not hub.spontaneous_floor_busy(103.0)
    with pytest.raises(ValueError):
        hub.spontaneous_floor_busy(float("nan"))


async def test_recent_pet_words_survive_next_vad_but_not_acoustic_hardware_claim():
    """Human reply can refer to the pet's offer, even without memory consent."""
    visual = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        now = time.monotonic()
        visual.hub.remember_spoken(
            "robot-01", "Want to play a little guessing game?", now
        )
        visual.hub.remember_tool(
            "robot-01", "visual_look", "Old uncertain camera guess", now
        )
        visual.voice_started("robot-01")
        timeline = visual.hub.interaction_timeline("robot-01", time.monotonic())
        words = [entry for entry in timeline
                 if entry["channel"] == "robot_speech"]
        assert len(words) == 1
        assert "guessing game" in words[0]["content"]
        assert words[0]["playback_verified"] is False
        assert words[0]["source"] == (
            "mac_tts_transmitted_not_speaker_playback_ack"
        )
        assert not [entry for entry in timeline
                    if entry["channel"] == "tool"]
        assert not [entry for entry in visual.hub.interaction_timeline(
            "robot-02", time.monotonic()
        ) if entry["channel"] == "robot_speech"]
        visual.voice_ended("robot-01")
        assert not [entry for entry in visual.hub.interaction_timeline(
            "robot-01", now + 31
        ) if entry["channel"] == "robot_speech"]
        visual.voice_transport_unavailable()
        # A disconnected camera/voice source cannot revoke evidence of the
        # Mac's previously transmitted words, but still cannot prove playback.
        assert visual.hub.spoken_history["robot-01"]
        retained = [
            item for item in visual.hub.interaction_timeline(
                "robot-01", time.monotonic()
            ) if item["channel"] == "robot_speech"
        ]
        assert len(retained) == 1
        assert retained[0]["playback_verified"] is False
    finally:
        await visual.close()


def test_spoken_receipt_requires_actual_bounded_transmitted_text():
    hub = CameraFrameHub(["robot-01"])
    for value, when in (
        ("", 2.0), ("x" * 281, 2.0), ("said", float("nan")),
        ("bad\x00text", 2.0),
    ):
        with pytest.raises(ValueError):
            hub.remember_spoken("robot-01", value, when)
    with pytest.raises(ValueError):
        hub.remember_spoken("robot-02", "not my pet", 2.0)


@pytest.mark.parametrize("source", ["proactive", "sensor", "external_pet"])
async def test_completed_brief_vad_cannot_publish_old_optional_jpeg(
    monkeypatch, source,
):
    """VAD may BEGIN and END during CPU decode; current voice=False is not enough."""
    import threading

    import desk_robot.multimodal as media

    entered = threading.Event()
    release = threading.Event()
    original = media._prepare

    def held_prepare(jpeg):
        entered.set()
        release.wait(timeout=2)
        return original(jpeg)

    monkeypatch.setattr(media, "_prepare", held_prepare)
    service = MultimodalOrchestrator(
        config(enabled=True),
        {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    service.start_speech_frames = lambda _robot_id: None
    started = time.monotonic()
    task = asyncio.create_task(
        service.offer_proactive("robot-02", image(), started)
        if source == "external_pet" else
        service.capture("robot-02", source=source)
    )
    try:
        assert await asyncio.wait_for(
            asyncio.to_thread(entered.wait, 0.8), timeout=1
        )
        # Human voice on a DIFFERENT head gets the global attention floor.
        service.voice_started("robot-01")
        service.voice_ended("robot-01")
        assert not service.hub.user_active("robot-01", time.monotonic())
        release.set()
        if source == "external_pet":
            assert await asyncio.wait_for(task, timeout=1) is None
        else:
            with pytest.raises(RuntimeError, match="superseded"):
                await asyncio.wait_for(task, timeout=1)
        assert not service.hub.frames["robot-02"]
    finally:
        release.set()
        await service.close()


@pytest.mark.parametrize("source", ["speech", "voice_question"])
@pytest.mark.parametrize("invalidate", ["new_turn", "transport_loss"])
async def test_old_native_camera_cannot_repopulate_new_voice_turn(
    monkeypatch, source, invalidate,
):
    """An /omni-frame HTTP task is not owned by the cancellable VAD sampler."""
    import threading

    import desk_robot.multimodal as media

    entered, release = threading.Event(), threading.Event()
    original = media._prepare

    def held_prepare(jpeg):
        entered.set()
        release.wait(timeout=2)
        return original(jpeg)

    monkeypatch.setattr(media, "_prepare", held_prepare)
    service = MultimodalOrchestrator(
        config(enabled=True),
        {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    service.start_speech_frames = lambda _robot_id: None
    task = asyncio.create_task(service.capture("robot-01", source=source))
    try:
        assert await asyncio.wait_for(
            asyncio.to_thread(entered.wait, 0.8), timeout=1
        )
        if invalidate == "new_turn":
            service.voice_started("robot-02")
            service.voice_ended("robot-02")
        else:
            service.voice_transport_unavailable()
        release.set()
        with pytest.raises(RuntimeError, match="superseded"):
            await asyncio.wait_for(task, timeout=1)
        assert not service.hub.frames["robot-01"]
        assert service.status("robot-01")["software_timings"]["camera_errors"] >= 1
    finally:
        release.set()
        await service.close()


async def test_external_pet_photo_received_before_brief_voice_is_never_replayed():
    service = MultimodalOrchestrator(
        config(enabled=True),
        {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    service.start_speech_frames = lambda _robot_id: None
    try:
        old_receipt = time.monotonic()
        service.voice_started("robot-01")
        service.voice_ended("robot-01")
        await service.offer_proactive("robot-02", image(), old_receipt)
        assert not service.hub.frames["robot-02"]
        fresh = time.monotonic()
        await service.offer_proactive("robot-02", image(), fresh)
        assert len(service.hub.frames["robot-02"]) == 1
        assert service.hub.frames["robot-02"][-1].received_at == fresh
    finally:
        await service.close()


def test_equal_timestamp_tool_receipt_cannot_overwrite_first_result():
    """Same-clock duplicate completion must not replace authenticated evidence."""
    hub = CameraFrameHub(["robot-01"])
    hub.remember_tool("robot-01", "visual_look", "first completed frame", 10.0)
    hub.remember_tool("robot-01", "visual_look", "late duplicate", 10.0)
    receipts = hub.recent_tool_context("robot-01", 11.0)
    assert len(receipts) == 1
    assert receipts[0]["summary"] == "first completed frame"
    hub.remember_tool("robot-01", "visual_look", "new frame", 10.1)
    assert hub.recent_tool_context("robot-01", 11.0)[0]["summary"] == "new frame"


def test_video_loss_retains_five_kinds_of_tool_receipts_without_visual_guess():
    """A camera transport outage must not erase independent read-only facts."""
    hub = CameraFrameHub(["robot-01", "robot-02"])
    kinds = (
        "visual_look", "robot_status", "pickup_status",
        "sensor_telemetry", "memory_recall",
    )
    for index, kind in enumerate(kinds):
        hub.remember_tool("robot-01", kind, kind + " evidence", 100.0 + index * .1)
    hub.remember_tool("robot-02", "visual_look", "other pet visual guess", 100.0)
    assert {item["kind"] for item in hub.recent_tool_context("robot-01", 101)} == set(kinds)

    hub.discard_video("robot-01")
    receipts = hub.recent_tool_context("robot-01", 101)
    assert {item["kind"] for item in receipts} == set(kinds) - {"visual_look"}
    assert all(item["source"] != "local_vlm_interpretation_not_physical_measurement"
               for item in receipts)
    assert [entry["kind"] for entry in hub.recent_tool_context("robot-02", 101)] == [
        "visual_look"
    ]
    assert all(entry["kind"] != "visual_look" for entry in hub.interaction_timeline(
        "robot-01", 101
    ))
    hub.clear("robot-01")
    assert hub.recent_tool_context("robot-01", 101) == []


async def test_native_stream_subscriber_ignores_interleaved_sensor_snapshot():
    """A sensor burst cannot poison the native continuous video source."""
    visual = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    reader = visual.native_live_frames("robot-01")
    task = asyncio.create_task(anext(reader))
    try:
        await asyncio.sleep(0)
        visual.hub.offer("robot-01", image(), time.monotonic(), source="proactive")
        visual.hub.offer(
            "robot-01", image(square=True), time.monotonic(), source="sensor",
        )
        assert visual.hub.frames["robot-01"][-1].source == "sensor"
        async with visual._model_frame_conditions["robot-01"]:
            visual._model_frame_versions["robot-01"] += 1
            visual._model_frame_conditions["robot-01"].notify_all()
        selected = await asyncio.wait_for(task, timeout=1)
        assert selected.source == "proactive"
        assert selected.jpeg.startswith(b"\xff\xd8")
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await reader.aclose()
        await visual.close()


async def test_other_pets_new_human_turn_preserves_my_completed_nonvisual_tools():
    """One robot's voice cannot silently erase another pet's tool history."""
    visual = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        now = time.monotonic()
        for kind in ("robot_status", "pickup_status", "memory_recall"):
            visual.hub.remember_tool("robot-01", kind, kind, now)
        visual.hub.remember_tool("robot-01", "visual_look", "old scene", now)
        visual.hub.remember_tool("robot-02", "robot_status", "old turn", now)
        visual.voice_started("robot-02")
        assert {entry["kind"] for entry in visual.hub.recent_tool_context(
            "robot-01", time.monotonic()
        )} == {"robot_status", "pickup_status", "memory_recall"}
        assert visual.hub.recent_tool_context(
            "robot-02", time.monotonic()
        ) == []  # The speaking pet has actually started a new tool turn.
        visual.voice_ended("robot-02")
    finally:
        await visual.close()


async def test_lost_voice_transport_invalidates_old_tool_turn_not_only_visuals():
    """Disconnected voice auth cannot feed an interrupted tool reply next turn."""
    visual = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        now = time.monotonic()
        for robot_id in ("robot-01", "robot-02"):
            visual.hub.remember_tool(robot_id, "robot_status", "old status", now)
            visual.hub.remember_tool(robot_id, "visual_look", "old guess", now)
            assert visual.hub.recent_tool_context(robot_id, now)
        visual.voice_transport_unavailable()
        for robot_id in ("robot-01", "robot-02"):
            assert visual.hub.recent_tool_context(robot_id, time.monotonic()) == []
        # Audio/transcript provenance is reset without forging a speech end.
        assert all(not visual.hub.heard_history[robot_id]
                   for robot_id in ("robot-01", "robot-02"))
    finally:
        await visual.close()


def test_native_sent_audio_receipts_enter_only_own_bounded_live_history():
    """Model text is a sent-Opus estimate, never another pet's heard speech."""
    hub = CameraFrameHub(["robot-01", "robot-02"])
    now = time.monotonic()
    identity = "omni_sent_" + "a" * 12 + "_" + "b" * 20
    assert hub.remember_native_spoken("robot-01", identity, "I noticed the mug", now)
    # Even a known receipt ID cannot turn malformed text into an accepted
    # API result. Validate before duplicate suppression, without creating
    # any new per-pet speech or physical action evidence.
    for invalid in ("bad\\x00text".replace("\\x00", "\x00"), "  ", "x" * 201):
        with pytest.raises(ValueError, match="Invalid native model sent speech"):
            hub.remember_native_spoken("robot-01", identity, invalid, now)
    assert not hub.remember_native_spoken("robot-01", identity, "replayed", now)
    timeline = hub.interaction_timeline("robot-01", now)
    speech = [item for item in timeline if item["channel"] == "robot_speech"]
    assert len(speech) == 1
    assert speech[0]["content"] == "I noticed the mug"
    assert speech[0]["source"] == (
        "native_model_text_opus_sent_playback_unverified"
    )
    assert speech[0]["playback_verified"] is False
    assert hub.interaction_timeline("robot-02", now) == []
    with pytest.raises(ValueError):
        hub.remember_native_spoken("robot-02", identity, "expired", now - 10)
    with pytest.raises(ValueError):
        hub.remember_native_spoken("robot-02", identity, "future", now + 10)
    assert not hub.interaction_timeline("robot-01", now + 31)
    hub.clear("robot-01")
    assert not hub.native_spoken_ids["robot-01"]



def test_finite_rejects_unrepresentable_host_timestamps():
    """Untrusted integer timestamps must fail closed, not raise OverflowError."""
    from desk_robot.multimodal import _finite

    assert _finite(0)
    assert _finite(1.5)
    assert not _finite(True)
    assert not _finite(float("inf"))
    assert not _finite(10 ** 1000)
    assert not _finite(-(10 ** 1000))


def test_stale_speech_end_does_not_release_newer_human_vad():
    """Out of order end from the previous turn must not free the fleet floor."""
    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.notify("robot-01", "human_voice", 10.0)
    hub.notify("robot-01", "human_voice", 12.0)
    hub.speech_ended("robot-01", 11.0)
    assert hub.user_active("robot-01", 12.1)
    assert hub.spontaneous_floor_busy(12.1)
    hub.speech_ended("robot-01", 13.0)
    assert not hub.user_active("robot-01", 13.0)
    assert hub.spontaneous_floor_busy(13.2)
    assert not hub.spontaneous_floor_busy(14.0)


async def test_proactive_camera_ignoring_cancel_does_not_pin_live_camera_lock(
    monkeypatch,
):
    """An obsolete low-priority camera cannot hold a new human capture lock."""
    from desk_robot import controller

    original = controller._bounded_head_reply
    async def short_deadline(coro, *, seconds, timeout_message):
        return await original(coro, seconds=0.04,
                              timeout_message=timeout_message)
    monkeypatch.setattr(controller, "_bounded_head_reply", short_deadline)

    started = asyncio.Event()
    release = asyncio.Event()

    class StubbornCamera(Head):
        async def snapshot(self):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
                return image(square=True)

    head = StubbornCamera()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        with pytest.raises(TimeoutError, match="Live proactive camera timed out"):
            await asyncio.wait_for(
                visual.capture("robot-01", source="proactive"), timeout=.5,
            )
        assert started.is_set()
        assert not visual._camera_locks["robot-01"].locked()
        assert "robot-01" not in visual._proactive_snapshots
        assert not visual.hub.frames["robot-01"]
        release.set()
        await asyncio.sleep(0)
        assert not visual.hub.frames["robot-01"]
    finally:
        release.set()
        await visual.close()


async def test_uncooperative_visual_model_timeout_releases_fleet_inference_lock():
    """A slow provider that suppresses cancellation cannot starve five pets."""
    entered = asyncio.Event()
    release = asyncio.Event()
    cancelled = asyncio.Event()

    class StubbornModel:
        async def answer(self, question, frames):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
                return "An obsolete visual reply must not be published"

    service = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        StubbornModel(), asyncio.Lock(),
    )
    service._vision_timeout_s = 0.04
    try:
        with pytest.raises(RuntimeError, match="timed out"):
            await asyncio.wait_for(
                service.look("robot-01", "What is on my desk?"), timeout=.5,
            )
        assert entered.is_set()
        # Cancellation is delivered on the next event loop turn, after the
        # timeout handler has already relinquished its inference ownership.
        await asyncio.wait_for(cancelled.wait(), timeout=.5)
        await asyncio.wait_for(service.inference_lock.acquire(), timeout=.2)
        service.inference_lock.release()
        assert not service._look_tasks
        assert service.status("robot-01")["software_timings"]["visual_answers"] == 0
        assert service.hub.recent_tool_context("robot-01", time.monotonic()) == []
    finally:
        release.set()
        await asyncio.sleep(0)
        await service.close()


async def test_cancel_resistant_snapshot_keeps_physical_read_owned_across_turns(
    monkeypatch,
):
    """A stale snapshot cannot overlap a newer capture on the same XIAO."""
    from desk_robot import controller

    normal = controller._bounded_head_reply

    async def fast_timeout(coro, *, seconds, timeout_message):
        return await normal(coro, seconds=0.04, timeout_message=timeout_message)

    monkeypatch.setattr(controller, "_bounded_head_reply", fast_timeout)
    entered, released = asyncio.Event(), asyncio.Event()

    class StubbornHead(Head):
        async def snapshot(self):
            self.captures += 1
            if self.captures == 1:
                entered.set()
                while not released.is_set():
                    try:
                        await released.wait()
                    except asyncio.CancelledError:
                        continue
            return image(square=True)

    head, peer = StubbornHead(), Head()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": peer},
        Vision(), asyncio.Lock(),
    )
    try:
        with pytest.raises(TimeoutError, match="Live proactive camera timed out"):
            await visual.capture("robot-01", source="proactive")
        await asyncio.wait_for(entered.wait(), 0.2)
        assert not visual._head_snapshot_tasks["robot-01"].done()
        # An expired snapshot is still touching this device. Do not create
        # a competing human or background snapshot while it runs.
        with pytest.raises(RuntimeError, match="still in flight"):
            await visual.capture("robot-01", source="speech")
        assert head.captures == 1
        assert not visual.hub.frames["robot-01"]
        # The other robot is independently operational.
        await visual.capture("robot-02", source="speech")
        assert peer.captures == 1
        released.set()
        await asyncio.wait_for(visual._head_snapshot_tasks["robot-01"], 0.5)
        assert not visual.hub.frames["robot-01"]
        await visual.capture("robot-01", source="speech")
        assert head.captures == 2
        assert len(visual.hub.frames["robot-01"]) == 1
    finally:
        released.set()
        await visual.close()


async def test_old_speech_frame_worker_cannot_outlive_new_voice_epoch():
    """A cancelled sampler that ignores cancellation cannot serve a new turn."""
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    visual = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )

    async def stubborn_capture(robot_id, *, source, reuse_if_recent_s):
        calls.append((robot_id, source))
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
        return None

    visual.capture = stubborn_capture
    visual.hub.notify("robot-01", "human_voice", time.monotonic())
    visual._turn_epoch["robot-01"] = 1
    old = asyncio.create_task(visual._speech_frames("robot-01", 1))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        old.cancel()
        visual._turn_epoch["robot-01"] = 2
        visual.hub.notify("robot-01", "human_voice", time.monotonic())
        release.set()
        await asyncio.wait_for(old, timeout=0.4)
        assert calls == [("robot-01", "speech")]
    finally:
        release.set()
        if not old.done():
            old.cancel()
        await visual.close()


async def test_close_preserves_cancellation_resistant_physical_snapshot_ownership():
    """Shutdown must not forget an adapter still executing a device read."""
    started, release = asyncio.Event(), asyncio.Event()
    head = Head()
    async def stubborn_snapshot():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
        return b"\\xff\\xd8"

    head.snapshot = stubborn_snapshot
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    caller = asyncio.create_task(visual._head_snapshot("robot-01", source="speech"))
    try:
        await asyncio.wait_for(started.wait(), 1)
        physical = visual._head_snapshot_tasks["robot-01"]
        await asyncio.wait_for(visual.close(), 2)
        assert not physical.done()
        assert visual._head_snapshot_tasks["robot-01"] is physical
        release.set()
        await asyncio.wait_for(physical, 1)
        await asyncio.sleep(0)
        assert "robot-01" not in visual._head_snapshot_tasks
        assert visual._closed
    finally:
        release.set()
        if not caller.done():
            caller.cancel()
        await asyncio.gather(caller, return_exceptions=True)


async def test_close_uses_one_deadline_for_stream_and_physical_snapshot():
    """Two independent stubborn adapters must not double shutdown latency."""
    entered = [asyncio.Event(), asyncio.Event()]
    release = asyncio.Event()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )

    async def stubborn(index):
        entered[index].set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()

    stream = asyncio.create_task(stubborn(0))
    snapshot = asyncio.create_task(stubborn(1))
    visual._stream_tasks["robot-01"] = stream
    visual._head_snapshot_tasks["robot-02"] = snapshot
    try:
        await asyncio.gather(*(event.wait() for event in entered))
        start = asyncio.get_running_loop().time()
        await asyncio.wait_for(visual.close(), 1.5)
        elapsed = asyncio.get_running_loop().time() - start
        assert elapsed < 0.85, f"shutdown waited twice: {elapsed:.3f}s"
        assert visual._stream_tasks["robot-01"] is stream
        assert visual._head_snapshot_tasks["robot-02"] is snapshot
        release.set()
        await asyncio.gather(stream, snapshot)
        await asyncio.sleep(0)
        assert "robot-01" not in visual._stream_tasks
        assert "robot-02" not in visual._head_snapshot_tasks
    finally:
        release.set()
        await asyncio.gather(stream, snapshot, return_exceptions=True)


async def test_close_bounds_cancellation_resistant_stream_worker():
    """A stubborn stream worker cannot hang shutdown or lose ownership."""
    entered, release = asyncio.Event(), asyncio.Event()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )

    async def stubborn_stream():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()

    worker = asyncio.create_task(stubborn_stream())
    visual._stream_tasks["robot-01"] = worker
    try:
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.wait_for(visual.close(), 2)
        assert not worker.done()
        assert visual._stream_tasks["robot-01"] is worker
        release.set()
        await asyncio.wait_for(worker, 1)
        await asyncio.sleep(0)
        assert "robot-01" not in visual._stream_tasks
    finally:
        release.set()
        if not worker.done():
            worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


def test_authenticated_snapshot_release_preserves_quiet_floor_and_delayed_end():
    """Authenticated recovery must not let one of five pets talk over a pause."""
    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.notify("robot-01", "human_voice", 100.0)
    hub.reconcile_speech_snapshot(frozenset(), 101.0)
    assert not hub.user_active("robot-01", 101.0)
    assert hub.spontaneous_floor_busy(101.79)
    assert not hub.spontaneous_floor_busy(101.81)

    # A delayed duplicate end may not roll back a newer acoustic pause.
    hub.notify("robot-02", "human_voice", 102.0)
    hub.speech_ended("robot-02", 103.0)
    hub.speech_ended("robot-02", 102.5)
    assert not hub.user_active("robot-02", 103.0)
    assert hub.spontaneous_floor_busy(103.79)
    assert not hub.spontaneous_floor_busy(103.81)

    # A new VAD start still blocks spontaneous speech, regardless of pause.
    hub.notify("robot-01", "human_voice", 104.0)
    assert hub.spontaneous_floor_busy(104.1)




def test_missed_vad_start_snapshot_rejects_stale_end_and_preserves_epoch():
    """A recovered human turn is protected even without a speech_start edge."""
    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.reconcile_speech_snapshot(frozenset({"robot-02"}), 100.0)
    assert hub.voice_started_at["robot-02"] == 100.0
    hub.reconcile_speech_snapshot(frozenset({"robot-02"}), 101.0)
    assert hub.voice_started_at["robot-02"] == 100.0
    hub.speech_ended("robot-02", 99.0)
    assert hub.user_active("robot-02", 101.0)
    assert hub.spontaneous_floor_busy(101.0)
    hub.reconcile_speech_snapshot(frozenset(), 102.0)
    assert not hub.user_active("robot-02", 102.0)
    assert hub.spontaneous_floor_busy(102.79)
    assert not hub.spontaneous_floor_busy(102.81)


def test_aged_physical_situation_is_history_not_live_motion_authority():
    """An extended utterance should not erase older physical context."""
    from desk_robot.brain_context import compose_brain_context

    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.notify("robot-01", "handling_tilt", 1.0)
    hub.notify("robot-01", "side_object", 2.0)
    for index in range(20):
        hub.notify("robot-01", "touch", 2.1 + index * 0.01)
    timeline = hub.interaction_timeline("robot-01", 15.0, limit=10)
    past = {item["kind"]: item for item in timeline
            if item["channel"] == "sensor_history"}
    assert {"handling_tilt", "side_object"} <= past.keys()
    assert past["handling_tilt"]["age_ms"] == 14000
    assert all(item["historical_not_current"] is True for item in past.values())
    assert not any(item["channel"] == "sensor"
                   and item["kind"] == "handling_tilt" for item in timeline)
    prompt = compose_brain_context([], [], timeline).interaction
    assert "Earlier physical edge (14s ago; historical" in prompt
    assert "handling_tilt" in prompt
    assert hub.interaction_timeline("robot-02", 15.0) == []
    assert not any(item["channel"] == "sensor_history"
                   for item in hub.interaction_timeline("robot-01", 63.0))
    hub.clear("robot-01")
    assert not hub.situation_edges["robot-01"]


def test_future_tool_receipt_cannot_poison_latest_completed_result():
    hub = CameraFrameHub(["robot-01", "robot-02"])
    now = time.monotonic()
    with pytest.raises(ValueError, match="Future read-only tool receipt clock"):
        hub.remember_tool("robot-01", "robot_status",
                          "FUTURE_UNTRUSTED_STATUS", now + 3600)
    hub.remember_tool("robot-01", "robot_status",
                      "CURRENT_AUTHENTIC_STATUS", now)
    receipts = hub.recent_tool_context("robot-01", time.monotonic())
    assert len(receipts) == 1
    assert receipts[0]["summary"] == "CURRENT_AUTHENTIC_STATUS"
    assert "FUTURE_UNTRUSTED_STATUS" not in str(
        hub.interaction_timeline("robot-01", time.monotonic())
    )
    assert hub.recent_tool_context("robot-02", time.monotonic()) == []


def test_future_asr_receipt_is_rejected_before_dedup_and_turn_context():
    hub = CameraFrameHub(["robot-01"])
    now = time.monotonic()
    with pytest.raises(ValueError, match="Future native ASR receipt clock"):
        hub.remember_heard("robot-01", "voice-001",
                           "FUTURE_UNTRUSTED_REQUEST", now + 3600)
    assert hub.remember_heard("robot-01", "voice-001",
                              "CURRENT_HUMAN_REQUEST", now)
    timeline = hub.interaction_timeline("robot-01", time.monotonic())
    assert [event["content"] for event in timeline
            if event["channel"] == "human_transcript"] == [
                "CURRENT_HUMAN_REQUEST"
            ]


def test_future_vad_evidence_cannot_poison_speech_floor_or_later_end():
    hub = CameraFrameHub(["robot-01", "robot-02"])
    now = time.monotonic()
    with pytest.raises(ValueError, match="invalid time"):
        hub.notify("robot-01", "human_voice", now + 3600)
    assert not hub.user_active("robot-01", now)
    assert hub.recent_events("robot-01", now) == []
    # A real current turn must survive forged future end or monitor receipt.
    hub.notify("robot-01", "human_voice", now)
    assert hub.user_active("robot-01", now + 0.01)
    with pytest.raises(ValueError, match="VAD end timestamp"):
        hub.speech_ended("robot-01", now + 3600)
    with pytest.raises(ValueError, match="VAD snapshot"):
        hub.reconcile_speech_snapshot(frozenset(), now + 3600)
    assert hub.user_active("robot-01", now + 0.02)
    assert not hub.user_active("robot-02", now + 0.02)
    # A valid end retains 800 ms of post-human quiet, then releases floor.
    hub.speech_ended("robot-01", now + 0.03)
    assert not hub.user_active("robot-01", now + 0.04)
    assert hub.spontaneous_floor_busy(now + 0.5)
    assert not hub.spontaneous_floor_busy(now + 0.9)


def test_room_cache_does_not_cross_revoke_and_regrant():
    from desk_robot.room_station import RoomObservation

    policy = SimpleNamespace(
        mode="hardware", room_station_context_enabled=True,
        room_station_consent_generation=7,
    )
    hub = CameraFrameHub(["robot-01", "robot-02"], room_settings=policy)
    now = time.monotonic()
    first = RoomObservation(
        seq=1, at_ms=100, received_at=now,
        readings={}, summary="OLD_GRANT_ROOM_SAMPLE",
    )
    hub.remember_room(first)
    assert "OLD_GRANT_ROOM_SAMPLE" in str(
        hub.interaction_timeline("robot-02", now + 0.1)
    )

    # Revocation must immediately hide the old sample. Regrant without a
    # new USB measurement must not resurrect it on a different pet.
    policy.room_station_context_enabled = False
    assert "room_station" not in [
        event["channel"] for event in hub.interaction_timeline(
            "robot-01", now + 0.2
        )
    ]
    hub.remember_room(RoomObservation(
        seq=2, at_ms=200, received_at=now + 0.2,
        readings={}, summary="NOT_CONSENTED",
    ))
    policy.room_station_consent_generation = 8
    policy.room_station_context_enabled = True
    for robot_id in ("robot-01", "robot-02"):
        assert "room_station" not in [
            event["channel"] for event in hub.interaction_timeline(
                robot_id, now + 0.3
            )
        ]
    assert hub.shared_room == first

    second = RoomObservation(
        seq=3, at_ms=300, received_at=now + 0.4,
        readings={}, summary="NEW_GRANT_ROOM_SAMPLE",
    )
    hub.remember_room(second)
    assert hub.shared_room == second
    assert "NEW_GRANT_ROOM_SAMPLE" in str(
        hub.interaction_timeline("robot-01", now + 0.5)
    )
    assert "OLD_GRANT_ROOM_SAMPLE" not in str(
        hub.interaction_timeline("robot-01", now + 0.5)
    )

    # A bare hub remains suitable for a simulation or nonproduction fixture.
    independent = CameraFrameHub(["robot-01"])
    independent.remember_room(first)
    assert "OLD_GRANT_ROOM_SAMPLE" in str(
        independent.interaction_timeline("robot-01", now + 0.5)
    )


def test_future_camera_and_shared_room_receipts_cannot_block_real_observations():
    from desk_robot.room_station import RoomObservation

    hub = CameraFrameHub(["robot-01", "robot-02"])
    now = time.monotonic()
    prepared = _prepare(image())
    with pytest.raises(ValueError, match="invalid time"):
        hub.offer_prepared(
            "robot-01", prepared, now + 3600, source="proactive",
        )
    assert not hub.frames["robot-01"]
    assert hub.due("robot-01", now)
    legitimate_frame = hub.offer_prepared(
        "robot-01", prepared, now, source="proactive",
    )
    assert hub.selected("robot-01", "What is on the desk?", now) == [legitimate_frame]
    assert hub.selected("robot-02", "What do you see?", now) == []

    poisoned = RoomObservation(
        seq=1, at_ms=1, received_at=now + 3600,
        readings={}, summary="FUTURE_SHARED_STATION",
    )
    real = RoomObservation(
        seq=2, at_ms=2, received_at=now,
        readings={}, summary="CURRENT_SHARED_STATION",
    )
    with pytest.raises(ValueError, match="Room provenance"):
        hub.remember_room(poisoned)
    hub.remember_room(real)
    assert hub.shared_room == real
    assert "CURRENT_SHARED_STATION" in str(
        hub.interaction_timeline("robot-02", now)
    )
    assert "FUTURE_SHARED_STATION" not in str(
        hub.interaction_timeline("robot-01", now)
    )


def test_future_transmitted_speech_does_not_resurface_as_live_own_utterance():
    hub = CameraFrameHub(["robot-01", "robot-02"])
    now = time.monotonic()
    with pytest.raises(ValueError, match="Invalid actual transmitted pet speech"):
        hub.remember_spoken("robot-01", "FUTURE_SPEECH_NOT_PLAYED", now + 3600)
    assert hub.spoken_history["robot-01"] == hub.spoken_history["robot-02"]
    hub.remember_spoken("robot-01", "REAL_RECENT_AUDIO_SENT", now)
    entries = [item for item in hub.interaction_timeline("robot-01", now)
               if item["channel"] == "robot_speech"]
    assert len(entries) == 1
    assert entries[0]["content"] == "REAL_RECENT_AUDIO_SENT"
    assert entries[0]["playback_verified"] is False
    assert hub.interaction_timeline("robot-02", now) == []


@pytest.mark.parametrize("invalid", [[], {}, ["visual_look"], {"source": "model"}])
def test_unhashable_multimodal_cues_are_rejected_without_mutation(invalid):
    hub = CameraFrameHub(["robot-01", "robot-02"])
    now = time.monotonic()
    for invoke in (
        lambda: hub.notify("robot-01", invalid, now),
        lambda: hub.remember_tool("robot-01", invalid, "uncertain tool text", now),
        lambda: hub.remember_spoken(
            "robot-01", "sent speech", now, source=invalid,
        ),
    ):
        with pytest.raises(ValueError):
            invoke()
    assert not hub.event_history["robot-01"]
    assert not hub.tool_history["robot-01"]
    assert not hub.spoken_history["robot-01"]
    assert not hub.urgent["robot-01"]
    assert not hub.event_history["robot-02"]
    # Valid source labels retain their original provenance and behavior.
    hub.notify("robot-01", "human_voice", now)
    hub.remember_tool("robot-01", "visual_look", "Possibly a cup", now)
    hub.remember_spoken("robot-01", "Hello", now)
    assert hub.event_history["robot-01"][-1][0] == "human_voice"
    assert hub.tool_history["robot-01"][-1][0] == "visual_look"
    assert hub.spoken_history["robot-01"][-1][0] == "Hello"


def test_discarded_live_asr_event_cannot_replay_or_leak_to_peer():
    hub = CameraFrameHub(["robot-01", "robot-02"])
    event_id = "omni_" + "a" * 12 + "_" + "b" * 20
    now = time.monotonic()
    assert hub.remember_heard("robot-01", event_id, "Private words", now)
    hub.discard_heard("robot-01", event_id)
    assert not hub.heard_history["robot-01"]
    assert not hub.remember_heard("robot-01", event_id, "Replayed words", now)
    assert hub.remember_heard("robot-02", event_id, "Independent words", now)
    assert hub.heard_history["robot-02"][-1][1] == "Independent words"


@pytest.mark.parametrize("stage", ["snapshot", "decode"])
@pytest.mark.parametrize("grant_state", ["unchanged", "revoked", "regranted"])
async def test_capture_camera_grant_stays_revoked_after_fast_regrant(
    settings, stage, grant_state,
):
    """A completed old-grant JPEG must not enter the new consent epoch."""
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    rid = settings.robots[0].id
    entered, release = asyncio.Event(), asyncio.Event()
    head = Head()

    async def held_snapshot():
        head.captures += 1
        entered.set()
        await release.wait()
        return image(square=True)

    async def held_decode(jpeg, *, priority):
        entered.set()
        await release.wait()
        return _prepare(jpeg)

    if stage == "snapshot":
        head.snapshot = held_snapshot
    service = MultimodalOrchestrator(
        settings, {rid: head}, Vision(), asyncio.Lock(),
    )
    if stage == "decode":
        service._prepare_bounded = held_decode
    task = asyncio.create_task(service.capture(rid, source="speech"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        grant = settings.camera_consent_generation
        if grant_state != "unchanged":
            settings.voice_vision_tools_enabled = False
            if grant_state == "regranted":
                settings.voice_vision_tools_enabled = True
            assert settings.camera_consent_generation > grant
        release.set()
        if grant_state == "unchanged":
            evidence = await asyncio.wait_for(task, timeout=2)
            assert evidence.jpeg and service.hub.frames[rid]
        else:
            with pytest.raises(RuntimeError, match="Camera consent revoked"):
                await asyncio.wait_for(task, timeout=2)
            assert not service.hub.frames[rid]
    finally:
        release.set()
        await service.close()


async def test_new_camera_grant_cannot_reuse_cached_old_speech_frame(settings):
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    rid = settings.robots[0].id
    head = Head()
    service = MultimodalOrchestrator(
        settings, {rid: head}, Vision(), asyncio.Lock(),
    )
    try:
        await service.capture(rid, source="speech")
        assert head.captures == 1
        settings.voice_vision_tools_enabled = False
        settings.voice_vision_tools_enabled = True
        await service.capture(rid, source="speech", reuse_if_recent_s=0.65)
        assert head.captures == 2
        assert len(service.hub.frames[rid]) == 1
        assert service._metrics[rid]["native_speech_camera_reuses"] == 0
    finally:
        await service.close()


@pytest.mark.parametrize("regranted", [False, True])
async def test_external_proactive_jpeg_cannot_publish_after_camera_revoke(
    settings, regranted,
):
    settings.voice_vision_tools_enabled = True
    rid = settings.robots[0].id
    entered, release = asyncio.Event(), asyncio.Event()
    service = MultimodalOrchestrator(
        settings, {rid: Head()}, Vision(), asyncio.Lock(),
    )

    async def paused_decode(jpeg, *, priority=False):
        entered.set()
        await release.wait()
        return _prepare(jpeg)

    service._prepare_bounded = paused_decode
    task = asyncio.create_task(
        service.offer_proactive(rid, image(), time.monotonic())
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        settings.voice_vision_tools_enabled = False
        if regranted:
            settings.voice_vision_tools_enabled = True
        release.set()
        await asyncio.wait_for(task, timeout=2)
        assert not service.hub.frames[rid]
    finally:
        release.set()
        await service.close()


async def test_continuous_stream_regrant_during_decode_rejects_old_frame(settings):
    settings.voice_vision_tools_enabled = True
    rid = settings.robots[0].id
    entered, release = asyncio.Event(), asyncio.Event()

    class StreamingHead(Head):
        async def stream_frames(self):
            yield image(square=True), time.monotonic()
            await asyncio.Event().wait()

    service = MultimodalOrchestrator(
        settings, {rid: StreamingHead()}, Vision(), asyncio.Lock(),
    )

    async def paused_decode(jpeg, *, priority=False):
        entered.set()
        await release.wait()
        return _prepare(jpeg)

    service._prepare_bounded = paused_decode
    try:
        service.start_streams()
        await asyncio.wait_for(entered.wait(), timeout=2)
        settings.voice_vision_tools_enabled = False
        settings.voice_vision_tools_enabled = True
        release.set()
        await asyncio.wait_for(service._stream_tasks[rid], timeout=2)
        assert not service.hub.frames[rid]
        assert service._metrics[rid]["stream_frames_selected"] == 0
    finally:
        release.set()
        await service.close()


async def test_native_live_subscriber_does_not_cross_camera_regrant(settings):
    settings.voice_vision_tools_enabled = True
    rid = settings.robots[0].id
    service = MultimodalOrchestrator(
        settings, {rid: Head()}, Vision(), asyncio.Lock(),
    )
    stream = service.native_live_frames(rid)
    pending = asyncio.create_task(anext(stream))
    try:
        await asyncio.sleep(0.02)
        settings.voice_vision_tools_enabled = False
        settings.voice_vision_tools_enabled = True
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(pending, timeout=1)
        assert not service.hub.frames[rid]
    finally:
        await stream.aclose()
        await service.close()


def test_native_sent_receipt_seen_ids_survive_twelve_history_entries():
    """Old response IDs stay idempotent for the entire valid send window."""
    hub = CameraFrameHub(["robot-01", "robot-02"])
    now = time.monotonic()

    def receipt(index):
        return "omni_sent_" + "a" * 12 + "_" + f"{index:020x}"

    for index in range(13):
        assert hub.remember_native_spoken(
            "robot-01", receipt(index), f"sent line {index}", now,
        )
    assert len(hub.native_spoken_ids["robot-01"]) == 12
    assert receipt(0) not in hub.native_spoken_ids["robot-01"]
    before = list(hub.spoken_history["robot-01"])
    assert not hub.remember_native_spoken(
        "robot-01", receipt(0), "OBSOLETE REPLAYED LINE", now,
    )
    assert list(hub.spoken_history["robot-01"]) == before
    # A new VAD does not turn sent audio into another completed response.
    hub.notify("robot-01", "human_voice", now)
    hub.spoken_history["robot-01"].clear()
    assert not hub.remember_native_spoken(
        "robot-01", receipt(0), "OBSOLETE AFTER VAD", now,
    )
    assert not hub.spoken_history["robot-01"]
    assert hub.remember_native_spoken(
        "robot-02", receipt(0), "independent robot speech", now,
    )
    # Saturation refuses new evidence rather than evicting older live IDs.
    for index in range(13, 256):
        assert hub.remember_native_spoken(
            "robot-01", receipt(index), f"sent line {index}", now,
        )
    assert len(hub.native_spoken_seen["robot-01"]) == 256
    assert not hub.remember_native_spoken(
        "robot-01", receipt(256), "capacity overflow", now,
    )
    assert not hub.remember_native_spoken(
        "robot-01", receipt(0), "SATURATED OLD REPLAY", now,
    )
    # Expired admission may be reclaimed, without weakening the five-second
    # validation of actual transmitted timestamps.
    hub.native_spoken_seen["robot-01"][receipt(0)] = now - 6
    assert hub.remember_native_spoken(
        "robot-01", receipt(256), "fresh after expiry", now,
    )
    hub.clear("robot-01")
    assert not hub.native_spoken_seen["robot-01"]
    assert hub.native_spoken_seen["robot-02"]
