"""Bounded read-only object detection on one authenticated Sense camera frame.

Reuse the existing single-job Vision/YoloWorldVision inference owner. Model
qualification is an operator-supplied gate, not a promise that weights or real
key/candy accuracy were measured. Never dispatch a motor or infer floor pose.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Callable

from .object_targets import ObjectEvidence, ObjectOwner, ObjectQuery
from .vision import Detection, Vision, image_size


@dataclass(frozen=True)
class DetectorFrame:
    robot_id: str
    session_id: str
    turn_id: str
    origin_id: str
    epoch: int
    anchor_id: str
    calibration_id: str
    camera_boot: int
    host_boot_id: str
    camera_grant: int
    frame_seq: int
    # Both timestamps must be trusted Mac monotonic times in host_boot_id.
    # Unmapped Sense capture clocks must never be substituted here.
    captured_us: int
    received_us: int
    seen_at_wall_s: float
    jpeg: bytes


@dataclass(frozen=True)
class DetectorReceipt:
    status: str  # camera_seen, camera_not_seen, inconclusive, rejected
    reason: str
    evidence: ObjectEvidence | None = None
    box: tuple[float, float, float, float] | None = None
    may_execute: bool = False
    arrived: bool = False


def _frame_valid(frame: DetectorFrame, query: ObjectQuery, owner: ObjectOwner,
                 *, now_us: int, fresh_us: int) -> str | None:
    if (type(frame.robot_id) is not str or not frame.robot_id
            or type(frame.host_boot_id) is not str or not frame.host_boot_id
            or type(frame.frame_seq) is not int
            or not 1 <= frame.frame_seq <= 0xFFFFFFFF
            or any(type(x) is not int or not 0 <= x <= 0xFFFFFFFF
                   for x in (frame.camera_boot, frame.camera_grant))
            or type(frame.epoch) is not int or frame.epoch < 0
            or any(type(x) is not int or x < 0
                   for x in (frame.captured_us, frame.received_us))
            or type(frame.seen_at_wall_s) not in (float, int)
            or not math.isfinite(frame.seen_at_wall_s)
            or not 0 <= frame.seen_at_wall_s <= 4_102_444_800):
        return "invalid_frame"
    if (frame.robot_id, frame.session_id, frame.turn_id) != (
            query.robot_id, query.session_id, query.turn_id):
        return "foreign_or_old_turn_frame"
    if (frame.origin_id, frame.epoch, frame.anchor_id,
            frame.calibration_id, frame.camera_boot, frame.host_boot_id,
            frame.camera_grant) != (
            query.origin_id, query.epoch, query.anchor_id,
            query.calibration_id, query.camera_boot, query.host_boot_id,
            query.camera_grant):
        return "camera_or_map_changed"
    if (owner.robot_id, owner.session_id, owner.turn_id) != (
            query.robot_id, query.session_id, query.turn_id):
        return "turn_or_robot_changed"
    if (owner.origin_id, owner.epoch, owner.anchor_id,
            owner.calibration_id, owner.camera_boot, owner.host_boot_id,
            owner.camera_grant) != (
            query.origin_id, query.epoch, query.anchor_id,
            query.calibration_id, query.camera_boot, query.host_boot_id,
            query.camera_grant):
        return "camera_or_map_changed"
    if owner.camera_allowed is not True or owner.memory_allowed is not True:
        return "observation_consent_revoked"
    if (frame.captured_us < query.created_us
            or frame.received_us < frame.captured_us
            or frame.received_us > now_us
            or now_us - frame.captured_us > fresh_us):
        return "stale_or_unmapped_frame"
    return None


def _checked_detection(results: object, label: str, width: int, height: int,
                       threshold: float) -> tuple[str, Detection | None]:
    """A low score is uncertain, not a trustworthy negative observation."""
    if not isinstance(results, list) or len(results) > 128:
        return "invalid_detector_result", None
    accepted: list[Detection] = []
    low_confidence = False
    for item in results:
        if not isinstance(item, Detection) or item.label != label:
            return "invalid_detector_result", None
        box = item.box
        if (type(item.confidence) not in (int, float)
                or not math.isfinite(item.confidence)
                or not 0 < item.confidence <= 1
                or not isinstance(box, tuple) or len(box) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v)
                       for v in box)):
            return "invalid_detector_result", None
        x0, y0, x1, y1 = box
        if not 0 <= x0 < x1 <= width or not 0 <= y0 < y1 <= height:
            return "invalid_detector_result", None
        if item.confidence >= threshold:
            accepted.append(item)
        else:
            low_confidence = True
    if accepted:
        # Stable on equal confidence; do not fabricate a unique object ID.
        return "camera_seen", max(accepted, key=lambda d: d.confidence)
    return ("inconclusive_low_confidence" if low_confidence else "camera_not_seen"), None


async def detect_object_frame(
    detector: Vision,
    frame: DetectorFrame,
    query: ObjectQuery,
    owner: ObjectOwner,
    *,
    model_qualified: bool = False,
    now_us: int,
    clock_us: Callable[[], int],
    request_is_current: Callable[[], bool],
    safety_clear: Callable[[], bool],
    fresh_us: int = 250_000,
    timeout_s: float = 2.0,
    min_confidence: float = 0.85,
) -> DetectorReceipt:
    """Inspect one frame, fail closed on stale completion or human/STOP priority.

    Only a measured and explicitly enabled model can produce camera evidence.
    YoloWorldVision already retains its native single-job semaphore when an
    asyncio waiter times out; this adapter does not create a competing pool.
    """
    def reject(reason: str) -> DetectorReceipt:
        return DetectorReceipt("rejected", reason)

    if (not isinstance(frame, DetectorFrame)
            or not isinstance(query, ObjectQuery)
            or not isinstance(owner, ObjectOwner)
            or type(model_qualified) is not bool
            or type(now_us) is not int or now_us < 0
            or type(fresh_us) is not int or not 1 <= fresh_us <= 5_000_000
            or type(timeout_s) not in (int, float)
            or not math.isfinite(timeout_s) or not 0.01 <= timeout_s <= 5.0
            or type(min_confidence) not in (int, float)
            or not math.isfinite(min_confidence) or not 0 < min_confidence <= 1
            or not callable(clock_us) or not callable(request_is_current)
            or not callable(safety_clear)):
        return reject("invalid_detection_request")
    if model_qualified is not True:
        return reject("detector_not_qualified")
    if query.cancelled:
        return reject("cancelled")
    if (type(query.created_us) is not int or type(query.deadline_us) is not int
            or not 0 <= query.created_us <= now_us < query.deadline_us):
        return reject("deadline_or_clock_invalid")

    last_clock_us = now_us

    def live() -> str | None:
        nonlocal last_clock_us
        try:
            if safety_clear() is not True:
                return "safety_preempted"
            if request_is_current() is not True:
                return "request_invalidated"
            current = clock_us()
        except Exception:
            return "owner_unavailable"
        if type(current) is not int or current < last_clock_us:
            return "invalid_clock"
        last_clock_us = current
        if current >= query.deadline_us:
            return "deadline_expired"
        if current - frame.captured_us > fresh_us:
            return "frame_expired"
        return _frame_valid(frame, query, owner, now_us=current, fresh_us=fresh_us)

    reason = live()
    if reason:
        return reject(reason)
    try:
        width, height = image_size(frame.jpeg)
    except (OSError, ValueError, TypeError):
        return reject("invalid_camera_jpeg")
    reason = live()
    if reason:
        return reject(reason)

    # A noncooperative native inference must not retain an obsolete callback.
    # The existing Vision worker, not this coroutine, owns native completion.
    async def predict():
        return await detector.detect(frame.jpeg, query.label)

    task = asyncio.create_task(predict())
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    loop = asyncio.get_running_loop()
    real_deadline = loop.time() + timeout_s
    try:
        while not task.done():
            reason = live()
            if reason:
                task.cancel()
                return reject(reason)
            remaining = real_deadline - loop.time()
            if remaining <= 0:
                task.cancel()
                return reject("inference_timeout")
            await asyncio.wait((task,), timeout=min(0.025, remaining))
        # Native completion, not merely request submission, is the receipt.
        try:
            results = task.result()
        except Exception:
            return reject("detector_failed")
        reason = live()
        if reason:
            return reject(reason)
        outcome, best = _checked_detection(results, query.label, width, height,
                                           min_confidence)
        if outcome == "invalid_detector_result":
            return reject(outcome)
        if outcome == "inconclusive_low_confidence":
            return DetectorReceipt("inconclusive", outcome)
        # Source receipt remains the original Mac-frame receipt, NOT the time
        # a delayed model finished. Guide50 must separately project to floor.
        evidence = ObjectEvidence(
            robot_id=query.robot_id, label=query.label, source=outcome,
            seen_at_wall_s=frame.seen_at_wall_s, receipt_us=frame.received_us,
            origin_id=query.origin_id, epoch=query.epoch,
            anchor_id=query.anchor_id, calibration_id=query.calibration_id,
            camera_boot=query.camera_boot, host_boot_id=query.host_boot_id,
            camera_grant=query.camera_grant, frame_seq=frame.frame_seq,
            confidence=float(best.confidence) if best is not None else 1.0,
        )
        return DetectorReceipt(outcome, "qualified_frame_detection", evidence,
                               best.box if best is not None else None)
    except asyncio.CancelledError:
        task.cancel()
        raise
