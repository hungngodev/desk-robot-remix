"""Bounded, read-only last-seen object search through supported viewpoints.

A viewpoint is a search proposal, never object arrival or a motor permit.
Guide 50 supplies qualified remembered viewpoints and live map evidence.
Guide 40 supplies the live turn/camera owner; Guide 90 owns any motion adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .object_targets import ObjectOwner, ObjectQuery, ObjectTarget
from .route_planner import (
    GridSnapshot,
    RouteRequest,
    RouteResult,
    SafetyEnvelope,
    plan_route,
)


@dataclass(frozen=True)
class SearchViewpoint:
    robot_id: str
    origin_id: str
    epoch: int
    anchor_id: str
    calibration_id: str
    viewpoint_id: str
    cell: tuple[int, int]
    priority: int
    previously_reachable: bool
    inspected_in_request: bool = False
    # Required fixed-camera observation orientation in the map lattice.
    heading: int | None = None


@dataclass(frozen=True)
class ObjectSearchResult:
    status: str  # viewpoint_proposal, no_current_sighting, rejected
    reason: str
    viewpoint_id: str | None = None
    route: RouteResult | None = None
    considered: int = 0
    may_execute: bool = False
    arrived: bool = False
    # Candidate poses still unobserved after observing the proposed viewpoint.
    # A rejected route is not an observation, even if it consumed planning budget.
    remaining_viewpoints: int | None = None


def summarize_search_observation(
    *, label: str, final_cell: tuple[int, int], target: ObjectTarget | None,
    search: ObjectSearchResult | None, observation_status: str, reason: str,
) -> dict:
    """Report an observation, not a verified metric arrival or search coverage."""
    seen = observation_status == "camera_seen"
    exhausted = (
        observation_status == "camera_not_seen"
        and search is not None and search.status == "viewpoint_proposal"
        and search.remaining_viewpoints == 0
    )
    return {
        "status": ("target_seen_unverified_location" if seen else
                   "not_found_after_search" if exhausted else "no_current_sighting"),
        "reason": "metric_target_location_unverified" if seen else reason,
        "arrived": False,
        "target_observed": seen,
        "label": label,
        "last_seen_at_wall_s": (
            target.seen_at_wall_s if target is not None
            and target.status == "last_seen" and target.source == "camera_seen" else None
        ),
        "search_viewpoint_id": search.viewpoint_id if search is not None else None,
        "remaining_viewpoints": search.remaining_viewpoints if search is not None else None,
        "search_exhausted": exhausted,
        "final_cell": final_cell,
        "final_cell_verified": False,
        "motor_authorized": False,
        "charging_authorized": False,
        "physical_acceptance_pass": False,
    }


def propose_object_search(
    grid: GridSnapshot,
    route_request: RouteRequest,
    envelope: SafetyEnvelope,
    object_query: ObjectQuery,
    live_owner: ObjectOwner,
    target: ObjectTarget,
    viewpoints: tuple[SearchViewpoint, ...],
    *,
    now_us: int,
    clock_us: Callable[[], int] | None,
    request_is_current: Callable[[], bool] | None,
    max_viewpoints: int = 8,
    max_expansions_per_view: int = 512,
) -> ObjectSearchResult:
    """Find a safe observation pose to *look again*, not the object's position.

    All candidate locations come from previously reachable Guide 50 records.
    This function cannot dispatch motors, verify object presence or declare
    an arrival. Callers must repeat all owner/geometry checks after any await.
    """
    invalid = _validate_search_input(
        grid, route_request, envelope, object_query, live_owner, target, viewpoints,
        now_us, clock_us, request_is_current, max_viewpoints, max_expansions_per_view,
    )
    if invalid is not None:
        return _refuse(invalid)
    invalid = _validate_search_request(
        grid, route_request, object_query, live_owner, target, now_us,
    )
    if invalid is not None:
        return _refuse(invalid)

    clock = _SearchClock(clock_us, request_is_current, now_us)
    invalid = clock.live(grid, route_request, object_query)
    if invalid is not None:
        return _refuse(invalid)
    if not _has_search_hint(target):
        return _absent("no_same_map_last_seen_hint")
    invalid = _validate_viewpoints(viewpoints, object_query)
    if invalid is not None:
        return _refuse(invalid)
    return _search_candidates(
        grid, route_request, envelope, object_query, _rank_viewpoints(viewpoints),
        clock, max_viewpoints, max_expansions_per_view,
    )


def _refuse(reason: str, considered: int = 0) -> ObjectSearchResult:
    return ObjectSearchResult("rejected", reason, considered=considered)


def _absent(reason: str, considered: int = 0) -> ObjectSearchResult:
    return ObjectSearchResult("no_current_sighting", reason, considered=considered)


def _validate_search_input(
    grid: GridSnapshot, route_request: RouteRequest, envelope: SafetyEnvelope,
    object_query: ObjectQuery, live_owner: ObjectOwner, target: ObjectTarget,
    viewpoints: tuple[SearchViewpoint, ...], now_us: int,
    clock_us: Callable[[], int] | None, request_is_current: Callable[[], bool] | None,
    max_viewpoints: int, max_expansions_per_view: int,
) -> str | None:
    if (not isinstance(grid, GridSnapshot)
            or not isinstance(route_request, RouteRequest)
            or not isinstance(envelope, SafetyEnvelope)
            or not isinstance(object_query, ObjectQuery)
            or not isinstance(live_owner, ObjectOwner)
            or not isinstance(target, ObjectTarget)
            or type(now_us) is not int or now_us < 0
            or type(max_viewpoints) is not int or not 1 <= max_viewpoints <= 8
            or type(max_expansions_per_view) is not int
            or not 1 <= max_expansions_per_view <= 4096
            or not isinstance(viewpoints, tuple) or len(viewpoints) > 32
            or any(type(value) is not int or value < 0 for value in (
                grid.epoch, grid.expires_at_us, route_request.epoch,
                route_request.deadline_us, object_query.epoch,
                object_query.camera_boot, object_query.camera_grant,
                object_query.created_us, object_query.deadline_us,
                live_owner.epoch, live_owner.camera_boot,
                live_owner.camera_grant))
            or type(live_owner.camera_allowed) is not bool
            or type(live_owner.memory_allowed) is not bool):
        return "invalid_search_input"
    if not callable(clock_us) or not callable(request_is_current):
        return "missing_live_owner"
    return None


def _validate_search_request(
    grid: GridSnapshot, route_request: RouteRequest, object_query: ObjectQuery,
    live_owner: ObjectOwner, target: ObjectTarget, now_us: int,
) -> str | None:
    if object_query.cancelled or route_request.cancelled:
        return "cancelled"
    if ((object_query.robot_id, object_query.session_id, object_query.turn_id) !=
            (live_owner.robot_id, live_owner.session_id, live_owner.turn_id)):
        return "turn_or_robot_changed"
    if ((object_query.origin_id, object_query.epoch, object_query.anchor_id,
         object_query.calibration_id, object_query.camera_boot,
         object_query.host_boot_id, object_query.camera_grant) !=
            (live_owner.origin_id, live_owner.epoch, live_owner.anchor_id,
             live_owner.calibration_id, live_owner.camera_boot,
             live_owner.host_boot_id, live_owner.camera_grant)):
        return "origin_map_or_camera_changed"
    if (live_owner.memory_allowed is not True or live_owner.camera_allowed is not True):
        return "observation_consent_revoked"
    if ((route_request.robot_id, route_request.origin_id, route_request.epoch,
         route_request.anchor_id, route_request.session_id, route_request.turn_id) !=
            (object_query.robot_id, object_query.origin_id, object_query.epoch,
             object_query.anchor_id, object_query.session_id, object_query.turn_id)
            or route_request.deadline_us > object_query.deadline_us
            or (grid.robot_id, grid.origin_id, grid.epoch, grid.anchor_id,
                grid.calibration_id) !=
            (object_query.robot_id, object_query.origin_id, object_query.epoch,
             object_query.anchor_id, object_query.calibration_id)):
        return "route_or_map_identity_changed"
    if (type(object_query.created_us) is not int
            or type(object_query.deadline_us) is not int
            or not 0 <= object_query.created_us <= now_us < object_query.deadline_us):
        return "deadline_or_clock_invalid"
    if (target.robot_id != object_query.robot_id or target.label != object_query.label
            or target.may_execute is not False or target.arrived is not False):
        return "target_identity_or_authority_invalid"
    # A stale ObjectTarget may have the right robot/label and plausible floor
    # hint while belonging to an earlier session, boot, origin or consent.
    # Do not turn that historical result into a new viewpoint proposal.
    if (type(target.request_fence) is not ObjectQuery
            or target.request_fence != object_query):
        return "target_request_changed"
    return None


@dataclass
class _SearchClock:
    clock_us: Callable[[], int]
    request_is_current: Callable[[], bool]
    last_clock_us: int

    def read_clock(self) -> int:
        # The outer search and every nested route must share one high-water mark.
        current = self.clock_us()
        if type(current) is not int or current < self.last_clock_us:
            raise ValueError("Invalid search clock")
        self.last_clock_us = current
        return current

    def live(
        self, grid: GridSnapshot, route_request: RouteRequest, object_query: ObjectQuery,
    ) -> str | None:
        try:
            if self.request_is_current() is not True:
                return "request_invalidated"
        except Exception:
            return "request_invalidated"
        try:
            current = self.read_clock()
        except Exception:
            return "invalid_clock"
        if current >= object_query.deadline_us or current >= route_request.deadline_us:
            return "deadline_expired"
        if current >= grid.expires_at_us:
            return "map_expired"
        return None


def _has_search_hint(target: ObjectTarget) -> bool:
    # A user report or old memory with no same-map projection must not produce
    # an autonomous search. A fresh confirmed sighting uses the separate
    # target-approach sequence with its own measured physical authorization.
    return not (target.status != "last_seen" or target.source != "camera_seen"
                or not isinstance(target.search_hint_mm, tuple)
                or len(target.search_hint_mm) != 2
                or any(type(v) is not int or not -100_000 <= v <= 100_000
                       for v in target.search_hint_mm))


def _validate_viewpoints(
    viewpoints: tuple[SearchViewpoint, ...], object_query: ObjectQuery,
) -> str | None:
    identifiers: set[str] = set()
    for view in viewpoints:
        if (not isinstance(view, SearchViewpoint)
                or not isinstance(view.viewpoint_id, str)
                or not 1 <= len(view.viewpoint_id) <= 96
                or not view.viewpoint_id.isascii()
                or not all(ch.isalnum() or ch in "_-" for ch in view.viewpoint_id)
                or view.viewpoint_id in identifiers
                or type(view.priority) is not int or not 0 <= view.priority <= 100
                or type(view.previously_reachable) is not bool
                or type(view.inspected_in_request) is not bool
                or type(view.heading) is not int or view.heading not in range(4)
                or not isinstance(view.cell, tuple) or len(view.cell) != 2
                or any(type(v) is not int for v in view.cell)):
            return "invalid_viewpoint"
        identifiers.add(view.viewpoint_id)
        if ((view.robot_id, view.origin_id, view.epoch, view.anchor_id,
             view.calibration_id) !=
                (object_query.robot_id, object_query.origin_id,
                 object_query.epoch, object_query.anchor_id,
                 object_query.calibration_id)):
            return "foreign_or_stale_viewpoint"
    return None


def _rank_viewpoints(viewpoints: tuple[SearchViewpoint, ...]) -> list[SearchViewpoint]:
    # Different record IDs may represent the same fixed-camera pose.
    seen_poses = {(v.cell, v.heading) for v in viewpoints if v.inspected_in_request}
    candidates = []
    for view in sorted(viewpoints, key=lambda v: (v.priority, v.viewpoint_id)):
        pose = (view.cell, view.heading)
        if not view.previously_reachable or pose in seen_poses:
            continue
        seen_poses.add(pose)
        candidates.append(view)
    return candidates


def _route_to_viewpoint(
    grid: GridSnapshot, route_request: RouteRequest, envelope: SafetyEnvelope,
    view: SearchViewpoint, clock: _SearchClock, max_expansions_per_view: int,
) -> RouteResult:
    return plan_route(
        grid, RouteRequest(
            robot_id=route_request.robot_id,
            origin_id=route_request.origin_id,
            epoch=route_request.epoch,
            anchor_id=route_request.anchor_id,
            session_id=route_request.session_id,
            turn_id=route_request.turn_id,
            start=route_request.start,
            heading=route_request.heading,
            goal=view.cell,
            deadline_us=route_request.deadline_us,
            cancelled=route_request.cancelled,
            schema_version=route_request.schema_version,
            goal_heading=view.heading,
        ), envelope, now_us=clock.last_clock_us,
        max_expansions=max_expansions_per_view,
        clock_us=clock.read_clock, request_is_current=clock.request_is_current,
    )


def _valid_route_receipt(
    proposal: RouteResult, view: SearchViewpoint, object_query: ObjectQuery,
) -> bool:
    return not (not proposal.cells or proposal.cells[-1] != view.cell
                or type(proposal.final_heading) is not int
                or proposal.final_heading != view.heading
                or proposal.robot_id != object_query.robot_id
                or proposal.origin_id != object_query.origin_id
                or proposal.epoch != object_query.epoch
                or proposal.session_id != object_query.session_id
                or proposal.turn_id != object_query.turn_id)


def _search_candidates(
    grid: GridSnapshot, route_request: RouteRequest, envelope: SafetyEnvelope,
    object_query: ObjectQuery, candidates: list[SearchViewpoint], clock: _SearchClock,
    max_viewpoints: int, max_expansions_per_view: int,
) -> ObjectSearchResult:
    considered = 0
    for view in candidates[:max_viewpoints]:
        invalid = clock.live(grid, route_request, object_query)
        if invalid is not None:
            return _refuse(invalid, considered)
        considered += 1
        proposal = _route_to_viewpoint(
            grid, route_request, envelope, view, clock, max_expansions_per_view,
        )
        invalid = clock.live(grid, route_request, object_query)
        if invalid is not None:
            return _refuse(invalid, considered)
        if proposal.may_execute is not False:
            return _refuse("unexpected_route_authority", considered)
        if proposal.status == "planned":
            if not _valid_route_receipt(proposal, view, object_query):
                return _refuse("invalid_route_receipt", considered)
            return ObjectSearchResult(
                "viewpoint_proposal", "must_reobserve_target", view.viewpoint_id,
                proposal, considered, remaining_viewpoints=len(candidates) - 1,
            )
        if proposal.reason not in {"no_safe_route", "unsafe_goal"}:
            return _refuse(proposal.reason, considered)
    if len(candidates) > max_viewpoints:
        return _absent("search_budget_exhausted", considered)
    return _absent("no_reachable_uninspected_viewpoint", considered)
