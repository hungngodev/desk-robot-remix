"""Bounded, read-only body pose receipts for later map localization.

Body sample_us and Mac monotonic receipt clocks have different epochs. We
compare elapsed durations, never absolute clock readings. This module does not
anchor a map, clear local safety faults, or grant an actuator lease.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_MAX_SAMPLE_US = (1 << 53) - 1
_MAX_COORD_MM = 1_000_000
_MAX_RECEIPT_LAG_S = 0.25


class PoseError(ValueError):
    """Pose evidence cannot establish current continuous local odometry."""


@dataclass(frozen=True)
class PoseReceipt:
    robot_id: str
    body_boot: int
    origin: int
    seq: int
    sample_us: int
    x_mm: int
    y_mm: int
    yaw_mrad: int
    quality: str
    received_at: float
    head_boot: int | None = None

    @property
    def yaw_rad(self) -> float:
        return self.yaw_mrad / 1000.0


def _bounded_int(data: dict, name: str, lo: int, hi: int) -> int:
    value = data.get(name)
    if type(value) is not int or not lo <= value <= hi:
        raise PoseError(f"Invalid pose {name}")
    return value


def decode_pose(data: dict, robot_id: str, received_at: float) -> PoseReceipt:
    """Validate a version-one head-forwarded body sample without side effects."""
    if (not isinstance(data, dict) or type(robot_id) is not str
            or data.get("robot_id") != robot_id):
        raise PoseError("Pose robot identity mismatch")
    if type(received_at) not in (float, int) or not math.isfinite(received_at) or received_at < 0:
        raise PoseError("Invalid local pose receipt time")
    if _bounded_int(data, "v", 1, 1) != 1:
        raise PoseError("Unsupported pose version")
    quality = data.get("quality")
    if type(quality) is not str or quality not in ("valid", "degraded", "unavailable"):
        raise PoseError("Invalid pose quality")
    # Zero origin denotes unavailable odometry, never a usable local frame.
    body_boot = _bounded_int(data, "body_boot", 1, 0xffffffff)
    origin = _bounded_int(data, "origin", 0, 0xffffffff)
    if quality != "unavailable" and origin == 0:
        raise PoseError("Valid or degraded pose requires nonzero origin")
    head_boot = data.get("head_boot")
    if head_boot is not None:
        head_boot = _bounded_int(data, "head_boot", 0, 0xffffffff)
    return PoseReceipt(
        robot_id=robot_id,
        body_boot=body_boot,
        origin=origin,
        seq=_bounded_int(data, "seq", 1, 0xffffffff),
        sample_us=_bounded_int(data, "sample_us", 1, _MAX_SAMPLE_US),
        x_mm=_bounded_int(data, "x_mm", -_MAX_COORD_MM, _MAX_COORD_MM),
        y_mm=_bounded_int(data, "y_mm", -_MAX_COORD_MM, _MAX_COORD_MM),
        yaw_mrad=_bounded_int(data, "yaw_mrad", -3142, 3142),
        quality=quality,
        received_at=float(received_at),
        head_boot=head_boot,
    )


class PoseFence:
    """Observe a single robot's ordered poses; a reset invalidates localization.

    An initial valid packet is only a baseline, not proof of source freshness.
    After two continuous samples, current can return local odometry.
    That is still NOT map localization: needs_reanchor remains true until
    a separate measured tag observation establishes map-to-odom continuity.
    """

    def __init__(self, robot_id: str):
        if type(robot_id) is not str or not robot_id:
            raise ValueError("Pose fence needs a robot identity")
        self.robot_id = robot_id
        self.last: PoseReceipt | None = None
        self.needs_reanchor = True
        self.blocked_reason = "no_pose"
        self._continuous = False
        self._healthy_samples = 0
        self._retired: set[tuple[int, int, int | None]] = set()
        self._failed: set[tuple[int, int, int | None]] = set()

    def observe(self, data: dict, received_at: float) -> PoseReceipt:
        try:
            reading = decode_pose(data, self.robot_id, received_at)
        except PoseError:
            self._continuous = False
            self._healthy_samples = 0
            self.needs_reanchor = True
            self.blocked_reason = "invalid_pose"
            raise
        identity = (reading.body_boot, reading.origin, reading.head_boot)
        if identity in self._retired or identity in self._failed:
            self._continuous = False
            self.needs_reanchor = True
            self.blocked_reason = "retired_or_failed_origin"
            raise PoseError("Retired or failed body/head pose origin")
        old = self.last
        if old is not None:
            old_identity = (old.body_boot, old.origin, old.head_boot)
            if identity != old_identity:
                self._retired.add(old_identity)
                self.last = reading
                self._continuous = False
                self._healthy_samples = 0
                self.needs_reanchor = True
                self.blocked_reason = "origin_changed"
                raise PoseError("Pose body origin or head boot changed; re-anchor required")
            if (reading.seq <= old.seq or reading.sample_us <= old.sample_us
                    or reading.received_at < old.received_at):
                self._failed.add(identity)
                self._continuous = False
                self._healthy_samples = 0
                self.needs_reanchor = True
                self.blocked_reason = "replayed_or_reset_pose_clock"
                raise PoseError("Pose sequence, sample clock, or receipt clock reset")
            # Body and Mac clocks have unrelated epochs. A lagging source
            # duration cannot be rescued by a later, freshly timed HTTP GET.
            host_delta = reading.received_at - old.received_at
            body_delta = (reading.sample_us - old.sample_us) / 1_000_000
            if host_delta - body_delta > _MAX_RECEIPT_LAG_S:
                self._continuous = False
                self._healthy_samples = 0
                self.needs_reanchor = True
                self.blocked_reason = "stale_body_sample"
                raise PoseError("Pose body sample lags local receipt clock")
            # A huge forward leap can be a reset or incorrectly encoded unit.
            if body_delta - host_delta > 5:
                self._failed.add(identity)
                self._continuous = False
                self._healthy_samples = 0
                self.needs_reanchor = True
                self.blocked_reason = "implausible_pose_clock"
                raise PoseError("Pose sample clock advanced implausibly")
        self.last = reading
        self._healthy_samples = self._healthy_samples + 1 if reading.quality == "valid" else 0
        self._continuous = self._healthy_samples >= 2
        self.blocked_reason = "unanchored" if self._continuous else (
            "pose_not_valid" if reading.quality != "valid" else "awaiting_second_sample"
        )
        if reading.quality != "valid":
            self._continuous = False
            self.needs_reanchor = True
        return reading

    def invalidate(self, reason: str = "missing_pose") -> None:
        """An HTTP failure or older transport invalidates all cached planning evidence."""
        self._continuous = False
        self._healthy_samples = 0
        self.needs_reanchor = True
        self.blocked_reason = reason

    def current(self, now: float, *, max_age_s: float = 0.25) -> PoseReceipt | None:
        if (type(now) not in (int, float) or not math.isfinite(now)
                or type(max_age_s) not in (int, float)
                or not math.isfinite(max_age_s) or not 0 < max_age_s <= 1):
            self.blocked_reason = "invalid_freshness_window"
            return None
        if self.last is None or not self._continuous or self.last.quality != "valid":
            return None
        if not 0 <= now - self.last.received_at <= max_age_s:
            self.blocked_reason = "stale_receipt"
            self._continuous = False
            self._healthy_samples = 0
            self.needs_reanchor = True
            return None
        return self.last
