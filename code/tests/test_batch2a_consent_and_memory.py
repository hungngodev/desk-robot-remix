"""Focused unit regressions for remaining Batch 2A fixes."""
from __future__ import annotations

import asyncio
import sqlite3
import time
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from desk_robot.api import create_app
from desk_robot.api_readonly_planner import _PlanContext, _revalidate_context
from desk_robot.aux import validate_aux
from desk_robot.config import RobotConfig, Settings
from desk_robot.controller import Coordinator
from desk_robot.conversation import Conversation
from desk_robot.conversation_consent import GroupContextConsent
from desk_robot.dock_runtime import load_real_dock_calibration
from desk_robot.memory import MemoryStore
from desk_robot.multimodal import CameraEvidence, MultimodalOrchestrator
from desk_robot.observation_policy import prepare_camera_receipt
from desk_robot.operations import OperationError
from desk_robot.pet import PetController
from desk_robot.simulator import (
    SimulatedChat,
    SimulatedHead,
    SimulatedScene,
    SimulatedSpeaker,
    SimulationVision,
)
from desk_robot.vision import SceneChange
from fastapi.testclient import TestClient
from PIL import Image


def _robots(count: int = 2) -> list[RobotConfig]:
    return [
        RobotConfig(
            id=f"robot-0{i}",
            name=f"Pet {i}",
            head_url=f"http://127.0.0.{i}:8001",
            token_env=f"DESK_ROBOT_HEAD_{i}_TOKEN",
            device_id=f"head0{i}",
            voice=f"af_heart_{i}",
        )
        for i in range(1, count + 1)
    ]


def _tiny_jpeg() -> bytes:
    buf = BytesIO()
    img = Image.new("RGB", (64, 48), "white")
    for x in range(10, 40):
        for y in range(10, 35):
            img.putpixel((x, y), (20, 40, 80))
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_camera_evidence_repr_omits_jpeg_payload():
    ev = CameraEvidence(
        jpeg=b"\xff\xd8SECRET\xff\xd9",
        received_at=1.0,
        motion_fraction=0.1,
        source="proactive",
    )
    assert b"SECRET" in ev.jpeg
    rendered = repr(ev)
    assert "SECRET" not in rendered
    assert "jpeg=" not in rendered


@pytest.mark.asyncio
async def test_nfc_qualified_gate_excludes_unqualified_nfc_from_context():
    settings = Settings(mode="simulation", robots=_robots(1))
    robot_id = settings.robots[0].id
    assert settings.robot(robot_id).nfc_interactions_qualified is False

    pet = PetController.__new__(PetController)
    pet.settings = settings
    pet._proactive_aux_cursors = {}
    pet._proactive_aux_active_boot = {}
    pet._proactive_aux_retired_boots = {}
    pet.heads = {
        robot_id: SimpleNamespace(
            aux_status=AsyncMock(return_value={
                "robot_id": robot_id,
                "force": {
                    "adc": [100, 100], "valid": False, "calibrated": False,
                    "jaw_seq": 1, "boot_id": 1,
                },
                "proximity": {
                    "raw": 10, "valid": False, "gesture": 0,
                    "gesture_events": 0, "boot_id": 1, "physically_qualified": False,
                },
                "climate": {
                    "temp_centi": 2300, "rh_centi": 4500, "valid": True,
                    "seq": 10, "age_ms": 10,
                },
                "nfc": {"v": True, "e": 5, "s": 2, "t": 0xAABB},
                "power": {
                    "fuel_valid": True, "fuel_seq": 10, "fuel_age_ms": 10,
                    "cell_mv": 3900, "soc_centi": 8000,
                },
            })
        )
    }
    receipt = await pet._proactive_tool_receipt(robot_id, "aux_status")
    assert "nfc" not in receipt["data"]
    assert "fuel_gauge" in receipt["data"]

    settings.robots[0].nfc_interactions_qualified = True
    receipt_enabled = await pet._proactive_tool_receipt(robot_id, "aux_status")
    assert receipt_enabled["data"]["nfc"] == {"event_count": 5}


