"""Operator-only read-only diagnostics for the versioned WROOM pose stream.

A body pose is local odometry evidence, not an anchored map or a grant to move.
The existing authenticated HttpHead/PoseFence own the source validation.
"""

from __future__ import annotations

import time

import httpx
from fastapi import Depends, FastAPI, HTTPException

from .spatial_pose import PoseFence, PoseReceipt
from .transport import HeadError


def register_spatial_pose_route(app: FastAPI, *, operator, coordinator) -> None:
    @app.get("/v1/robots/{robot_id}/pose", dependencies=[Depends(operator)])
    async def read_body_pose(robot_id: str):
        """Inspect one real head receipt without enabling a robot or navigation."""
        owner = coordinator()
        owner.robot(robot_id)
        head = owner.heads[robot_id]
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
