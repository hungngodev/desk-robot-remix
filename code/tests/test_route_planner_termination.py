"""Bounded search and failure receipts on blocked desk maps (DRX-1220)."""

from dataclasses import replace

import pytest
from desk_robot import route_planner as planner
from desk_robot.route_planner import GridSnapshot, RouteRequest, SafetyEnvelope, plan_route


def fixtures(width=15, height=15):
    grid = GridSnapshot(
        "pet", "origin", 3, "tag", "cal", width, height, 20,
        ("safe",) * (width * height), 500, 4000, True,
    )
    request = RouteRequest(
        "pet", "origin", 3, "tag", "s", "t", (3, 7), 0, (9, 7), 3000,
    )
    envelope = SafetyEnvelope(3, 2, 2, 32, True)
    return grid, request, envelope


def assert_refused(result, reason):
    assert (result.status, result.reason, result.cells, result.may_execute) == (
        "rejected", reason, (), False,
    )
    assert result.final_heading is None and result.valid_until_us == 0


@pytest.mark.parametrize("marker", ["occupied", "unknown", "stale", "unsafe"])
@pytest.mark.parametrize("stationary", [False, True])
def test_completely_blocked_map_never_enters_search(monkeypatch, marker, stationary):
    grid, request, envelope = fixtures()
    grid = replace(grid, support=(marker,) * len(grid.support))
    if stationary:
        request = replace(request, goal=request.start)

    def unexpected_pop(_queue):
        pytest.fail("unsafe start must be rejected before search")

    monkeypatch.setattr(planner.heapq, "heappop", unexpected_pop)
    assert_refused(plan_route(grid, request, envelope, now_us=1000), "unsafe_start")


def test_stationary_safe_pose_never_enters_search(monkeypatch):
    grid, request, envelope = fixtures()
    request = replace(request, goal=request.start, goal_heading=request.heading)

    def unexpected_pop(_queue):
        pytest.fail("stationary proposal must not search")

    monkeypatch.setattr(planner.heapq, "heappop", unexpected_pop)
    result = plan_route(grid, request, envelope, now_us=1000, max_expansions=1)
    assert (result.status, result.reason, result.cells) == (
        "planned", "at_observation_pose", (request.start,),
    )
    assert result.final_heading == request.heading and not result.may_execute


def test_zero_clearance_corridor_between_safe_rooms():
    grid, request, envelope = fixtures()
    support = tuple(
        "safe" if x <= 4 or x >= 8 or y == 7 else "unknown"
        for y in range(grid.height) for x in range(grid.width)
    )
    grid = replace(grid, support=support)
    # A 20 mm aisle with an inflated radius of 10 mm touches unknown support.
    tangent = replace(envelope, footprint_radius_mm=6)
    assert_refused(plan_route(grid, request, tangent, now_us=1000), "no_safe_route")
    # A positive 1 mm margin is a read-only straight proposal, not a motor permit.
    narrower = replace(tangent, footprint_radius_mm=5)
    result = plan_route(grid, request, narrower, now_us=1000)
    assert result.status == "planned"
    assert result.cells == tuple((x, 7) for x in range(3, 10))
    assert not result.may_execute


@pytest.mark.parametrize("budget", [1, 64, 4096])
def test_large_disconnected_map_has_bounded_heap_work(monkeypatch, budget):
    grid, request, envelope = fixtures(128, 64)
    grid = replace(grid, support=tuple(
        "occupied" if x == 64 else "safe"
        for _y in range(grid.height) for x in range(grid.width)
    ))
    request = replace(request, start=(5, 32), goal=(120, 32))
    original_pop = planner.heapq.heappop
    pops = 0

    def bounded_pop(queue):
        nonlocal pops
        pops += 1
        # Each expansion enqueues at most three successors, even with stale entries.
        assert pops <= 1 + 3 * budget
        return original_pop(queue)

    monkeypatch.setattr(planner.heapq, "heappop", bounded_pop)
    result = plan_route(grid, request, envelope, now_us=1000, max_expansions=budget)
    assert_refused(result, "search_budget_exhausted")
    assert pops >= budget + 1


@pytest.mark.parametrize("invalidate", ["none", "cancel", "deadline", "map_expiry"])
def test_isolated_start_final_expansion_rechecks_liveness(monkeypatch, invalidate):
    grid, request, envelope = fixtures()
    grid = replace(grid, support=tuple(
        "safe" if (x, y) in (request.start, request.goal) else "unknown"
        for y in range(grid.height) for x in range(grid.width)
    ))
    if invalidate == "map_expiry":
        request = replace(request, deadline_us=5000)
    current, clock, pops = True, 1000, 0
    original_pop = planner.heapq.heappop

    def pop(queue):
        nonlocal current, clock, pops
        pops += 1
        assert pops == 1
        item = original_pop(queue)
        if invalidate == "cancel":
            current = False
        elif invalidate == "deadline":
            clock = request.deadline_us
        elif invalidate == "map_expiry":
            clock = grid.expires_at_us
        return item

    monkeypatch.setattr(planner.heapq, "heappop", pop)
    result = plan_route(
        grid, request, envelope, now_us=1000, max_expansions=1,
        clock_us=lambda: clock, request_is_current=lambda: current,
    )
    reason = {
        "none": "no_safe_route", "cancel": "request_invalidated",
        "deadline": "deadline_or_map_expired", "map_expiry": "deadline_or_map_expired",
    }[invalidate]
    assert_refused(result, reason)
    assert pops == 1


@pytest.mark.parametrize("exit_path", ["unsafe_start", "unsafe_goal", "search_budget_exhausted"])
@pytest.mark.parametrize(("failure", "reason"), [
    ("cancel", "request_invalidated"),
    ("guard_error", "request_invalidated"),
    ("clock_error", "invalid_clock"),
    ("deadline", "deadline_or_map_expired"),
    ("map_expiry", "deadline_or_map_expired"),
])
def test_terminal_refusals_preserve_liveness_failure(monkeypatch, exit_path, failure, reason):
    grid, request, envelope = fixtures()
    if failure == "map_expiry":
        request = replace(request, deadline_us=5000)
    invalidated = False
    if exit_path != "search_budget_exhausted":
        blocked = request.start if exit_path == "unsafe_start" else request.goal
        blocked_index = blocked[1] * grid.width + blocked[0]

        class InvalidatingSupport(tuple):
            def __getitem__(self, index):
                nonlocal invalidated
                if isinstance(index, slice) and index.start == blocked_index:
                    invalidated = True
                return super().__getitem__(index)

        support = list(grid.support)
        support[blocked_index] = "unknown"
        grid = replace(grid, support=InvalidatingSupport(support))
    else:
        original_pop = planner.heapq.heappop
        pops = 0

        def pop(queue):
            nonlocal invalidated, pops
            pops += 1
            item = original_pop(queue)
            if pops == 2:
                invalidated = True
            return item

        monkeypatch.setattr(planner.heapq, "heappop", pop)

    def current():
        if invalidated and failure == "guard_error":
            raise RuntimeError("private guard diagnostic")
        return not (invalidated and failure == "cancel")

    def clock():
        if invalidated:
            if failure == "clock_error":
                raise TimeoutError("private clock diagnostic")
            if failure == "deadline":
                return request.deadline_us
            if failure == "map_expiry":
                return grid.expires_at_us
        return 1000

    result = plan_route(
        grid, request, envelope, now_us=1000, max_expansions=1,
        clock_us=clock, request_is_current=current,
    )
    assert invalidated
    assert_refused(result, reason)
