"""Bounded, read-only body pose receipts for later map localization.

Body sample_us and Mac monotonic receipt clocks have different epochs. We
compare elapsed durations, never absolute clock readings. This module does not
anchor a map, clear local safety faults, or grant an actuator lease.
Metric pose is already integrated by the body from measured per-unit wheel
travel per count and effective track width. Never rescale it using CAD chassis
width, nominal wheel radius, or commanded motor steps.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace

_MAX_SAMPLE_US = (1 << 53) - 1
_MAX_LOCAL_CLOCK_S = _MAX_SAMPLE_US / 1_000_000
_MAX_COORD_MM = 1_000_000
_MAX_RECEIPT_LAG_S = 0.25
_MAX_CONTINUITY_RECEIPTS = 64
_POSE_V1_FIELDS = frozenset({
    "robot_id", "v", "body_boot", "origin", "seq", "sample_us",
    "x_mm", "y_mm", "yaw_mrad", "quality", "head_boot",
})


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
    request_started_at: float | None = None

    @property
    def yaw_rad(self) -> float:
        return self.yaw_mrad / 1000.0


def _bounded_int(data: dict, name: str, lo: int, hi: int) -> int:
    value = data.get(name)
    if type(value) is not int or not lo <= value <= hi:
        raise PoseError(f"Invalid pose {name}")
    return value


def _valid_local_clock(value: object) -> bool:
    # Bound before float conversion; huge ints overflow and huge floats lose timing precision.
    return type(value) in (int, float) and 0 <= value <= _MAX_LOCAL_CLOCK_S


def decode_pose(data: dict, robot_id: str, received_at: float) -> PoseReceipt:
    """Validate a version-one head-forwarded body sample without side effects."""
    if (not isinstance(data, dict) or type(robot_id) is not str
            or data.get("robot_id") != robot_id):
        raise PoseError("Pose robot identity mismatch")
    if not _valid_local_clock(received_at):
        raise PoseError("Invalid local pose receipt time")
    if _bounded_int(data, "v", 1, 1) != 1:
        raise PoseError("Unsupported pose version")
    # Sense validates the exact body schema before adding transport identity.
    # Reject unknown fields here too; legacy head_boot remains optional.
    if not data.keys() <= _POSE_V1_FIELDS:
        raise PoseError("Unexpected pose field")
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
        self._clock_reference: PoseReceipt | None = None
        self.needs_reanchor = True
        self.blocked_reason = "no_pose"
        self._continuous = False
        self._healthy_samples = 0
        self._retired_body_boots: set[int] = set()
        self._retired_origins: set[tuple[int, int]] = set()
        self._retired_head_boots: set[int] = set()
        self._failed: set[tuple[int, int, int | None]] = set()
        # Retain only actual receipt objects from this uninterrupted fence.
        # Bounded eviction fails closed for an old bracket, never restores it.
        self._receipts: deque[PoseReceipt] = deque(maxlen=_MAX_CONTINUITY_RECEIPTS)

    def observe(
        self, data: dict, received_at: float, *, request_started_at: float | None = None,
    ) -> PoseReceipt:
        try:
            reading = decode_pose(data, self.robot_id, received_at)
        except PoseError:
            self.invalidate("invalid_pose")
            raise
        if request_started_at is not None:
            # Local GET duration is a conservative transport age allowance,
            # not proof of UART transaction correlation or device capture time.
            if (not _valid_local_clock(request_started_at)
                    or not 0 <= received_at - request_started_at <= _MAX_RECEIPT_LAG_S):
                self.invalidate("pose_transport_delayed")
                raise PoseError("Pose request age exceeds local freshness budget")
            reading = replace(reading, request_started_at=float(request_started_at))
        identity = (reading.body_boot, reading.origin, reading.head_boot)
        if (reading.body_boot in self._retired_body_boots
                or (reading.body_boot, reading.origin) in self._retired_origins
                or reading.head_boot in self._retired_head_boots
                or identity in self._failed):
            self.invalidate("retired_or_failed_origin")
            raise PoseError("Retired or failed body/head pose origin")
        old = self.last
        if reading.head_boot is None and old is not None and old.head_boot is not None:
            # An incomplete reply is not evidence of a different boot. Preserve
            # the last identified sequence fence so recovery cannot replay it.
            self.invalidate("missing_head_boot")
            raise PoseError("Missing head boot identity")
        if old is not None:
            old_identity = (old.body_boot, old.origin, old.head_boot)
            if identity != old_identity:
                # Body source clocks do not reset when only the head or origin
                # changes. Reject a replay before replacing the known baseline.
                if (reading.received_at < old.received_at
                        or (reading.body_boot == old.body_boot
                            and (reading.seq <= old.seq or reading.sample_us <= old.sample_us))):
                    self.invalidate("replayed_or_reset_pose_clock")
                    raise PoseError("Pose sequence, sample clock, or receipt clock reset")
                if reading.body_boot == old.body_boot:
                    host_delta = reading.received_at - old.received_at
                    body_delta = (reading.sample_us - old.sample_us) / 1_000_000
                    if body_delta - host_delta > 5:
                        self.invalidate("implausible_pose_clock")
                        raise PoseError("Pose sample clock advanced implausibly")
                # Retire each changed identity independently: a different head
                # boot must never resurrect a previously invalidated body origin.
                if reading.body_boot != old.body_boot:
                    self._retired_body_boots.add(old.body_boot)
                elif reading.origin != old.origin and old.origin != 0:
                    self._retired_origins.add((old.body_boot, old.origin))
                if reading.head_boot != old.head_boot and old.head_boot is not None:
                    self._retired_head_boots.add(old.head_boot)
                # Origin zero is a repeatable unavailable diagnostic, not a frame.
                self.last = reading
                # The best source clock offset belongs to the body boot, not
                # the head or origin. A new frame cannot launder source lag.
                if reading.body_boot != old.body_boot or self._relative_lag_s(reading) < 0:
                    self._clock_reference = reading
                self.invalidate("origin_changed")
                raise PoseError("Pose body origin or head boot changed; re-anchor required")
            if (reading.seq <= old.seq or reading.sample_us <= old.sample_us
                    or reading.received_at < old.received_at):
                self._failed.add(identity)
                self.invalidate("replayed_or_reset_pose_clock")
                raise PoseError("Pose sequence, sample clock, or receipt clock reset")
            # Body and Mac clocks have unrelated epochs. A lagging source
            # duration cannot be rescued by a later, freshly timed HTTP GET.
            host_delta = reading.received_at - old.received_at
            body_delta = (reading.sample_us - old.sample_us) / 1_000_000
            if host_delta - body_delta > _MAX_RECEIPT_LAG_S:
                self.invalidate("stale_body_sample")
                raise PoseError("Pose body sample lags local receipt clock")
            # A huge forward leap can be a reset or incorrectly encoded unit.
            if body_delta - host_delta > 5:
                self._failed.add(identity)
                self.invalidate("implausible_pose_clock")
                raise PoseError("Pose sample clock advanced implausibly")
        # Keep the best observed relative offset for this body boot. Sliding the
        # baseline on every packet would hide a slowly growing source backlog.
        # This is a conservative relative bound, not a synchronized clock or
        # proof that the first sample was fresh. No unmeasured drift allowance.
        lag = self._relative_lag_s(reading)
        if lag > _MAX_RECEIPT_LAG_S:
            self.invalidate("stale_body_sample")
            raise PoseError("Pose body sample cumulatively lags local receipt clock")
        if self._clock_reference is None or lag < 0:
            self._clock_reference = reading
        self.last = reading
        if reading.head_boot is None:
            # Legacy packets remain readable diagnostics and replay checked,
            # but cannot establish camera-bound local odometry continuity.
            self.invalidate("missing_head_boot")
            return reading
        self._healthy_samples = self._healthy_samples + 1 if reading.quality == "valid" else 0
        self._continuous = self._healthy_samples >= 2
        self.blocked_reason = "unanchored" if self._continuous else (
            "pose_not_valid" if reading.quality != "valid" else "awaiting_second_sample"
        )
        if reading.quality != "valid":
            self.invalidate("pose_not_valid")
        else:
            self._receipts.append(reading)
        return reading

    def _relative_lag_s(self, reading: PoseReceipt) -> float:
        reference = self._clock_reference
        if reference is None:
            return 0.0
        return ((reading.received_at - reference.received_at)
                - (reading.sample_us - reference.sample_us) / 1_000_000)

    def invalidate(self, reason: str = "missing_pose") -> None:
        """An HTTP failure or older transport invalidates all cached planning evidence."""
        self._continuous = False
        self._healthy_samples = 0
        self.needs_reanchor = True
        self.blocked_reason = reason
        self._receipts.clear()

    def owns_continuous_receipt(self, receipt: PoseReceipt) -> bool:
        """True only for an actual accepted receipt in the current continuity."""
        return self._continuous and any(item is receipt for item in self._receipts)

    def receipt_source_lag_s(self, receipt: PoseReceipt) -> float | None:
        """Relative source lag of an owned receipt, without changing continuity."""
        if not self.owns_continuous_receipt(receipt):
            return None
        return max(0.0, self._relative_lag_s(receipt))

    def continuous_receipts_between(
        self, before: PoseReceipt, after: PoseReceipt,
    ) -> tuple[PoseReceipt, ...]:
        """Return retained observations between two owned endpoints, or none."""
        if (not self.owns_continuous_receipt(before)
                or not self.owns_continuous_receipt(after) or before.seq >= after.seq):
            return ()
        return tuple(item for item in self._receipts if before.seq <= item.seq <= after.seq)

    def current(self, now: float, *, max_age_s: float = 0.25) -> PoseReceipt | None:
        if (not _valid_local_clock(now)
                or type(max_age_s) not in (int, float) or not 0 < max_age_s <= 1):
            self.invalidate("invalid_freshness_window")
            return None
        if self.last is None or not self._continuous or self.last.quality != "valid":
            return None
        age_start = (self.last.request_started_at if self.last.request_started_at is not None
                     else self.last.received_at)
        # HTTP duration and relative source lag may overlap; use the stricter
        # age bound rather than renewing either one at the latest receipt.
        age_start = min(age_start, self.last.received_at - self._relative_lag_s(self.last))
        if now < self.last.received_at or not 0 <= now - age_start <= max_age_s:
            self.invalidate("stale_receipt")
            return None
        return self.last
