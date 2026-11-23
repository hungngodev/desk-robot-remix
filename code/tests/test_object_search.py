"""Offline Guide 60 last-seen viewpoint planning and negative replay."""

from dataclasses import replace

import pytest
from desk_robot.object_search import SearchViewpoint, propose_object_search
from desk_robot.object_targets import ObjectOwner, ObjectQuery, ObjectTarget
from desk_robot.route_planner import GridSnapshot, RouteRequest, SafetyEnvelope


def fixtures():
    query = ObjectQuery(
        "robot-01", "key", "session-2", "turn-7", "origin-3", 8,
        "tag-4", "cal-5", 101, "mac-boot-5", 12, 900_000, 1_500_000,
    )
    owner = ObjectOwner(
        "robot-01", "session-2", "turn-7", "origin-3", 8, "tag-4",
        "cal-5", 101, "mac-boot-5", 12, True, True,
    )
    target = ObjectTarget(
        "last_seen", "not_currently_confirmed", "robot-01", "key",
        "camera_seen", 1800000000.1, search_hint_mm=(120, 220),
        request_fence=query,
    )
    grid = GridSnapshot(
        "robot-01", "origin-3", 8, "tag-4", "cal-5", 15, 15, 20,
        ("safe",) * 225, 800_000, 1_400_000, True,
    )
    request = RouteRequest(
        "robot-01", "origin-3", 8, "tag-4", "session-2", "turn-7",
        (3, 7), 0, (9, 7), 1_500_000,
    )
    envelope = SafetyEnvelope(3, 2, 2, 32, True)
    viewpoint = SearchViewpoint(
        "robot-01", "origin-3", 8, "tag-4", "cal-5", "view-1",
        (9, 7), 0, True,
    )
    return grid, request, envelope, query, owner, target, viewpoint


def search(*, candidates=None, clock_us=None, is_current=None, now_us=1_000_000,
           **changes):
    grid, request, env, query, owner, target, view = fixtures()
    return propose_object_search(
        changes.get("grid", grid), changes.get("route_request", request),
        changes.get("envelope", env), changes.get("object_query", query),
        changes.get("live_owner", owner), changes.get("target", target),
        candidates if candidates is not None else (view,), now_us=now_us,
        clock_us=clock_us if clock_us is not None else lambda: 1_000_000,
        request_is_current=is_current if is_current is not None else lambda: True,
        max_viewpoints=changes.get("max_viewpoints", 8),
        max_expansions_per_view=changes.get("max_expansions_per_view", 512),
    )


def test_last_seen_selects_safe_viewpoint_not_arrival_or_motor_command():
    result = search()
    assert result.status == "viewpoint_proposal"
    assert result.reason == "must_reobserve_target"
    assert result.viewpoint_id == "view-1"
    assert result.route is not None and result.route.cells[-1] == (9, 7)
    assert not result.arrived and not result.may_execute
    assert result.route.may_execute is False
    assert result.considered == 1
    assert search() == result


def test_unreachable_first_viewpoint_skipped_in_favor_of_next_safe_candidate():
    grid, _, _, _, _, _, view = fixtures()
    blocked = list(grid.support)
    blocked[7 * grid.width + 9] = "unsafe"
    second = replace(view, viewpoint_id="view-2", cell=(8, 7), priority=1)
    result = search(grid=replace(grid, support=tuple(blocked)),
                    candidates=(view, second))
    assert result.status == "viewpoint_proposal"
    assert result.viewpoint_id == "view-2" and result.considered == 2
    assert result.route is not None and result.route.cells[-1] == (8, 7)


def test_unknown_support_blocks_all_search_viewpoints():
    grid, _, _, _, _, _, _ = fixtures()
    support = list(grid.support)
    for y in range(grid.height):
        support[y * grid.width + 7] = "unknown"
    result = search(grid=replace(grid, support=tuple(support)))
    assert result.status == "no_current_sighting"
    assert result.reason == "no_reachable_uninspected_viewpoint"
    assert result.route is None and not result.may_execute


def test_unseen_or_user_reported_target_cannot_trigger_viewpoint_plan():
    _, _, _, _, _, target, _ = fixtures()
    for replacement in (
        replace(target, status="unknown", search_hint_mm=None),
        replace(target, status="user_reported", source="user_reported"),
        replace(target, status="current_sighting", search_hint_mm=None),
        replace(target, search_hint_mm=None),
    ):
        result = search(target=replacement)
        assert result.status == "no_current_sighting"
        assert result.route is None and not result.may_execute


def test_inspected_viewpoint_is_never_visited_twice():
    _, _, _, _, _, _, view = fixtures()
    result = search(candidates=(replace(view, inspected_in_request=True),))
    assert result.reason == "no_reachable_uninspected_viewpoint"
    assert result.considered == 0


def test_unverified_or_absent_viewpoint_never_yields_route():
    _, _, _, _, _, _, view = fixtures()
    assert search(candidates=(replace(view, previously_reachable=False),)).route is None
    assert search(candidates=()).route is None


@pytest.mark.parametrize("changed", [
    {"robot_id": "robot-02"},
    {"origin_id": "old-origin"},
    {"epoch": 9},
    {"anchor_id": "tag-9"},
    {"calibration_id": "cal-6"},
])
def test_foreign_or_unanchored_viewpoint_refused(changed):
    _, _, _, _, _, _, view = fixtures()
    result = search(candidates=(replace(view, **changed),))
    assert result.status == "rejected"
    assert result.reason == "foreign_or_stale_viewpoint"
    assert result.route is None


