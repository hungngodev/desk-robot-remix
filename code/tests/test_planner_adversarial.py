from dataclasses import replace

import pytest

from desk_robot.route_planner import (
    GridSnapshot,
    RouteRequest,
    SafetyEnvelope,
    plan_route,
    revalidate_route_step,
)


def fixture():
    w, h = 9, 5
    support = tuple(
        'safe' if y == 2 or (x in (1, 2, 6, 7) and y in (1, 3)) else 'unknown'
        for y in range(h) for x in range(w)
    )
    grid = GridSnapshot('r', 'o', 1, 'a', 'c', w, h, 20, support, 10, 1000, True)
    request = RouteRequest('r', 'o', 1, 'a', 's', 't', (1, 2), 0, (7, 2), 800)
    return grid, request, SafetyEnvelope(5, 1, 1, 5, True)


def test_stop_margin_blocks_narrow_bottleneck_with_safe_endpoints():
    grid, request, envelope = fixture()
    narrow = plan_route(grid, request, envelope, now_us=20)
    assert narrow.status == 'planned'
    assert narrow.cells == tuple((x, 2) for x in range(1, 8))
    assert not narrow.may_execute
    blocked = plan_route(grid, request, replace(envelope, stopping_margin_mm=5), now_us=20)
    assert blocked.status == 'rejected'
    assert blocked.reason == 'no_safe_route'
    assert not blocked.may_execute


@pytest.mark.parametrize('field,value', [('map_observed_at_us', None), ('cells', None),
                                        ('map_observed_at_us', True), ('map_observed_at_us', -1)])
def test_invalid_route_receipt_fails_closed(field, value):
    grid, request, envelope = fixture()
    route = plan_route(grid, request, envelope, now_us=20)
    assert revalidate_route_step(grid, route, envelope, start=(1, 2), heading=0,
                                 goal=(2, 2), now_us=20)
    assert not revalidate_route_step(grid, replace(route, **{field: value}), envelope,
                                     start=(1, 2), heading=0, goal=(2, 2), now_us=20)


@pytest.mark.parametrize('index', range(3))
def test_invalid_planner_input_rejected(index):
    args = list(fixture())
    args[index] = None
    assert plan_route(*args, now_us=20).status == 'rejected'
