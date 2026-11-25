"""Bounded, read-only grid route proposals for one identified desk robot.

This is NOT a motion controller. A qualified pose/grid producer (guide 50)
may construct a snapshot; the authorized actuator owner (guide 90) must
independently recheck every motion and physical clearance before execution.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

# Grid states are explicit. Everything except observed-safe support is blocked.
SAFE = "safe"
_DIRECTIONS = ((1, 0), (0, 1), (-1, 0), (0, -1))  # +X, +Y, -X, -Y
# SpatialGrid's last update may be up to 5 s old when a 5 s snapshot
# is emitted. Any greater observation-to-expiry interval is not qualified.
_MAX_MAP_OBSERVATION_TO_EXPIRY_US = 10_000_000


@dataclass(frozen=True)
class GridSnapshot:
    robot_id: str
    origin_id: str
    epoch: int
    anchor_id: str
    calibration_id: str
    width: int
    height: int
    cell_mm: int
    support: tuple[str, ...]  # row-major; safe, occupied, unknown, stale, unsafe
    observed_at_us: int
    expires_at_us: int
    anchored: bool
    schema_version: int = 1


@dataclass(frozen=True)
class RouteRequest:
    robot_id: str
    origin_id: str
    epoch: int
    anchor_id: str
    session_id: str
    turn_id: str
    start: tuple[int, int]
    heading: int  # 0 +X, 1 +Y, 2 -X, 3 -Y; no autonomous reverse
    goal: tuple[int, int]
    deadline_us: int
    cancelled: bool = False
    schema_version: int = 1
    # Optional exact lattice heading at the goal; None is a generic route.
    goal_heading: int | None = None


@dataclass(frozen=True)
class SafetyEnvelope:
    footprint_radius_mm: int
    localization_error_mm: int
    stopping_margin_mm: int
    swept_turn_radius_mm: int
    geometry_qualified: bool  # true for explicit simulation OR measured physical geometry


@dataclass(frozen=True)
class RouteResult:
    status: str  # planned or rejected
    reason: str
    cells: tuple[tuple[int, int], ...] = ()
    robot_id: str = ""
    origin_id: str = ""
    epoch: int = -1
    session_id: str = ""
    turn_id: str = ""
    # A proposal cannot authorize a motor command, even if source metadata is good.
    may_execute: bool = False
    # Preserve the exact map provenance and validity window for downstream
    # revalidation. These fields are evidence, never an actuator permit.
    anchor_id: str = ""
    calibration_id: str = ""
    map_observed_at_us: int = 0
    valid_until_us: int = 0
    final_heading: int | None = None


def plan_route(
    grid: GridSnapshot,
    request: RouteRequest,
    envelope: SafetyEnvelope,
    *,
    now_us: int,
    max_expansions: int = 4096,
    clock_us: Callable[[], int] | None = None,
    request_is_current: Callable[[], bool] | None = None,
) -> RouteResult:
    """Return a deterministic forward-only grid proposal or a finite refusal.

    The 4-connected lattice is conservative: each position needs fully known
    support over the inflated footprint; any heading change also needs the
    swept turn clearance. This does not claim that a 90-degree lattice corner
    is a calibrated physical wheel trajectory. Guide 90 must convert poses to
    measured, newly verified bounded pulses or reject the proposal.
    """
    def refuse(reason: str) -> RouteResult:
        return RouteResult("rejected", reason)

    if (type(now_us) is not int or now_us < 0
            or type(max_expansions) is not int or not 1 <= max_expansions <= 4096):
        return refuse("invalid_budget")
    if (type(grid.width) is not int or type(grid.height) is not int
            or type(grid.cell_mm) is not int or not 1 <= grid.width <= 128
            or not 1 <= grid.height <= 128 or grid.width * grid.height > 8192
            or not 1 <= grid.cell_mm <= 100
            or not isinstance(grid.support, tuple)
            or len(grid.support) != grid.width * grid.height
            or any(type(s) is not str or s not in {
                SAFE, "occupied", "unknown", "stale", "unsafe"
            } for s in grid.support)):
        return refuse("invalid_grid")
    if (not all(isinstance(s, str) and s for s in (
            grid.robot_id, grid.origin_id, grid.anchor_id, grid.calibration_id,
            request.robot_id, request.origin_id, request.anchor_id,
            request.session_id, request.turn_id))
            or type(grid.epoch) is not int or grid.epoch < 0
            or type(request.epoch) is not int or request.epoch < 0):
        return refuse("invalid_identity")
    if (type(grid.schema_version) is not int or grid.schema_version != 1
            or type(request.schema_version) is not int or request.schema_version != 1):
        return refuse("unsupported_schema")
    if grid.robot_id != request.robot_id:
        return refuse("robot_mismatch")
    if (grid.origin_id != request.origin_id or grid.epoch != request.epoch
            or grid.anchor_id != request.anchor_id):
        return refuse("map_epoch_changed")
    if type(request.cancelled) is not bool:
        return refuse("invalid_cancellation_state")
    if request.cancelled:
        return refuse("cancelled")
    if (grid.anchored is not True
            or type(grid.observed_at_us) is not int
            or type(grid.expires_at_us) is not int
            or grid.observed_at_us <= 0 or grid.observed_at_us > now_us
            or grid.expires_at_us <= now_us
            or not 0 < grid.expires_at_us - grid.observed_at_us
            <= _MAX_MAP_OBSERVATION_TO_EXPIRY_US):
        return refuse("unanchored_or_stale_map")
    if type(request.deadline_us) is not int or request.deadline_us <= now_us:
        return refuse("deadline_expired")
    if (type(request.heading) is not int or request.heading not in range(4)
            or (request.goal_heading is not None and
                (type(request.goal_heading) is not int or request.goal_heading not in range(4)))
            or any(not isinstance(point, tuple) or len(point) != 2
                   or any(type(axis) is not int for axis in point)
                   for point in (request.start, request.goal))):
        return refuse("invalid_pose")
    metrics = (envelope.footprint_radius_mm, envelope.localization_error_mm,
               envelope.stopping_margin_mm, envelope.swept_turn_radius_mm)
    if (envelope.geometry_qualified is not True
            or any(type(x) is not int or not 0 <= x <= 400 for x in metrics)
            or envelope.footprint_radius_mm == 0
            or envelope.swept_turn_radius_mm < envelope.footprint_radius_mm):
        return refuse("unqualified_clearance")

    radius = (envelope.footprint_radius_mm + envelope.localization_error_mm
              + envelope.stopping_margin_mm)
    turn_radius = (envelope.swept_turn_radius_mm + envelope.localization_error_mm
                   + envelope.stopping_margin_mm)
    # Bounds apply to inflated radii, not just each independently valid input.
    if (turn_radius > 400 or radius > 400
            or math.ceil(turn_radius / grid.cell_mm + 0.5) > 24):
        # Bound the maximum per-state raster footprint and cancellation lag.
        return refuse("unqualified_clearance")

    def proposal(reason: str, cells: tuple[tuple[int, int], ...],
                 final_heading: int) -> RouteResult:
        return RouteResult(
            status="planned", reason=reason, cells=cells,
            robot_id=request.robot_id, origin_id=request.origin_id,
            epoch=request.epoch, session_id=request.session_id,
            turn_id=request.turn_id, anchor_id=grid.anchor_id,
            calibration_id=grid.calibration_id,
            map_observed_at_us=grid.observed_at_us,
            valid_until_us=min(grid.expires_at_us, request.deadline_us),
            final_heading=final_heading,
        )

    last_clock_us = now_us

    def live() -> str | None:
        nonlocal last_clock_us
        if request_is_current is not None:
            try:
                if request_is_current() is not True:
                    return "request_invalidated"
            except Exception:
                return "request_invalidated"
        if clock_us is None:
            return None
        try:
            current = clock_us()
        except Exception:
            return "invalid_clock"
        if type(current) is not int or current < last_clock_us:
            return "invalid_clock"
        last_clock_us = current
        if current >= request.deadline_us or current >= grid.expires_at_us:
            return "deadline_or_map_expired"
        return None

    @lru_cache(maxsize=8192)
    def clear(x: int, y: int, clearance_mm: int) -> bool:
        # A cell is unsafe if the *square* touches the inflated disk. Off-map
        # is unknown support, including at edges/corners.
        reach = math.ceil(clearance_mm / grid.cell_mm + 0.5)
        for dy in range(-reach, reach + 1):
            for dx in range(-reach, reach + 1):
                distance = math.hypot(
                    max(0, abs(dx) - 0.5) * grid.cell_mm,
                    max(0, abs(dy) - 0.5) * grid.cell_mm,
                )
                if distance > clearance_mm:
                    continue
                cx, cy = x + dx, y + dy
                if (not 0 <= cx < grid.width or not 0 <= cy < grid.height
                        or grid.support[cy * grid.width + cx] != SAFE):
                    return False
        return True

    expired = live()
    if expired:
        return refuse(expired)
    if not clear(*request.start, radius):
        return refuse("unsafe_start")
    if not clear(*request.goal, radius):
        return refuse("unsafe_goal")
    if (request.start == request.goal and
            request.goal_heading in (None, request.heading)):
        # A long clearance scan may outlive the request or its map epoch.
        expired = live()
        if expired:
            return refuse(expired)
        return proposal("at_observation_pose", (request.start,), request.heading)

    start_state = (*request.start, request.heading)
    best = {start_state: 0}
    parent: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    queue = [(abs(request.goal[0] - request.start[0])
              + abs(request.goal[1] - request.start[1]), 0, 0, *start_state)]
    expanded = 0
    while queue:
        expired = live()
        if expired:
            return refuse(expired)
        if expanded >= max_expansions:
            return refuse("search_budget_exhausted")
        _, cost, turns, x, y, heading = heapq.heappop(queue)
        state = (x, y, heading)
        if cost != best.get(state):
            continue
        expanded += 1
        if ((x, y) == request.goal and
                request.goal_heading in (None, heading)):
            route = [(x, y)]
            while state in parent:
                state = parent[state]
                route.append((state[0], state[1]))
            route.reverse()
            # The goal pop and route reconstruction are not an execution lease.
            # Refuse an obsolete proposal even if every earlier cell was safe.
            expired = live()
            if expired:
                return refuse(expired)
            return proposal("simulation_proposal_only", tuple(route), heading)
        # Straight, left, right. A 180-degree reverse or spin is never emitted.
        for new_heading in (heading, (heading + 1) % 4, (heading - 1) % 4):
            dx, dy = _DIRECTIONS[new_heading]
            nx, ny = x + dx, y + dy
            if not clear(nx, ny, radius):
                continue
            turning = new_heading != heading
            if turning and (not clear(x, y, turn_radius)
                            or not clear(nx, ny, turn_radius)):
                continue
            next_state = (nx, ny, new_heading)
            new_cost = cost + 1 + int(turning)
            if new_cost >= best.get(next_state, math.inf):
                continue
            best[next_state] = new_cost
            parent[next_state] = (x, y, heading)
            priority = new_cost + abs(request.goal[0] - nx) + abs(request.goal[1] - ny)
            heapq.heappush(queue, (priority, new_cost, turns + int(turning),
                                   nx, ny, new_heading))
    return refuse("no_safe_route")


def revalidate_route_step(
    grid: GridSnapshot,
    route: RouteResult,
    envelope: SafetyEnvelope,
    *,
    start: tuple[int, int],
    heading: int,
    goal: tuple[int, int],
    now_us: int,
    clock_us: Callable[[], int] | None = None,
) -> bool:
    """Recheck one exact proposed edge (or stationary pose), never detour or renew it."""
    if (route.status != "planned" or route.may_execute is not False
            or type(now_us) is not int or type(route.valid_until_us) is not int
            or now_us >= route.valid_until_us
            or (grid.robot_id, grid.origin_id, grid.epoch, grid.anchor_id, grid.calibration_id)
            != (route.robot_id, route.origin_id, route.epoch, route.anchor_id, route.calibration_id)
            or type(grid.observed_at_us) is not int
            or grid.observed_at_us < route.map_observed_at_us):
        return False
    expected = (start,) if start == goal else (start, goal)
    if (start == goal and start not in route.cells
            or start != goal and not any(
                (a, b) == expected for a, b in zip(route.cells, route.cells[1:], strict=False)
            )):
        return False
    check = plan_route(
        grid,
        RouteRequest(
            robot_id=route.robot_id, origin_id=route.origin_id,
            epoch=route.epoch, anchor_id=route.anchor_id,
            session_id=route.session_id, turn_id=route.turn_id,
            start=start, heading=heading, goal=goal, deadline_us=route.valid_until_us,
        ),
        envelope,
        now_us=now_us,
        max_expansions=2,
        clock_us=clock_us,
    )
    return check.status == "planned" and check.cells == expected