def test_social_autonomy_revoke_and_regrant_cannot_revive_queued_speech():
    settings = Settings(
        mode="simulation",
        robots=_robots(2),
        fleet_text_sharing_enabled=True,
        fleet_social_autonomy_enabled=True,
    )
    pet = PetController.__new__(PetController)
    pet.settings = settings
    pet._closed = False
    pet.voice_monitor_ready = True
    pet.max_observation_age = 30.0
    pet._speech_task = None
    pet._speech_participants = frozenset()
    pet.multimodal = None
    pet.coordinator_jobs = None
    pet._states = {
        r.id: SimpleNamespace(
            enabled=True, generation=1, quiet=False, quiet_changed_at=0.0,
            last_social_fault_at=0.0, dock_guard=SimpleNamespace(inhibited=False),
            dock_seated=False, dock_contact_present=False, dock_input_good=False,
            dock_charge_indicated=False, last_battery_low=False, suppressed=0,
            last_initiative_suppression=None,
        )
        for r in settings.robots
    }
    pet.is_quiet = lambda _rid: False
    pet._human_active_in_fleet = lambda _now: False
    pet._camera_generation_current = lambda _rid, _g: True
    pet._social_safety_clear = lambda _rid: True

    seen_permission = []

    async def fake_run(*_args, permission_check=None, **_kwargs):
        seen_permission.append(permission_check())
        settings.fleet_social_autonomy_enabled = False
        settings.fleet_social_autonomy_enabled = True
        seen_permission.append(permission_check())
        return []

    pet.conversation = SimpleNamespace(run=fake_run)
    pet.memory = None
    asyncio.run(pet._speak_social(
        settings.robots[0].id, SceneChange("key", "A brass key appeared", 0.9), 1,
        offered_at=time.monotonic(),
        social_peer_id=settings.robots[1].id, social_peer_generation=1,
        camera_derived=False, newer_human_turn=lambda: False,
    ))
    assert seen_permission == [True, False]


def test_low_battery_and_dock_inhibit_veto_scheduled_activity_and_speech():
    settings = Settings(mode="simulation", robots=_robots(1))
    robot_id = settings.robots[0].id
    pet = PetController.__new__(PetController)
    pet.settings = settings
    pet._group_last_spoken = -float("inf")
    pet.speech_cooldown = 120.0
    pet._states = {
        robot_id: SimpleNamespace(
            last_battery_low=True,
            dock_guard=SimpleNamespace(inhibited=False),
            dock_seated=False, dock_contact_present=False,
            dock_input_good=False, dock_charge_indicated=False,
        )
    }
    pet.is_quiet = lambda _rid: False
    assert pet._activity_local_veto(robot_id, 100.0) == "battery_low"
    pet._states[robot_id].last_battery_low = False
    assert pet._activity_local_veto(robot_id, 100.0) is None


@pytest.mark.asyncio
async def test_person_oled_cue_suppressed_under_quiet_mode():
    settings = Settings(mode="hardware", robots=_robots(1), voice_vision_tools_enabled=True)
    robot_id = settings.robots[0].id
    pet = PetController.__new__(PetController)
    pet.settings = settings
    pet._closed = False
    pet.max_observation_age = 30.0
    pet._vision_preemption_epoch = 1
    face_mock = AsyncMock()
    pet.heads = {robot_id: SimpleNamespace(face_event=face_mock)}
    pet._states = {
        robot_id: SimpleNamespace(
            enabled=True, generation=1, quiet=True, quiet_changed_at=0.0,
            last_person_face_cue_at=0.0, last_person_face_attempt_at=0.0,
        )
    }
    pet._camera_generation_current = lambda _rid, _g: True
    pet._human_active_in_fleet = lambda _now: False
    pet._quiet_hours_active = lambda: False
    pet.is_quiet = lambda rid: pet._states[rid].quiet

    await pet._cue_person_face(
        robot_id, SceneChange("person", "Someone walked by", 0.95), 1, time.monotonic(), 1,
    )
    face_mock.assert_not_called()