@pytest.mark.parametrize("changed", [
    {"camera_boot": 102},
    {"host_boot_id": "rebooted-mac"},
    {"camera_grant": 13},
    {"origin_id": "picked-up"},
    {"epoch": 9},
])
def test_live_owner_identity_change_refuses_all_routes(changed):
    _, _, _, _, owner, _, _ = fixtures()
    result = search(live_owner=replace(owner, **changed))
    assert result.status == "rejected"
    assert result.reason == "origin_map_or_camera_changed"
    assert result.route is None


def test_old_turn_and_memory_or_camera_consent_revoke_stop_search():
    _, _, _, query, owner, _, _ = fixtures()
    for change in (replace(owner, session_id="other"),
                   replace(owner, turn_id="new"),
                   replace(owner, robot_id="robot-02")):
        assert search(live_owner=change).reason == "turn_or_robot_changed"
    for change in (replace(owner, camera_allowed=False),
                   replace(owner, memory_allowed=False)):
        assert search(live_owner=change).reason == "observation_consent_revoked"
    assert search(object_query=replace(query, cancelled=True)).reason == "cancelled"


def test_operator_stop_before_search_and_while_planning():
    assert search(is_current=lambda: False).reason == "request_invalidated"
    _, _, _, _, _, _, view = fixtures()
    calls = 0

    def current():
        nonlocal calls
        calls += 1
        return calls < 4

    result = search(candidates=(view,), is_current=current)
    assert result.status == "rejected" and result.reason == "request_invalidated"
    assert result.route is None and not result.may_execute


def test_monotonic_rollback_and_deadline_expiry_are_finite_refusals():
    assert search(clock_us=lambda: 900_000).reason == "invalid_clock"
    assert search(clock_us=lambda: 1_500_000).reason == "deadline_expired"
    assert search(clock_us=lambda: 1_400_000).reason == "map_expired"
    assert search(now_us=1_500_000).reason == "deadline_or_clock_invalid"


def test_no_clock_or_owner_callback_never_proposes_motion():
    grid, request, envelope, query, owner, target, view = fixtures()
    for clock, is_current in ((None, lambda: True), (lambda: 1_000_000, None)):
        result = propose_object_search(grid, request, envelope, query, owner, target,
                                       (view,), now_us=1_000_000,
                                       clock_us=clock, request_is_current=is_current)
        assert result.reason == "missing_live_owner"
        assert result.route is None


def test_same_request_cannot_extend_deadline_or_use_other_map():
    grid, request, _, _, _, _, _ = fixtures()
    assert search(route_request=replace(request, deadline_us=1_600_000)).reason == (
        "route_or_map_identity_changed"
    )
    assert search(grid=replace(grid, epoch=9)).reason == "route_or_map_identity_changed"


def test_budget_and_duplicate_viewpoint_ids_are_rejected():
    _, _, _, _, _, _, view = fixtures()
    assert search(candidates=(view, view)).reason == "invalid_viewpoint"
    assert search(candidates=(view,) * 33).reason == "invalid_search_input"
    assert search(max_viewpoints=0).reason == "invalid_search_input"
    assert search(max_expansions_per_view=True).reason == "invalid_search_input"
    repeated = tuple(replace(view, viewpoint_id=f"view-{i}", cell=(i % 5 + 8, 7),
                             priority=i) for i in range(12))
    result = search(candidates=repeated, max_viewpoints=1)
    assert result.considered == 1
    assert not result.may_execute


def test_malformed_target_or_viewpoint_never_enters_route_planner():
    _, _, _, _, _, target, view = fixtures()
    assert search(target=replace(target, may_execute=True)).reason == (
        "target_identity_or_authority_invalid"
    )
    assert search(candidates=(replace(view, cell=(True, 7)),)).reason == (
        "invalid_viewpoint"
    )
    assert search(target=replace(target, search_hint_mm=(float("nan"), 5))).reason == (
        "no_same_map_last_seen_hint"
    )



def test_unfenced_manually_created_target_cannot_reach_route_planner():
    _, _, _, _, _, target, _ = fixtures()
    result = search(target=replace(target, request_fence=None))
    assert result.reason == "target_request_changed"
    assert result.route is None and not result.may_execute


@pytest.mark.parametrize(("query_change", "owner_change", "route_change"), [
    ({"session_id": "new-session"}, {"session_id": "new-session"},
     {"session_id": "new-session"}),
    ({"turn_id": "new-turn"}, {"turn_id": "new-turn"},
     {"turn_id": "new-turn"}),
    ({"camera_boot": 102}, {"camera_boot": 102}, {}),
    ({"host_boot_id": "new-mac"}, {"host_boot_id": "new-mac"}, {}),
    ({"camera_grant": 13}, {"camera_grant": 13}, {}),
    ({"deadline_us": 1_600_000}, {}, {}),
])
def test_old_last_seen_target_rejected_after_fresh_request_owner_change(
    query_change, owner_change, route_change,
):
    _, request, _, query, owner, target, _ = fixtures()
    result = search(
        object_query=replace(query, **query_change),
        live_owner=replace(owner, **owner_change),
        route_request=replace(request, **route_change),
        target=target,
    )
    assert result.reason == "target_request_changed"
    assert result.status == "rejected"
    assert result.route is None and not result.may_execute


@pytest.mark.parametrize("change", [
    {"origin_id": "new-body-boot"},
    {"epoch": 9},
    {"anchor_id": "new-tag"},
])
def test_old_last_seen_target_rejected_after_reanchoring(change):
    grid, request, _, query, owner, target, _ = fixtures()
    result = search(
        grid=replace(grid, **change),
        route_request=replace(request, **change),
        object_query=replace(query, **change),
        live_owner=replace(owner, **change),
        target=target,
    )
    assert result.reason == "target_request_changed"
    assert result.route is None and not result.may_execute
