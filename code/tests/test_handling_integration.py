"""One real WROOM MPU6050 frame path through Mac pet and private memory."""
import asyncio
from itertools import count
from pathlib import Path
from types import SimpleNamespace

from desk_robot.config import load_settings
from desk_robot.conversation import Conversation
from desk_robot.memory import MemoryStore
from desk_robot.pet import PetController
from desk_robot.simulator import SimulatedSpeaker

_IMU_FRAMES = count(1)


def status(acc=(0, 0, 16384), gyro=(0, 0, 0)):
    return {
        "left": 0, "right": 0, "drive_ms": 0,
        "imu": {
            "family": 4, "gyro_id": 0x68, "aux_id": 0,
            "valid": True, "age_ms": 30,
            "boot_id": 1, "sample_ms": next(_IMU_FRAMES) * 50,
            "acc": list(acc), "gyro": list(gyro),
        },
    }


class NoneChat:
    async def reply(self, history):
        raise AssertionError("Quiet handling test must never call LLM")


class NoneVision:
    async def compare(self, before, after):
        raise AssertionError("No camera image was manufactured for an IMU event")


async def test_qualified_real_wroom_imu_tilt_reaches_only_own_memory(tmp_path):
    settings = load_settings(
        Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    )
    settings.mode = "hardware"
    settings.robots[0].handling_interactions_qualified = True
    memory = MemoryStore(tmp_path, [robot.id for robot in settings.robots])
    conversation = Conversation(settings, NoneChat(), SimulatedSpeaker(), memory=memory)
    pet = PetController(settings, {}, conversation, memory, NoneVision())
    seen = []

    class Events:
        def notify(self, robot_id, kind, at):
            seen.append((robot_id, kind))

        def clear(self, robot_id):
            assert robot_id in {r.id for r in settings.robots}

        def discard_video(self, robot_id):
            # Pet cleanup always clears transient camera evidence. This
            # sensor-only test hub has no stored images but must honor the
            # same identity-scoped invalidation contract.
            assert robot_id in {r.id for r in settings.robots}

    pet.multimodal = SimpleNamespace(hub=Events())
    state = pet.states["robot-01"]
    state.enabled = True
    state.generation = 8
    state.quiet = True
    try:
        for _ in range(8):
            frame = status()
            await pet._observe_imu("robot-01", 8, frame)
            await pet._observe_imu("robot-01", 8, frame)
        # Duplicate HTTP observations of one hardware conversion are ignored.
        assert memory.count("robot-01") == 0
        for _ in range(2):
            frame = status(acc=(12551, 0, 10531))
            await pet._observe_imu("robot-01", 8, frame)
            await pet._observe_imu("robot-01", 8, frame)
        records = memory.recent("robot-01")
        assert [r.kind for r in records] == ["handling_tilt"]
        assert records[0].source_robot == "robot-01"
        assert records[0].witnessed is True
        assert state.handling_events == 1
        assert seen == [("robot-01", "handling_tilt")]
        assert all(memory.count(r.id) == 0 for r in settings.robots[1:])
        # Repeated same pose cannot create more memory events.
        for _ in range(6):
            await pet._observe_imu("robot-01", 8, status(acc=(12551, 0, 10531)))
        assert memory.count("robot-01") == 1
        state.enabled = False
        for _ in range(4):
            await pet._observe_imu("robot-01", 8, status())
        assert memory.count("robot-01") == 1
    finally:
        await pet.close()


async def test_unqualified_imu_never_creates_physical_fact_or_camera_trigger(tmp_path):
    settings = load_settings(
        Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    )
    settings.mode = "hardware"
    memory = MemoryStore(tmp_path, [robot.id for robot in settings.robots])
    conversation = Conversation(settings, NoneChat(), SimulatedSpeaker(), memory=memory)
    pet = PetController(settings, {}, conversation, memory, NoneVision())
    state = pet.states["robot-01"]
    state.enabled = True
    state.generation = 3
    try:
        for _ in range(15):
            await pet._observe_imu("robot-01", 3, status(acc=(16000, 0, 0)))
        assert state.handling_events == 0
        assert memory.count("robot-01") == 0
        assert pet.status("robot-01")["motor_control_enabled_by_pet"] is False
    finally:
        await pet.close()

async def test_body_poll_counts_transport_age_before_handling_memory(tmp_path):
    settings = load_settings(
        Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    )
    settings.mode = "hardware"
    settings.robots[0].handling_interactions_qualified = True
    memory = MemoryStore(tmp_path, [robot.id for robot in settings.robots])
    conversation = Conversation(settings, NoneChat(), SimulatedSpeaker(), memory=memory)
    frame = status()
    delay = 0.0

    async def read_body():
        if delay:
            await asyncio.sleep(delay)
        return frame

    pet = PetController(
        settings, {"robot-01": SimpleNamespace(status=read_body)},
        conversation, memory, NoneVision(),
    )
    state = pet.states["robot-01"]
    state.enabled = True
    state.generation = 9
    state.quiet = True

    def body(acc=(0, 0, 16384)):
        data = status(acc=acc)
        data["robot_id"] = "robot-01"
        data["motor"] = {"m0": data.pop("left"), "m1": data.pop("right")}
        return data

    try:
        for _ in range(8):
            frame = body()
            await pet._touch_from_body("robot-01", 9)
        assert state.handling_gate.reference is not None
        frame = body(acc=(12551, 0, 10531))
        await pet._touch_from_body("robot-01", 9)
        frame = body(acc=(12551, 0, 10531))
        delay = 0.22  # 30ms firmware age + 220ms delivery exceeds 200ms.
        await pet._touch_from_body("robot-01", 9)
        assert state.handling_gate.reference is None
        assert state.handling_events == 0
        assert memory.count("robot-01") == 0
        # Fresh transport must still support the real poll path.
        delay = 0.0
        for _ in range(8):
            frame = body()
            await pet._touch_from_body("robot-01", 9)
        for _ in range(2):
            frame = body(acc=(12551, 0, 10531))
            await pet._touch_from_body("robot-01", 9)
        assert [r.kind for r in memory.recent("robot-01")] == ["handling_tilt"]
        assert state.handling_events == 1
    finally:
        await pet.close()

