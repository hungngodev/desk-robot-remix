"""Sleep-aware monotonic clock checks for Mac wake deadlines (868UGjP)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from desk_robot import controller as controller_mod
from desk_robot import operations as operations_mod
from desk_robot import sleep_clock
from desk_robot.config import RobotConfig, Settings
from desk_robot.controller import Coordinator
from desk_robot.operations import OperationError, dispatch_job_command
from desk_robot.simulator import SimulatedHead, SimulationVision


def test_continuous_monotonic_selects_platform_sleep_clock(monkeypatch):
    seen: list[int] = []

    def fake_clock_gettime(clk_id: int) -> float:
        seen.append(clk_id)
        return 42.5

    monkeypatch.setattr(sleep_clock.sys, "platform", "darwin")
    monkeypatch.setattr(sleep_clock.time, "CLOCK_MONOTONIC", 99, raising=False)
    monkeypatch.setattr(sleep_clock.time, "clock_gettime", fake_clock_gettime)
    assert sleep_clock.continuous_monotonic() == 42.5
    assert seen == [99]

    seen.clear()
    monkeypatch.setattr(sleep_clock.sys, "platform", "linux")
    monkeypatch.setattr(sleep_clock.time, "CLOCK_BOOTTIME", 77, raising=False)
    assert sleep_clock.continuous_monotonic() == 42.5
    assert seen == [77]


@pytest.mark.asyncio
async def test_operator_permit_and_drive_deadline_expire_after_sleep(monkeypatch):
    mono_now = 100.0
    cont_now = 100.0
    monkeypatch.setattr(controller_mod.time, "monotonic", lambda: mono_now)
    monkeypatch.setattr(controller_mod, "continuous_monotonic", lambda: cont_now)
    monkeypatch.setattr(operations_mod, "monotonic", lambda: mono_now)
    monkeypatch.setattr(operations_mod, "continuous_monotonic", lambda: cont_now)

    settings = Settings(
        mode="simulation",
        robots=[RobotConfig(
            id="robot-01", name="Pet",
            token_env="DESK_ROBOT_HEAD_1_TOKEN", motion_enabled=True,
        )],
    )
    robot_id = settings.robots[0].id
    coord = Coordinator(
        settings,
        {r.id: SimulatedHead(r.id) for r in settings.robots},
        SimulationVision(),
    )
    await coord.operator_arm(robot_id)
    coord._require_live_permit(robot_id)

    # Simulate host sleep where time.monotonic() freezes while continuous clock advances 35s.
    cont_now = 135.0
    with pytest.raises(OperationError, match="Operator permit missing or expired"):
        coord._require_live_permit(robot_id)

    head = SimpleNamespace(command=None)

    async def slow_head_command(_cmd):
        nonlocal cont_now
        cont_now += 2.0
        return {"robot_id": robot_id, "reply": "ACK drive 20 20 100"}

    head.command = slow_head_command
    cont_now = 200.0

    # When continuous clock advances past drive budget during dispatch check, reject before send.
    class PreExpiredHead:
        supports_dispatch_check = True

        async def command(self, cmd, *, dispatch_check=None):
            nonlocal cont_now
            cont_now += 5.0
            if dispatch_check is not None:
                dispatch_check()
            return {"robot_id": robot_id, "reply": "ACK " + cmd}

    with pytest.raises(OperationError, match="Drive dispatch expired"):
        await dispatch_job_command(
            PreExpiredHead(), "drive 20 20 100", lambda: None, robot_id=robot_id,
        )
    await coord.close()


def test_elapsed_with_sleep_prefers_larger_elapsed():
    assert sleep_clock.elapsed_with_sleep(
        10.0, 20.0, now_monotonic=10.5, now_continuous=28.0,
    ) == 8.0
    assert sleep_clock.elapsed_with_sleep(
        10.0, 20.0, now_monotonic=15.0, now_continuous=21.0,
    ) == 5.0
