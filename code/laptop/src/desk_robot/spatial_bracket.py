"""Stationary JPEG/odometry receipt validation for localization replay.

The two device clocks are never subtracted from one another. Timing bounds
must come from measured source-to-Mac latency on the actual assembly;
synthetic bounds are usable only for replay. The motion owner must supply
the epoch and disarmed state. This module cannot establish an anchor, grant
motion, or independently attest the caller's calibration/motion evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from .spatial_frames import FrameError, PlanarTransform, odom_base_transform
from .spatial_pose import PoseFence, PoseReceipt

_MAX_CLOCK = (1 << 53) - 1


class BracketError(ValueError):
    """The selected JPEG lacks a consistent stationary receipt bracket."""


def _number(value: object, lo: float, hi: float) -> bool:
    return type(value) in (int, float) and lo <= value <= hi


def _integer(value: object, lo: int, hi: int) -> bool:
    return type(value) is int and lo <= value <= hi


def _camera_identity(identity: object) -> bool:
    return (type(identity) is tuple and len(identity) == 3
            and _integer(identity[0], 0, 0xffffffff)
            and _integer(identity[1], 1, 0xffffffff)
            and _integer(identity[2], 1, _MAX_CLOCK))


@dataclass(frozen=True)
class StationaryBracket:
    robot_id: str
    body_boot: int
    origin: int
    camera_identity: tuple[int, int, int]
    stream_generation: int
    motion_epoch: int
    before_seq: int
    after_seq: int
    earliest_image_at: float
    latest_image_at: float
    odom_base: PlanarTransform


def validate_stationary_bracket(
    *,
    fence: PoseFence,
    before: PoseReceipt,
    after: PoseReceipt,
    previous_camera: tuple[int, int, int],
    camera: tuple[int, int, int],
    camera_received_at: float,
    stream_generation_before: int,
    stream_generation_after: int,
    motion_epoch_before: int,
    motion_epoch_after: int,
    disarmed_before: bool,
    disarmed_after: bool,
    now: float,
    max_optical_lag_s: float,
    max_body_lag_s: float,
) -> StationaryBracket:
    """Validate a conservative receipt bracket, not an optical timestamp.

    An earlier accepted camera identity is mandatory; a new head boot or
    stream reconnect requires a new baseline. Exact equal odom coordinates
    are intentionally conservative until measured stationary jitter bounds
    exist. Equal endpoints alone are not stationarity: callers also need
    an unchanged authoritative motion epoch and disarmed state.
    """
    if (type(fence) is not PoseFence
            or type(before) is not PoseReceipt or type(after) is not PoseReceipt
            or not _number(now, 0, _MAX_CLOCK)
            or not _number(camera_received_at, 0, now)
            or not _number(max_optical_lag_s, 0.001, 0.20)
            or not _number(max_body_lag_s, 0.001, 0.25)):
        raise BracketError("Missing bounded timing or pose evidence")
    if fence.current(now) != after:
        raise BracketError("After pose is not current authenticated continuity")
    if (before.robot_id != fence.robot_id or after.robot_id != fence.robot_id
            or before.head_boot is None or after.head_boot is None
            or not _integer(before.body_boot, 1, 0xffffffff)
            or not _integer(before.origin, 1, 0xffffffff)
            or (before.body_boot, before.origin, before.head_boot)
            != (after.body_boot, after.origin, after.head_boot)
            or before.quality != "valid" or after.quality != "valid"
            or not _integer(before.seq, 1, 0xffffffff)
            or not _integer(after.seq, 1, 0xffffffff)
            or not before.seq < after.seq
            or not _integer(before.sample_us, 1, _MAX_CLOCK)
            or not _integer(after.sample_us, 1, _MAX_CLOCK)
            or not before.sample_us < after.sample_us):
        raise BracketError("Pose identity, origin or ordering changed")
    if (not _camera_identity(previous_camera) or not _camera_identity(camera)
            or previous_camera[0] != camera[0] or camera[0] != after.head_boot
            or not previous_camera[1] < camera[1]
            or not previous_camera[2] < camera[2]
            or not _integer(stream_generation_before, 1, _MAX_CLOCK)
            or not _integer(stream_generation_after, 1, _MAX_CLOCK)
            or stream_generation_before != stream_generation_after):
        raise BracketError("Camera boot, sequence or stream generation changed")
    if (not _integer(motion_epoch_before, 0, _MAX_CLOCK)
            or not _integer(motion_epoch_after, 0, _MAX_CLOCK)
            or motion_epoch_before != motion_epoch_after
            or disarmed_before is not True or disarmed_after is not True):
        raise BracketError("Motion or pickup epoch changed or body not disarmed")
    if (not _number(before.received_at, 0, now)
            or not _number(after.received_at, 0, now)
            or not _number(before.request_started_at, 0, before.received_at)
            or not _number(after.request_started_at, 0, after.received_at)
            or before.received_at - before.request_started_at > max_body_lag_s
            or after.received_at - after.request_started_at > max_body_lag_s):
        raise BracketError("Pose transport timing unavailable or excessive")
    earliest = camera_received_at - max_optical_lag_s
    if (earliest < 0 or before.received_at > earliest
            or after.request_started_at < camera_received_at
            or after.received_at - max_body_lag_s < camera_received_at
            or now - camera_received_at > 0.20
            or after.received_at - before.received_at + max_body_lag_s > 0.5):
        raise BracketError("Pose receipts do not bound the possible image time")
    try:
        first = odom_base_transform(before)
        last = odom_base_transform(after)
    except FrameError as exc:
        raise BracketError("Invalid bracket transform") from exc
    if first != last:
        raise BracketError("Stationary bracket contains changed odometry")
    return StationaryBracket(
        robot_id=after.robot_id, body_boot=after.body_boot, origin=after.origin,
        camera_identity=camera, stream_generation=stream_generation_after,
        motion_epoch=motion_epoch_after, before_seq=before.seq, after_seq=after.seq,
        earliest_image_at=earliest, latest_image_at=camera_received_at,
        odom_base=last,
    )
