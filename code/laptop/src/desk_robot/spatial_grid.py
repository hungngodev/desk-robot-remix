"""Read-only 20 mm occupancy evidence; WROOM CliffGuard remains authoritative.

This stores projected *range* evidence, not a vision-only free-space guess.
Actual cell projection and anchoring remain blocked until measured hardware
geometry and synchronized pose brackets are available. No motor permission.
"""

from __future__ import annotations

from dataclasses import dataclass

CELL_MM = 20
MIN_LOG_ODDS = -4.0
MAX_LOG_ODDS = 4.0
_MAX_SOURCE_RECEIPT_LAG_US = 250_000
_MAX_SOURCE_FORWARD_LEAP_US = 5_000_000
_OBSTACLE_WEIGHT = {"obstacle_clear": -0.8, "obstacle_hit": 1.2}
_FLOOR_KINDS = frozenset({"floor_supported", "floor_unsafe"})


class GridEvidenceError(ValueError):
    """Unqualified, stale, replayed or mismatched spatial evidence."""


@dataclass(frozen=True)
class RangeCellBatch:
    robot_id: str
    body_boot: int
    origin_id: str
    epoch: int
    calibration_id: str
    lane: int
    sequence: int
    sample_us: int  # WROOM monotonic, not comparable to Mac epoch
    received_us: int  # Mac monotonic time at trusted transport receipt
    kind: str
    cells: tuple[tuple[int, int], ...]
    geometry_qualified: bool


@dataclass(frozen=True)
class SpatialSnapshot:
    robot_id: str
    origin_id: str
    epoch: int
    anchor_id: str
    calibration_id: str
    width: int
    height: int
    cell_mm: int
    support: tuple[str, ...]
    observed_at_us: int
    expires_at_us: int
    anchored: bool = False
    schema_version: int = 1


@dataclass
class _Cell:
    obstacle_log_odds: float = 0.0
    obstacle_received_us: int = 0
    obstacle_sample_us: int = 0
    floor: str = "unknown"
    floor_received_us: int = 0
    floor_sample_us: int = 0
    obstacle_calibration: str = ""
    floor_calibration: str = ""
    obstacle_epoch: int = -1
    floor_epoch: int = -1


