"""Guide 90 end-to-end cross-layer integration replays for spatial navigation and recall."""

from __future__ import annotations

import asyncio
import time
from io import BytesIO

import pytest
from desk_robot.api import create_app
from desk_robot.controller import OperationError
from desk_robot.memory import CameraProvenance
from desk_robot.object_search import SearchViewpoint
from desk_robot.object_targets import ObjectEvidence
from desk_robot.route_planner import SafetyEnvelope
from desk_robot.spatial_grid import RangeCellBatch
from desk_robot.spatial_memory import SpatialEvidence
from desk_robot.vision import Detection
from fastapi.testclient import TestClient
from PIL import Image


def _valid_jpeg() -> bytes:
    output = BytesIO()
    Image.new("RGB", (640, 480)).save(output, format="JPEG")
    return output.getvalue()


class SpatialHead:
    """Fake WROOM + Sense head providing bounded pose ticks, range status, and JPEG frames."""

    def __init__(self, robot_id: str):
        self.robot_id = robot_id
        self.commands: list[str] = []
        self.armed = False
        self.pose_seq = 0
        self.body_boot = 7
        self.origin = 11
        self.head_boot = 21
        self.x_mm = 0
        self.y_mm = 0
        self.yaw_mrad = 0
        self.replay_pose = False
        self.safety_fault = "none"
        self.safety_ready = True
        self.front_mm = 700
        self.frame_seq = 0

    async def status(self):
        return {
            "robot_id": self.robot_id,
            "backend": "stepper_28byj48",
            "armed": self.armed,
            "watchdog_ms": 500,
            "safety": {
                "required": True,
                "ready": self.safety_ready,
                "fault": self.safety_fault,
            },
            "ranges": {
                "present_mask": 31,
                "valid_mask": 31,
                "mm": [50, 50, 50, 50, self.front_mm],
                "age_ms": [5, 5, 5, 5, 5],
            },
            "imu": {
                "family": 1,
                "valid": True,
                "age_ms": 10,
                "acc": [0, 0, 16384],
                "gyro": [0, 0, 0],
            },
            "touch": {"active": False},
        }

    async def pose_status(self):
        if not self.replay_pose:
            self.pose_seq += 1
        return {
            "robot_id": self.robot_id,
            "v": 1,
            "quality": "valid",
            "body_boot": self.body_boot,
            "origin": self.origin,
            "head_boot": self.head_boot,
            "seq": self.pose_seq,
            "sample_us": 1_000_000 + self.pose_seq * 100_000,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "yaw_mrad": self.yaw_mrad,
        }

    async def snapshot(self):
        self.frame_seq += 1
        return _valid_jpeg()

    async def command(self, cmd: str):
        self.commands.append(cmd)
        if cmd == "arm":
            self.armed = True
        elif cmd == "halt":
            self.armed = False
        elif cmd == "drive 20 20 100":
            self.x_mm += 20


def _seed_safe_grid(spatial, robot_id: str, head: SpatialHead, *, width: int = 8, height: int = 8):
    env = SafetyEnvelope(
        footprint_radius_mm=3,
        localization_error_mm=2,
        stopping_margin_mm=2,
        swept_turn_radius_mm=15,
        geometry_qualified=True,
    )
    spatial.bind_qualified_grid(
        robot_id,
        body_boot=head.body_boot,
        origin_id=str(head.origin),
        anchor_id="tag-1",
        calibration_id="cal-1",
        camera_boot=head.head_boot,
        width=width,
        height=height,
        envelope=env,
        ttl_us=5_000_000,
        anchored=True,
    )
    cells = tuple((x, y) for y in range(height) for x in range(width))
    now_us = spatial.now_us()
    spatial.record_range_batch(
        robot_id,
        RangeCellBatch(
            robot_id=robot_id,
            body_boot=head.body_boot,
            origin_id=str(head.origin),
            epoch=spatial.state(robot_id).epoch,
            calibration_id="cal-1",
            kind="floor_supported",
            lane=0,
            sequence=1,
            sample_us=100_000,
            received_us=now_us,
            geometry_qualified=True,
            cells=cells,
        ),
        now_us=now_us,
    )
    spatial.record_range_batch(
        robot_id,
        RangeCellBatch(
            robot_id=robot_id,
            body_boot=head.body_boot,
            origin_id=str(head.origin),
            epoch=spatial.state(robot_id).epoch,
            calibration_id="cal-1",
            kind="obstacle_clear",
            lane=4,
            sequence=1,
            sample_us=100_000,
            received_us=now_us,
            geometry_qualified=True,
            cells=cells,
        ),
        now_us=now_us,
    )


