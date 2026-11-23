"""Offline qualified detector admission and cancellation replay for Guide 60."""

import asyncio
from dataclasses import replace
from io import BytesIO

import pytest
from desk_robot.object_detector import DetectorFrame, detect_object_frame
from desk_robot.object_targets import ObjectOwner, ObjectQuery
from desk_robot.vision import Detection
from PIL import Image


def fixtures():
    q = ObjectQuery("robot-01", "key", "session-2", "turn-7", "origin-3", 8,
                    "tag-4", "cal-5", 101, "mac-boot-5", 12, 900_000, 1_500_000)
    owner = ObjectOwner("robot-01", "session-2", "turn-7", "origin-3", 8,
                        "tag-4", "cal-5", 101, "mac-boot-5", 12, True, True)
    buf = BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, format="JPEG")
    frame = DetectorFrame(
        "robot-01", "session-2", "turn-7", "origin-3", 8, "tag-4", "cal-5",
        101, "mac-boot-5", 12, 24, 960_000, 970_000, 1_800_000_000.0,
        buf.getvalue(),
    )
    return q, owner, frame


class FakeDetector:
    def __init__(self, detections=None, *, gate=None):
        self.detections = detections if detections is not None else [
            Detection("key", 0.96, (4.0, 3.0, 15.0, 14.0))
        ]
        self.calls = 0
        self.gate = gate
        self.started = asyncio.Event()
        self.cancelled = False

    async def detect(self, jpeg, label):
        self.calls += 1
        self.started.set()
        try:
            if self.gate is not None:
                await self.gate.wait()
            return self.detections
        except asyncio.CancelledError:
            self.cancelled = True
            raise


