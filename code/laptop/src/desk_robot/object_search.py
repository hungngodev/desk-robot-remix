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


@dataclass(frozen=True)
class ObjectSearchResult:
    status: str  # viewpoint_proposal, no_current_sighting, rejected
    reason: str
    viewpoint_id: str | None = None
    route: RouteResult | None = None
    considered: int = 0
    may_execute: bool = False
    arrived: bool = False


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

    def refuse(reason: str, considered: int = 0) -> ObjectSearchResult:
        return ObjectSearchResult("rejected", reason, considered=considered)

    def absent(reason: str, considered: int = 0) -> ObjectSearchResult:
        return ObjectSearchResult("no_current_sighting", reason, considered=considered)

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
        return refuse("invalid_search_input")
    if not callable(clock_us) or not callable(request_is_current):
        return refuse("missing_live_owner")
    if object_query.cancelled or route_request.cancelled:
        return refuse("cancelled")
    if ((object_query.robot_id, object_query.session_id, object_query.turn_id) !=
            (live_owner.robot_id, live_owner.session_id, live_owner.turn_id)):
        return refuse("turn_or_robot_changed")
    if ((object_query.origin_id, object_query.epoch, object_query.anchor_id,
         object_query.calibration_id, object_query.camera_boot,
         object_query.host_boot_id, object_query.camera_grant) !=
            (live_owner.origin_id, live_owner.epoch, live_owner.anchor_id,
             live_owner.calibration_id, live_owner.camera_boot,
             live_owner.host_boot_id, live_owner.camera_grant)):
        return refuse("origin_map_or_camera_changed")
    if (live_owner.memory_allowed is not True or live_owner.camera_allowed is not True):
        return refuse("observation_consent_revoked")
    if ((route_request.robot_id, route_request.origin_id, route_request.epoch,
         route_request.anchor_id, route_request.session_id, route_request.turn_id) !=
            (object_query.robot_id, object_query.origin_id, object_query.epoch,
             object_query.anchor_id, object_query.session_id, object_query.turn_id)
            or route_request.deadline_us > object_query.deadline_us
            or (grid.robot_id, grid.origin_id, grid.epoch, grid.anchor_id,
                grid.calibration_id) !=
            (object_query.robot_id, object_query.origin_id, object_query.epoch,
             object_query.anchor_id, object_query.calibration_id)):
        return refuse("route_or_map_identity_changed")
    if (type(object_query.created_us) is not int
            or type(object_query.deadline_us) is not int
            or not 0 <= object_query.created_us <= now_us < object_query.deadline_us):
        return refuse("deadline_or_clock_invalid")
    if (target.robot_id != object_query.robot_id or target.label != object_query.label
            or target.may_execute is not False or target.arrived is not False):
        return refuse("target_identity_or_authority_invalid")

    last_clock_us = now_us

    def live() -> str | None:
        nonlocal last_clock_us
        try:
            if request_is_current() is not True:
                return "request_invalidated"
            current = clock_us()
        except Exception:
            return "request_invalidated"
        if type(current) is not int or current < last_clock_us:
            return "invalid_clock"
        last_clock_us = current
        if current >= object_query.deadline_us or current >= route_request.deadline_us:
            return "deadline_expired"
        if current >= grid.expires_at_us:
            return "map_expired"
        return None

    invalid = live()
    if invalid is not None:
        return refuse(invalid)
    # A user report or old memory with no same-map projection must not produce
    # an autonomous search. A fresh confirmed sighting uses the separate
    # target-approach sequence with its own measured physical authorization.
    if (target.status != "last_seen" or target.source != "camera_seen"
            or not isinstance(target.search_hint_mm, tuple)
            or len(target.search_hint_mm) != 2
            or any(type(v) is not int or not -100_000 <= v <= 100_000
                   for v in target.search_hint_mm)):
        return absent("no_same_map_last_seen_hint")

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
                or not isinstance(view.cell, tuple) or len(view.cell) != 2
                or any(type(v) is not int for v in view.cell)):
            return refuse("invalid_viewpoint")
        identifiers.add(view.viewpoint_id)
        if ((view.robot_id, view.origin_id, view.epoch, view.anchor_id,
             view.calibration_id) !=
                (object_query.robot_id, object_query.origin_id,
                 object_query.epoch, object_query.anchor_id,
                 object_query.calibration_id)):
            return refuse("foreign_or_stale_viewpoint")

    candidates = sorted(
        (v for v in viewpoints
         if v.previously_reachable and not v.inspected_in_request),
        key=lambda v: (v.priority, v.viewpoint_id),
    )
    considered = 0
    for view in candidates[:max_viewpoints]:
        invalid = live()
        if invalid is not None:
            return refuse(invalid, considered)
        considered += 1
        proposal = plan_route(
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
            ), envelope, now_us=last_clock_us,
            max_expansions=max_expansions_per_view,
            clock_us=clock_us, request_is_current=request_is_current,
        )
        invalid = live()
        if invalid is not None:
            return refuse(invalid, considered)
        if proposal.may_execute is not False:
            return refuse("unexpected_route_authority", considered)
        if proposal.status == "planned":
            if (not proposal.cells or proposal.cells[-1] != view.cell
                    or proposal.robot_id != object_query.robot_id
                    or proposal.origin_id != object_query.origin_id
                    or proposal.epoch != object_query.epoch
                    or proposal.session_id != object_query.session_id
                    or proposal.turn_id != object_query.turn_id):
                return refuse("invalid_route_receipt", considered)
            return ObjectSearchResult(
                "viewpoint_proposal", "must_reobserve_target", view.viewpoint_id,
                proposal, considered,
            )
        if proposal.reason not in {"no_safe_route", "unsafe_goal"}:
            return refuse(proposal.reason, considered)
    if len(candidates) > max_viewpoints:
        return absent("search_budget_exhausted", considered)
    return absent("no_reachable_uninspected_viewpoint", considered)