def test_spatial_endpoints_and_navigation_fail_closed_by_default(settings, tokens, tmp_path):
    """Guide 90 routes enforce auth, consent, and spatial_navigation_qualified=False default."""
    settings.memory_dir = tmp_path / "memory"
    settings.trials_file = tmp_path / "trials.jsonl"
    app = create_app(settings)
    op = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}

    with TestClient(app) as client:
        grid = client.get("/v1/robots/robot-01/spatial/grid", headers=tool).json()
        assert grid["initialized"] is False
        assert grid["navigation_authorized"] is False
        assert grid["motor_authorized"] is False

        mem = client.get(
            "/v1/robots/robot-01/spatial/memory",
            params={"object_key": "key"},
            headers=tool,
        ).json()
        assert mem["status"] == "unknown"
        assert mem["navigation_authorized"] is False

        # Enable motion without spatial_navigation_qualified -> refused BEFORE permit consumption.
        assert client.post("/v1/robots/robot-01/enable", headers=op).status_code == 200
        assert "robot-01" in app.state.runtime.coordinator.permits
        denied = client.post(
            "/v1/robots/robot-01/navigate",
            headers=op,
            json={"goal": [2, 2], "start": [2, 2]},
        )
        assert denied.status_code == 409
        assert "robot-01" in app.state.runtime.coordinator.permits

        # Tool token cannot POST /navigate.
        assert (
            client.post(
                "/v1/robots/robot-01/navigate",
                headers=tool,
                json={"goal": [2, 2], "start": [2, 2]},
            ).status_code
            == 403
        )

        # In hardware mode, memory recall endpoint respects voice_memory_tools_enabled.
        settings.mode = "hardware"
        settings.voice_memory_tools_enabled = False
        assert (
            client.get(
                "/v1/robots/robot-01/spatial/memory",
                params={"object_key": "key"},
                headers=tool,
            ).status_code
            == 403
        )