def test_scheduled_quiet_blocks_exploration_and_narrows_stop_event(monkeypatch):
    monkeypatch.setenv("DESK_ROBOT_API_TOKEN", "op-secret-" + "x" * 24)
    monkeypatch.setenv("DESK_ROBOT_TOOL_TOKEN", "tool-secret-" + "y" * 24)
    robots = _robots(1)
    robots[0].motion_enabled = True
    settings = Settings(
        mode="simulation",
        robots=robots,
        pet_quiet_hours=("00:00", "23:59"),
    )
    app = create_app(settings)
    monkeypatch.setattr("desk_robot.config.quiet_hours_active", lambda *_args, **_kwargs: True)
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {app.state.operator_token}"}
        res = client.post("/v1/robots/robot-01/explore", headers=headers)
        assert res.status_code == 409
        assert "Quiet mode" in res.text

    heads = {r.id: SimulatedHead(r.id) for r in settings.robots}
    coord = Coordinator(settings, heads, SimulationVision())
    coord.is_quiet = lambda _rid: True
    with pytest.raises(OperationError, match="quiet mode active"):
        coord.explore("robot-01")


def test_tool_stop_preserves_fleet_latch_while_operator_stop_recovers(monkeypatch):
    monkeypatch.setenv("DESK_ROBOT_API_TOKEN", "op-secret-" + "x" * 24)
    monkeypatch.setenv("DESK_ROBOT_TOOL_TOKEN", "tool-secret-" + "y" * 24)
    settings = Settings(mode="simulation", robots=_robots(1))
    app = create_app(settings)
    with TestClient(app) as client:
        coord = app.state.runtime.coordinator
        coord._fleet_motion_owner = "latched-job"
        coord.jobs["latched-job"] = SimpleNamespace(id="latched-job", robot_id="robot-01")
        task = Mock(done=lambda: True)
        coord.tasks["latched-job"] = task
        coord._motion_children["latched-job"] = ()

        tool_headers = {"Authorization": f"Bearer {app.state.tool_token}"}
        op_headers = {"Authorization": f"Bearer {app.state.operator_token}"}

        assert client.post("/v1/pet/robot-01/pause", headers=tool_headers).status_code == 200
        assert coord._fleet_motion_owner == "latched-job"
        assert client.post("/v1/robots/robot-01/stop", headers=tool_headers).status_code == 200
        assert coord._fleet_motion_owner == "latched-job"

        assert client.post("/v1/robots/robot-01/stop", headers=op_headers).status_code == 200
        assert coord._fleet_motion_owner is None