async def inspect(detector, *, query=None, owner=None, frame=None, **kwargs):
    q, o, f = fixtures()
    return await detect_object_frame(
        detector, frame or f, query or q, owner or o,
        model_qualified=kwargs.pop("model_qualified", True),
        now_us=kwargs.pop("now_us", 1_000_000),
        clock_us=kwargs.pop("clock_us", lambda: 1_000_000),
        request_is_current=kwargs.pop("request_is_current", lambda: True),
        safety_clear=kwargs.pop("safety_clear", lambda: True),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_qualified_detection_keeps_frame_receipt_and_never_grants_motion():
    detector = FakeDetector()
    result = await inspect(detector)
    assert result.status == "camera_seen"
    assert result.reason == "qualified_frame_detection"
    assert result.evidence is not None
    assert result.evidence.frame_seq == 24
    assert result.evidence.receipt_us == 970_000
    assert result.evidence.camera_boot == 101
    assert result.evidence.floor_mm is None
    assert result.evidence.projection_qualified is False
    assert result.box == (4.0, 3.0, 15.0, 14.0)
    assert result.may_execute is False and result.arrived is False
    assert detector.calls == 1


@pytest.mark.asyncio
async def test_empty_detection_is_view_specific_absence_not_arrival():
    result = await inspect(FakeDetector([]))
    assert result.status == "camera_not_seen"
    assert result.evidence is not None
    assert result.evidence.source == "camera_not_seen"
    assert result.evidence.floor_mm is None
    assert not result.arrived and not result.may_execute
    # Poor scores must not be elevated to a false negative or positive.
    result = await inspect(FakeDetector([Detection("key", 0.55, (4, 4, 14, 14))]))
    assert result.status == "inconclusive"
    assert result.evidence is None


@pytest.mark.asyncio
async def test_no_operator_model_qualification_means_no_inference():
    fake = FakeDetector()
    result = await inspect(fake, model_qualified=False)
    assert result.reason == "detector_not_qualified"
    assert result.evidence is None and fake.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("frame_change,reason", [
    ({"robot_id": "robot-02"}, "foreign_or_old_turn_frame"),
    ({"turn_id": "prior"}, "foreign_or_old_turn_frame"),
    ({"host_boot_id": "prior-mac"}, "camera_or_map_changed"),
    ({"camera_grant": 11}, "camera_or_map_changed"),
    ({"camera_boot": 102}, "camera_or_map_changed"),
    ({"frame_seq": 0x1_0000_0000}, "invalid_frame"),
    ({"frame_seq": 0}, "invalid_frame"),
    ({"captured_us": 899_999}, "stale_or_unmapped_frame"),
    ({"captured_us": 970_001}, "stale_or_unmapped_frame"),
    ({"received_us": 1_000_001}, "stale_or_unmapped_frame"),
    ({"seen_at_wall_s": float("nan")}, "invalid_frame"),
])
async def test_untrusted_or_stale_camera_frame_never_enters_detector(frame_change, reason):
    _, _, frame = fixtures()
    fake = FakeDetector()
    result = await inspect(fake, frame=replace(frame, **frame_change))
    assert result.reason == reason
    assert result.evidence is None and fake.calls == 0


@pytest.mark.asyncio
async def test_cancelled_or_faulted_owner_never_infers():
    query, owner, _ = fixtures()
    for opts in (
        {"query": replace(query, cancelled=True)},
        {"owner": replace(owner, turn_id="next")},
        {"owner": replace(owner, camera_allowed=False)},
        {"request_is_current": lambda: False},
        {"safety_clear": lambda: False},
    ):
        fake = FakeDetector()
        result = await inspect(fake, **opts)
        assert result.status == "rejected"
        assert result.evidence is None and fake.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("prediction", [
    [Detection("key", float("nan"), (4, 4, 14, 14))],
    [Detection("key", 0.9, (4, 4, 41, 14))],
    [Detection("key", 0.9, (14, 4, 4, 14))],
    [Detection("wrapped candy", 0.9, (4, 4, 14, 14))],
    [Detection("key", True, (4, 4, 14, 14))],
    [Detection("key", 0.9, (True, 4, 14, 14))],
    [object()],
    [Detection("key", 0.95, (1, 2, 3, 4))] * 129,
])
async def test_bad_model_geometry_or_label_is_not_evidence(prediction):
    result = await inspect(FakeDetector(prediction))
    assert result.reason == "invalid_detector_result"
    assert result.evidence is None


@pytest.mark.asyncio
async def test_pending_model_is_preempted_by_live_user_stop():
    gate = asyncio.Event()
    detector = FakeDetector(gate=gate)
    active = True
    task = asyncio.create_task(inspect(detector, request_is_current=lambda: active))
    await asyncio.wait_for(detector.started.wait(), timeout=1)
    active = False
    result = await asyncio.wait_for(task, timeout=1)
    await asyncio.sleep(0)
    assert result.reason == "request_invalidated"
    assert detector.cancelled
    assert result.evidence is None


@pytest.mark.asyncio
async def test_native_timeout_is_bounded_even_with_frozen_test_clock():
    gate = asyncio.Event()
    detector = FakeDetector(gate=gate)
    result = await inspect(detector, timeout_s=0.03)
    await asyncio.sleep(0)
    assert result.reason == "inference_timeout"
    assert detector.cancelled and result.evidence is None


@pytest.mark.asyncio
async def test_late_result_expired_or_new_turn_is_never_committed():
    now = 1_000_000

    def clock():
        return now

    gate = asyncio.Event()
    detector = FakeDetector(gate=gate)
    task = asyncio.create_task(inspect(detector, clock_us=clock, fresh_us=250_000))
    await asyncio.wait_for(detector.started.wait(), timeout=1)
    now = 1_300_000
    gate.set()
    result = await task
    assert result.reason == "frame_expired"
    assert result.evidence is None and not result.arrived


@pytest.mark.asyncio
async def test_invalid_jpeg_and_model_failure_fail_closed():
    _, _, frame = fixtures()
    fake = FakeDetector()
    result = await inspect(fake, frame=replace(frame, jpeg=b"\xff\xd8notajpeg\xff\xd9"))
    assert result.reason == "invalid_camera_jpeg"
    assert fake.calls == 0

    class BrokenDetector:
        async def detect(self, jpeg, label):
            raise RuntimeError("native unavailable")

    result = await inspect(BrokenDetector())
    assert result.reason == "detector_failed"
    assert result.evidence is None


@pytest.mark.asyncio
async def test_external_task_cancellation_propagates_without_receipt():
    detector = FakeDetector(gate=asyncio.Event())
    task = asyncio.create_task(inspect(detector))
    await asyncio.wait_for(detector.started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    assert detector.cancelled
