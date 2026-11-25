"""Operator-only read-only diagnostics for the versioned WROOM pose stream.

A body pose is local odometry evidence, not an anchored map or a grant to move.
The existing authenticated HttpHead/PoseFence own the source validation.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .spatial_pose import PoseFence, PoseReceipt
from .transport import HeadError


# SpatialGrid admits at most 64 cells per axis. Reject coercions before
# submitting or deferring any job; the planner still checks the actual grid.
GridCoordinate = Annotated[int, Field(strict=True, ge=0, le=63)]
GridHeading = Annotated[int, Field(strict=True, ge=0, le=3)]


class NavigateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = Field(default=None, min_length=1, max_length=64)
    goal: tuple[GridCoordinate, GridCoordinate] | None = None
    goal_heading: GridHeading | None = None
    start: tuple[GridCoordinate, GridCoordinate] = (0, 0)
    heading: GridHeading = 0


def register_spatial_pose_route(
    app: FastAPI,
    *,
    operator,
    coordinator,
    authorize=None,
    settings=None,
    spatial=None,
) -> None:
    read_dep = authorize if authorize is not None else operator

    @app.get("/v1/robots/{robot_id}/pose", dependencies=[Depends(operator)])
    async def read_body_pose(robot_id: str):
        """Inspect one real head receipt without enabling a robot or navigation."""
        owner = coordinator()
        owner.robot(robot_id)
        head = owner.heads.get(robot_id)
        if head is None:
            raise HTTPException(503, "Pose head unavailable")
        reader = getattr(head, "pose_status", None)
        if not callable(reader):
            raise HTTPException(501, "Pose unsupported by configured head")

        try:
            receipt = await reader()
        except HeadError as exc:
            # Old Sense/WROOM versions have no pose command. Preserve that
            # compatibility outcome instead of making up an origin.
            cause = exc.__cause__
            if (isinstance(cause, httpx.HTTPStatusError)
                    and cause.response.status_code in (404, 501)):
                raise HTTPException(501, "Pose unsupported by head/body firmware") from exc
            raise

        if type(receipt) is not PoseReceipt or receipt.robot_id != robot_id:
            raise HeadError("Pose receipt robot identity mismatch")
        fence = getattr(head, "pose_fence", None)
        current = fence.current(time.monotonic()) if isinstance(fence, PoseFence) else None

        return {
            "robot_id": robot_id,
            "schema_version": 1,
            "available": True,
            "pose": {
                "body_boot": receipt.body_boot,
                "origin": receipt.origin,
                "seq": receipt.seq,
                "sample_us": receipt.sample_us,
                "x_mm": receipt.x_mm,
                "y_mm": receipt.y_mm,
                "yaw_mrad": receipt.yaw_mrad,
                "quality": receipt.quality,
                "head_boot": receipt.head_boot,
            },
            "local_odometry_continuous": current == receipt and current is not None,
            "blocked_reason": (
                fence.blocked_reason if isinstance(fence, PoseFence) else "no_pose_fence"
            ),
            "needs_reanchor": True,
            "map_anchored": False,
            "navigation_authorized": False,
            "motor_authorized": False,
            "charging_authorized": False,
            "physical_acceptance_pass": False,
        }

    def _spatial_owner():
        owner = spatial() if callable(spatial) else None
        if owner is None:
            owner = getattr(getattr(app.state, "runtime", None), "spatial", None)
        if owner is None:
            raise HTTPException(503, "Spatial runtime unavailable")
        return owner

    @app.get("/v1/robots/{robot_id}/spatial/grid", dependencies=[Depends(read_dep)])
    async def read_spatial_grid(robot_id: str):
        """Read-only occupancy summary for one robot; never grants motion."""
        coordinator().robot(robot_id)
        return _spatial_owner().grid_summary(robot_id)

    @app.get("/v1/robots/{robot_id}/spatial/memory", dependencies=[Depends(read_dep)])
    async def read_spatial_memory(
        robot_id: str,
        object_key: str = Query(min_length=1, max_length=64),
    ):
        """Read-only object spatial recall respecting private memory consent."""
        coordinator().robot(robot_id)
        if settings is not None and settings.mode == "hardware" and (
            not settings.voice_memory_tools_enabled
        ):
            raise HTTPException(403, "Spatial object memory recall requires memory consent")
        owner = _spatial_owner()
        runtime = getattr(app.state, "runtime", None)
        conversation = getattr(runtime, "conversation", None)
        revisions = getattr(conversation, "_private_memory_generation", None)
        revision = revisions.get(robot_id) if isinstance(revisions, dict) else None
        if type(revision) is not int or not 0 <= revision < 2**63:
            raise HTTPException(409, "Private memory revision unavailable")
        state = owner.state(robot_id)
        origin = (state.epoch, state.body_boot, state.origin_id)
        mode = getattr(settings, "mode", None)
        grant = getattr(settings, "voice_memory_consent_generation", None)
        try:
            # SQLite may wait on a writer. Do not stall STOP or other robot
            # requests on the event loop while reading private evidence.
            result = await asyncio.to_thread(owner.recall_memory, robot_id, object_key)
        except ValueError as exc:
            raise HTTPException(400, "Invalid spatial memory query") from exc
        except (sqlite3.Error, OSError) as exc:
            raise HTTPException(503, "Spatial memory unavailable") from exc
        if (getattr(settings, "mode", None) != mode
                or getattr(settings, "voice_memory_consent_generation", None) != grant
                or (mode == "hardware" and not settings.voice_memory_tools_enabled)):
            raise HTTPException(403, "Spatial memory consent changed during read")
        current_runtime = getattr(app.state, "runtime", None)
        current_conversation = getattr(current_runtime, "conversation", None)
        current_revisions = getattr(current_conversation, "_private_memory_generation", None)
        if (current_runtime is not runtime or current_conversation is not conversation
                or not isinstance(current_revisions, dict)
                or type(current_revisions.get(robot_id)) is not int
                or current_revisions[robot_id] != revision):
            raise HTTPException(409, "Private memory changed during read")
        if (_spatial_owner() is not owner or owner.state(robot_id) is not state
                or (state.epoch, state.body_boot, state.origin_id) != origin):
            raise HTTPException(409, "Spatial origin changed during read")
        if (not isinstance(result, dict) or result.get("robot_id") != robot_id
                or result.get("object_key") != object_key):
            raise HTTPException(503, "Spatial memory identity mismatch")
        return result

    @app.post("/v1/robots/{robot_id}/navigate",
              dependencies=[Depends(operator)], status_code=202)
    async def navigate_robot(
        robot_id: str,
        request: NavigateRequest,
        defer_on_voice: bool = False,
    ):
        """Start bounded qualified spatial navigation or object re-observation."""
        coord = coordinator()
        robot = coord.robot(robot_id)

        def submit():
            return coord.navigate(
                robot_id,
                label=request.label,
                goal=request.goal,
                goal_heading=request.goal_heading,
                start=request.start,
                heading=request.heading,
            )

        if defer_on_voice and coord.voice_blocks_motion() is not None:
            if settings is not None and settings.mode == "hardware" and request.label is not None:
                expected_grant = settings.camera_consent_generation

                def consent_check() -> bool:
                    return (
                        settings.voice_vision_tools_enabled
                        and settings.camera_consent_generation == expected_grant
                        and robot.motion_enabled
                        and robot.spatial_navigation_qualified
                    )
            else:
                def consent_check() -> bool:
                    return (
                        robot.motion_enabled and robot.spatial_navigation_qualified
                    )
            deferred = coord.defer_motion(
                robot_id,
                "navigate",
                submit_fn=submit,
                consent_check=consent_check,
            )
            return {
                "id": deferred.id,
                "robot_id": robot_id,
                "kind": "navigate",
                "state": "deferred_for_voice",
            }
        return submit().data()