def test_dock_marker_mismatch_rejected_before_any_drive(tmp_path):
    calib_path = tmp_path / "dock_cal.json"
    calib_path.write_text(
        '{"schema_version":1,"measured":true,"robot_id":"robot-01",'
        '"head_device_id":"head01","fx":400,"fy":400,"cx":320,"cy":240,'
        '"tag_side_mm":60,"marker_id":99,"distortion_coeffs":[0,0,0,0,0],'
        '"image_width_px":640,"image_height_px":480,"camera_sensor_pid":"OV5640",'
        '"mount_lateral_offset_mm":0,"mount_yaw_deg":0,"mount_forward_offset_mm":10,'
        '"target_distance_mm":150}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="assigned robot dock marker"):
        load_real_dock_calibration(
            calib_path, robot_id="robot-01", head_device_id="head01", expected_marker_id=12,
        )
    cal, dist = load_real_dock_calibration(
        calib_path, robot_id="robot-01", head_device_id="head01", expected_marker_id=99,
    )
    assert cal.marker_id == 99 and dist == 150.0


def test_memory_upgrade_migrates_old_episode_mutations_into_replay_fence(tmp_path):
    db_file = tmp_path / "robot-01.sqlite3"
    conn = sqlite3.connect(db_file)
    conn.execute(
        "CREATE TABLE memories(event_id TEXT PRIMARY KEY, source_robot TEXT NOT NULL,"
        " witnessed INTEGER NOT NULL, kind TEXT NOT NULL, summary TEXT NOT NULL,"
        " observed_at REAL NOT NULL, confidence REAL NOT NULL, relay_token TEXT)"
    )
    conn.execute(
        "CREATE TABLE memory_identity("
        "singleton INTEGER PRIMARY KEY CHECK(singleton=1), robot_id TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO memory_identity VALUES (1, 'robot-01')")
    conn.execute("CREATE TABLE deleted_episode_ids(event_id TEXT PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE deletion_fence_guard("
        "singleton INTEGER PRIMARY KEY CHECK(singleton=1), writes_sealed INTEGER NOT NULL)"
    )
    conn.execute("INSERT INTO deletion_fence_guard VALUES (1, 0)")
    conn.execute(
        "CREATE TABLE episode_mutations("
        "event_id TEXT PRIMARY KEY, generation INTEGER NOT NULL)"
    )
    conn.execute("INSERT INTO episode_mutations VALUES ('old-evicted-corr-1', 2)")
    conn.commit()
    conn.close()
    db_file.chmod(0o600)

    store = MemoryStore(tmp_path, ["robot-01"])
    assert store.remember(
        "robot-01", "old-evicted-corr-1", "stale summary",
        kind="key", source_robot="robot-01", witnessed=True, observed_at=1.0, confidence=0.9,
    ) is False


def test_room_freshness_and_epoch_fence_in_conversation_and_planner():
    settings = Settings(
        mode="hardware", robots=_robots(1),
        room_station_enabled=True, room_station_port="/dev/cu.usbserial-1",
        room_station_context_enabled=True,
    )
    fence = GroupContextConsent.capture(settings, has_multimodal=False)
    fence.admit_room(received_at=100.0, connection_epoch=1)
    assert not fence.revoked(private_memory_current=True, now=110.0, current_room_epoch=1)
    assert fence.revoked(private_memory_current=True, now=113.0, current_room_epoch=1)
    assert fence.revoked(private_memory_current=True, now=110.0, current_room_epoch=2)

    snap = _PlanContext(
        visual=None, turn_at_request=None,
        camera_context_used=False, camera_consent_generation=0, camera_granted_at_request=False,
        room_context_used=True, room_consent_generation=0,
        memory_granted_at_request=False, memory_consent_generation=0,
        context="", room_received_at=time.monotonic() - 20.0, room_connection_epoch=1,
    )
    app = SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(
        multimodal=SimpleNamespace(hub=SimpleNamespace(_room_connection_epoch=1)),
    )))
    with pytest.raises(Exception, match="expired"):
        _revalidate_context(app, settings, "robot-01", snap)


@pytest.mark.asyncio
async def test_camera_opt_out_cancels_inflight_look_and_prevents_stale_reply():
    settings = Settings(
        mode="hardware",
        robots=_robots(1),
        voice_vision_tools_enabled=True,
        vision_model="llava:test",
    )
    entered = asyncio.Event()
    gate = asyncio.Event()

    class BlockingScene:
        async def answer(self, _question, _images, **_kwargs):
            entered.set()
            await gate.wait()
            return "stale answer"

    heads = {r.id: SimulatedHead(r.id) for r in settings.robots}
    orch = MultimodalOrchestrator(settings, heads, BlockingScene(), asyncio.Lock())
    settings.register_camera_revocation(orch._camera_revoked)
    try:
        orch.hub.offer(
            settings.robots[0].id, _tiny_jpeg(),
            received_at=time.monotonic(), source="proactive",
        )
        task = asyncio.create_task(orch.look(settings.robots[0].id, "What is on the desk?"))
        await asyncio.wait_for(entered.wait(), timeout=1.0)
        settings.voice_vision_tools_enabled = False
        settings.voice_vision_tools_enabled = True
        with pytest.raises(RuntimeError, match="Camera consent revoked"):
            await asyncio.wait_for(task, timeout=1.0)
    finally:
        gate.set()
        await orch.close()


