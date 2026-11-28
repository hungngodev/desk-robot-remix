"""Integration regression for battery-only optional speech admission."""
import asyncio
import math
from pathlib import Path

from desk_robot.config import load_settings
from desk_robot.conversation import Conversation
from desk_robot.memory import MemoryStore
from desk_robot.pet import PetController
from desk_robot.simulator import SimulatedSpeaker
from desk_robot.vision import SceneChange


async def test_battery_warning_cooldown_survives_description_and_generation_changes(tmp_path):
    class BatteryChat:
        async def proactive_decision(self, _history):
            return {"action": "speak", "text": "My charge is getting low."}

    class NoScene:
        async def compare(self, before, after):
            raise AssertionError("Battery speech does not require a camera")

    fleet = load_settings(
        Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    )
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    pet = PetController(
        fleet, {}, Conversation(fleet, BatteryChat(), speaker, memory=memory),
        memory, NoScene(), speech_cooldown=0,
    )
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 95
    try:
        pet._consider_speech(
            "robot-01", SceneChange("battery_low", "Fuel gauge started low", 1.0), 95,
        )
        async with asyncio.timeout(2):
            while pet._speech_task is not None:
                await asyncio.sleep(0.01)
        assert speaker.spoken == [("robot-01", "My charge is getting low.")]
        assert math.isfinite(state.last_battery_warning_at)
        assert pet.states["robot-02"].last_battery_warning_at == -math.inf

        # A new episode or observer restart can change the description.
        # Neither the wording nor a zero general cooldown may refund this budget.
        state.generation += 1
        pet._consider_speech(
            "robot-01", SceneChange("battery_low", "Fuel gauge remains low", 1.0), 96,
        )
        assert pet._speech_task is None
        assert state.last_initiative_gate_reason == "battery_warning_cooldown"
        assert len(speaker.spoken) == 1
    finally:
        state.enabled = False
        await pet.close()


async def test_deferred_low_battery_dock_rechecks_voltage_after_voice(monkeypatch, tmp_path):
    """A valid low-charge request cannot spend a permit after voltage falls during speech."""
    from types import MethodType, SimpleNamespace
    from unittest.mock import AsyncMock, Mock, sentinel

    from desk_robot import controller

    robot_id = "robot-01"
    robot = SimpleNamespace(
        autonomous_low_battery_dock_enabled=True,
        motion_enabled=True,
        dock_motion_qualified=True,
        dock_turn_sign=1,
        dock_forward_sign=1,
        dock_beacon_id=1,
        dock_calibration=tmp_path / "calibration.json",
        motor_backend="dc_pwm_guarded",
        battery_low_percent=20,
    )
    monkeypatch.setattr(controller, "load_real_dock_calibration", Mock())
    for cell_mv in (3349, 3350):
        power = {
            "fuel_valid": True, "cell_mv": 3650, "soc_centi": 1800,
            "fuel_seq": 1, "fuel_age_ms": 10,
        }
        head = SimpleNamespace(status=AsyncMock(return_value={
            "robot_id": robot_id, "backend": robot.motor_backend, "armed": False,
            "touch": {"active": False},
            "safety": {"required": True, "ready": True, "fault": "none"},
            "imu": {"family": 4, "valid": True, "age_ms": 10,
                    "acc": [0, 0, 16384], "gyro": [0, 0, 0]},
            "ranges": {"present_mask": 31, "valid_mask": 31,
                       "mm": [50, 50, 50, 50, 600], "age_ms": [5] * 5},
            "power": power,
        }), command=AsyncMock())
        coord = SimpleNamespace(
            robot=Mock(return_value=robot),
            settings=SimpleNamespace(
                camera_consent_generation=1, mode="hardware", voice_vision_tools_enabled=True,
            ),
            heads={robot_id: head},
            dock_inhibited=Mock(return_value=False),
            tasks={},
            voice_blocks_motion=Mock(return_value="human voice active"),
            permits={},
            closed=False,
            _permit_epoch={robot_id: 0},
            _robot_busy=Mock(return_value=False),
            _stop_confirmations=SimpleNamespace(blocked=Mock(return_value=False)),
            dock=Mock(return_value=sentinel.dock_job),
        )
        for name in ("_record_local_fault", "_hardware_preflight", "_retire_permit",
                     "operator_arm", "request_autonomous_low_battery_dock"):
            setattr(coord, name, MethodType(getattr(controller.Coordinator, name), coord))
        assert await coord.request_autonomous_low_battery_dock(robot_id) is None
        head.status.assert_not_awaited()
        coord.dock.assert_not_called()
        assert not coord.permits
        initial, expires_at, grant = coord._deferred_autonomous_dock.pop(robot_id)

        # Re-enter the same request with the original expiry and consent, as the
        # deferred dispatcher does. Only the new head receipt may grant motion.
        power.update(cell_mv=cell_mv, fuel_seq=2)
        coord.voice_blocks_motion.return_value = None
        result = await coord.request_autonomous_low_battery_dock(
            robot_id, initial_low=initial, _expires_at=expires_at, _camera_grant=grant,
        )
        head.status.assert_awaited_once()
        head.command.assert_not_awaited()
        if cell_mv < 3350:
            assert result is None
            coord.dock.assert_not_called()
            assert not coord.permits
        else:
            assert result is sentinel.dock_job
            coord.dock.assert_called_once_with(robot_id)
            assert robot_id in coord.permits
