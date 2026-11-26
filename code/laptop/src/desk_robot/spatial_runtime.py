"""Guide 90 runtime owner for spatial memory, occupancy grid, search, and routes.

Connects per-robot PoseFence, SpatialGrid, SpatialMemory, resolve_object_target,
propose_object_search, detect_object_frame, and plan_route behind fail-closed
safety defaults. Never grants motor or charging rights directly.
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field

from .config import Settings
from .memory import MemoryStore
from .object_detector import DetectorFrame, DetectorReceipt, detect_object_frame
from .object_search import ObjectSearchResult, SearchViewpoint, propose_object_search
from .object_targets import (
    ObjectEvidence,
    ObjectOwner,
    ObjectQuery,
    ObjectTarget,
    resolve_object_target,
)
from .route_planner import GridSnapshot, RouteRequest, RouteResult, SafetyEnvelope, plan_route
from .spatial_frames import FrameError, PlanarTransform, odom_base_transform
from .spatial_grid import CELL_MM, GridEvidenceError, RangeCellBatch, SpatialGrid
from .spatial_memory import SpatialEvidence, SpatialMemory, SpatialSighting
from .spatial_pose import PoseError, PoseFence, PoseReceipt
from .vision import Vision


@dataclass
class RobotSpatialState:
    robot_id: str
    pose_fence: PoseFence
    grid: SpatialGrid | None = None
    last_navigation_pose: PoseReceipt | None = None
    map_to_odom: PlanarTransform | None = None
    epoch: int = 1
    body_boot: int = 0
    origin_id: str = "unanchored"
    anchor_id: str = "unanchored"
    calibration_id: str = "uncalibrated"
    camera_boot: int = 0
    envelope: SafetyEnvelope | None = None
    viewpoints: list[SearchViewpoint] = field(default_factory=list)
    observations: list[ObjectEvidence] = field(default_factory=list)
    invalidated_reason: str | None = "unanchored"


class SpatialRuntime:
    """Cohesive per-robot Guide 50/60 coordinator shared across Runtime, API, and Controller."""

    def __init__(self, settings: Settings, memory: MemoryStore):
        self.settings = settings
        self.memory = memory
        self.spatial_memory = SpatialMemory(memory)
        self.host_boot_id = f"host-{uuid.uuid4().hex[:16]}"
        self.states: dict[str, RobotSpatialState] = {
            robot.id: RobotSpatialState(robot_id=robot.id, pose_fence=PoseFence(robot.id))
            for robot in settings.robots
        }

    @staticmethod
    def now_us() -> int:
        return int(time.monotonic() * 1_000_000)

    def state(self, robot_id: str) -> RobotSpatialState:
        return self.states[robot_id]

    def invalidate_robot(self, robot_id: str, *, reason: str) -> None:
        """Invalidate map continuity, viewpoints, and pose fence on pickup, STOP, or fault."""
        state = self.states.get(robot_id)
        if state is None:
            return
        state.epoch += 1
        state.invalidated_reason = reason
        state.pose_fence.invalidate(reason)
        state.last_navigation_pose = None
        state.map_to_odom = None
        if state.grid is not None:
            state.grid.invalidate_origin(state.body_boot, f"reset-{state.epoch}")
            state.grid.epoch = state.epoch
            state.origin_id = state.grid.origin_id
        else:
            state.origin_id = f"reset-{state.epoch}"
        state.viewpoints.clear()

    def bind_qualified_grid(
        self,
        robot_id: str,
        *,
        body_boot: int,
        origin_id: str,
        anchor_id: str,
        calibration_id: str,
        camera_boot: int,
        width: int,
        height: int,
        envelope: SafetyEnvelope,
        ttl_us: int = 2_000_000,
        anchored: bool = False,
        map_to_odom: PlanarTransform | None = None,
    ) -> SpatialGrid:
        """Bind a bounded per-robot occupancy grid for an identified origin and calibration."""
        state = self.states[robot_id]
        if (type(anchored) is not bool or type(camera_boot) is not int
                or not 0 <= camera_boot <= 0xffffffff):
            raise ValueError("Invalid spatial anchor identity")
        if map_to_odom is not None and (
            type(map_to_odom) is not PlanarTransform
            or (map_to_odom.parent, map_to_odom.child) != ("map", "odom")
        ):
            raise ValueError("Invalid map-to-odom localization transform")
        next_epoch = state.epoch + 1
        grid = SpatialGrid(
            robot_id,
            body_boot,
            origin_id,
            anchor_id,
            calibration_id,
            width,
            height,
            epoch=next_epoch,
            ttl_us=ttl_us,
        )
        grid.inherit_clock_reference(state.grid)
        state.epoch = next_epoch
        state.body_boot = body_boot
        state.origin_id = origin_id
        state.anchor_id = anchor_id
        state.calibration_id = calibration_id
        state.camera_boot = camera_boot
        state.envelope = envelope
        state.map_to_odom = map_to_odom
        state.last_navigation_pose = None
        state.invalidated_reason = None if anchored else "unanchored"
        grid.anchored = anchored
        state.grid = grid
        state.viewpoints.clear()
        return grid

    def observe_pose(
        self,
        robot_id: str,
        payload: dict | PoseReceipt,
        *,
        received_at: float | None = None,
        request_started_at: float | None = None,
        source_fence: PoseFence | None = None,
    ) -> PoseReceipt:
        """Validate pose stream continuity; reset spatial map epoch if origin/boot changes."""
        state = self.states[robot_id]
        stamp = time.monotonic() if received_at is None else received_at
        if type(payload) is PoseReceipt:
            previous = state.last_navigation_pose
            if (not isinstance(source_fence, PoseFence)
                    or payload.robot_id != robot_id
                    or source_fence.current(stamp) is not payload
                    or not source_fence.owns_continuous_receipt(payload)
                    or (previous is not None and payload.seq <= previous.seq)):
                self.invalidate_robot(robot_id, reason="pose_receipt_not_current")
                raise PoseError("Navigation pose receipt not current")
            state.pose_fence = source_fence
            receipt = payload
        else:
            if self.settings.mode == "hardware":
                self.invalidate_robot(robot_id, reason="pose_receipt_untyped")
                raise PoseError("Hardware navigation requires authenticated pose receipt")
            try:
                receipt = state.pose_fence.observe(
                    payload,
                    stamp,
                    request_started_at=request_started_at,
                )
            except PoseError:
                self.invalidate_robot(robot_id, reason=state.pose_fence.blocked_reason)
                raise
        if state.grid is not None and state.body_boot > 0 and (
            receipt.body_boot != state.body_boot
        ):
            self.invalidate_robot(robot_id, reason="body_boot_changed")
            raise PoseError("Pose body boot differs from anchored map")
        if state.grid is not None and state.grid.anchored and (
            str(receipt.origin) != state.origin_id
            or receipt.head_boot != state.camera_boot
            or receipt.quality != "valid"
        ):
            self.invalidate_robot(robot_id, reason="pose_anchor_identity_changed")
            raise PoseError("Pose origin, head boot or quality differs from anchored map")
        state.last_navigation_pose = receipt
        return receipt

    def localized_pose_cell_heading(
        self,
        robot_id: str,
        receipt: PoseReceipt,
        *,
        yaw_tolerance_rad: float = math.pi / 6,
    ) -> tuple[tuple[int, int], int]:
        """Project a validated PoseReceipt through map_to_odom into grid (cell, heading)."""
        state = self.states[robot_id]
        if (state.grid is None or not state.grid.anchored
                or state.map_to_odom is None
                or type(receipt) is not PoseReceipt
                or receipt.robot_id != robot_id
                or receipt.quality != "valid"
                or (state.body_boot > 0 and receipt.body_boot != state.body_boot)
                or str(receipt.origin) != state.origin_id
                or receipt.head_boot != state.camera_boot):
            raise PoseError("Map-localized pose unavailable")
        try:
            map_base = state.map_to_odom.compose(odom_base_transform(receipt))
        except FrameError as exc:
            raise PoseError("Invalid map-to-base pose transform") from exc
        cell_x = math.floor(map_base.x_mm / CELL_MM)
        cell_y = math.floor(map_base.y_mm / CELL_MM)
        if not (0 <= cell_x < state.grid.width and 0 <= cell_y < state.grid.height):
            raise PoseError("Localized pose outside anchored spatial grid")
        heading = round(map_base.yaw_rad / (math.pi / 2)) % 4
        if abs(math.remainder(map_base.yaw_rad - heading * (math.pi / 2), math.tau)) > yaw_tolerance_rad:
            raise PoseError("Localized heading diverges from lattice orientation")
        return (cell_x, cell_y), heading

    def verify_pose_matches_route_state(
        self,
        robot_id: str,
        receipt: PoseReceipt,
        *,
        expected_cell: tuple[int, int],
        expected_heading: int,
        yaw_tolerance_rad: float = math.pi / 6,
    ) -> tuple[tuple[int, int], int]:
        """Fail closed and invalidate map if observed localized pose diverges from route state."""
        try:
            actual = self.localized_pose_cell_heading(
                robot_id, receipt, yaw_tolerance_rad=yaw_tolerance_rad,
            )
        except PoseError:
            self.invalidate_robot(robot_id, reason="pose_odometry_divergence")
            raise
        if actual != (expected_cell, expected_heading):
            self.invalidate_robot(robot_id, reason="pose_odometry_divergence")
            raise PoseError(
                f"Observed pose {actual} diverges from route state {(expected_cell, expected_heading)}"
            )
        return actual

    def record_range_batch(
        self, robot_id: str, batch: RangeCellBatch, *, now_us: int | None = None,
    ) -> None:
        state = self.states[robot_id]
        if state.grid is None:
            raise ValueError("Spatial grid not initialized for robot")
        was_anchored = state.grid.anchored
        try:
            state.grid.record(batch, now_us=self.now_us() if now_us is None else now_us)
        except GridEvidenceError:
            if was_anchored and not state.grid.anchored:
                self.invalidate_robot(robot_id, reason="range_clock_invalidated")
            raise

    def register_viewpoint(self, robot_id: str, viewpoint: SearchViewpoint) -> None:
        state = self.states[robot_id]
        if (
            viewpoint.robot_id != robot_id
            or viewpoint.origin_id != state.origin_id
            or viewpoint.epoch != state.epoch
            or viewpoint.anchor_id != state.anchor_id
            or viewpoint.calibration_id != state.calibration_id
        ):
            raise ValueError("Viewpoint epoch or origin mismatch")
        state.viewpoints = [
            vp for vp in state.viewpoints if vp.viewpoint_id != viewpoint.viewpoint_id
        ][-31:]
        state.viewpoints.append(viewpoint)

    def record_object_sighting(
        self,
        robot_id: str,
        evidence: ObjectEvidence,
        *,
        event_id: str | None = None,
        spatial_evidence: SpatialEvidence | None = None,
    ) -> bool:
        """Record volatile object observation and optionally attach to existing episodic SQLite row."""
        state = self.states[robot_id]
        if evidence.robot_id != robot_id:
            raise ValueError("Object evidence robot identity mismatch")
        # No live producer yet proves camera exposure against a stationary
        # motion bracket. Reject both positive and negative camera claims;
        # an unproven frame must not enter the route cache or episode store.
        if self.settings.mode == "hardware" and evidence.source in (
            "camera_seen", "camera_not_seen",
        ):
            return False
        state.observations.append(evidence)
        if len(state.observations) > 64:
            state.observations = state.observations[-64:]
        if event_id is not None and spatial_evidence is not None:
            return self.spatial_memory.attach(robot_id, event_id, spatial_evidence)
        return True

    def make_owner(
        self,
        robot_id: str,
        *,
        session_id: str = "operator-session",
        turn_id: str = "operator-turn",
    ) -> ObjectOwner:
        state = self.states[robot_id]
        hw = self.settings.mode == "hardware"
        camera_allowed = True if not hw else self.settings.voice_vision_tools_enabled
        memory_allowed = True if not hw else self.settings.voice_memory_tools_enabled
        return ObjectOwner(
            robot_id=robot_id,
            session_id=session_id,
            turn_id=turn_id,
            origin_id=state.origin_id,
            epoch=state.epoch,
            anchor_id=state.anchor_id,
            calibration_id=state.calibration_id,
            camera_boot=state.camera_boot,
            host_boot_id=self.host_boot_id,
            camera_grant=self.settings.camera_consent_generation,
            camera_allowed=camera_allowed,
            memory_allowed=memory_allowed,
        )

    def plan_navigation(
        self,
        robot_id: str,
        *,
        start: tuple[int, int] = (0, 0),
        heading: int = 0,
        goal: tuple[int, int] | None = None,
        label: str | None = None,
        goal_heading: int | None = None,
        session_id: str = "operator-session",
        turn_id: str = "operator-turn",
        now_us: int | None = None,
        horizon_us: int = 1_500_000,
    ) -> tuple[RouteResult, ObjectTarget | None, ObjectSearchResult | None]:
        """Resolve optional target/search viewpoint and compute bounded Guide 60 route proposal."""
        state = self.states[robot_id]
        if state.grid is None or state.envelope is None:
            return RouteResult("rejected", "unanchored_or_stale_map"), None, None
        current_us = self.now_us() if now_us is None else now_us
        grid = state.grid
        envelope = state.envelope
        epoch = state.epoch
        camera_boot = state.camera_boot
        camera_grant = self.settings.camera_consent_generation
        snapshot: GridSnapshot = grid.to_route_snapshot(now_us=current_us)

        def request_current() -> bool:
            current = self.states[robot_id]
            return (
                current is state and current.epoch == epoch and current.grid is grid
                and current.envelope == envelope and grid.epoch == epoch and grid.anchored
                and current.origin_id == snapshot.origin_id
                and current.anchor_id == snapshot.anchor_id
                and current.calibration_id == snapshot.calibration_id
                and current.camera_boot == camera_boot
                and (self.settings.mode != "hardware" or (
                    self.settings.voice_vision_tools_enabled
                    and self.settings.camera_consent_generation == camera_grant
                ))
            )

        target_res: ObjectTarget | None = None
        search_res: ObjectSearchResult | None = None
        chosen_goal = goal
        chosen_heading = goal_heading

        if label is not None:
            owner = self.make_owner(robot_id, session_id=session_id, turn_id=turn_id)
            query = ObjectQuery(
                robot_id=robot_id,
                label=label,
                session_id=session_id,
                turn_id=turn_id,
                origin_id=state.origin_id,
                epoch=state.epoch,
                anchor_id=state.anchor_id,
                calibration_id=state.calibration_id,
                camera_boot=state.camera_boot,
                host_boot_id=self.host_boot_id,
                camera_grant=self.settings.camera_consent_generation,
                created_us=current_us,
                deadline_us=current_us + horizon_us,
            )
            target_res = resolve_object_target(
                query,
                owner,
                tuple(state.observations),
                now_us=current_us,
            )
            if chosen_goal is None:
                if target_res.status == "current_sighting" and target_res.confirmed_floor_mm is not None:
                    cx, cy = target_res.confirmed_floor_mm
                    chosen_goal = (cx // CELL_MM, cy // CELL_MM)
                elif state.viewpoints:
                    route_req = RouteRequest(
                        robot_id=robot_id,
                        origin_id=state.origin_id,
                        epoch=state.epoch,
                        anchor_id=state.anchor_id,
                        session_id=session_id,
                        turn_id=turn_id,
                        start=start,
                        heading=heading,
                        goal=start,
                        deadline_us=current_us + horizon_us,
                        goal_heading=chosen_heading,
                    )
                    search_res = propose_object_search(
                        snapshot,
                        route_req,
                        state.envelope,
                        query,
                        owner,
                        target_res,
                        tuple(state.viewpoints),
                        now_us=current_us,
                        clock_us=self.now_us,
                        request_is_current=request_current,
                    )
                    if search_res.status == "viewpoint_proposal" and search_res.route is not None:
                        return search_res.route, target_res, search_res
                    return RouteResult("rejected", search_res.reason), target_res, search_res
                else:
                    return RouteResult("rejected", target_res.reason), target_res, None

        if chosen_goal is None:
            return RouteResult("rejected", "missing_goal_or_target"), target_res, search_res

        route_req = RouteRequest(
            robot_id=robot_id,
            origin_id=state.origin_id,
            epoch=state.epoch,
            anchor_id=state.anchor_id,
            session_id=session_id,
            turn_id=turn_id,
            start=start,
            heading=heading,
            goal=chosen_goal,
            deadline_us=current_us + horizon_us,
            goal_heading=chosen_heading,
        )
        route_res = plan_route(
            snapshot,
            route_req,
            state.envelope,
            now_us=current_us,
            clock_us=self.now_us,
            request_is_current=request_current,
        )
        return route_res, target_res, search_res

    async def confirm_target_frame(
        self,
        detector: Vision,
        frame: DetectorFrame,
        *,
        label: str,
        session_id: str = "operator-session",
        turn_id: str = "operator-turn",
        model_qualified: bool = False,
        safety_clear,
        request_is_current,
    ) -> DetectorReceipt:
        # Match the controller's hardware capture hold at the runtime owner.
        # A fresh JPEG receipt and current body status cannot establish that
        # the original exposure avoided wheel motion or camera mount slew.
        if self.settings.mode == "hardware":
            return DetectorReceipt("rejected", "camera_stationarity_unproven")
        state = self.states[frame.robot_id]
        now_us = self.now_us()
        owner = self.make_owner(frame.robot_id, session_id=session_id, turn_id=turn_id)
        query = ObjectQuery(
            robot_id=frame.robot_id,
            label=label,
            session_id=session_id,
            turn_id=turn_id,
            origin_id=state.origin_id,
            epoch=state.epoch,
            anchor_id=state.anchor_id,
            calibration_id=state.calibration_id,
            camera_boot=state.camera_boot,
            host_boot_id=self.host_boot_id,
            camera_grant=self.settings.camera_consent_generation,
            created_us=min(now_us, frame.captured_us),
            deadline_us=now_us + 2_000_000,
        )
        def live_owner_current() -> bool:
            # An immutable admission snapshot is not a live owner. A caller's
            # job can still be running while its camera/map/grant was replaced.
            return (
                request_is_current() is True
                and self.settings.mode != "hardware"
                and self.states.get(frame.robot_id) is state
                and self.make_owner(
                    frame.robot_id, session_id=session_id, turn_id=turn_id,
                ) == owner
            )

        return await detect_object_frame(
            detector,
            frame,
            query,
            owner,
            model_qualified=model_qualified,
            now_us=now_us,
            clock_us=self.now_us,
            request_is_current=(
                live_owner_current if callable(request_is_current) else request_is_current
            ),
            safety_clear=safety_clear,
        )

    def grid_summary(self, robot_id: str, *, now_us: int | None = None) -> dict:
        state = self.states[robot_id]
        current_us = self.now_us() if now_us is None else now_us
        base = {
            "robot_id": robot_id,
            "epoch": state.epoch,
            "origin_id": state.origin_id,
            "anchor_id": state.anchor_id,
            "calibration_id": state.calibration_id,
            "anchored": bool(state.grid.anchored) if state.grid is not None else False,
            "blocked_reason": state.invalidated_reason or state.pose_fence.blocked_reason,
            "viewpoints": len(state.viewpoints),
            "navigation_authorized": False,
            "motor_authorized": False,
            "charging_authorized": False,
            "physical_acceptance_pass": False,
        }
        if state.grid is None:
            return {**base, "initialized": False}
        snap = state.grid.snapshot(now_us=current_us)
        counts: dict[str, int] = {}
        for cell_state in snap.support:
            counts[cell_state] = counts.get(cell_state, 0) + 1
        return {
            **base,
            "initialized": True,
            "width": snap.width,
            "height": snap.height,
            "cell_mm": snap.cell_mm,
            "observed_at_us": snap.observed_at_us,
            "expires_at_us": snap.expires_at_us,
            "cell_counts": counts,
        }

    def recall_memory(
        self, robot_id: str, object_key: str, *, now_wall: float | None = None,
    ) -> dict:
        state = self.states[robot_id]
        sighting: SpatialSighting | None = self.spatial_memory.last_seen(
            robot_id,
            object_key,
            now=time.time() if now_wall is None else now_wall,
            current_origin=(state.body_boot, state.origin_id),
        )
        if sighting is None:
            return {
                "robot_id": robot_id,
                "object_key": object_key,
                "status": "unknown",
                "navigation_authorized": False,
                "arrived": False,
                "motor_authorized": False,
            }
        ev = sighting.evidence
        return {
            "robot_id": robot_id,
            "object_key": object_key,
            "status": sighting.status,
            "event_id": sighting.event_id,
            "observed_at": ev.observed_at,
            "age_s": sighting.age_s,
            "episode_confidence": sighting.episode_confidence,
            "body_boot": ev.body_boot,
            "frame": ev.frame,
            "anchor_id": ev.anchor_id,
            "origin_id": ev.origin_id,
            "calibration_id": ev.calibration_id,
            "x_mm": ev.x_mm,
            "y_mm": ev.y_mm,
            "uncertainty_mm": ev.uncertainty_mm,
            "navigation_authorized": False,
            "arrived": False,
            "motor_authorized": False,
        }