@pytest.mark.parametrize("observation", ["seen", "missing", "camera_failed", "expired"])
def test_api_spatial_search_navigate_and_target_confirmation(
    settings, tokens, tmp_path, monkeypatch, observation,
):
    """End-to-end API navigate uses SearchViewpoint -> plan_route -> live head steps -> detector verification."""
    settings.memory_dir = tmp_path / "memory"
    settings.trials_file = tmp_path / "trials.jsonl"
    monkeypatch.setattr("desk_robot.controller.image_size", lambda _jpeg: (640, 480))

    app = create_app(settings)
    op = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}

    class FakeKeyVision:
        def __init__(self, detected: bool):
            self.detected = detected

        async def detect(self, _jpeg: bytes, target: str):
            if not self.detected:
                return []
            return [Detection(label=target, confidence=0.95, box=(100.0, 100.0, 220.0, 220.0))]

    with TestClient(app) as client:
        rt = app.state.runtime
        robot = settings.robots[0]
        robot.spatial_navigation_qualified = True
        robot.object_detector_qualified = True
        robot.dock_turn_sign = 1
        robot.dock_forward_sign = 1
        head = SpatialHead("robot-01")
        rt.coordinator.heads["robot-01"] = head
        rt.pet.heads["robot-01"] = head
        rt.coordinator.vision = FakeKeyVision(observation in {"seen", "expired"})
        original_snapshot = head.snapshot
        original_confirm = rt.spatial.confirm_target_frame
        if observation == "expired":
            async def delayed_confirm(*args, **kwargs):
                receipt = await original_confirm(*args, **kwargs)
                await asyncio.sleep(0.27)
                return receipt

            monkeypatch.setattr(rt.spatial, "confirm_target_frame", delayed_confirm)
        if observation == "camera_failed":
            async def unavailable_snapshot():
                raise TimeoutError("Injected camera interruption")

            head.snapshot = unavailable_snapshot
        rt.coordinator.set_voice_state(monitor_enforced=False, monitor_ready=True)

        _seed_safe_grid(rt.spatial, "robot-01", head)
        st = rt.spatial.state("robot-01")
        # Record a durable eyewitness memory + spatial sighting so last_seen works.
        now_wall = time.time()
        assert rt.memory.remember(
            "robot-01",
            "evt-key-1",
            "Brass key near lamp",
            kind="key",
            source_robot="robot-01",
            witnessed=True,
            observed_at=now_wall,
            camera_provenance=CameraProvenance(
                received_at=now_wall,
                interpreted_at=now_wall,
                source_identity=(head.head_boot, 1, 100),
            ),
        )
        # Historical/in-memory camera observation yields "last_seen" search hint -> SearchViewpoint.
        obs_us = max(2_000_000, rt.spatial.now_us())
        past_receipt_us = obs_us - 1_000_000
        rt.spatial.record_object_sighting(
            "robot-01",
            ObjectEvidence(
                robot_id="robot-01",
                label="key",
                source="camera_seen",
                seen_at_wall_s=now_wall - 10.0,
                receipt_us=past_receipt_us,
                origin_id=st.origin_id,
                epoch=st.epoch,
                anchor_id=st.anchor_id,
                calibration_id=st.calibration_id,
                camera_boot=st.camera_boot,
                host_boot_id=rt.spatial.host_boot_id,
                camera_grant=settings.camera_consent_generation,
                frame_seq=1,
                floor_mm=(80, 60),
                projection_qualified=True,
                confidence=0.93,
                captured_us=past_receipt_us - 50,
            ),
            event_id="evt-key-1",
            spatial_evidence=SpatialEvidence(
                object_key="key",
                observed_at=now_wall,
                body_boot=head.body_boot,
                origin_id=st.origin_id,
                pose_seq=1,
                pose_sample_us=100,
                camera_boot=st.camera_boot,
                camera_seq=1,
                camera_complete_us=100,
                calibration_id=st.calibration_id,
                x_mm=80,
                y_mm=60,
                yaw_mrad=0,
                uncertainty_mm=20,
            ),
        )
        rt.spatial.register_viewpoint(
            "robot-01",
            SearchViewpoint(
                robot_id="robot-01",
                origin_id=st.origin_id,
                epoch=st.epoch,
                anchor_id=st.anchor_id,
                calibration_id=st.calibration_id,
                viewpoint_id="vp-key-1",
                cell=(3, 2),
                heading=0,
                priority=1,
                previously_reachable=True,
                inspected_in_request=False,
            ),
        )

        # Read-only APIs expose memory pending_localization and bounded grid counts.
        mem = client.get(
            "/v1/robots/robot-01/spatial/memory",
            params={"object_key": "key"},
            headers=tool,
        ).json()
        assert mem["status"] == "pending_localization"
        assert mem["navigation_authorized"] is False

        grid = client.get("/v1/robots/robot-01/spatial/grid", headers=tool).json()
        assert grid["initialized"] is True
        assert grid["anchored"] is True
        assert grid["cell_counts"]["safe"] > 0

        # Execute bounded navigation to search viewpoint (2, 2) -> (3, 2) and confirm target visually.
        assert client.post("/v1/robots/robot-01/enable", headers=op).status_code == 200
        nav = client.post(
            "/v1/robots/robot-01/navigate",
            headers=op,
            json={"label": "key", "start": [2, 2], "heading": 0},
        )
        assert nav.status_code == 202, nav.text
        job_id = nav.json()["id"]

        for _ in range(40):
            job = client.get(f"/v1/jobs/{job_id}", headers=tool).json()
            if job["state"] in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(0.05)

        assert job["state"] == "succeeded"
        expected = {
            "seen": "target_seen_unverified_location",
            "missing": "not_found_after_search",
            "camera_failed": "no_current_sighting",
            "expired": "no_current_sighting",
        }[observation]
        assert job["result"]["status"] == expected
        assert job["result"]["arrived"] is False
        assert job["result"]["target_observed"] is (observation == "seen")
        assert job["result"]["search_exhausted"] is (observation == "missing")
        assert job["result"]["last_seen_at_wall_s"] == now_wall - 10.0
        assert job["result"]["final_cell_verified"] is False
        if observation == "camera_failed":
            assert job["result"]["reason"] == "camera_unavailable"
        if observation == "expired":
            assert job["result"]["reason"] == "frame_expired"
            assert len(st.observations) == 1
            monkeypatch.setattr(rt.spatial, "confirm_target_frame", original_confirm)
        head.snapshot = original_snapshot
        assert job["result"]["motor_authorized"] is False
        assert job["result"]["physical_acceptance_pass"] is False
        assert "arm" in head.commands and "halt" in head.commands
        assert any(cmd.startswith("drive ") for cmd in head.commands)

        # Occluded / moved target never falsely reports arrived=True.
        rt.coordinator.vision = FakeKeyVision(False)
        assert client.post("/v1/robots/robot-01/enable", headers=op).status_code == 200
        nav_missing = client.post(
            "/v1/robots/robot-01/navigate",
            headers=op,
            json={"label": "key", "goal": [3, 2], "start": [2, 2], "heading": 0},
        )
        assert nav_missing.status_code == 202
        job_id_2 = nav_missing.json()["id"]
        for _ in range(40):
            job2 = client.get(f"/v1/jobs/{job_id_2}", headers=tool).json()
            if job2["state"] in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(0.05)
        assert job2["state"] == "succeeded"
        assert job2["result"]["status"] == "no_current_sighting"
        assert job2["result"]["arrived"] is False
        assert job2["result"]["target_observed"] is False