class SpatialGrid:
    """A bounded single-origin spatial evidence cache, not a safety layer."""

    def __init__(self, robot_id: str, body_boot: int, origin_id: str,
                 anchor_id: str, calibration_id: str, width: int, height: int,
                 *, epoch: int = 0, ttl_us: int = 1_000_000):
        if (not all(type(x) is str and x for x in (
                robot_id, origin_id, anchor_id, calibration_id))
                or type(body_boot) is not int or not 0 <= body_boot <= 0xffffffff
                or type(epoch) is not int or epoch < 0
                or type(width) is not int or type(height) is not int
                or not 1 <= width <= 64 or not 1 <= height <= 64
                or type(ttl_us) is not int or not 1 <= ttl_us <= 5_000_000):
            raise ValueError("Invalid bounded spatial grid definition")
        self.robot_id = robot_id
        self.body_boot = body_boot
        self.origin_id = origin_id
        self.anchor_id = anchor_id
        self.calibration_id = calibration_id
        self.epoch = epoch
        self.width = width
        self.height = height
        self.ttl_us = ttl_us
        self.anchored = False  # Only future validated map-to-odom can change this.
        self._cells: dict[tuple[int, int], _Cell] = {}
        self._last_source: dict[int, tuple[int, int, int]] = {}
        self._last_update_us = 0

    def record(self, batch: RangeCellBatch, *, now_us: int) -> None:
        """Atomically add a projected, qualified WROOM range observation.

        Lane 0..3 may report floor support/unsafe, lane 4 forward obstruction
        and clearance, lanes 5..7 obstruction only. Side/rear absence of an
        echo must never authorize reverse or a corridor clearance.
        """
        if (type(now_us) is not int or now_us < 0
                or not isinstance(batch, RangeCellBatch)
                or batch.robot_id != self.robot_id or batch.body_boot != self.body_boot
                or batch.origin_id != self.origin_id or batch.epoch != self.epoch
                or batch.calibration_id != self.calibration_id
                or batch.geometry_qualified is not True
                or type(batch.kind) is not str
                or type(batch.lane) is not int or not 0 <= batch.lane <= 7
                or type(batch.sequence) is not int or not 1 <= batch.sequence <= 0xffffffff
                or type(batch.sample_us) is not int or not 1 <= batch.sample_us < (1 << 63)
                or type(batch.received_us) is not int
                or not 0 < batch.received_us <= now_us
                or now_us - batch.received_us > 250_000
                or type(batch.cells) is not tuple or not batch.cells
                or len(batch.cells) > 256
                or any(not isinstance(cell, tuple) or len(cell) != 2
                       or any(type(i) is not int for i in cell)
                       or not 0 <= cell[0] < self.width
                       or not 0 <= cell[1] < self.height for cell in batch.cells)):
            raise GridEvidenceError("Invalid grid source, calibration, timestamp, or cell")
        if len(set(batch.cells)) != len(batch.cells):
            raise GridEvidenceError("Invalid grid source, calibration, timestamp, or cell")
        if batch.kind in _FLOOR_KINDS:
            if batch.lane > 3:
                raise GridEvidenceError("Only downward ToF may update floor support")
        elif batch.kind in _OBSTACLE_WEIGHT:
            if batch.lane < 4 or (batch.kind == "obstacle_clear" and batch.lane != 4):
                raise GridEvidenceError("Only qualified forward ToF may free obstacle cells")
        else:
            raise GridEvidenceError("JPEG, tag and unsupported evidence cannot update grid")
        previous = self._last_source.get(batch.lane)
        if previous is not None and (batch.sequence <= previous[0]
                                     or batch.sample_us <= previous[1]
                                     or batch.received_us < previous[2]):
            raise GridEvidenceError("Replayed or reset ToF source sequence")
        if previous is not None:
            # WROOM and Mac have unrelated clock epochs, but their elapsed
            # durations must agree within transport lag tolerance. A newly
            # received packet can still contain an old sensor conversion.
            source_elapsed = batch.sample_us - previous[1]
            receipt_elapsed = batch.received_us - previous[2]
            if (receipt_elapsed - source_elapsed > _MAX_SOURCE_RECEIPT_LAG_US
                    or source_elapsed - receipt_elapsed > _MAX_SOURCE_FORWARD_LEAP_US):
                # Revoke prior free-space evidence immediately. Preserve the
                # last trusted per-lane source fence so replay cannot recover
                # the map. Later genuinely fresh samples must refill both
                # floor and obstacle layers before any cell becomes safe.
                self._cells.clear()
                self._last_update_us = 0
                self.anchored = False
                raise GridEvidenceError("ToF source clock diverged from Mac receipt")
        # Per-lane replay fences alone cannot order overlapping observations
        # from different lanes of the same WROOM clock. Reject the whole batch
        # before changing any cell; a tied capture cannot clear a hazard.
        floor_layer = batch.kind in _FLOOR_KINDS
        clearing = batch.kind in ("floor_supported", "obstacle_clear")
        for cell in batch.cells:
            target = self._cells.get(cell)
            if target is None:
                continue
            calibration = target.floor_calibration if floor_layer else target.obstacle_calibration
            epoch = target.floor_epoch if floor_layer else target.obstacle_epoch
            sample = target.floor_sample_us if floor_layer else target.obstacle_sample_us
            receipt = target.floor_received_us if floor_layer else target.obstacle_received_us
            if calibration == batch.calibration_id and epoch == batch.epoch and (
                    batch.sample_us < sample or batch.received_us < receipt
                    or (clearing and batch.sample_us == sample)):
                raise GridEvidenceError("Out-of-order cell evidence")
        # Except for deliberate temporal-fault revocation above, all source
        # validation precedes cell updates.
        for cell in batch.cells:
            target = self._cells.setdefault(cell, _Cell())
            if batch.kind in _FLOOR_KINDS:
                target.floor = "supported" if batch.kind == "floor_supported" else "unsafe"
                target.floor_received_us = batch.received_us
                target.floor_sample_us = batch.sample_us
                target.floor_calibration = batch.calibration_id
                target.floor_epoch = batch.epoch
            else:
                # Evidence from a different geometry must never cancel a fresh
                # obstacle hit or lend false clearance after recalibration.
                if (target.obstacle_calibration != batch.calibration_id
                        or target.obstacle_epoch != batch.epoch
                        or target.obstacle_received_us == 0
                        or not 0 <= batch.received_us - target.obstacle_received_us <= self.ttl_us):
                    # An expired prior hit or clearance cannot bias fresh evidence.
                    # Clock rollback also discards the prior belief, never revives it.
                    target.obstacle_log_odds = 0.0
                if batch.kind == "obstacle_hit":
                    # A new qualified hit contradicts earlier free-space evidence.
                    # Discard negative confidence immediately; keep positive
                    # occupancy confidence for bounded, ordered clearing.
                    target.obstacle_log_odds = max(0.0, target.obstacle_log_odds)
                target.obstacle_log_odds = max(MIN_LOG_ODDS, min(MAX_LOG_ODDS,
                    target.obstacle_log_odds + _OBSTACLE_WEIGHT[batch.kind]))
                target.obstacle_received_us = batch.received_us
                target.obstacle_sample_us = batch.sample_us
                target.obstacle_calibration = batch.calibration_id
                target.obstacle_epoch = batch.epoch
        self._last_source[batch.lane] = (
            batch.sequence, batch.sample_us, batch.received_us
        )
        self._last_update_us = max(self._last_update_us, batch.received_us)

    def state(self, x: int, y: int, *, now_us: int) -> str:
        if (type(x) is not int or type(y) is not int
                or not 0 <= x < self.width or not 0 <= y < self.height
                or type(now_us) is not int or now_us < 0):
            raise ValueError("Cell or clock outside map")
        cell = self._cells.get((x, y))
        if cell is None:
            return "unknown"
        if (cell.obstacle_calibration and (cell.obstacle_calibration != self.calibration_id
                                           or cell.obstacle_epoch != self.epoch)
                or cell.floor_calibration and (cell.floor_calibration != self.calibration_id
                                               or cell.floor_epoch != self.epoch)):
            return "out_of_calibration"
        if cell.floor == "unsafe":
            # An expired cliff observation is still nontraversable, but it is
            # no longer current evidence. Keep stale provenance visible.
            if not 0 <= now_us - cell.floor_received_us <= self.ttl_us:
                return "stale"
            return "unsafe"
        if (cell.floor_received_us == 0 or cell.obstacle_received_us == 0):
            return "unknown"
        if (not 0 <= now_us - cell.floor_received_us <= self.ttl_us
                or not 0 <= now_us - cell.obstacle_received_us <= self.ttl_us):
            return "stale"
        if cell.obstacle_log_odds >= 0.5:
            return "occupied"
        if cell.floor == "supported" and cell.obstacle_log_odds <= -0.5:
            return "safe"
        return "unknown"

    def log_odds(self, x: int, y: int) -> float:
        cell = self._cells.get((x, y))
        if cell is None or cell.obstacle_epoch != self.epoch:
            return 0.0
        return cell.obstacle_log_odds

    def invalidate_calibration(self, calibration_id: str) -> None:
        if type(calibration_id) is not str or not calibration_id:
            raise ValueError("Calibration ID required")
        if calibration_id != self.calibration_id:
            self.calibration_id = calibration_id
            self.epoch += 1
            self.anchored = False
            self._last_source.clear()

    def invalidate_origin(self, body_boot: int, origin_id: str) -> None:
        if (type(body_boot) is not int or not 0 <= body_boot <= 0xffffffff
                or type(origin_id) is not str or not origin_id):
            raise ValueError("New body origin required")
        self.body_boot = body_boot
        self.origin_id = origin_id
        self.epoch += 1
        self.anchored = False
        self._cells.clear()
        self._last_source.clear()
        self._last_update_us = 0

    def snapshot(self, *, now_us: int) -> SpatialSnapshot:
        if type(now_us) is not int or now_us < 0:
            raise ValueError("Invalid snapshot clock")
        states = tuple(
            self.state(x, y, now_us=now_us)
            for y in range(self.height) for x in range(self.width)
        )
        # Route planner allows only these known support states. Its safe-only
        # admission translates uncalibrated to unsafe, never to free.
        route_states = tuple("unsafe" if s == "out_of_calibration" else s for s in states)
        # A snapshot cannot renew the lifetime of any safe cell's evidence.
        # The planner treats expiry as exclusive, including the TTL boundary.
        expires_at_us = now_us + self.ttl_us
        for index, state in enumerate(states):
            if state == "safe":
                cell = self._cells[(index % self.width, index // self.width)]
                expires_at_us = min(
                    expires_at_us,
                    min(cell.floor_received_us, cell.obstacle_received_us) + self.ttl_us,
                )
        return SpatialSnapshot(
            robot_id=self.robot_id, origin_id=self.origin_id, epoch=self.epoch,
            anchor_id=self.anchor_id, calibration_id=self.calibration_id,
            width=self.width, height=self.height, cell_mm=CELL_MM,
            support=route_states, observed_at_us=self._last_update_us,
            expires_at_us=expires_at_us, anchored=self.anchored,
        )

    def to_route_snapshot(self, *, now_us: int):
        """Bridge the exact immutable fixture consumed by Guide 60."""
        from .route_planner import GridSnapshot

        return GridSnapshot(**vars(self.snapshot(now_us=now_us)))
