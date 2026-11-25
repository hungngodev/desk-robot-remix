"""Dock observations and operator motion admission for the Mac API."""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException

from .api_lifecycle import require_runtime_ready
from .config import Settings
from .controller import OperationError
from .dock_evidence import observe_dock_evidence
from .dock_runtime import observe_actual_dock


def register_dock_routes(
    app: FastAPI, settings: Settings, *, authorize, operator, coordinator,
) -> None:
    @app.post("/v1/robots/{robot_id}/dock/approach",
              dependencies=[Depends(operator), Depends(require_runtime_ready)], status_code=202)
    async def dock_approach(robot_id: str):
        return coordinator().dock(robot_id).data()

    @app.get("/v1/robots/{robot_id}/dock/observe", dependencies=[Depends(authorize)])
    async def dock_observe(robot_id: str):
        """Passive marker detection only, bounded by the original camera grant."""
        robot = coordinator().robot(robot_id)
        if not settings.voice_vision_tools_enabled:
            raise HTTPException(403, "Camera consent required for dock observation")
        camera_grant = settings.camera_consent_generation

        def original_camera_grant_valid() -> bool:
            return (
                settings.voice_vision_tools_enabled
                and settings.camera_consent_generation == camera_grant
            )

        result = await observe_actual_dock(
            coordinator().heads[robot_id], robot,
            consent_valid=original_camera_grant_valid,
        )
        if not settings.voice_vision_tools_enabled:
            raise HTTPException(403, "Camera consent revoked during dock observation")
        if settings.camera_consent_generation != camera_grant:
            raise HTTPException(409, "Camera grant changed during dock observation")
        return result

    @app.get("/v1/robots/{robot_id}/dock/ir",
             dependencies=[Depends(authorize)])
    async def dock_ir(robot_id: str):
        """Observe two independent NEC receivers, never move or charge."""
        coordinator().robot(robot_id)
        if settings.mode != "hardware":
            return {
                "robot_id": robot_id, "available": False,
                "physical_qualified": False,
                "motor_authorized": False,
                "charging_authorized": False,
            }
        getter = getattr(coordinator().heads[robot_id], "ir_status", None)
        if not callable(getter):
            raise OperationError("This head has no direct dual NEC receiver")
        return await getter()

    @app.get("/v1/robots/{robot_id}/dock/evidence",
             dependencies=[Depends(authorize)])
    async def dock_evidence(robot_id: str):
        """Three physical dock pin samples, never a battery charging verdict."""
        coordinator().robot(robot_id)
        if settings.mode != "hardware":
            return {
                "robot_id": robot_id, "state": "no_physical_hardware",
                "charging_verified": False, "motor_authorized": False,
                "charging_authorized": False,
            }
        head = coordinator().heads[robot_id]
        if not callable(getattr(head, "aux_status", None)):
            raise OperationError("This head has no dock auxiliary telemetry")
        return await observe_dock_evidence(head, robot_id)
