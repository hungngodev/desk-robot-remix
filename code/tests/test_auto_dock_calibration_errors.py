"""Autonomous dock calibration errors cannot silently hide programming defects."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from desk_robot import controller


@pytest.fixture
def coordinator(tmp_path):
    robot = SimpleNamespace(
        autonomous_low_battery_dock_enabled=True,
        motion_enabled=True,
        dock_motion_qualified=True,
        dock_turn_sign=1,
        dock_forward_sign=1,
        dock_beacon_id=1,
        dock_calibration=tmp_path / "private-calibration.json",
    )
    return SimpleNamespace(
        robot=Mock(return_value=robot),
        settings=SimpleNamespace(
            camera_consent_generation=1, mode="hardware", voice_vision_tools_enabled=True,
        ),
        dock_inhibited=Mock(return_value=False),
        tasks={},
        voice_blocks_motion=Mock(return_value=None),
        permits={},
        operator_arm=AsyncMock(),
        dock=Mock(),
    )


@pytest.mark.parametrize("error_type", [FileNotFoundError, PermissionError, ValueError])
async def test_expected_calibration_failure_is_logged_and_blocks_motion(
    coordinator, monkeypatch, caplog, error_type,
):
    loader = Mock(side_effect=error_type("private-calibration-content"))
    monkeypatch.setattr(controller, "load_real_dock_calibration", loader)
    with caplog.at_level(logging.WARNING, logger=controller.__name__):
        result = await controller.Coordinator.request_autonomous_low_battery_dock(
            coordinator, "robot-01",
        )
    assert result is None
    loader.assert_called_once_with(
        coordinator.robot.return_value.dock_calibration, robot_id="robot-01",
    )
    assert f"Autonomous dock calibration rejected for robot-01: {error_type.__name__}" in (
        caplog.messages
    )
    assert "private-calibration-content" not in caplog.text
    coordinator.operator_arm.assert_not_awaited()
    coordinator.dock.assert_not_called()
    assert coordinator.permits == {}


@pytest.mark.parametrize("error_type", [RuntimeError, TypeError, asyncio.CancelledError,
                                       KeyboardInterrupt])
async def test_unexpected_calibration_failure_propagates_without_motion(
    coordinator, monkeypatch, error_type,
):
    failure = error_type("injected failure")
    monkeypatch.setattr(controller, "load_real_dock_calibration", Mock(side_effect=failure))
    with pytest.raises(error_type) as caught:
        await controller.Coordinator.request_autonomous_low_battery_dock(
            coordinator, "robot-01",
        )
    assert caught.value is failure
    coordinator.operator_arm.assert_not_awaited()
    coordinator.dock.assert_not_called()
    assert coordinator.permits == {}