async def test_spatial_navigation_halts_on_pickup_invalidation_and_pose_replay(settings, tmp_path):
    """Pickup handling_tilt invalidates map epoch and halts navigation; replayed pose fails closed."""
    from desk_robot.runtime import Runtime

    settings.memory_dir = tmp_path / "memory"
    settings.trials_file = tmp_path / "trials.jsonl"
    robot = settings.robots[0]
    robot.spatial_navigation_qualified = True
    robot.motion_enabled = True
    rt = Runtime(settings)
    head = SpatialHead("robot-01")
    rt.coordinator.heads["robot-01"] = head
    rt.pet.heads["robot-01"] = head
    try:
        _seed_safe_grid(rt.spatial, "robot-01", head)
        # Replayed pose sequence invalidates map epoch immediately.
        rt.spatial.observe_pose("robot-01", await head.pose_status())
        head.replay_pose = True
        with pytest.raises(Exception, match="Pose sequence"):
            rt.spatial.observe_pose("robot-01", await head.pose_status())
        assert rt.spatial.state("robot-01").grid.anchored is False
        with pytest.raises(OperationError, match="unanchored_or_stale_map"):
            rt.coordinator.navigate("robot-01", goal=(5, 2), start=(2, 2), heading=0)

        # Re-anchor grid under new body origin, then simulate pickup handling_tilt mid-navigation.
        head.replay_pose = False
        head.origin += 1
        head.pose_seq += 1
        with pytest.raises(Exception, match="origin"):
            rt.spatial.observe_pose("robot-01", await head.pose_status())
        _seed_safe_grid(rt.spatial, "robot-01", head)

        class DelayOnceHead(SpatialHead):
            async def command(self, cmd: str):
                await super().command(cmd)
                if cmd.startswith("drive "):
                    rt.pet._notify_sensor("robot-01", "handling_tilt")

        delayed_head = DelayOnceHead("robot-01")
        delayed_head.origin = head.origin
        delayed_head.pose_seq = head.pose_seq
        rt.coordinator.heads["robot-01"] = delayed_head
        await rt.coordinator.operator_arm("robot-01")
        job = rt.coordinator.navigate("robot-01", goal=(6, 2), start=(2, 2), heading=0)
        await asyncio.wait_for(rt.coordinator.tasks[job.id], timeout=5)
        assert job.state == "failed"
        assert "invalidated" in (job.error or "")
        assert rt.spatial.state("robot-01").grid.anchored is False
        assert "halt" in delayed_head.commands
    finally:
        await rt.close()


