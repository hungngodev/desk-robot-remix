"""Delayed A* completion is not a new motion permit."""

import asyncio
import heapq
import threading
from types import SimpleNamespace

import pytest
from desk_robot import route_planner as planner


@pytest.fixture
def route_inputs():
    grid = planner.GridSnapshot(
        "robot-01", "origin", 8, "anchor", "cal", 15, 15, 20,
        ("safe",) * 225, 800_000, 1_400_000, True,
    )
    request = planner.RouteRequest(
        "robot-01", "origin", 8, "anchor", "session", "old-turn",
        (3, 7), 0, (9, 7), 1_500_000,
    )
    return grid, request, planner.SafetyEnvelope(3, 2, 2, 32, True)


def delay_goal_pop(monkeypatch, goal):
    """Pause after the final search-loop check, not before admission."""
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()

    def pop(queue):
        item = heapq.heappop(queue)
        if item[3:5] == goal:
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(timeout=5):
                raise TimeoutError("test did not release planner")
        return item

    # Do not monkeypatch the heapq module shared by the asyncio event loop.
    monkeypatch.setattr(
        planner, "heapq", SimpleNamespace(heappop=pop, heappush=heapq.heappush),
    )
    return entered, release


@pytest.mark.asyncio
async def test_goal_pop_rejects_retired_turn_on_same_map(monkeypatch, route_inputs):
    grid, request, envelope = route_inputs
    baseline = planner.plan_route(grid, request, envelope, now_us=1_000_000)
    assert baseline.status == "planned" and baseline.cells[-1] == request.goal
    entered, release = delay_goal_pop(monkeypatch, request.goal)
    retired = threading.Event()
    worker = asyncio.create_task(asyncio.to_thread(
        planner.plan_route, grid, request, envelope, now_us=1_000_000,
        request_is_current=lambda: not retired.is_set(),
    ))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        # A human redirect retires the old turn, not necessarily the map.
        retired.set()
        release.set()
        result = await asyncio.wait_for(worker, 2)
        assert result.status == "rejected"
        assert result.reason == "request_invalidated"
        assert not result.cells and result.may_execute is False
    finally:
        release.set()
        await worker


@pytest.mark.asyncio
async def test_stop_fences_even_uncooperative_planner_completion(
    monkeypatch, route_inputs, settings,
):
    from desk_robot.controller import Coordinator
    from desk_robot.simulator import SimulatedHead, SimulationVision

    grid, request, envelope = route_inputs
    entered, release = delay_goal_pop(monkeypatch, request.goal)
    for robot in settings.robots:
        robot.motor_backend = "stepper_28byj48"
    head = SimulatedHead("robot-01")
    coordinator = Coordinator(
        settings, {"robot-01": head, "robot-02": SimulatedHead("robot-02")},
        SimulationVision(),
    )
    halt_sent = asyncio.Event()
    attempted_drives = []
    completed = []
    original = head.command

    async def record(command):
        if command.startswith("drive "):
            attempted_drives.append(command)
        if command == "halt":
            halt_sent.set()
        return await original(command)

    monkeypatch.setattr(head, "command", record)

    async def delayed_work(job):
        # Deliberately model a worker that cannot observe the retired turn.
        # Its geometrically valid proposal must not reacquire motor authority.
        worker = asyncio.create_task(asyncio.to_thread(
            planner.plan_route, grid, request, envelope, now_us=1_000_000,
        ))
        try:
            result = await asyncio.shield(worker)
        except asyncio.CancelledError:
            result = await worker
        completed.append(result)
        await coordinator._motion_command(job, "drive 20 20 100")
        return {"status": "unexpected_drive"}

    start = tuple(head.position)
    try:
        await coordinator.operator_arm("robot-01")
        job = coordinator._submit("robot-01", "navigate", delayed_work)
        await asyncio.wait_for(entered.wait(), 2)
        stopping = asyncio.create_task(coordinator.stop("robot-01"))
        await asyncio.wait_for(halt_sent.wait(), 2)
        release.set()
        await asyncio.wait_for(stopping, 4)
        assert len(completed) == 1 and completed[0].status == "planned"
        assert completed[0].cells[-1] == request.goal
        assert not attempted_drives and tuple(head.position) == start
        assert job.state == "cancelled" and job.result is None
        assert not head.armed and "robot-01" not in coordinator.permits
    finally:
        release.set()
        await coordinator.close()