@pytest.mark.asyncio
async def test_invalid_gauge_cell_mv_stays_diagnostic_and_preserves_siblings():
    aux = validate_aux({
        "robot_id": "robot-01",
        "pulse": {
            "present": False, "valid": False, "part_id": 0x15, "red": 0, "ir": 0,
            "age_ms": 0, "bpm": None, "medical": False,
        },
        "angles": {"present_mask": 0, "valid_mask": 0, "raw": [0, 0, 0], "magnet": [0, 0, 0]},
        "force": {
            "adc": [100, 100], "valid": False, "calibrated": False,
            "jaw_seq": 1, "boot_id": 1,
        },
        "proximity": {
            "raw": 10, "valid": False, "gesture": 0, "gesture_events": 0,
            "boot_id": 1, "physically_qualified": False,
        },
        "power": {
            "cell_mv": 1200, "soc_centi": 0, "bus_mv": 4000, "shunt_uv": 0,
            "fuel_valid": False, "monitor_valid": True, "current_calibrated": False,
            "fuel_seq": 0, "fuel_age_ms": 10,
        },
        "climate": {"temp_centi": 2300, "rh_centi": 4500, "valid": True, "seq": 1, "age_ms": 10},
    }, "robot-01")
    assert aux["power"]["cell_mv"] == 1200 and aux["power"]["fuel_valid"] is False
    assert aux["climate"]["temp_centi"] == 2300

    settings = Settings(mode="simulation", robots=_robots(1))
    pet = PetController.__new__(PetController)
    pet.settings = settings
    pet._proactive_aux_cursors = {}
    pet._proactive_aux_active_boot = {}
    pet._proactive_aux_retired_boots = {}
    pet.heads = {"robot-01": SimpleNamespace(aux_status=AsyncMock(return_value=aux))}
    receipt = await pet._proactive_tool_receipt("robot-01", "aux_status")
    assert "fuel_gauge" not in receipt["data"]
    assert receipt["data"]["sht41"]["temp_centi"] == 2300


def test_fleet_cooldowns_survive_controller_restart(tmp_path):
    mem_dir = tmp_path / "mem"
    mem_dir.mkdir(mode=0o700)
    settings = Settings(mode="hardware", robots=_robots(2), memory_dir=mem_dir)
    heads = {r.id: SimulatedHead(r.id) for r in settings.robots}
    chat = SimulatedChat()
    speaker = SimulatedSpeaker()
    store = MemoryStore(mem_dir, [r.id for r in settings.robots])
    conv = Conversation(settings, chat, speaker, memory=store)
    p1 = PetController(settings, heads, conv, store, SimulatedScene())
    now = time.monotonic()
    p1._group_last_spoken = now - 5.0
    p1._social_last_started = now - 10.0
    p1._persist_fleet_cooldowns()

    p2 = PetController(settings, heads, conv, store, SimulatedScene())
    now2 = time.monotonic()
    assert 0 <= now2 - p2._group_last_spoken < 15.0
    assert 0 <= now2 - p2._social_last_started < 20.0


