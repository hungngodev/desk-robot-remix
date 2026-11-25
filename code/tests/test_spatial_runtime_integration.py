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
        self._last_sample_us = 0
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
            self._last_sample_us = max(
                self._last_sample_us + 1, int(time.monotonic() * 1_000_000),
            )
        return {
            "robot_id": self.robot_id,
            "v": 1,
            "quality": "valid",
            "body_boot": self.body_boot,
            "origin": self.origin,
            "head_boot": self.head_boot,
            "seq": self.pose_seq,
            "sample_us": self._last_sample_us,
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


def _seed_safe_grid(
    spatial,
    robot_id: str,
    head: SpatialHead,
    *,
    width: int = 8,
    height: int = 8,
    map_to_odom=None,
):
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
        map_to_odom=map_to_odom,
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
            confidence=0.63,
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
        assert mem["observed_at"] == now_wall
        assert mem["age_s"] >= 0
        assert mem["episode_confidence"] == 0.63
        assert mem["body_boot"] == head.body_boot
        assert mem["origin_id"] == st.origin_id
        assert mem["navigation_authorized"] is False
        assert mem["motor_authorized"] is False
        assert mem["arrived"] is False

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

        drive_injections = 0

        class DelayOnceHead(SpatialHead):
            async def command(self, cmd: str):
                nonlocal drive_injections
                await super().command(cmd)
                if cmd.startswith("drive "):
                    drive_injections += 1
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
        assert drive_injections == 1
        assert sum(1 for c in delayed_head.commands if c.startswith("drive ")) == 1
        assert delayed_head.commands.index("halt") > max(
            i for i, c in enumerate(delayed_head.commands) if c.startswith("drive ")
        )

        # Also exercise pickup invalidation during second-edge pose IO after 1 clean drive.
        delayed_head.origin += 1
        delayed_head.pose_seq += 1
        with pytest.raises(Exception, match="origin"):
            rt.spatial.observe_pose("robot-01", await delayed_head.pose_status())
        _seed_safe_grid(rt.spatial, "robot-01", delayed_head)

        class SecondEdgePickupHead(SpatialHead):
            def __init__(self, robot_id: str):
                super().__init__(robot_id)
                self.drives = 0
                self.triggered = False

            async def command(self, cmd: str):
                await super().command(cmd)
                if cmd.startswith("drive "):
                    self.drives += 1

            async def pose_status(self):
                if self.drives >= 1 and not self.triggered:
                    self.triggered = True
                    rt.pet._notify_sensor("robot-01", "handling_tilt")
                return await super().pose_status()

        edge2_head = SecondEdgePickupHead("robot-01")
        edge2_head.origin = delayed_head.origin
        edge2_head.pose_seq = delayed_head.pose_seq
        rt.coordinator.heads["robot-01"] = edge2_head
        await rt.coordinator.operator_arm("robot-01")
        job2 = rt.coordinator.navigate("robot-01", goal=(5, 2), start=(2, 2), heading=0)
        await asyncio.wait_for(rt.coordinator.tasks[job2.id], timeout=5)
        assert job2.state == "failed"
        assert sum(1 for c in edge2_head.commands if c.startswith("drive ")) == 1
        assert "halt" in edge2_head.commands
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


@pytest.mark.parametrize("change", ["epoch", "camera_boot", "camera_grant", "turn", None])
async def test_detector_revalidates_live_owner_after_inference(
    settings, monkeypatch, change,
):
    """A running job cannot revive a result from an earlier spatial owner."""
    from desk_robot.object_detector import DetectorFrame
    from desk_robot.runtime import Runtime

    settings.voice_vision_tools_enabled = True
    rt = Runtime(settings)
    entered, release = asyncio.Event(), asyncio.Event()
    live = True
    task = None

    class HeldVision:
        async def detect(self, _jpeg: bytes, target: str):
            entered.set()
            await release.wait()
            return [Detection(label=target, confidence=0.95, box=(10, 10, 40, 40))]

    try:
        robot_id = settings.robots[0].id
        _seed_safe_grid(rt.spatial, robot_id, SpatialHead(robot_id))
        st = rt.spatial.state(robot_id)
        now_us = rt.spatial.now_us()
        monkeypatch.setattr(rt.spatial, "now_us", lambda: now_us)
        frame = DetectorFrame(
            robot_id=robot_id,
            session_id="operator-session",
            turn_id="operator-turn",
            origin_id=st.origin_id,
            epoch=st.epoch,
            anchor_id=st.anchor_id,
            calibration_id=st.calibration_id,
            camera_boot=st.camera_boot,
            host_boot_id=rt.spatial.host_boot_id,
            camera_grant=settings.camera_consent_generation,
            frame_seq=1,
            captured_us=now_us,
            received_us=now_us,
            seen_at_wall_s=time.time(),
            jpeg=_valid_jpeg(),
        )
        task = asyncio.create_task(rt.spatial.confirm_target_frame(
            HeldVision(), frame, label="key", model_qualified=True,
            safety_clear=lambda: True, request_is_current=lambda: live,
        ))
        await asyncio.wait_for(entered.wait(), timeout=1)
        if change == "epoch":
            rt.spatial.invalidate_robot(robot_id, reason="test_epoch_changed")
        elif change == "camera_boot":
            st.camera_boot += 1
        elif change == "camera_grant":
            settings.voice_vision_tools_enabled = False
            settings.voice_vision_tools_enabled = True
        elif change == "turn":
            live = False
        release.set()
        receipt = await asyncio.wait_for(task, timeout=1)
        if change is None:
            assert receipt.status == "camera_seen"
            assert receipt.evidence is not None
        else:
            assert receipt.status == "rejected"
            assert receipt.reason == "request_invalidated"
            assert receipt.evidence is None
        assert receipt.may_execute is False
        assert receipt.arrived is False
        assert not st.observations
    finally:
        release.set()
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
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


class _HardwarePoseHead(SpatialHead):
    """Hardware-contract test head emitting typed PoseReceipts through a PoseFence."""

    def __init__(
        self,
        robot_id: str,
        *,
        x_mm: int = 0,
        y_mm: int = 0,
        yaw_mrad: int = 0,
        ignore_turn: bool = False,
        freeze_forward_after: int | None = None,
    ):
        from desk_robot.spatial_pose import PoseFence

        super().__init__(robot_id)
        self.x_mm = x_mm
        self.y_mm = y_mm
        self.yaw_mrad = yaw_mrad
        self.pose_fence = PoseFence(robot_id)
        self.ignore_turn = ignore_turn
        self.freeze_forward_after = freeze_forward_after
        self._forward_count = 0

    async def pose_status(self):
        payload = await super().pose_status()
        return self.pose_fence.observe(payload, time.monotonic())

    async def command(self, cmd: str):
        import math

        self.commands.append(cmd)
        if cmd == "arm":
            self.armed = True
        elif cmd == "halt":
            self.armed = False
        elif cmd == "drive 20 20 100":
            self._forward_count += 1
            if self.freeze_forward_after is None or self._forward_count <= self.freeze_forward_after:
                theta = self.yaw_mrad / 1000.0
                self.x_mm += round(20 * math.cos(theta))
                self.y_mm += round(20 * math.sin(theta))
        elif cmd == "drive 20 -20 100" and not self.ignore_turn:
            self.yaw_mrad = round(math.remainder(self.yaw_mrad / 1000.0 + math.pi / 2, math.tau) * 1000.0)
        elif cmd == "drive -20 20 100" and not self.ignore_turn:
            self.yaw_mrad = round(math.remainder(self.yaw_mrad / 1000.0 - math.pi / 2, math.tau) * 1000.0)


async def _setup_hardware_pose_runtime(settings, tmp_path, head: _HardwarePoseHead, map_to_odom):
    from types import SimpleNamespace

    from desk_robot.multimodal import CameraEvidence
    from desk_robot.runtime import Runtime

    settings.memory_dir = tmp_path / "memory"
    settings.trials_file = tmp_path / "trials.jsonl"
    robot = settings.robots[0]
    robot.head_url = "http://192.168.1.51:8001"
    robot.voice = "voice-1"
    robot.motor_backend = "stepper_28byj48"
    robot.motion_enabled = True
    robot.spatial_navigation_qualified = True
    robot.dock_turn_sign = 1
    robot.dock_forward_sign = 1
    settings.robots = [robot]
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True

    rt = Runtime(settings)

    async def _noop_interrupt(_robot):
        return True

    rt.conversation.speaker = SimpleNamespace(interrupt=_noop_interrupt)
    rt.coordinator.heads["robot-01"] = head
    rt.pet.heads["robot-01"] = head
    _seed_safe_grid(rt.spatial, "robot-01", head, map_to_odom=map_to_odom)
    rt.coordinator.multimodal = SimpleNamespace(
        stream_owns_camera=lambda _id: True,
        status=lambda _id: {"camera_stream_connected": True},
        hub=SimpleNamespace(
            frames={
                "robot-01": [
                    CameraEvidence(
                        jpeg=_valid_jpeg(),
                        received_at=time.monotonic(),
                        motion_fraction=0.0,
                        source="proactive",
                        source_identity=(head.head_boot, 1, 1),
                    )
                ]
            }
        ),
    )
    # Prime continuous PoseFence baseline so subsequent pose_status() is current.
    await head.pose_status()
    return rt


async def test_hardware_navigate_derives_shifted_start_and_heading_from_localized_pose(settings, tmp_path):
    """Hardware navigation derives initial cell and heading from map_to_odom + live PoseReceipt."""
    import math

    from desk_robot.spatial_frames import PlanarTransform

    # map<-odom rotated +90 deg and shifted: odom (20, -20, 0) -> map (60, 40, +pi/2) -> cell (3, 2), heading 1 (+Y).
    head = _HardwarePoseHead("robot-01", x_mm=20, y_mm=-20, yaw_mrad=0)
    map_to_odom = PlanarTransform("map", "odom", 40.0, 20.0, math.pi / 2)
    rt = await _setup_hardware_pose_runtime(settings, tmp_path, head, map_to_odom)
    try:
        await rt.coordinator.operator_arm("robot-01")
        job = rt.coordinator.navigate("robot-01", goal=(3, 3))
        await asyncio.wait_for(rt.coordinator.tasks[job.id], timeout=5)
        assert job.state == "succeeded", job.error
        assert job.result["status"] == "waypoint_reached"
        assert job.result["final_cell"] == (3, 3)
        assert job.result["final_heading"] == 1
        assert [c for c in head.commands if c.startswith("drive ")] == ["drive 20 20 100"]
    finally:
        await rt.close()


async def test_hardware_navigate_rejects_shifted_start_or_heading_before_any_drive(settings, tmp_path):
    """Caller start=(0,0), heading=0 must fail closed with zero pulses when live pose is elsewhere."""
    from desk_robot.spatial_frames import PlanarTransform

    head = _HardwarePoseHead("robot-01", x_mm=40, y_mm=20, yaw_mrad=1571)
    map_to_odom = PlanarTransform("map", "odom", 0.0, 0.0, 0.0)
    rt = await _setup_hardware_pose_runtime(settings, tmp_path, head, map_to_odom)
    try:
        await rt.coordinator.operator_arm("robot-01")
        job = rt.coordinator.navigate("robot-01", goal=(1, 0), start=(0, 0), heading=0)
        await asyncio.wait_for(rt.coordinator.tasks[job.id], timeout=5)
        assert job.state == "failed"
        assert "diverges from route state" in (job.error or "")
        assert not any(c.startswith("drive ") for c in head.commands)
        assert rt.spatial.state("robot-01").grid.anchored is False
        assert rt.spatial.state("robot-01").map_to_odom is None
    finally:
        await rt.close()


@pytest.mark.parametrize("failure_mode", ["failed_turn", "failed_forward"])
async def test_hardware_navigate_halts_on_mid_route_odometry_divergence(
    settings, tmp_path, failure_mode,
):
    """Missing turn or unachieved step halts before next pulse and invalidates spatial anchor."""
    from desk_robot.spatial_frames import PlanarTransform

    if failure_mode == "failed_turn":
        head = _HardwarePoseHead("robot-01", x_mm=40, y_mm=40, yaw_mrad=0, ignore_turn=True)
        goal = (2, 3)  # Requires turn at (2, 2) to heading 1 before stepping to (2, 3).
    else:
        head = _HardwarePoseHead("robot-01", x_mm=40, y_mm=40, yaw_mrad=0, freeze_forward_after=1)
        goal = (5, 2)  # Pulse 1 reaches (3,2), pulse 2 stalls at (3,2), pre-pulse 3 halts on (3,2) != (4,2).
    map_to_odom = PlanarTransform("map", "odom", 0.0, 0.0, 0.0)
    rt = await _setup_hardware_pose_runtime(settings, tmp_path, head, map_to_odom)
    try:
        await rt.coordinator.operator_arm("robot-01")
        job = rt.coordinator.navigate("robot-01", goal=goal)
        await asyncio.wait_for(rt.coordinator.tasks[job.id], timeout=5)
        assert job.state == "failed"
        assert "diverges from route state" in (job.error or "")
        if failure_mode == "failed_turn":
            assert [c for c in head.commands if c.startswith("drive ")] == ["drive 20 -20 100"]
        else:
            assert [c for c in head.commands if c.startswith("drive ")] == ["drive 20 20 100", "drive 20 20 100"]
        assert "halt" in head.commands
        assert rt.spatial.state("robot-01").grid.anchored is False
        assert rt.spatial.state("robot-01").map_to_odom is None
    finally:
        await rt.close()


async def test_hardware_navigate_refuses_missing_map_to_odom(settings, tmp_path):
    """Hardware navigation refuses to start when map_to_odom is unbound."""
    head = _HardwarePoseHead("robot-01", x_mm=40, y_mm=40, yaw_mrad=0)
    rt = await _setup_hardware_pose_runtime(settings, tmp_path, head, map_to_odom=None)
    try:
        await rt.coordinator.operator_arm("robot-01")
        with pytest.raises(OperationError, match="map-to-odom localization unqualified"):
            rt.coordinator.navigate("robot-01", goal=(3, 2))
        assert head.commands == []
    finally:
        await rt.close()


def test_f036_first_unit_anchoring_split_and_reanchor_replay(tmp_path):
    """F036 keeps first-unit AprilTag anchoring required while testing fail-closed re-anchor."""
    from pathlib import Path

    from desk_robot.spatial_bracket import validate_stationary_bracket
    from desk_robot.spatial_frames import (
        PlanarTransform,
        map_odom_transform,
        odom_base_transform,
    )
    from desk_robot.spatial_pose import PoseFence
    from desk_robot.spatial_runtime import SpatialRuntime

    root = Path(__file__).resolve().parents[2]
    source_map = (root / "docs/source-map.md").read_text(encoding="utf-8")
    coverage = (root / "agents/coverage.md").read_text(encoding="utf-8")
    product_def = (root / "docs/product-definition.md").read_text(encoding="utf-8")

    f036_src = next(
        line for line in source_map.splitlines() if line.startswith("| `F036` |")
    )
    f036_cov = next(
        line for line in coverage.splitlines() if 'id="feature-f036"' in line
    )
    assert "REQUIRED FIRST-UNIT ANCHORING" in f036_src
    assert "| EXPANSION |" not in f036_src
    assert "REQUIRED FIRST-UNIT ANCHORING" in f036_cov
    assert "| EXPANSION |" not in f036_cov
    assert "9/10 reanchors within 20 mm" in product_def
    for guide in (
        "50-map-and-spatial-memory.md",
        "60-object-recall-and-navigation.md",
        "90-integration-and-release-evidence.md",
    ):
        assert guide in f036_src and guide in f036_cov

    # Trusted JPEG/pose bracket -> anchor -> pickup invalidation -> fresh re-anchor.
    class FakeSettings:
        def __init__(self, memory_dir):
            self.memory_dir = memory_dir
            self.robots = [type("R", (), {"id": "robot-01"})()]

        def robot(self, rid):
            assert rid == "robot-01"
            return self.robots[0]

    from desk_robot.memory import MemoryStore

    store = MemoryStore(tmp_path / "mem", ["robot-01"])
    spatial = SpatialRuntime(FakeSettings(tmp_path / "mem"), store)
    fence = PoseFence("robot-01")
    t0 = 1000.0
    before = fence.observe(
        {
            "robot_id": "robot-01", "v": 1, "body_boot": 7, "origin": 11,
            "head_boot": 21, "seq": 1, "sample_us": 100_000,
            "x_mm": 0, "y_mm": 0, "yaw_mrad": 0, "quality": "valid",
        },
        t0,
        request_started_at=t0 - 0.01,
    )
    after = fence.observe(
        {
            "robot_id": "robot-01", "v": 1, "body_boot": 7, "origin": 11,
            "head_boot": 21, "seq": 2, "sample_us": 380_000,
            "x_mm": 0, "y_mm": 0, "yaw_mrad": 0, "quality": "valid",
        },
        t0 + 0.28,
        request_started_at=t0 + 0.27,
    )
    bracket = validate_stationary_bracket(
        fence=fence, before=before, after=after,
        previous_camera=(21, 1, 100), camera=(21, 2, 200),
        camera_received_at=t0 + 0.11,
        stream_generation_before=1, stream_generation_after=1,
        motion_epoch_before=1, motion_epoch_after=1,
        disarmed_before=True, disarmed_after=True,
        now=t0 + 0.28, max_optical_lag_s=0.10, max_body_lag_s=0.15,
    )
    map_base = PlanarTransform("map", "base_link", 40.0, 20.0, 0.0)
    map_to_odom = map_odom_transform(map_base, bracket.odom_base)
    env = SafetyEnvelope(3, 2, 2, 15, True)
    spatial.bind_qualified_grid(
        "robot-01", body_boot=7, origin_id="11", anchor_id="tag-1",
        calibration_id="cal-1", camera_boot=21, width=6, height=6,
        envelope=env, ttl_us=5_000_000, anchored=True, map_to_odom=map_to_odom,
    )
    assert spatial.state("robot-01").grid.anchored is True
    assert spatial.state("robot-01").map_to_odom == map_to_odom

    # Pickup invalidates the anchor and map_to_odom (fail closed).
    spatial.invalidate_robot("robot-01", reason="pickup")
    assert spatial.state("robot-01").grid.anchored is False
    assert spatial.state("robot-01").map_to_odom is None

    # Origin transition (11 -> 12) raises PoseError to retire old origin and
    # force re-anchoring; the subsequent two continuous frames in origin 12
    # establish the new bracket safely without motion.
    with pytest.raises(Exception, match="re-anchor required"):
        fence.observe(
            {
                "robot_id": "robot-01", "v": 1, "body_boot": 7, "origin": 12,
                "head_boot": 21, "seq": 3, "sample_us": 820_000,
                "x_mm": 10, "y_mm": 0, "yaw_mrad": 0, "quality": "valid",
            },
            t0 + 0.72,
            request_started_at=t0 + 0.71,
        )
    b2 = fence.observe(
        {
            "robot_id": "robot-01", "v": 1, "body_boot": 7, "origin": 12,
            "head_boot": 21, "seq": 4, "sample_us": 1_100_000,
            "x_mm": 10, "y_mm": 0, "yaw_mrad": 0, "quality": "valid",
        },
        t0 + 1.0,
        request_started_at=t0 + 0.99,
    )
    a2 = fence.observe(
        {
            "robot_id": "robot-01", "v": 1, "body_boot": 7, "origin": 12,
            "head_boot": 21, "seq": 5, "sample_us": 1_380_000,
            "x_mm": 10, "y_mm": 0, "yaw_mrad": 0, "quality": "valid",
        },
        t0 + 1.28,
        request_started_at=t0 + 1.27,
    )
    br2 = validate_stationary_bracket(
        fence=fence, before=b2, after=a2,
        previous_camera=(21, 2, 200), camera=(21, 3, 300),
        camera_received_at=t0 + 1.11,
        stream_generation_before=1, stream_generation_after=1,
        motion_epoch_before=2, motion_epoch_after=2,
        disarmed_before=True, disarmed_after=True,
        now=t0 + 1.28, max_optical_lag_s=0.10, max_body_lag_s=0.15,
    )
    new_map_to_odom = map_odom_transform(
        PlanarTransform("map", "base_link", 40.0, 20.0, 0.0),
        br2.odom_base,
    )
    assert a2.origin == 12
    assert b2.body_boot == 7 and odom_base_transform(a2) == br2.odom_base
    spatial.bind_qualified_grid(
        "robot-01", body_boot=7, origin_id="12", anchor_id="tag-1",
        calibration_id="cal-1", camera_boot=21, width=6, height=6,
        envelope=env, ttl_us=5_000_000, anchored=True, map_to_odom=new_map_to_odom,
    )
    assert spatial.state("robot-01").grid.anchored is True
    assert spatial.state("robot-01").origin_id == "12"
    assert spatial.state("robot-01").map_to_odom == new_map_to_odom


async def test_hardware_navigation_rejects_pose_expired_during_health_io(
    settings, tmp_path, monkeypatch,
):
    """A fresh body health response must not renew older localization evidence."""
    from desk_robot.spatial_frames import PlanarTransform

    head = _HardwarePoseHead("robot-01", x_mm=40, y_mm=40, yaw_mrad=0)
    transform = PlanarTransform("map", "odom", 0.0, 0.0, 0.0)
    rt = await _setup_hardware_pose_runtime(settings, tmp_path, head, transform)
    health = rt.coordinator._assert_armed_health

    async def delayed_health(robot_id, **kwargs):
        body = await health(robot_id, **kwargs)
        if head.pose_seq == 3:
            # The third sample is the first edge's verified pose. Keep the
            # map, camera and body verdict valid while its 250 ms age expires.
            await asyncio.sleep(0.27)
        return body

    monkeypatch.setattr(rt.coordinator, "_assert_armed_health", delayed_health)
    try:
        await rt.coordinator.operator_arm("robot-01")
        job = rt.coordinator.navigate("robot-01", goal=(3, 2))
        await asyncio.wait_for(rt.coordinator.tasks[job.id], timeout=5)
        assert job.state == "failed"
        assert "pose receipt expired" in (job.error or "")
        assert not any(c.startswith("drive ") for c in head.commands)
        assert "halt" in head.commands
        assert not rt.spatial.state("robot-01").grid.anchored
    finally:
        await rt.close()


@pytest.mark.parametrize("hazard_kind", ["clean", "floor_unsafe", "front_obstacle"])
async def test_three_cell_straight_route_revalidates_later_edges_independently(
    settings, tmp_path, hazard_kind,
):
    """DRX-070: multi-edge route reaches goal in 3 drives cleanly, or aborts after 1 drive on later edge loss."""
    from desk_robot.runtime import Runtime

    settings.memory_dir = tmp_path / "memory"
    settings.trials_file = tmp_path / "trials.jsonl"
    robot = settings.robots[0]
    robot.motion_enabled = True
    robot.spatial_navigation_qualified = True
    rt = Runtime(settings)

    class MultiEdgeHead(SpatialHead):
        def __init__(self, robot_id: str):
            super().__init__(robot_id)
            self.drive_count = 0
            self.injected = False

        async def command(self, cmd: str):
            await super().command(cmd)
            if cmd.startswith("drive "):
                self.drive_count += 1

        async def pose_status(self):
            if hazard_kind != "clean" and self.drive_count >= 1 and not self.injected:
                self.injected = True
                st = rt.spatial.state("robot-01")
                now_us = rt.spatial.now_us()
                rt.spatial.record_range_batch(
                    "robot-01",
                    RangeCellBatch(
                        robot_id="robot-01",
                        body_boot=self.body_boot,
                        origin_id=st.origin_id,
                        epoch=st.epoch,
                        calibration_id=st.calibration_id,
                        kind=("floor_unsafe" if hazard_kind == "floor_unsafe" else "obstacle_hit"),
                        lane=(2 if hazard_kind == "floor_unsafe" else 4),
                        sequence=2,
                        sample_us=200_000,
                        received_us=now_us,
                        geometry_qualified=True,
                        cells=((4, 2),),
                    ),
                    now_us=now_us,
                )
            return await super().pose_status()

    head = MultiEdgeHead("robot-01")
    rt.coordinator.heads["robot-01"] = head
    try:
        _seed_safe_grid(rt.spatial, "robot-01", head)
        await rt.coordinator.operator_arm("robot-01")
        job = rt.coordinator.navigate("robot-01", goal=(5, 2), start=(2, 2), heading=0)
        await asyncio.wait_for(rt.coordinator.tasks[job.id], timeout=5)
        drives = [c for c in head.commands if c.startswith("drive ")]
        if hazard_kind == "clean":
            assert job.state == "succeeded"
            assert len(drives) == 3
        else:
            assert job.state == "failed"
            assert "route clearance or validity lost" in (job.error or "")
            assert len(drives) == 1
            assert "halt" in head.commands
    finally:
        await rt.close()


def test_explicit_goal_report_only_target_omits_eyewitness_timestamp(
    settings, tokens, tmp_path, monkeypatch,
):
    """DRX-170 API check: report_only / user_reported target has no camera eyewitness timestamp."""
    from desk_robot.object_targets import ObjectEvidence

    settings.memory_dir = tmp_path / "memory"
    settings.trials_file = tmp_path / "trials.jsonl"
    app = create_app(settings)
    op = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
    monkeypatch.setattr("desk_robot.controller.image_size", lambda _jpeg: (640, 480))

    class MissingVision:
        async def detect(self, _jpeg: bytes, _target: str):
            return []

    with TestClient(app) as client:
        rt = app.state.runtime
        rt.coordinator.vision = MissingVision()
        robot = settings.robots[0]
        robot.spatial_navigation_qualified = True
        robot.object_detector_qualified = True
        head = SpatialHead("robot-01")
        rt.coordinator.heads["robot-01"] = head
        _seed_safe_grid(rt.spatial, "robot-01", head)
        now_wall = time.time()
        rt.spatial.record_object_sighting(
            "robot-01",
            ObjectEvidence(
                robot_id="robot-01",
                label="key",
                source="user_reported",
                seen_at_wall_s=now_wall - 10.0,
            ),
        )
        assert client.post("/v1/robots/robot-01/enable", headers=op).status_code == 200
        resp = client.post(
            "/v1/robots/robot-01/navigate",
            headers=op,
            json={"label": "key", "goal": [3, 2], "start": [2, 2], "heading": 0},
        )
        assert resp.status_code == 202
        job_id = resp.json()["id"]
        for _ in range(40):
            job = client.get(f"/v1/jobs/{job_id}", headers=tool).json()
            if job["state"] in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(0.05)
        assert job["state"] == "succeeded"
        assert job["result"]["status"] == "no_current_sighting"
        assert job["result"]["last_seen_at_wall_s"] is None
        assert job["result"]["arrived"] is False
        assert job["result"]["motor_authorized"] is False


@pytest.mark.parametrize("late_error", [False, True])
async def test_navigation_discards_pose_after_map_epoch_replacement(
    settings, tmp_path, monkeypatch, late_error,
):
    """A retired pose request cannot update or invalidate a replacement map."""
    from desk_robot.spatial_frames import PlanarTransform

    head = _HardwarePoseHead("robot-01", x_mm=40, y_mm=40, yaw_mrad=0)
    transform = PlanarTransform("map", "odom", 0.0, 0.0, 0.0)
    rt = await _setup_hardware_pose_runtime(settings, tmp_path, head, transform)
    original_pose = head.pose_status
    entered = asyncio.Event()
    release = asyncio.Event()

    async def delayed_pose():
        receipt = await original_pose()
        entered.set()
        await release.wait()
        if late_error:
            raise OSError("Retired pose request failed")
        return receipt

    monkeypatch.setattr(head, "pose_status", delayed_pose)
    try:
        await rt.coordinator.operator_arm("robot-01")
        job = rt.coordinator.navigate("robot-01", goal=(3, 2))
        await asyncio.wait_for(entered.wait(), timeout=2)
        old_epoch = rt.spatial.state("robot-01").epoch
        _seed_safe_grid(rt.spatial, "robot-01", head, map_to_odom=transform)
        replacement = rt.spatial.state("robot-01")
        replacement_epoch = replacement.epoch
        replacement_grid = replacement.grid
        assert replacement_epoch > old_epoch
        release.set()
        await asyncio.wait_for(rt.coordinator.tasks[job.id], timeout=5)
        assert job.state == "failed"
        assert "spatial map invalidated during pose read" in (job.error or "")
        assert not any(cmd.startswith("drive ") for cmd in head.commands)
        assert "halt" in head.commands
        current = rt.spatial.state("robot-01")
        assert current.epoch == replacement_epoch
        assert current.grid is replacement_grid
        assert current.grid.anchored
        assert current.last_navigation_pose is None
    finally:
        release.set()
        await rt.close()


@pytest.mark.parametrize("flag", ["motion_enabled", "spatial_navigation_qualified"])
async def test_navigation_rechecks_qualification_after_pose_io(settings, tmp_path, flag):
    """Revoking either motion qualification during pose IO must prevent dispatch."""
    from desk_robot.runtime import Runtime

    settings.memory_dir = tmp_path / "memory"
    settings.trials_file = tmp_path / "trials.jsonl"
    robot = settings.robots[0]
    robot.motion_enabled = True
    robot.spatial_navigation_qualified = True
    rt = Runtime(settings)

    class RevokingHead(SpatialHead):
        async def pose_status(self):
            receipt = await super().pose_status()
            setattr(robot, flag, False)
            return receipt

    head = RevokingHead("robot-01")
    rt.coordinator.heads["robot-01"] = head
    try:
        _seed_safe_grid(rt.spatial, "robot-01", head)
        await rt.coordinator.operator_arm("robot-01")
        job = rt.coordinator.navigate("robot-01", start=(2, 2), goal=(3, 2))
        await asyncio.wait_for(rt.coordinator.tasks[job.id], timeout=5)
        assert job.state == "failed"
        assert "Spatial navigation requires" in (job.error or "")
        assert not any(cmd.startswith("drive ") for cmd in head.commands)
        assert "halt" in head.commands
    finally:
        await rt.close()