def test_api_navigate_defer_on_voice_and_stop_discard(settings, tokens, tmp_path):
    """defer_on_voice queues /navigate safely during human speech and STOP discards it."""
    settings.memory_dir = tmp_path / "memory"
    settings.trials_file = tmp_path / "trials.jsonl"
    app = create_app(settings)
    op = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}

    with TestClient(app) as client:
        rt = app.state.runtime
        robot = settings.robots[0]
        robot.spatial_navigation_qualified = True
        head = SpatialHead("robot-01")
        rt.coordinator.heads["robot-01"] = head
        _seed_safe_grid(rt.spatial, "robot-01", head)
        assert client.post("/v1/robots/robot-01/enable", headers=op).status_code == 200
        rt.coordinator.set_voice_state(
            monitor_enforced=True,
            monitor_ready=True,
            active_robots=frozenset({"robot-01"}),
        )
        deferred = client.post(
            "/v1/robots/robot-01/navigate",
            headers=op,
            params={"defer_on_voice": "true"},
            json={"goal": [3, 2], "start": [2, 2]},
        )
        assert deferred.status_code == 202
        assert deferred.json()["state"] == "deferred_for_voice"
        assert head.commands == []

        assert client.post("/v1/robots/robot-01/stop", headers=op).status_code == 200
        req_id = deferred.json()["id"]
        assert rt.coordinator._deferred_requests[req_id].state == "discarded"


async def test_spatial_navigate_barrier_cancellation_and_pre_pickup_rejection(
    settings, tmp_path, monkeypatch,
):
    """STOP between route pulses prevents pulse 2; pickup invalidates old frames without map resurrection."""
    from desk_robot.object_detector import DetectorFrame
    from desk_robot.runtime import Runtime

    settings.memory_dir = tmp_path / "memory"
    settings.trials_file = tmp_path / "trials.jsonl"
    robot = settings.robots[0]
    robot.spatial_navigation_qualified = True
    robot.object_detector_qualified = True
    robot.motion_enabled = True
    monkeypatch.setattr("desk_robot.controller.image_size", lambda _jpeg: (640, 480))

    class FixedVision:
        async def detect(self, _jpeg: bytes, target: str):
            return [Detection(label=target, confidence=0.95, box=(100.0, 100.0, 220.0, 220.0))]

    rt = Runtime(settings)
    first_drive_seen = asyncio.Event()
    release_first_drive = asyncio.Event()

    class BarrierHead(SpatialHead):
        async def command(self, cmd: str):
            await super().command(cmd)
            if cmd.startswith("drive "):
                first_drive_seen.set()
                await asyncio.wait_for(release_first_drive.wait(), timeout=5)

    head = BarrierHead("robot-01")
    rt.coordinator.heads["robot-01"] = head
    rt.pet.heads["robot-01"] = head
    try:
        _seed_safe_grid(rt.spatial, "robot-01", head)
        pre_pickup_epoch = rt.spatial.state("robot-01").epoch
        pre_pickup_origin = rt.spatial.state("robot-01").origin_id
        pre_pickup_anchor = rt.spatial.state("robot-01").anchor_id

        await rt.coordinator.operator_arm("robot-01")
        job = rt.coordinator.navigate("robot-01", goal=(6, 2), start=(2, 2), heading=0)
        await asyncio.wait_for(first_drive_seen.wait(), timeout=5)
        await rt.coordinator.stop("robot-01")
        release_first_drive.set()
        await asyncio.wait_for(rt.coordinator.tasks[job.id], timeout=5)
        assert job.state == "cancelled"
        assert sum(1 for c in head.commands if c.startswith("drive ")) == 1
        assert "halt" in head.commands

        # Late pre-pickup camera frame submitted after handling_tilt pickup
        # must fail closed at detector confirmation without touching the map or memory.
        now_us = rt.spatial.now_us()
        rt.pet._notify_sensor("robot-01", "handling_tilt")
        assert rt.spatial.state("robot-01").grid.anchored is False
        pre_pickup_frame = DetectorFrame(
            robot_id="robot-01",
            session_id="operator-session",
            turn_id="operator-turn",
            origin_id=pre_pickup_origin,
            epoch=pre_pickup_epoch,
            anchor_id=pre_pickup_anchor,
            calibration_id="cal-1",
            camera_boot=head.head_boot,
            host_boot_id=rt.spatial.host_boot_id,
            camera_grant=settings.camera_consent_generation,
            frame_seq=99,
            captured_us=max(1, now_us - 50),
            received_us=now_us,
            seen_at_wall_s=time.time(),
            jpeg=_valid_jpeg(),
        )
        receipt = await rt.spatial.confirm_target_frame(
            FixedVision(),
            pre_pickup_frame,
            label="candy",
            model_qualified=True,
            safety_clear=lambda: False,
            request_is_current=lambda: rt.spatial.state("robot-01").epoch == pre_pickup_epoch,
        )
        assert receipt.status == "rejected"
        assert receipt.reason in ("safety_preempted", "request_invalidated", "camera_or_map_changed")
        assert receipt.may_execute is False
        assert receipt.arrived is False
        assert rt.spatial.state("robot-01").grid.anchored is False
        assert rt.spatial.spatial_memory.last_seen("robot-01", "candy", now=time.time()) is None
    finally:
        release_first_drive.set()
        await rt.close()