def test_clock_step_between_completions_preserves_receipt_chronology():
    r1 = prepare_camera_receipt(
        robot_id="robot-01", event_id="e1", wall_now=2000.0,
        monotonic_now=100.0, received_at=95.0, max_age=20.0,
        source_identity=None, receipt_wall_at=1500.0,
    )
    r2 = prepare_camera_receipt(
        robot_id="robot-01", event_id="e2", wall_now=1400.0,
        monotonic_now=105.0, received_at=99.0, max_age=20.0,
        source_identity=None, receipt_wall_at=1504.0,
    )
    assert r1 is not None and r2 is not None
    assert r1[1] < r2[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("mode", ["fresh", "expired", "usb_invalidated"])
async def test_conversation_run_blocks_expired_or_usb_invalidated_room_speech(
    monkeypatch, tmp_path, streaming, mode,
):
    from desk_robot import conversation as conv_mod
    from desk_robot.multimodal import CameraFrameHub
    from desk_robot.room_station import RoomObservation

    now = [1000.0]
    monkeypatch.setattr(conv_mod.time, "monotonic", lambda: now[0])

    settings = Settings(
        mode="hardware",
        robots=_robots(2),
        fleet_text_sharing_enabled=True,
        room_station_enabled=True,
        room_station_port="/dev/cu.usbserial-1",
        room_station_context_enabled=True,
    )
    ids = ["robot-01", "robot-02"]
    hub = CameraFrameHub(ids, room_settings=settings)
    hub.remember_room(RoomObservation(
        seq=1, at_ms=100, received_at=1000.0, readings={},
        summary="Unique reading 742 ppm",
    ))

    class Chat:
        async def reply(self, _history):
            if mode == "expired":
                now[0] = 1013.0
            elif mode == "usb_invalidated":
                hub.invalidate_room()
            return "Current reading is 742 ppm."

    if streaming:
        async def stream_reply(_history):
            if mode == "expired":
                now[0] = 1013.0
            elif mode == "usb_invalidated":
                hub.invalidate_room()
            yield "Current reading is 742 ppm."

        chat = Chat()
        chat.stream_reply = stream_reply
    else:
        chat = Chat()

    speaker = SimulatedSpeaker()
    mem = MemoryStore(tmp_path / "mem", ids)
    conv = Conversation(settings, chat, speaker, memory=mem)
    conv.multimodal = SimpleNamespace(hub=hub)
    if mode == "fresh":
        transcript = await conv.run(ids, "Check room", 1)
        assert len(transcript) == 1 and len(speaker.spoken) == 1
    else:
        with pytest.raises(RuntimeError, match="revoked"):
            await conv.run(ids, "Check room", 1)
        assert speaker.spoken == []


@pytest.mark.asyncio
async def test_camera_off_on_blocks_regranted_vlm_overlap_until_revoked_call_exits():
    """Cancellation-resistant VLM call holds the sole slot across OFF->ON until it settles."""
    settings = Settings(
        mode="hardware",
        robots=_robots(1),
        voice_vision_tools_enabled=True,
        vision_model="llava:test",
    )
    entered_first = asyncio.Event()
    cancelled_first = asyncio.Event()
    release_first = asyncio.Event()
    active_calls = 0
    max_concurrent = 0

    class StubbornScene:
        async def answer(self, question, _images, **_kwargs):
            nonlocal active_calls, max_concurrent
            active_calls += 1
            max_concurrent = max(max_concurrent, active_calls)
            try:
                if question == "First question":
                    entered_first.set()
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        cancelled_first.set()
                        await release_first.wait()
                        return "stale uncooperative answer"
                return "fresh authorized answer"
            finally:
                active_calls -= 1

    robot_id = settings.robots[0].id
    heads = {r.id: SimulatedHead(r.id) for r in settings.robots}
    orch = MultimodalOrchestrator(settings, heads, StubbornScene(), asyncio.Lock())
    try:
        orch.hub.offer(
            robot_id, _tiny_jpeg(), received_at=time.monotonic(), source="proactive",
        )
        first_look = asyncio.create_task(orch.look(robot_id, "First question"))
        await asyncio.wait_for(entered_first.wait(), timeout=1.0)

        # Revoke consent and immediately opt back in while first VLM task resists cancel.
        settings.voice_vision_tools_enabled = False
        await asyncio.wait_for(cancelled_first.wait(), timeout=1.0)
        with pytest.raises(RuntimeError, match="Camera consent revoked"):
            await asyncio.wait_for(first_look, timeout=1.0)

        settings.voice_vision_tools_enabled = True
        orch.hub.offer(
            robot_id, _tiny_jpeg(), received_at=time.monotonic(), source="proactive",
        )
        # Regranted query must not overlap the still-running pre-revocation VLM call.
        with pytest.raises(RuntimeError, match="unfinished revoked call"):
            await orch.look(robot_id, "Second question while blocked")
        assert max_concurrent == 1
        assert orch.hub.recent_tool_context(robot_id, time.monotonic()) == []

        # Once the pre-revocation call settles locally, a newly authorized query succeeds.
        release_first.set()
        await asyncio.sleep(0.02)
        result = await orch.look(robot_id, "Third question after settlement")
        assert result["answer"] == "fresh authorized answer"
        assert max_concurrent == 1
    finally:
        release_first.set()
        await orch.close()
