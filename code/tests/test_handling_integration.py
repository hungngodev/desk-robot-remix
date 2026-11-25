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
    async def run_sequence(qualified: bool):
        settings = load_settings(
            Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
        )
        settings.mode = "hardware"
        settings.robots[0].handling_interactions_qualified = qualified
        memory = MemoryStore(tmp_path / f"q_{qualified}", [robot.id for robot in settings.robots])
        conversation = Conversation(settings, NoneChat(), SimulatedSpeaker(), memory=memory)
        pet = PetController(settings, {}, conversation, memory, NoneVision())
        seen = []

        class Events:
            def notify(self, robot_id, kind, at):
                seen.append((robot_id, kind))

            def clear(self, robot_id):
                assert robot_id in {r.id for r in settings.robots}

            def discard_video(self, robot_id):
                assert robot_id in {r.id for r in settings.robots}

        pet.multimodal = SimpleNamespace(hub=Events())
        state = pet.states["robot-01"]
        state.enabled = True
        state.generation = 3
        state.quiet = True
        try:
            for _ in range(8):
                await pet._observe_imu("robot-01", 3, status())
            for _ in range(2):
                await pet._observe_imu("robot-01", 3, status(acc=(12551, 0, 10531)))
            return (
                state.handling_gate.reference,
                state.handling_events,
                memory.count("robot-01"),
                seen,
                pet.status("robot-01")["motor_control_enabled_by_pet"],
            )
        finally:
            await pet.close()

    ref_unq, events_unq, mem_unq, seen_unq, motor_unq = await run_sequence(False)
    assert ref_unq is None
    assert events_unq == 0
    assert mem_unq == 0
    assert seen_unq == []
    assert motor_unq is False

    ref_q, events_q, mem_q, seen_q, motor_q = await run_sequence(True)
    assert ref_q is not None
    assert events_q == 1
    assert mem_q == 1
    assert seen_q == [("robot-01", "handling_tilt")]
    assert motor_q is False

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


async def test_drx062_fault_handling_discrimination_in_active_dialogue_without_memory(
    tmp_path,
):
    """Typed fault cause, upright lift candidate, single cliff, tilt and putdown stay distinct."""
    from desk_robot.attention import AttentionLedger
    from desk_robot.brain_context import compose_brain_context
    from desk_robot.multimodal import CameraFrameHub

    settings = load_settings(
        Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    )
    settings.mode = "hardware"
    settings.voice_memory_tools_enabled = False
    settings.robots[0].handling_interactions_qualified = True
    memory = MemoryStore(tmp_path, [r.id for r in settings.robots])
    speaker = SimulatedSpeaker()
    conversation = Conversation(settings, NoneChat(), speaker, memory=memory)
    stopped = []

    async def on_fault(rid):
        stopped.append(rid)

    pet = PetController(
        settings, {}, conversation, memory, NoneVision(), on_local_fault=on_fault,
    )
    ids = [r.id for r in settings.robots]
    hub = CameraFrameHub(ids)
    attention = AttentionLedger(ids)
    pet.multimodal = SimpleNamespace(hub=hub)
    pet.attention = attention
    state = pet.states["robot-01"]
    state.enabled = True
    state.generation = 12
    state.quiet = False

    def render_live():
        now = __import__("time").monotonic()
        tl = hub.interaction_timeline("robot-01", now, limit=10)
        tl.extend(attention.timeline("robot-01", now))
        return compose_brain_context([], [], tl).interaction

    try:
        # Establish upright calibrated IMU baseline & healthy WROOM baseline.
        for _ in range(8):
            await pet._observe_imu("robot-01", 12, status())
        await pet._observe_body_safety("robot-01", 12, {
            "safety": {"required": True, "ready": True, "fault": "none"},
        })
        import time as _time
        attention.begin_topic("robot-01", "Planning lunch recipes", _time.monotonic())

        # 1. Slow upright lift candidate: multi-cliff floor loss + upright qualified IMU.
        await pet._observe_body_safety("robot-01", 12, {
            "safety": {"required": True, "ready": False, "fault": "floor_out_of_range", "sensor": 0},
            "ranges": {"valid_mask": 0x10, "mm": [260, 260, 260, 260, 500]},
            "imu": {"valid": True, "age_ms": 20, "acc": [0, 0, 16384]},
        })
        lift_ctx = render_live()
        assert "floor_out_of_range_upright_lift" in lift_ctx
        assert "Planning lunch recipes" in lift_ctx
        assert len(lift_ctx) <= 400

        # 5. Stable putdown recovery: emits context without motor rearm or forced TTS.
        await pet._observe_body_safety("robot-01", 12, {
            "safety": {"required": True, "ready": True, "fault": "none"},
        })
        putdown_ctx = render_live()
        assert "stable_putdown" in putdown_ctx
        assert "not current telemetry" in putdown_ctx
        assert "do not drive, reverse, rearm" in putdown_ctx

        # 3. Ordinary single cliff channel (other 3 cliff channels see floor).
        await pet._observe_body_safety("robot-01", 12, {
            "safety": {"required": True, "ready": False, "fault": "floor_out_of_range", "sensor": 2},
            "ranges": {"valid_mask": 0x1f, "mm": [50, 50, 260, 50, 500]},
            "imu": {"valid": True, "age_ms": 20, "acc": [0, 0, 16384]},
        })
        single_ctx = render_live()
        assert "floor_out_of_range_ch2" in single_ctx
        assert single_ctx != lift_ctx

        # 4. Noisy / invalid safety frame ignored cleanly.
        before_events = state.safety_fault_events
        await pet._observe_body_safety("robot-01", 12, {
            "safety": {"required": True, "ready": "bad", "fault": "floor_out_of_range"},
        })
        await pet._observe_body_safety("robot-01", 12, {
            "safety": {"required": True, "ready": False, "fault": "BAD!"},
        })
        assert state.safety_fault_events == before_events

        # 2. Sustained tilt alone via IMU produces distinct handling_tilt cue.
        for _ in range(2):
            await pet._observe_imu("robot-01", 12, status(acc=(12551, 0, 10531)))
        tilt_ctx = render_live()
        assert "handling_tilt" in tilt_ctx
        assert "upright_lift" in lift_ctx
        assert speaker.spoken == []
        assert pet.status("robot-01")["motor_control_enabled_by_pet"] is False
    finally:
        state.enabled = False
        await pet.close()