async def test_navigation_rechecks_swept_neighbor_after_pose_io(settings, tmp_path):
    """An unsafe cell outside the centerline vetoes the pending turn."""
    from desk_robot.runtime import Runtime

    settings.memory_dir = tmp_path / "memory"
    settings.trials_file = tmp_path / "trials.jsonl"
    robot = settings.robots[0]
    robot.motion_enabled = True
    robot.spatial_navigation_qualified = True
    rt = Runtime(settings)

    class HazardHead(SpatialHead):
        async def pose_status(self):
            st = rt.spatial.state("robot-01")
            now_us = rt.spatial.now_us()
            rt.spatial.record_range_batch(
                "robot-01",
                RangeCellBatch(
                    "robot-01", self.body_boot, st.origin_id, st.epoch,
                    st.calibration_id, 0, 2, 200_000, now_us,
                    "floor_unsafe", ((1, 2),), True,
                ),
                now_us=now_us,
            )
            return await super().pose_status()

    head = HazardHead("robot-01")
    rt.coordinator.heads["robot-01"] = head
    try:
        _seed_safe_grid(rt.spatial, "robot-01", head)
        await rt.coordinator.operator_arm("robot-01")
        job = rt.coordinator.navigate("robot-01", start=(2, 2), goal=(2, 3))
        await asyncio.wait_for(rt.coordinator.tasks[job.id], timeout=5)
        assert job.state == "failed"
        assert "route clearance or validity lost" in (job.error or "")
        assert not any(cmd.startswith("drive ") for cmd in head.commands)
        assert "halt" in head.commands
    finally:
        await rt.close()


async def test_navigation_consumes_real_typed_pose_receipt(settings, tmp_path):
    from desk_robot.runtime import Runtime
    from desk_robot.spatial_pose import PoseError, PoseFence

    settings.memory_dir = tmp_path / "memory"
    settings.trials_file = tmp_path / "trials.jsonl"
    rt = Runtime(settings)
    head = SpatialHead("robot-01")
    try:
        _seed_safe_grid(rt.spatial, "robot-01", head)
        fence = PoseFence("robot-01")
        fence.observe(await head.pose_status(), time.monotonic())
        receipt = fence.observe(await head.pose_status(), time.monotonic())
        assert rt.spatial.observe_pose(
            "robot-01", receipt, source_fence=fence,
        ) is receipt
        assert rt.spatial.state("robot-01").grid.anchored
        with pytest.raises(PoseError, match="not current"):
            rt.spatial.observe_pose("robot-01", receipt, source_fence=fence)
        assert not rt.spatial.state("robot-01").grid.anchored
    finally:
        await rt.close()


async def test_plan_callback_rejects_in_place_epoch_change(settings, tmp_path, monkeypatch):
    from desk_robot.route_planner import plan_route
    from desk_robot.runtime import Runtime

    settings.memory_dir = tmp_path / "memory"
    settings.trials_file = tmp_path / "trials.jsonl"
    rt = Runtime(settings)
    head = SpatialHead("robot-01")
    try:
        _seed_safe_grid(rt.spatial, "robot-01", head)

        def invalidate_during_plan(*args, **kwargs):
            rt.spatial.invalidate_robot("robot-01", reason="pickup")
            return plan_route(*args, **kwargs)

        monkeypatch.setattr("desk_robot.spatial_runtime.plan_route", invalidate_during_plan)
        route, _, _ = rt.spatial.plan_navigation(
            "robot-01", start=(2, 2), goal=(3, 2),
        )
        assert route.status == "rejected"
        assert not route.may_execute
        assert not rt.spatial.state("robot-01").grid.anchored
    finally:
        await rt.close()
